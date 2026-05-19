"""
ETF 計算層（calc layer）
從 etf_dashboard.py 抽出的純計算函式：殖利率 / 總報酬 / 折溢價 / 風險指標 / 同儕排名 / 戰情室列計算
依賴：etf_fetch（單向；calc 永遠不依賴 render）。
"""
import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import timedelta

from etf_fetch import (
    fetch_etf_price, fetch_etf_dividends, fetch_etf_info,
    fetch_etf_nav_history, _get_etf_launch_price,
)


@st.cache_data(ttl=900, max_entries=50, show_spinner=False)
def _compute_etf_warroom_row(ticker: str, name: str, role: str) -> dict:
    """ETF 追蹤戰情室單列健檢計算（核心/衛星依 role 分流燈號邏輯）。

    核心資產（穩領息）燈號 → 「健康燈號」欄位：
        🔴 賺息賠本（總報酬 < 殖利率）→ 考慮換股
        🟡 趨勢轉弱（跌破 MA60）
        🟢 體質健康（總報酬 ≥ 殖利率 且 站上 MA60）
        其他附帶警示：條件 B 破發 / 條件 C 溢價>1% 加註於燈號文字

    衛星資產（賺價差，跌了就買 σ 分級）燈號 → 「σ位階」欄位：
        🟢🟢🟢 股災價（< MA20-3σ）→ 大買 50%
        🟢🟢   超跌價（< MA20-2σ）→ 買 30%
        🟢     便宜價（< MA20-1σ）→ 小買 20%
        ⚪     中性區（MA20-1σ ~ MA20+1.5σ）
        🟠     偏高（≥ MA20+1.5σ）→ 不追高
        🔴     準備停利（≥ MA20+2σ）

    回傳欄位：
        代號 / 名稱 / 類型 / 市價 / 折溢價% / 年化配息率% / 1年含息報酬% /
        距月線% / 距季線% / σ位階 / 走勢（30日）/ 健康燈號 / 動作建議
    """
    _empty = {
        '代號': ticker, '名稱': name, '類型': role,
        '市價': None, '折溢價%': None, '年化配息率%': None,
        '1年含息報酬%': None, '距月線%': None, '距季線%': None,
        'σ位階': None, '走勢': [], '健康燈號': '⚪ 資料不足', '動作建議': '—',
    }
    try:
        df = fetch_etf_price(ticker, period='1y')
        if df.empty or 'Close' not in df.columns:
            return _empty
        divs = fetch_etf_dividends(ticker)
        info = fetch_etf_info(ticker)

        _cur = float(df['Close'].iloc[-1])
        _ttl = calc_total_return_1y(df, divs)
        _yld = calc_current_yield(df, divs)
        _prem = calc_premium_discount(info, df, ticker)
        _prem_pct = _prem.get('premium_pct') if isinstance(_prem, dict) else None

        # 均線 & 乖離
        _ma20v = float(df['Close'].rolling(20).mean().iloc[-1]) if len(df) >= 20 else None
        _ma60v = float(df['Close'].rolling(60).mean().iloc[-1]) if len(df) >= 60 else None
        _bias20 = round((_cur - _ma20v) / _ma20v * 100, 2) if (_ma20v and _ma20v > 0) else None
        _bias60 = round((_cur - _ma60v) / _ma60v * 100, 2) if (_ma60v and _ma60v > 0) else None

        # MA20 ± σ（衛星「跌了就買」分級）：用近 1 年 daily close 的標準差
        _sigma_label, _sigma_action, _sigma_emoji = None, None, None
        if _ma20v is not None and len(df) >= 60:
            _std = float(df['Close'].tail(252).std())  # 近 1 年 daily std
            if _std > 0:
                _lo3 = _ma20v - 3 * _std
                _lo2 = _ma20v - 2 * _std
                _lo1 = _ma20v - 1 * _std
                _hi15 = _ma20v + 1.5 * _std
                _hi2 = _ma20v + 2 * _std
                if _cur < _lo3:
                    _sigma_emoji, _sigma_label, _sigma_action = '🟢🟢🟢', '股災價(<-3σ)', '大買 50%'
                elif _cur < _lo2:
                    _sigma_emoji, _sigma_label, _sigma_action = '🟢🟢', '超跌價(<-2σ)', '買 30%'
                elif _cur < _lo1:
                    _sigma_emoji, _sigma_label, _sigma_action = '🟢', '便宜價(<-1σ)', '小買 20%'
                elif _cur >= _hi2:
                    _sigma_emoji, _sigma_label, _sigma_action = '🔴', '準備停利(≥+2σ)', '分批停利'
                elif _cur >= _hi15:
                    _sigma_emoji, _sigma_label, _sigma_action = '🟠', '偏高(≥+1.5σ)', '不追高/減碼'
                else:
                    _sigma_emoji, _sigma_label, _sigma_action = '⚪', '中性區(±1σ)', '靜待訊號'

        # 30 日 sparkline
        _spark = [float(x) for x in df['Close'].tail(30).tolist()]

        # ── 燈號分流：核心 vs 衛星 ──────────────────────────────
        _is_core = (role == '核心')
        _is_sat = (role == '衛星')

        if _is_core:
            # 核心：總報酬 vs 殖利率 + MA60 趨勢
            _below_ma60 = (_ma60v is not None and _cur < _ma60v)
            _has_yld = _yld and _yld > 0
            _extra = []
            # 條件 B 破發
            _lp = _get_etf_launch_price(ticker, df)
            if _lp and _cur < _lp:
                _extra.append(f'破發(<{_lp:.1f})')
            # 條件 C 溢價
            if _prem_pct is not None and _prem_pct > 1:
                _extra.append(f'溢價過高({_prem_pct:+.2f}%)')
            elif _prem_pct is not None and _prem_pct < 0:
                _extra.append(f'折價({_prem_pct:+.2f}%)')

            if _has_yld and _ttl < _yld:
                _lamp = f'🔴 賺息賠本({_ttl:.1f}%<{_yld:.1f}%)→考慮換股'
                _action_hint = '考慮換股（核心紀律不容侵蝕本金）'
            elif _below_ma60:
                _lamp = f'🟡 趨勢轉弱（跌破 MA60 {_ma60v:.2f}）'
                _action_hint = '觀察均線止跌；不加碼'
            elif _has_yld:
                _lamp = f'🟢 體質健康（{_ttl:.1f}% ≥ {_yld:.1f}%）'
                _action_hint = '正常續抱領息'
            else:
                _lamp = '🟡 中性持有（無配息資料）'
                _action_hint = '觀察'
            if _extra:
                _lamp += ' ｜ ' + ' / '.join(_extra)

        elif _is_sat:
            # 衛星：直接拿 σ 位階當燈號
            if _sigma_emoji:
                _lamp = f'{_sigma_emoji} {_sigma_label}'
                _action_hint = _sigma_action or '—'
            else:
                _lamp = '⚪ σ 資料不足'
                _action_hint = '—'

        else:
            # 其他角色：保留舊邏輯精簡版
            _warns = []
            if _yld and _yld > 0 and _ttl < _yld:
                _warns.append('賺息賠本')
            if _prem_pct is not None and _prem_pct > 1:
                _warns.append(f'溢價{_prem_pct:+.2f}%')
            _lamp = ('🔴 ' + ' ｜ '.join(_warns)) if _warns else '🟡 中性持有'
            _action_hint = '—'

        return {
            '代號': ticker, '名稱': name, '類型': role,
            '市價': round(_cur, 2),
            '折溢價%': (round(_prem_pct, 2) if _prem_pct is not None else None),
            '年化配息率%': (round(_yld, 2) if _yld else None),
            '1年含息報酬%': round(_ttl, 2),
            '距月線%': _bias20,
            '距季線%': _bias60,
            'σ位階': (f'{_sigma_emoji} {_sigma_label}' if _sigma_emoji else None),
            '走勢': _spark,
            '健康燈號': _lamp,
            '動作建議': _action_hint,
        }
    except Exception as e:
        print(f'[warroom/{ticker}] {type(e).__name__}: {e}')
        _empty['健康燈號'] = f'⚪ 計算失敗：{type(e).__name__}'
        return _empty


def calc_current_yield(df: pd.DataFrame, divs: pd.Series) -> float:
    """近12個月現金殖利率(%)"""
    if df.empty or divs.empty:
        return 0.0
    try:
        cutoff = df.index[-1] - timedelta(days=365)
        annual_div = float(divs[divs.index >= cutoff].sum())
        price = float(df['Close'].iloc[-1])
        return round(annual_div / price * 100, 2) if price > 0 else 0.0
    except Exception:
        return 0.0


def calc_total_return_1y(df: pd.DataFrame, divs: pd.Series) -> float:
    """近1年含息總報酬率(%)"""
    if df.empty:
        return 0.0
    try:
        cutoff = df.index[-1] - timedelta(days=365)
        df_1y = df[df.index >= cutoff]
        if len(df_1y) < 2:
            return 0.0
        p_start = float(df_1y['Close'].iloc[0])
        p_end   = float(df_1y['Close'].iloc[-1])
        div_sum = float(divs[divs.index >= cutoff].sum()) if not divs.empty else 0.0
        return round((p_end - p_start + div_sum) / p_start * 100, 2)
    except Exception:
        return 0.0


def calc_avg_yield(df: pd.DataFrame, divs: pd.Series, years: int = 5) -> float:
    """近N年平均殖利率（孫慶龍7%公式）"""
    if df.empty or divs.empty:
        return 0.0
    try:
        now = df.index[-1]
        result = []
        for y in range(years):
            y_start = now - timedelta(days=365 * (y + 1))
            y_end   = now - timedelta(days=365 * y)
            y_div   = float(divs[(divs.index >= y_start) & (divs.index < y_end)].sum())
            df_y    = df[(df.index >= y_start) & (df.index < y_end)]
            if df_y.empty or y_div <= 0:
                continue
            avg_p = float(df_y['Close'].mean())
            if avg_p > 0:
                result.append(y_div / avg_p * 100)
        return round(sum(result) / len(result), 2) if result else 0.0
    except Exception:
        return 0.0


def check_vcp_signal(df: pd.DataFrame) -> dict:
    """春哥 VCP 波幅收縮偵測"""
    r = {'signal': False, 'above_ma50': False, 'above_ma200': False,
         'vol_confirm': False, 'weekly_ranges': [], 'stop_loss': None}
    if df is None or len(df) < 210:
        return r
    try:
        close  = df['Close']
        last_c = float(close.iloc[-1])
        ma50   = float(close.rolling(50).mean().iloc[-1])
        ma200  = float(close.rolling(200).mean().iloc[-1])
        r['above_ma50']  = last_c > ma50
        r['above_ma200'] = last_c > ma200
        r['stop_loss']   = round(last_c * 0.92, 2)

        # 週K波幅（近5週）
        df_w = df.resample('W').agg({'High':'max','Low':'min',
                                       'Close':'last','Volume':'sum'}).dropna()
        if len(df_w) >= 6:
            ranges = []
            for i in range(-5, 0):
                row = df_w.iloc[i]
                mid = (float(row['High']) + float(row['Low'])) / 2
                if mid > 0:
                    ranges.append(round((float(row['High']) - float(row['Low'])) / mid * 100, 1))
            r['weekly_ranges'] = ranges
            if len(ranges) >= 5:
                early_avg = sum(ranges[:2]) / 2
                late_avg  = sum(ranges[-2:]) / 2
                shrinking = late_avg < early_avg * 0.6
                vol_ma50  = float(df['Volume'].rolling(50).mean().iloc[-1])
                vol_now   = float(df['Volume'].iloc[-1])
                r['vol_confirm'] = vol_now > vol_ma50
                r['signal'] = (r['above_ma50'] and r['above_ma200']
                                and shrinking and r['vol_confirm'])
    except Exception:
        pass
    return r


def calc_premium_discount(info: dict, df: "pd.DataFrame", ticker: str = '') -> dict:
    """折溢價率 = (市價 - 淨值) / 淨值 × 100
    核心原則：NAV 與市價必須來自同一日，避免跨來源日期錯位。
    主動式 ETF（代號末碼字母 e.g. 00980A）NAV 公布常 T+1 延遲，加三守門員：
      G1：NAV 最新日 vs 市價最新日相差 ≥1 交易日 → stale，回傳 N/A
      G2：主動式 ETF |prem| > 2.0% → 疑 NAV 同日寫入但數值未更新 → 回傳 N/A
      G3：NAV 最新日早於「前一交易日」→ 雙源同步落後（FinMind+yfinance 同日卡關）
    資料來源：1. TWSE OpenAPI 直讀（同日 NAV+市價+折溢價率）
              2. FinMind NAV history + df 同日 inner join（精確日期配對）
              3. yfinance info navPrice
    """
    import pandas as _pd_prem
    import re as _re_prem
    import datetime as _dt_prem
    _code_clean = ticker.replace('.TW', '').replace('.TWO', '') if ticker else ''
    _is_active_etf = bool(_re_prem.match(r'^\d{4,5}[A-Z]$', _code_clean))
    _ACTIVE_PREM_MAX = 2.0  # 主動式 ETF |prem| 門檻，超過判定 NAV stale

    def _prev_business_day(_d):
        _d2 = _d - _dt_prem.timedelta(days=1)
        while _d2.weekday() >= 5:   # 5=Sat, 6=Sun
            _d2 -= _dt_prem.timedelta(days=1)
        return _d2
    _PREV_BD = _prev_business_day(_dt_prem.date.today())

    _stale_payload = {'nav': None, 'price': None, 'premium_pct': None,
                      'warning': False, 'stale_nav': True}
    try:
        if ticker:
            _nav_hist = fetch_etf_nav_history(ticker, days=10)
            if not _nav_hist.empty and 'nav' in _nav_hist.columns:
                _last = _nav_hist.iloc[-1]

                # ── 路徑A：TWSE 已含同日折溢價率，直接使用 ──
                if 'premium_pct' in _nav_hist.columns:
                    _prem_val = _last.get('premium_pct')
                    _price_val = _last.get('price', None)
                    if _prem_val is not None and not _pd_prem.isna(_prem_val):
                        _pv = float(_prem_val)
                        if _is_active_etf and abs(_pv) > _ACTIVE_PREM_MAX:
                            print(f'[折溢價-A/stale] {ticker}: prem={_pv}% > ±{_ACTIVE_PREM_MAX}%')
                            return _stale_payload
                        _latest_nav = float(_last['nav'])
                        _pr = float(_price_val) if _price_val else (_latest_nav * (1 + _pv / 100))
                        print(f'[折溢價-A] {ticker}: nav={_latest_nav} prem={_pv}% (TWSE直讀)')
                        return {'nav': _latest_nav, 'price': round(_pr, 4),
                                'premium_pct': _pv, 'warning': _pv > 1.0}

                # ── 路徑B：FinMind NAV history + df Same-Date Inner Join ──
                # 與「近30日淨值」表格相同的精確日期配對邏輯，杜絕日期錯位
                if not df.empty and 'Close' in df.columns:
                    _nav_df = _nav_hist[['date', 'nav']].copy()
                    _nav_df['date'] = _pd_prem.to_datetime(_nav_df['date']).dt.normalize()
                    _nav_df = _nav_df.set_index('date')
                    _price_s = df[['Close']].copy()
                    _price_s.index = _pd_prem.to_datetime(_price_s.index).normalize()
                    _merged = _nav_df.join(_price_s, how='inner').dropna()
                    if not _merged.empty:
                        _nav_date_used = _merged.index[-1]
                        _nav_d_only = _nav_date_used.date()
                        _price_latest = _price_s.index.max()
                        _gap_days = (_price_latest - _nav_date_used).days
                        if _gap_days >= 1:
                            print(f'[折溢價-B/stale-G1] {ticker}: NAV={_nav_d_only} 落後 {_gap_days}d')
                            return _stale_payload
                        # G3：雙源同步落後 — NAV 早於前一交易日，配對 OK 但整體資料過時
                        if _nav_d_only < _PREV_BD:
                            print(f'[折溢價-B/stale-G3] {ticker}: NAV={_nav_d_only} < prev BD {_PREV_BD}')
                            return _stale_payload
                        _row = _merged.iloc[-1]  # 最近一筆同日配對
                        _nav_v = float(_row['nav'])
                        _pr_v  = float(_row['Close'])
                        _prem  = round((_pr_v - _nav_v) / _nav_v * 100, 2)
                        if _is_active_etf and abs(_prem) > _ACTIVE_PREM_MAX:
                            print(f'[折溢價-B/stale-G2] {ticker}: prem={_prem}% > ±{_ACTIVE_PREM_MAX}%')
                            return _stale_payload
                        print(f'[折溢價-B] {ticker}: date={_nav_d_only} nav={_nav_v} price={_pr_v} prem={_prem}%')
                        return {'nav': _nav_v, 'price': _pr_v,
                                'premium_pct': _prem, 'warning': _prem > 1.0,
                                'data_date': _nav_d_only}

        print(f'[折溢價] {ticker}: 所有路徑失敗，回傳 N/A')
    except Exception as _ep:
        import traceback as _tb_p; print(f'[折溢價] 錯誤: {_ep}'); _tb_p.print_exc()
    return {'nav': None, 'price': None, 'premium_pct': None, 'warning': False}


def calc_tracking_error(df: pd.DataFrame, bench_df: pd.DataFrame) -> float:
    """追蹤誤差 = std(ETF日報酬 - 基準日報酬) × √252 × 100"""
    try:
        if df.empty or bench_df.empty:
            return None
        etf_r   = df['Close'].pct_change().dropna()
        bench_r = bench_df['Close'].pct_change().dropna()
        common  = etf_r.index.intersection(bench_r.index)
        if len(common) < 20:
            return None
        diff = etf_r.loc[common] - bench_r.loc[common]
        return round(float(diff.std() * (252 ** 0.5) * 100), 2)
    except Exception:
        return None


def calc_mdd(df: pd.DataFrame) -> float:
    """最大回撤 MDD(%)"""
    try:
        close    = df['Close']
        roll_max = close.cummax()
        return round(float(((close - roll_max) / roll_max * 100).min()), 2)
    except Exception:
        return None


def calc_cagr(df: pd.DataFrame) -> float:
    """年化報酬率 CAGR(%)"""
    try:
        if len(df) < 2:
            return 0.0
        days  = (df.index[-1] - df.index[0]).days
        if days < 30:
            return 0.0
        y     = days / 365.25
        start = float(df['Close'].iloc[0])
        end   = float(df['Close'].iloc[-1])
        return round(((end / start) ** (1 / y) - 1) * 100, 2)
    except Exception:
        return 0.0


def calc_sharpe(df: pd.DataFrame, rf: float = 5.33) -> float:
    """夏普值（年化，rf預設5.33% FEDFUNDS）"""
    try:
        ret     = df['Close'].pct_change().dropna()
        if len(ret) < 20:
            return 0.0
        ann_ret = float(ret.mean() * 252 * 100)
        ann_vol = float(ret.std() * (252 ** 0.5) * 100)
        return round((ann_ret - rf) / ann_vol, 2) if ann_vol > 0 else 0.0
    except Exception:
        return 0.0


def auto_detect_benchmark(ticker: str) -> str:
    t = ticker.upper()
    if t.endswith('.TW') or t.endswith('.TWO'):
        return '0050.TW'
    return '^GSPC'


@st.cache_data(ttl=3600, max_entries=50, show_spinner=False)
def compute_etf_peer_ranking(ticker: str, periods: tuple = (63, 126, 252)) -> dict:
    """ETF 同儕近 3M/6M/1Y 報酬排名（總報酬率含息，用 yfinance Adj Close）。

    Parameters
    ----------
    ticker : str
        目標 ETF 代號，如 '0050.TW'。
    periods : tuple[int, ...]
        交易日視窗（預設 63=3M、126=6M、252=1Y）。

    Returns
    -------
    dict
      命中：{63: {'self_ret': float, 'peer_median': float, 'percentile': float,
                  'peer_count': int}, 126: {...}, 252: {...},
             'category': str, 'peers': list[str]}
      無同儕：{'_err': '同儕資料不足', 'category': ''}
    """
    from etf_categories import get_peers, get_category_name
    _peers = get_peers(ticker)
    _category = get_category_name(ticker)
    if len(_peers) < 3:
        return {'_err': '同儕資料不足', 'category': _category, 'peers': _peers}
    _all = [ticker] + _peers
    _result: dict = {'category': _category, 'peers': _peers}
    try:
        _hist = yf.download(_all, period='2y', auto_adjust=True,
                            progress=False, threads=False)
        # yf.download 多 ticker 回 MultiIndex (column 0=field, 1=ticker)；單一回扁平
        if isinstance(_hist.columns, pd.MultiIndex):
            _close = _hist['Close']
        else:
            _close = _hist[['Close']].rename(columns={'Close': _all[0]})
        if _close.empty:
            return {'_err': 'yfinance 抓不到價格', 'category': _category, 'peers': _peers}
        for _p in periods:
            if len(_close) < _p + 1:
                _result[_p] = {'_err': f'資料不足 {_p} 日'}
                continue
            _window = _close.iloc[-(_p + 1):]
            _rets = (_window.iloc[-1] / _window.iloc[0] - 1.0) * 100.0
            _rets = _rets.dropna()
            if ticker not in _rets.index or len(_rets) < 3:
                _result[_p] = {'_err': '有效樣本不足'}
                continue
            _self = float(_rets[ticker])
            _peer_only = _rets.drop(ticker)
            _median = float(_peer_only.median())
            # percentile：self 高於 N% 同儕；用 strict less 計
            _pct = float((_peer_only < _self).sum()) / len(_peer_only) * 100.0
            _result[_p] = {
                'self_ret': round(_self, 2),
                'peer_median': round(_median, 2),
                'percentile': round(_pct, 1),
                'peer_count': len(_peer_only),
            }
        return _result
    except Exception as _e:
        import traceback as _tb_pr
        print(f'[peer-rank] {ticker} ❌ {type(_e).__name__}: {_e}')
        _tb_pr.print_exc()
        return {'_err': f'{type(_e).__name__}', 'category': _category, 'peers': _peers}


# ══════════════════════════════════════════════════════════════
# 持股重疊度（Holdings Overlap）— 純函式，零外部依賴
# ══════════════════════════════════════════════════════════════
def calc_holdings_overlap_pct(h1, h2):
    """權重 Overlap%：兩 ETF 共同持股、取較小權重加總。業界標準同質性指標。

    公式：Σ min(w_A_i, w_B_i)  for i in (A ∩ B)

    語意：兩檔 ETF 同一支股票，A 配 5%、B 配 10% → 只算 5%（重疊部分）。
    結果 0-100%，數值越高表示組合越同質。

    Parameters
    ----------
    h1, h2 : dict[str, float] | None
        個股名 → 權重百分比（如 5.0 表示 5%）。None/空 dict 回 0.0。

    Returns
    -------
    float  0-100，已四捨五入到小數點 2 位。
    """
    if not h1 or not h2:
        return 0.0
    _common = set(h1.keys()) & set(h2.keys())
    if not _common:
        return 0.0
    _overlap = 0.0
    for _k in _common:
        try:
            _overlap += min(float(h1[_k]), float(h2[_k]))
        except (TypeError, ValueError):
            continue
    return round(min(_overlap, 100.0), 2)


def calc_jaccard_overlap(h1, h2):
    """Jaccard 集合重疊：|A ∩ B| / |A ∪ B| × 100%。

    只看「有沒有同一支股票」，**完全忽略權重**。適合比較持股清單骨架是否雷同。
    與 `calc_holdings_overlap_pct` 互補：
      - Jaccard 高 + Overlap 低 → 持股名單雷同但權重分布差異大
      - Jaccard 低 + Overlap 高 → 少數共同持股被重壓（風險集中）
      - 兩者都高 → 同質性極高，分散效益差

    Parameters
    ----------
    h1, h2 : dict[str, float] | None | iterable
        只取 keys（個股名）。None/空回 0.0。

    Returns
    -------
    float  0-100，已四捨五入到小數點 2 位。
    """
    if not h1 or not h2:
        return 0.0
    _s1 = set(h1.keys() if hasattr(h1, 'keys') else h1)
    _s2 = set(h2.keys() if hasattr(h2, 'keys') else h2)
    _union = _s1 | _s2
    if not _union:
        return 0.0
    return round(len(_s1 & _s2) / len(_union) * 100, 2)


def build_holdings_overlap_matrix(holdings_dict, method='weight'):
    """建立 ETF × ETF 持股重疊矩陣（0-100%）。對角線恆為 100。

    Parameters
    ----------
    holdings_dict : dict[str, dict[str, float] | None]
        key=ETF ticker，value=該 ETF 的成份股字典（calc_holdings_overlap_pct 的輸入）。
        value 為 None / 空者：該 ETF 對應行列全標 NaN（UI 端顯示為灰色 N/A）。
    method : 'weight' | 'jaccard'
        'weight' → 用 `calc_holdings_overlap_pct`（業界標準）
        'jaccard' → 用 `calc_jaccard_overlap`（集合重疊）

    Returns
    -------
    pandas.DataFrame  N×N 對稱矩陣，index/columns 都是 ticker。
    """
    import pandas as _pd
    import numpy as _np
    _tickers = list(holdings_dict.keys())
    _func = calc_jaccard_overlap if method == 'jaccard' else calc_holdings_overlap_pct
    _n = len(_tickers)
    _mat = _np.full((_n, _n), _np.nan, dtype=float)
    for _i, _ta in enumerate(_tickers):
        _ha = holdings_dict.get(_ta)
        if not _ha:
            continue
        _mat[_i, _i] = 100.0
        for _j in range(_i + 1, _n):
            _tb = _tickers[_j]
            _hb = holdings_dict.get(_tb)
            if not _hb:
                continue
            _v = _func(_ha, _hb)
            _mat[_i, _j] = _v
            _mat[_j, _i] = _v
    return _pd.DataFrame(_mat, index=_tickers, columns=_tickers)


# ══════════════════════════════════════════════════════════════
# 主動 ETF 弱勢度檢測（PR — claude/etf-weakness-manager）
# Gemini 邏輯：大跌時跌得比大盤深 + 反彈時漲得比大盤慢 + 連兩季輸盤 = 該換
# ══════════════════════════════════════════════════════════════
def calc_weakness_metrics(etf_returns, bench_returns):
    """主動 ETF 弱勢度核心指標（純函式，無 I/O）。

    輸入兩條日報酬序列（pct_change 已算好），對齊後計算：
      - 大跌弱勢率 down_ratio: 大盤跌日中 ETF 跌更深的比例 (0-100%)
      - 反彈弱勢率 up_ratio:   大盤漲日中 ETF 漲更慢的比例 (0-100%)
      - 季報酬輸盤連續數 quarter_lose_streak: 用 quarter 重採樣
        最近 N 季 ETF 季報酬 < bench 季報酬的「連續」最近季數
      - Tracking error te_pct: 日報酬差的年化標準差 (%)

    Returns
    -------
    dict 7 個 key；資料 < 30 天 → {'_err': 'insufficient_data', 'sample': N}
    """
    import pandas as _pd_w
    import numpy as _np_w
    if etf_returns is None or bench_returns is None:
        return {'_err': 'none_input'}
    _df = _pd_w.concat([etf_returns, bench_returns], axis=1, keys=['etf', 'bench']).dropna()
    if len(_df) < 30:
        return {'_err': 'insufficient_data', 'sample': int(len(_df))}

    _down = _df[_df['bench'] < 0]
    _up = _df[_df['bench'] > 0]
    _down_n = len(_down)
    _up_n = len(_up)
    _down_lose = int((_down['etf'] < _down['bench']).sum()) if _down_n > 0 else 0
    _up_lose = int((_up['etf'] < _up['bench']).sum()) if _up_n > 0 else 0
    _down_ratio = round(_down_lose / _down_n * 100, 1) if _down_n > 0 else 0.0
    _up_ratio = round(_up_lose / _up_n * 100, 1) if _up_n > 0 else 0.0

    # 季報酬：cumprod 算 quarterly compound return
    _etf_q = (1 + _df['etf']).resample('QE').prod() - 1
    _bench_q = (1 + _df['bench']).resample('QE').prod() - 1
    _q_cmp = _pd_w.concat([_etf_q, _bench_q], axis=1, keys=['etf', 'bench']).dropna()
    _streak = 0
    for _i in range(len(_q_cmp) - 1, -1, -1):
        if _q_cmp['etf'].iloc[_i] < _q_cmp['bench'].iloc[_i]:
            _streak += 1
        else:
            break

    _diff = _df['etf'] - _df['bench']
    _te = float(_diff.std() * _np_w.sqrt(252) * 100) if _diff.std() > 0 else 0.0

    return {
        'down_days': _down_n,
        'down_loss_days': _down_lose,
        'down_ratio': _down_ratio,
        'up_days': _up_n,
        'up_miss_days': _up_lose,
        'up_ratio': _up_ratio,
        'quarter_lose_streak': _streak,
        'te_pct': round(_te, 2),
        'sample': len(_df),
    }


def _auto_bench_for_etf(ticker: str) -> str:
    """根據 ETF ticker suffix 自動選 benchmark。

    .TW / .TWO / 純數字 → ^TWII（台股加權）；其他 → ^GSPC（S&P 500）
    """
    _t = (ticker or '').upper().strip()
    if _t.endswith('.TW') or _t.endswith('.TWO') or _t.replace('.', '').isalnum() and any(c.isdigit() for c in _t[:4]):
        _code = _t.replace('.TW', '').replace('.TWO', '')
        if _code and _code[0].isdigit():
            return '^TWII'
    return '^GSPC'


@st.cache_data(ttl=900, max_entries=50, show_spinner=False)
def compute_etf_weakness_row(ticker: str, name: str = '',
                              bench_ticker: str | None = None,
                              period: str = '1y') -> dict:
    """高階組裝：抓 ETF / benchmark 價格 → 算 returns → 呼叫 calc_weakness_metrics
    + 抓經理人。回傳給 UI 使用的整列 dict。
    """
    from etf_fetch import is_active_etf, fetch_etf_manager
    _bench = bench_ticker or _auto_bench_for_etf(ticker)
    _is_act = is_active_etf(ticker)

    _row = {
        '代號': ticker, '名稱': name or ticker,
        '主被動': '主動式' if _is_act else '被動式',
        'benchmark': _bench,
        '經理人': '—', '任期': '—',
        '大跌弱勢率%': None, '反彈弱勢率%': None,
        '連敗季數': None, 'TE%': None, '樣本日': 0,
        '燈號': '⚪ 未檢測', '動作建議': '—',
    }
    if not _is_act:
        _row['燈號'] = '⚪ 被動追蹤型，免測弱勢'
        _row['動作建議'] = '長期持有；觀察 tracking error'

    try:
        _etf_df = fetch_etf_price(ticker, period=period)
        _bench_df = fetch_etf_price(_bench, period=period)
        if _etf_df.empty or _bench_df.empty:
            _row['燈號'] = '⚪ 價格資料不足'
            return _row
        _er = _etf_df['Close'].pct_change()
        _br = _bench_df['Close'].pct_change()
        _m = calc_weakness_metrics(_er, _br)
        if '_err' in _m:
            _row['燈號'] = f'⚪ {_m.get("_err", "calc_err")} (n={_m.get("sample", 0)})'
            return _row
        _row['大跌弱勢率%'] = _m['down_ratio']
        _row['反彈弱勢率%'] = _m['up_ratio']
        _row['連敗季數'] = _m['quarter_lose_streak']
        _row['TE%'] = _m['te_pct']
        _row['樣本日'] = _m['sample']
    except Exception as _e:
        print(f'[weakness/{ticker}] {type(_e).__name__}: {_e}')
        _row['燈號'] = f'⚪ 抓取失敗：{type(_e).__name__}'
        return _row

    _tenure_days = None
    if _is_act:
        _mg = fetch_etf_manager(ticker)
        if _mg:
            _row['經理人'] = _mg.get('name', '—')
            _tenure_days = _mg.get('tenure_days')
            if _tenure_days is not None:
                _row['任期'] = (f'{_tenure_days // 30} 個月' if _tenure_days < 365
                              else f'{_tenure_days / 365:.1f} 年')
            elif _mg.get('since'):
                _row['任期'] = f'自 {_mg["since"]}'

    if _is_act:
        _down = _row['大跌弱勢率%'] or 0
        _up = _row['反彈弱勢率%'] or 0
        _streak = _row['連敗季數'] or 0
        _new_manager = isinstance(_tenure_days, int) and _tenure_days < 180
        if _streak >= 2:
            _row['燈號'] = f'🚨 連續{_streak}季輸盤'
            _row['動作建議'] = ('⏳ 新經理人 <6 月，再給時間'
                              if _new_manager
                              else '考慮換到大盤被動式 ETF（如 0050）')
        elif _down > 60 and _up > 60:
            _row['燈號'] = '🔴 雙向弱勢'
            _row['動作建議'] = '近期表現雙向落後大盤；觀察 1-2 季'
        elif _down > 60:
            _row['燈號'] = '🟡 大跌弱勢'
            _row['動作建議'] = '下跌防禦力不足，注意'
        elif _up > 60:
            _row['燈號'] = '🟡 反彈無力'
            _row['動作建議'] = '反彈追不上大盤，績效落後'
        else:
            _row['燈號'] = '🟢 體質正常'
            _row['動作建議'] = '續抱觀察'

    return _row
