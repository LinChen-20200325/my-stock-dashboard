"""
ETF AI 儀表板核心引擎 v1.0
Tab ⑥ 單一 ETF 深度診斷 | Tab ⑦ 組合配置 | Tab ⑧ 回測 | Tab ⑨ AI 綜合評斷
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import yfinance as yf
from datetime import timedelta
from unified_decision import render_unified_decision
from daily_checklist import calc_stats

def _fetch_news_for(ticker: str, name: str = "", n: int = 4) -> str:
    """抓取個股/ETF 相關新聞，回傳格式化字串。失敗時回傳空字串。"""
    try:
        import feedparser as _fp, html as _h, re as _re2
    except ImportError:
        return ""
    _q = f"{ticker} {name}".strip()
    _feeds = [
        f'https://news.google.com/rss/search?q={_q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant',
        f'https://news.google.com/rss/search?q=Taiwan+ETF+{ticker}&hl=en-US&gl=US&ceid=US:en',
    ]
    _out = []
    for _url in _feeds:
        try:
            for _e in _fp.parse(_url).entries:
                _t = _h.unescape(_e.get('title', '')).strip()
                _p = str(_e.get('published', ''))[:10]
                if _t:
                    _out.append(f'- {_t}（{_p}）')
                if len(_out) >= n:
                    break
        except Exception:
            pass
        if len(_out) >= n:
            break
    return '\n'.join(_out[:n]) if _out else '（暫無相關新聞）'


# ── 總經連動配置建議表 ────────────────────────────────────────
MACRO_ALLOC = {
    'bull':    {'股票型ETF': 70, '債券型ETF': 15, '貨幣/現金': 15},
    'neutral': {'股票型ETF': 50, '債券型ETF': 30, '貨幣/現金': 20},
    'bear':    {'股票型ETF': 20, '債券型ETF': 50, '貨幣/現金': 30},
}
MACRO_DESC = {
    'bull':    '🟢 多頭市場：加大股票型ETF比重，可佈局成長型/科技型ETF',
    'neutral': '🟡 中性市場：股債平衡，降低單一類型集中度',
    'bear':    '🔴 空頭市場：大幅降低股票曝險，增加投資級債券ETF + 現金',
}

# ═══════════════════════════════════════════════════════════════
# 快取資料層
# ═══════════════════════════════════════════════════════════════

# ── MK 規格 條件 B：台灣 ETF 發行價對照表（用於破發檢測）──────
# 台灣常見 ETF 發行價（多為 10/15/20/30/40 元）；債券 ETF 多為 40 元
_TW_ETF_LAUNCH_PRICE = {
    '0050': 36.98, '0051': 25.57, '0052': 36.99, '0053': 22.20,
    '0055': 12.95, '0056': 25.20, '0057': 38.10,
    '006203': 25, '006204': 30, '006208': 30, '00646': 20,
    '00692': 20, '00701': 20, '00713': 20, '00730': 20,
    '00731': 20, '00733': 20, '00735': 20, '00850': 20,
    '00878': 15, '00881': 15, '00882': 15, '00891': 15,
    '00892': 15, '00893': 15, '00895': 15, '00896': 15,
    '00897': 15, '00898': 15, '00899': 15, '00900': 15,
    '00901': 15, '00902': 15, '00903': 15, '00904': 15,
    '00905': 15, '00907': 15, '00910': 15, '00911': 15,
    '00912': 15, '00913': 15, '00915': 15, '00916': 15,
    '00918': 15, '00919': 20, '00920': 15, '00921': 15,
    '00922': 15, '00923': 15, '00924': 15, '00925': 15,
    '00927': 15, '00929': 15, '00930': 15, '00932': 15,
    '00934': 10, '00935': 10, '00936': 10, '00939': 15,
    '00940': 10, '00941': 10, '00942B': 15, '00943': 15,
    '00944': 10, '00945B': 15, '00946': 10, '00947': 10,
    # 債券 ETF 多為 40 元起始
    '00679B': 40, '00687B': 40, '00696B': 40, '00697B': 40,
    '00710B': 40, '00711B': 40, '00712':  20, '00714':  30,
    '00718B': 40, '00719B': 40, '00720B': 40, '00721B': 40,
    '00722B': 40, '00723B': 40, '00724B': 40, '00725B': 40,
    '00726B': 40, '00727B': 40, '00772B': 40, '00773B': 40,
    '00777B': 40, '00778B': 40, '00779B': 40, '00780B': 40,
    '00781B': 40, '00782B': 40, '00783B': 40, '00784B': 40,
    '00785B': 40, '00786B': 40, '00787B': 40, '00788B': 40,
    '00795B': 40, '00834B': 40, '00836B': 40, '00837B': 40,
    '00840B': 40, '00845B': 40, '00846B': 40, '00847B': 40,
    '00848B': 40, '00849B': 40, '00853B': 40, '00857B': 40,
    '00859B': 40, '00860B': 40, '00862B': 40, '00863B': 40,
    '00864B': 40, '00865B': 40, '00867B': 40, '00870B': 40,
    '00883B': 40, '00890B': 40, '00937B': 40,
}


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


def _get_etf_launch_price(ticker: str, df: "pd.DataFrame|None" = None):
    """取得 ETF 發行價（用於 MK 規格條件 B 破發檢測）。

    優先序：
    1. 內建台灣 ETF 對照表（最精準）
    2. df 首個交易日收盤價（已還原權息，僅供 fallback 估算）

    Returns
    -------
    float | None
    """
    _code = (ticker or '').replace('.TWO', '').replace('.TW', '').upper().strip()
    _v = _TW_ETF_LAUNCH_PRICE.get(_code)
    if _v is not None:
        return float(_v)
    # fallback：用 df 第一筆收盤估算（僅當美股 ETF / 未收錄者）
    try:
        if df is not None and len(df) > 0:
            return float(df['Close'].iloc[0])
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600, max_entries=10)
def fetch_etf_price(ticker: str, period: str = '5y') -> pd.DataFrame:
    """取得 ETF 歷史價格（auto_adjust=True 還原權息）"""
    try:
        df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df.ffill()
    except Exception as e:
        st.error(f'❌ 無法取得 {ticker} 價格：{e}')
        return pd.DataFrame()

@st.cache_data(ttl=3600, max_entries=10)
def fetch_etf_dividends(ticker: str) -> pd.Series:
    """取得 ETF 歷史配息"""
    try:
        divs = yf.Ticker(ticker).dividends
        if divs.empty:
            return pd.Series(dtype=float)
        divs.index = pd.to_datetime(divs.index).tz_localize(None)
        return divs
    except Exception:
        return pd.Series(dtype=float)

@st.cache_data(ttl=3600, max_entries=10)
def fetch_etf_info(ticker: str) -> dict:
    """取得 ETF 基本資訊（費用率/Beta/AUM）"""
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}

def fetch_sitca_expense_ratio(ticker: str, *, attempts: int = 1):
    """從 SITCA 投信投顧公會抓台股 ETF 內扣費用率（Primary，海外 IP 走 NAS proxy）。

    URL: https://www.sitca.org.tw/ROC/Industry/IN2211.aspx?pid=IN2222_01

    Returns
    -------
    float | None  比例形式（0.0036 = 0.36%）；找不到 ticker 或抓取失敗回 None。
    """
    from proxy_helper import fetch_url as _fu_sit
    import pandas as _pd_sit, re as _re_sit
    _t = (ticker or '').replace('.TW', '').replace('.tw', '').strip()
    if not _t or not _t.isdigit():
        return None  # SITCA 只收純台股 ETF 數字代號（0050、00878 等）
    try:
        r = _fu_sit(
            'https://www.sitca.org.tw/ROC/Industry/IN2211.aspx?pid=IN2222_01',
            timeout=15, attempts=attempts,
        )
        if r is None or r.status_code != 200:
            return None
        r.encoding = 'utf-8'
        # ASP.NET 頁面通常一張總費用率表；多表都試找含「代號」+「費用率」欄位的那張
        tables = _pd_sit.read_html(r.text)
        # ticker 標準化：去掉 leading 0（治 pandas 把 "0050" parse 成 int 50 的場景）
        _tn = _t.lstrip('0') or '0'
        for tbl in tables:
            # 注意：column 可能是 MultiIndex tuple，比對用 str(c)，但取值用原物件 c
            code_col = next((c for c in tbl.columns
                             if any(k in str(c) for k in ('代號', 'ETF', 'Code'))), None)
            rate_col = next((c for c in tbl.columns
                             if '費用率' in str(c) or '費用比率' in str(c)), None)
            if code_col is None or rate_col is None:
                continue
            # 雙向 leading-zero 容忍：cell 也 strip leading 0 後比對
            _digits = tbl[code_col].astype(str).str.replace(r'\D', '', regex=True)
            row = tbl[_digits.where(_digits != '', '0').str.lstrip('0').replace('', '0') == _tn]
            if row.empty:
                continue
            raw = str(row[rate_col].iloc[0])
            m = _re_sit.search(r'(\d+(?:\.\d+)?)', raw)
            if not m:
                continue
            v = float(m.group(1))
            # SITCA 表格數字常見已是百分比（0.36 = 0.36%），標準化成「比例」回傳
            print(f'[SITCA/expense] ✅ {_t} = {v}% (col={rate_col})')
            return v / 100.0
        print(f'[SITCA/expense] ⚠️ {_t} 未找到符合 column 的表格 (tables={len(tables)})')
        return None
    except Exception as e:
        print(f'[SITCA/expense] ❌ {_t}: {type(e).__name__}: {e}')
        return None


def fetch_moneydj_expense_ratio(ticker: str):
    """從 MoneyDJ ETF Basic0004 頁面抓「經理費 + 保管費」總費用率（私募/已下市 ETF 備援）。

    URL: https://www.moneydj.com/ETF/X/Basic/Basic0004.xdjhtm?etfid=XXXX.TW

    Returns
    -------
    float | None  比例形式（0.0036 = 0.36%）；找不到或抓取失敗回 None。
    """
    import re as _re_mdje
    _t = (ticker or '').replace('.tw', '.TW').strip()
    if not _t:
        return None
    # MoneyDJ etfid 通常吃 '0050.TW' 格式；純數字補 .TW
    if _t.isdigit():
        _t = f'{_t}.TW'
    _url = f'https://www.moneydj.com/ETF/X/Basic/Basic0004.xdjhtm?etfid={_t}'
    _hdrs = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8',
        'Referer': 'https://www.moneydj.com/',
    }
    try:
        # curl_cffi Chrome TLS 指紋優先；失敗降級 requests
        try:
            from curl_cffi import requests as _cffi_mdje
            _r = _cffi_mdje.get(_url, impersonate='chrome124', timeout=12)
        except Exception:
            import requests as _rq_mdje
            _r = _rq_mdje.get(_url, headers=_hdrs, timeout=12, verify=False)
        if _r.status_code != 200:
            print(f'[MoneyDJ/expense] {_t}: HTTP {_r.status_code}')
            return None
        _txt = _r.text
        # 直掃「經理費 X.XX%」與「保管費 X.XX%」合計；MoneyDJ Basic0004 表格常以 td 緊鄰呈現
        _mng = _re_mdje.search(r'經理費[^\d%]{0,30}?(\d+(?:\.\d+)?)\s*%', _txt)
        _cus = _re_mdje.search(r'保管費[^\d%]{0,30}?(\d+(?:\.\d+)?)\s*%', _txt)
        if _mng and _cus:
            _total = float(_mng.group(1)) + float(_cus.group(1))
            print(f'[MoneyDJ/expense] ✅ {_t} = {_total}% (mng={_mng.group(1)}+cus={_cus.group(1)})')
            return _total / 100.0
        # Fallback：找「總費用率 / 內含費用率」單一欄位
        _tot = _re_mdje.search(r'(?:總費用率|內含費用率|費用率)[^\d%]{0,30}?(\d+(?:\.\d+)?)\s*%', _txt)
        if _tot:
            _v = float(_tot.group(1))
            print(f'[MoneyDJ/expense] ✅ {_t} = {_v}% (總費用率欄位)')
            return _v / 100.0
        print(f'[MoneyDJ/expense] ⚠️ {_t} 頁面無「經理費/保管費/總費用率」欄位')
        return None
    except Exception as _e:
        print(f'[MoneyDJ/expense] ❌ {_t}: {type(_e).__name__}: {_e}')
        return None


def get_etf_expense_ratio_safe(ticker: str):
    """安全讀取 ETF 費用率：SITCA → MoneyDJ → yfinance 三段備援；缺失回 None 不崩潰"""
    # 1. 台股 ETF（純數字代號）優先走 SITCA（投信投顧公會官方），yfinance 對 .TW 票常 stale
    _sit = fetch_sitca_expense_ratio(ticker)
    if _sit is not None:
        return _sit
    # 2. MoneyDJ Basic0004（私募/已下市/SITCA 未收錄的台股 ETF 兜底）
    _mdj = fetch_moneydj_expense_ratio(ticker)
    if _mdj is not None:
        return _mdj
    # 3. yfinance.info（海外 ETF 主要來源；台股 ETF 末段保險）
    try:
        info = fetch_etf_info(ticker)
        return (info.get('annualReportExpenseRatio')
                or info.get('totalExpenseRatio')
                or info.get('expenseRatio'))
    except Exception:
        return None

# ═══════════════════════════════════════════════════════════════
# 計算函式
# ═══════════════════════════════════════════════════════════════

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

# ── NAV 合理範圍常數（用於 fetch_etf_nav_history 多源 sanity check）──
_NAV_MIN, _NAV_MAX = 0.5, 100000


def _safe_float(s, strip_chars: str = ',%') -> float | None:
    """安全 float 解析：失敗回 None。

    Replaces inline `try: float(...) except: pass` pattern；避免 bare except
    吞掉 KeyboardInterrupt / SystemExit。
    """
    try:
        _t = str(s).strip()
        for _c in strip_chars:
            _t = _t.replace(_c, '')
        return float(_t) if _t else None
    except (ValueError, TypeError):
        return None


@st.cache_data(ttl=7200, show_spinner=False, max_entries=10)
def fetch_etf_nav_history(ticker: str, days: int = 35, ver: int = 4) -> "pd.DataFrame":
    """ETF 歷史淨值及折溢價（最近 N 個交易日）

    資料來源優先順序（5 段備援 + 1 兜底）：
      1. FinMind TaiwanETFNetAssetValue（批次，有/無 token 皆可）
      2. goodinfo.tw StockDetail（不受 TWSE IP 封鎖）
      3. TWSE OpenAPI（僅 NAS Proxy 環境）
      4. MoneyDJ BeautifulSoup
      5. yfinance navPrice
      *. 兜底：FinMind 過舊資料（前述 5 段全失敗時）

    Args
    ----
    ticker : str  ETF 代號（含 .TW 後綴）
    days   : int  目標回溯交易日（含緩衝 +10 日）
    ver    : int  cache key bumper — 升版觸發 @st.cache_data 失效；不入函式邏輯。

    Returns
    -------
    pd.DataFrame  欄位：date / price / nav / premium / premium_pct
    """
    import os
    import datetime as _dt
    import requests as _rq_etfnav
    code = ticker.replace('.TW', '').replace('.TWO', '')
    # st.secrets 優先（Streamlit Cloud secrets 不自動匯出至 os.environ）
    token = (getattr(st, 'secrets', {}).get('FINMIND_TOKEN')
             or os.environ.get('FINMIND_TOKEN', ''))
    start = (_dt.date.today() - _dt.timedelta(days=days + 10)).strftime('%Y-%m-%d')
    _df_stale = None       # 備援：FinMind 過舊資料
    _days_stale: int | None = None

    # ── 1. FinMind ETF NAV（試兩個 dataset 名稱 + 多種欄位名稱）───────────
    for _ds1 in ['TaiwanETFNetAssetValue', 'TaiwanStockETFNAV']:
        try:
            _p = {'dataset': _ds1, 'data_id': code, 'start_date': start}
            if token: _p['token'] = token
            _r = _rq_etfnav.get('https://api.finmindtrade.com/api/v4/data', params=_p,
                                  timeout=15)
            _j = _r.json()
            _jstatus = _j.get('status')
            _jdata   = _j.get('data')
            # 接受 status=200 / status=None（部分 proxy 環境）；排除已知錯誤碼
            _status_ok = str(_jstatus) not in ('400', '401', '402', '403', '404', '500')
            if _jdata and _status_ok:
                _df = pd.DataFrame(_jdata)
                # 自動偵測 NAV 欄位名稱（FinMind 兩個版本欄位名不同）
                _nav_field = next((f for f in ['nav', 'base_unit_net_value', 'NavPrice', 'netAssetValue']
                                   if f in _df.columns), None)
                if _nav_field is None:
                    print(f'[ETF NAV] {code} {_ds1}: 找不到 NAV 欄位，現有={list(_df.columns)}')
                    continue
                _df['date'] = pd.to_datetime(_df['date']).dt.date
                _df['nav']  = pd.to_numeric(_df[_nav_field], errors='coerce')
                _df = _df[_df['nav'].notna() & (_df['nav'] > 0)].sort_values('date')
                if _df.empty:
                    print(f'[ETF NAV] {code} {_ds1}: 所有 nav 欄位為空/NaN，跳過')
                    continue
                _latest_d   = _df['date'].iloc[-1]
                _days_stale = (_dt.date.today() - _latest_d).days
                _df_stale   = _df[['date', 'nav']]   # 保留，供 path 4 備援
                print(f'[ETF NAV] {code} {_ds1}(field={_nav_field}): {len(_df)} 筆, 最新={_latest_d}, 距今={_days_stale}d')
                if _days_stale <= 14:          # 14天內視為可用（含連假/公告延遲）
                    return _df_stale
                print(f'[ETF NAV] {_ds1} {code} 資料較舊({_days_stale}d)，嘗試其他來源')
                break   # 找到資料就不再嘗試第二個 dataset
            else:
                _msg = str(_j.get('msg', ''))[:80]
                print(f'[ETF NAV] FinMind {_ds1} {code}: status={_jstatus} data_len={len(_jdata) if _jdata else 0} msg={_msg}')
        except Exception as _e1:
            print(f'[ETF NAV] FinMind {_ds1} {code}: {_e1}')

    # ── 2. goodinfo.tw — 不受 TWSE IP 封鎖，抓取 ETF 淨值 ───────────────────
    try:
        from bs4 import BeautifulSoup as _BS4_gi
        import re as _re_gi
        _url_gi = f'https://goodinfo.tw/tw/StockDetail.asp?STOCK_ID={code}'
        _hdrs_gi = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'zh-TW,zh;q=0.9', 'Referer': 'https://goodinfo.tw/tw/'}
        try:
            from curl_cffi import requests as _cffi_gi
            _r_gi = _cffi_gi.get(_url_gi, impersonate='chrome124', timeout=12)
        except Exception:
            _r_gi = _rq_etfnav.get(_url_gi, headers=_hdrs_gi, timeout=12, verify=False)
        if _r_gi.status_code == 200:
            _soup_gi = _BS4_gi(_r_gi.text, 'lxml')
            _nav_gi, _prem_gi = None, None
            # 策略1：在 <td> 中找「淨值」標籤，取下一格數字
            for _td_gi in _soup_gi.find_all('td'):
                _txt_gi = _td_gi.get_text(strip=True)
                if _txt_gi in ('淨值', '每單位淨值', 'NAV'):
                    _sib_gi = _td_gi.find_next_sibling('td')
                    if _sib_gi:
                        _v = _safe_float(_sib_gi.get_text(strip=True))
                        if _v is not None and _NAV_MIN < _v < _NAV_MAX:
                            _nav_gi = _v
                    if _nav_gi:
                        break
            # 策略2：regex 掃全文
            if not _nav_gi:
                _m_gi = _re_gi.search(r'淨值[^\d<]{0,30}?(\d{1,5}\.\d{2,6})', _r_gi.text)
                if _m_gi:
                    _v = _safe_float(_m_gi.group(1))
                    if _v is not None and _NAV_MIN < _v < _NAV_MAX:
                        _nav_gi = _v
            # 嘗試抓折溢價率
            if _nav_gi:
                for _td_gi2 in _soup_gi.find_all('td'):
                    if '折溢價' in _td_gi2.get_text(strip=True):
                        _sib_gi2 = _td_gi2.find_next_sibling('td')
                        if _sib_gi2:
                            _m_p = _re_gi.search(r'([+-]?\d+\.?\d*)', _sib_gi2.get_text(strip=True))
                            if _m_p:
                                _prem_gi = _safe_float(_m_p.group(1))
                        if _prem_gi is not None:
                            break
                _row_gi = {'date': _dt.date.today(), 'nav': _nav_gi}
                if _prem_gi is not None: _row_gi['premium_pct'] = _prem_gi
                print(f'[ETF NAV] {code} goodinfo: nav={_nav_gi} prem={_prem_gi}%')
                return pd.DataFrame([_row_gi])
            else:
                print(f'[ETF NAV] {code} goodinfo: 找不到淨值欄位')
        else:
            print(f'[ETF NAV] {code} goodinfo: HTTP {_r_gi.status_code}')
    except Exception as _e_gi:
        print(f'[ETF NAV] goodinfo {code}: {_e_gi}')

    # ── 3. TWSE OpenAPI（openapi.twse.com.tw 非主站，先直連再走 Proxy）──────
    try:
        from daily_checklist import get_nas_proxy as _gnp_nav
        _nas_nav = _gnp_nav()
    except Exception:
        _nas_nav = None

    def _parse_twse_row(row_dict, ep_label):
        _nav2 = 0.0
        for _nk in ['單位淨值', '淨值', 'NetAssetValue', 'nav']:
            _v = _safe_float(row_dict.get(_nk, ''))
            if _v is not None:
                _nav2 = _v
                break
        _price2 = 0.0
        for _pk in ['收盤價', 'ClosingPrice', 'close']:
            _v = _safe_float(row_dict.get(_pk, ''))
            if _v is not None:
                _price2 = _v
                break
        _prem_key = next((k for k in row_dict if '折溢價' in str(k)), None)
        _prem2 = _safe_float(row_dict[_prem_key]) if _prem_key else None
        if _prem2 is None and _nav2 > 0 and _price2 > 0:
            _prem2 = round((_price2 - _nav2) / _nav2 * 100, 2)
        if _nav2 > 0:
            _r_out = {'date': _dt.date.today(), 'nav': _nav2}
            if _price2 > 0:
                _r_out['price'] = _price2
            if _prem2 is not None:
                _r_out['premium_pct'] = _prem2
            print(f'[ETF NAV] {code} TWSE({ep_label}): nav={_nav2} price={_price2} prem={_prem2}%')
            return _r_out
        return None

    for _proxy_candidate in ([None] + ([_nas_nav] if _nas_nav else [])):
        _ptag = 'direct' if _proxy_candidate is None else 'proxy'
        for _op_id2 in ['TaiwanStockPremiumDiscountRatio', 'TaiwanStockNetValue']:
            try:
                _ep2 = f'https://openapi.twse.com.tw/v1/ETF/{_op_id2}'
                _r2 = _rq_etfnav.get(_ep2, headers={'Accept': 'application/json',
                                                      'User-Agent': 'Mozilla/5.0'},
                                      proxies=_proxy_candidate, timeout=10, verify=False)
                _j2 = _r2.json()
                _df2 = pd.DataFrame(_j2 if isinstance(_j2, list) else [])
                if _df2.empty:
                    print(f'[ETF NAV] TWSE {_op_id2}({_ptag}): 回傳空資料'); continue
                _code_col = next((c for c in _df2.columns if '證券代號' in str(c) or c == 'code'), None)
                if _code_col is None:
                    print(f'[ETF NAV] TWSE {_op_id2}({_ptag}): 找不到 證券代號 欄位'); continue
                _match = _df2[_df2[_code_col].astype(str).str.strip() == code]
                if _match.empty:
                    print(f'[ETF NAV] TWSE {_op_id2}({_ptag}): 找不到 {code}'); continue
                _out2 = _parse_twse_row(_match.iloc[0].to_dict(), f'{_op_id2}/{_ptag}')
                if _out2:
                    return pd.DataFrame([_out2])
            except Exception as _e2:
                print(f'[ETF NAV] TWSE {_op_id2}({_ptag}) {code}: {_e2}')
        # 若無 _nas_nav，外層 list 為 [None] 單元素，loop 自然結束無需 break

    # ── 4. MoneyDJ 爬蟲（BeautifulSoup，不需 token）──────────────────────
    try:
        from bs4 import BeautifulSoup as _BS4
        _hdrs_mdj = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8',
            'Referer': 'https://www.moneydj.com/',
        }
        _url_mdj = f'https://www.moneydj.com/ETF/X/Basic/Basic0004.xdjhtm?etfid={code}'
        # 優先用 curl_cffi 模擬 Chrome TLS 指紋，繞過反爬蟲；失敗再降級 requests
        try:
            from curl_cffi import requests as _cffi_req
            _r_mdj = _cffi_req.get(_url_mdj, impersonate='chrome124', timeout=12)
        except Exception:
            _r_mdj = _rq_etfnav.get(_url_mdj, headers=_hdrs_mdj, timeout=12, verify=False)
        if _r_mdj.status_code == 200:
            _soup = _BS4(_r_mdj.text, 'lxml')
            _nav_mdj = None
            # 策略1：找含「淨值」的 th/td，取下一格數字
            for _th in _soup.find_all(['th', 'td', 'span', 'div', 'dt']):
                _t = _th.get_text(strip=True)
                if ('淨值' in _t or 'NAV' in _t) and len(_t) < 20:
                    _td = _th.find_next_sibling()
                    if _td:
                        _v = _safe_float(_td.get_text(strip=True))
                        if _v is not None and _v > 0:
                            _nav_mdj = _v
                            break
            # 策略2：regex 直接掃 HTML
            if not _nav_mdj:
                import re as _re_mdj
                _m = _re_mdj.search(r'(?:淨值|NAV)[^\d]{0,20}?(\d{1,5}\.\d{2,6})', _r_mdj.text)
                if _m:
                    _nav_mdj = _safe_float(_m.group(1))
            if _nav_mdj and _nav_mdj > 0:
                print(f'[ETF NAV] MoneyDJ {code}: nav={_nav_mdj}')
                return pd.DataFrame([{'date': _dt.date.today(), 'nav': _nav_mdj}])
            else:
                print(f'[ETF NAV] MoneyDJ {code}: HTTP {_r_mdj.status_code} 找不到淨值')
        else:
            print(f'[ETF NAV] MoneyDJ {code}: HTTP {_r_mdj.status_code}')
    except Exception as _e_mdj:
        print(f'[ETF NAV] MoneyDJ {code}: {_e_mdj}')

    # ── 5. yfinance ETF info.navPrice（加限速 retry）──────────────────────
    import time as _t3
    for _sfx3 in ('.TW', '.TWO'):
        for _retry3 in range(3):
            try:
                import yfinance as _yf3
                _tk3 = _yf3.Ticker(f'{code}{_sfx3}')
                _info3 = _tk3.info
                _nav3 = _info3.get('navPrice') or _info3.get('regularMarketNAV')
                if _nav3 and float(_nav3) > 0:
                    print(f'[ETF NAV] yfinance {code}{_sfx3}: navPrice={_nav3}')
                    return pd.DataFrame([{'date': _dt.date.today(), 'nav': float(_nav3)}])
                break  # 沒資料，不 retry
            except Exception as _e3:
                _e3s = str(_e3)
                if ('Too Many Requests' in _e3s or 'Rate' in _e3s) and _retry3 < 2:
                    _t3.sleep(2 + _retry3 * 2)  # 2s, 4s
                    print(f'[ETF NAV] yfinance {code}{_sfx3}: 限速 retry {_retry3+1}/3')
                    continue
                print(f'[ETF NAV] yfinance {code}{_sfx3}: {_e3}')
                break

    # ── 最終兜底：FinMind 過舊資料（goodinfo/MoneyDJ/yfinance 全部失敗時）────
    if _df_stale is not None and not _df_stale.empty:
        print(f'[ETF NAV] {code} 最終兜底: FinMind過舊資料({_days_stale}d)，所有即時來源失敗')
        return _df_stale

    return pd.DataFrame()

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

# ═══════════════════════════════════════════════════════════════
# UI 輔助元件
# ═══════════════════════════════════════════════════════════════

def macro_allocation_banner(regime: str) -> None:
    """總經連動配置建議橫幅"""
    alloc = MACRO_ALLOC.get(regime, MACRO_ALLOC['neutral'])
    desc  = MACRO_DESC.get(regime, MACRO_DESC['neutral'])
    bg_map  = {'bull': '#0d2618', 'neutral': '#1e1a00', 'bear': '#2a0d0d'}
    brd_map = {'bull': '#2ea043',  'neutral': '#d29922',  'bear': '#f85149'}
    bg  = bg_map.get(regime, '#1a1f2e')
    brd = brd_map.get(regime, '#1f6feb')
    alloc_html = ' &nbsp;|&nbsp; '.join(
        f'<b>{k}</b>&nbsp;<span style="color:#58a6ff;">{v}%</span>'
        for k, v in alloc.items()
    )
    st.markdown(
        f'''<div style="background:{bg};border:1px solid {brd};border-radius:10px;
padding:10px 16px;margin-bottom:14px;">
<div style="font-size:12px;font-weight:700;color:#8b949e;margin-bottom:2px;">
📡 總經連動配置建議（來源：Tab① 市場評估）</div>
<div style="font-size:13px;color:#c9d1d9;">{desc}</div>
<div style="font-size:13px;margin-top:6px;">{alloc_html}</div>
</div>''', unsafe_allow_html=True)

def _colored_box(text: str, color: str = 'green') -> None:
    """統一彩色提示框"""
    cfg = {
        'green':  ('#0d2618', '#2ea043'),
        'yellow': ('#1e1a00', '#d29922'),
        'red':    ('#2a0d0d', '#f85149'),
        'blue':   ('#0a1628', '#1f6feb'),
    }
    bg, brd = cfg.get(color, cfg['blue'])
    st.markdown(
        f'<div style="background:{bg};border:1px solid {brd};border-radius:8px;'
        f'padding:10px 14px;margin:6px 0;">{text}</div>',
        unsafe_allow_html=True)

def _teacher_conclusion(teacher: str, indicator_val: str, conclusion: str,
                        action: str = '', color: str | None = None) -> None:
    """ETF dashboard 老師結論卡（與 app.py teacher_conclusion 同格式，直接 render）"""
    if color is None:
        _neg_kw = ['警戒', '危險', '賣超', '空單', '減碼', '停損', '撤離', '跌破', '過熱', '回調', '降倉', '空頭', '侵蝕', '高估']
        _pos_kw = ['強勢', '買超', '多頭', '安全', '健康', '買進', '加碼', '流入', '突破', '進攻', '上漲', '低估', '特價']
        if any(k in conclusion + action for k in _neg_kw):
            color = '#2ea043'
        elif any(k in conclusion + action for k in _pos_kw):
            color = '#da3633'
        else:
            color = '#d29922'
    _icon = {'宏爺': '🎯', '孫慶龍': '💡', '弘爺': '🎯', '朱家泓': '📊',
             '妮可': '📈', '春哥': '🌱', '蔡森': '📐', '郭俊宏': '💰'}.get(teacher, '👤')
    _action_str = f'，{action}' if action else ''
    st.markdown(
        f'<div style="border-left:3px solid {color};padding:6px 10px;margin:4px 0;'
        f'background:rgba(0,0,0,0.2);border-radius:0 6px 6px 0;">'
        f'<span style="color:#ffd700;font-weight:700;font-size:12px;">{_icon} {teacher}</span>'
        f'<span style="color:#8b949e;font-size:12px;">：</span>'
        f'<span style="color:#c9d1d9;font-size:12px;">{indicator_val} → </span>'
        f'<span style="color:{color};font-size:12px;font-weight:600;">{conclusion}</span>'
        f'<span style="color:#8b949e;font-size:11px;">{_action_str}</span>'
        f'</div>',
        unsafe_allow_html=True)

def _plot_etf_chart(df: pd.DataFrame, ticker: str,
                    benchmark: str, bench_df: pd.DataFrame) -> None:
    """ETF 走勢圖 + MA50/MA200 + 標準化基準（Y軸：漲幅%，以起始日為0%）"""
    fig   = go.Figure()
    close = df['Close']
    base  = float(close.iloc[0])   # 起始價，用來換算漲幅%

    def _pct(s): return ((s / base) - 1) * 100   # → 相對起始點的漲幅%

    _hover = '%{x|%Y-%m-%d}  %{y:.2f}%<extra></extra>'
    fig.add_trace(go.Scatter(x=df.index, y=_pct(close).round(2),
                              name=ticker, line=dict(color='#58a6ff', width=2),
                              hovertemplate=_hover))
    fig.add_trace(go.Scatter(x=df.index, y=_pct(close.rolling(50).mean()).round(2),
                              name='MA50', line=dict(color='#ffa657', width=1, dash='dot'),
                              hovertemplate=_hover))
    fig.add_trace(go.Scatter(x=df.index, y=_pct(close.rolling(200).mean()).round(2),
                              name='MA200', line=dict(color='#f85149', width=1, dash='dash'),
                              hovertemplate=_hover))
    if not bench_df.empty:
        _bc   = bench_df['Close'].reindex(df.index).ffill().dropna()
        _bc_b = float(_bc.iloc[0])
        _bc_pct = ((_bc / _bc_b) - 1) * 100   # 基準也從0%起算
        fig.add_trace(go.Scatter(x=_bc.index, y=_bc_pct.round(2),
                                  name=f'{benchmark}（基準）',
                                  line=dict(color='#3fb950', width=1.2, dash='dash'),
                                  hovertemplate=_hover))
    fig.update_layout(
        template='plotly_dark', height=380,
        margin=dict(l=0, r=0, t=20, b=0),
        paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
        legend=dict(orientation='h', yanchor='bottom', y=1.01),
        yaxis=dict(title='漲幅 (%)', ticksuffix='%', zeroline=True,
                   zerolinecolor='#444', zerolinewidth=1),
    )
    st.plotly_chart(fig, width='stretch')

def _plot_correlation(corr: pd.DataFrame) -> None:
    """相關係數熱力圖"""
    labels = list(corr.columns)
    z      = corr.values.tolist()
    text   = [[f'{v:.2f}' for v in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=labels, y=labels,
        text=text, texttemplate='%{text}',
        colorscale='RdBu_r', zmid=0, zmin=-1, zmax=1,
        colorbar=dict(thickness=10),
    ))
    fig.update_layout(
        template='plotly_dark', height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
    )
    st.plotly_chart(fig, width='stretch')

def _render_bias(df: pd.DataFrame, ticker: str) -> None:
    """BIAS 乖離率：(Close - MAn) / MAn × 100%，顯示 MA20/MA60/MA120"""
    if df is None or len(df) < 20:
        st.info('資料不足，無法計算 BIAS')
        return
    close = df['Close'] if 'Close' in df.columns else df['close']
    bias_rows = []
    for n, label in [(20, 'MA20'), (60, 'MA60'), (120, 'MA120')]:
        if len(close) >= n:
            ma  = float(close.rolling(n).mean().iloc[-1])
            cur = float(close.iloc[-1])
            bias = (cur - ma) / ma * 100
            if bias > 10:
                hint = '🔴 嚴重高估，注意拉回'
            elif bias > 5:
                hint = '🟡 偏高，謹慎追高'
            elif bias < -10:
                hint = '🟢 嚴重低估，逢低佈局機會'
            elif bias < -5:
                hint = '🟡 偏低，可分批承接'
            else:
                hint = '⚪ 中性偏離，正常波動'
            bias_rows.append({'均線': label, 'MA值': f'{ma:.2f}',
                               'BIAS(%)': f'{bias:+.2f}%', '訊號': hint})
    if bias_rows:
        st.dataframe(pd.DataFrame(bias_rows), use_container_width=True, hide_index=True)
        # 視覺化近60日 BIAS(MA20)
        if len(close) >= 60:
            ma20 = close.rolling(20).mean()
            b20  = (close - ma20) / ma20 * 100
            b20  = b20.dropna().tail(60)
            fig  = go.Figure(go.Bar(
                x=b20.index, y=b20.values,
                marker_color=['#f85149' if v > 0 else '#3fb950' for v in b20.values],
                name='BIAS(MA20)',
            ))
            fig.add_hline(y=10,  line_dash='dot', line_color='#f85149',
                          annotation_text='+10%')
            fig.add_hline(y=-10, line_dash='dot', line_color='#3fb950',
                          annotation_text='-10%')
            fig.update_layout(
                template='plotly_dark', height=220,
                yaxis_title='BIAS %', margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
            )
            st.plotly_chart(fig, width='stretch')

# ═══════════════════════════════════════════════════════════════
# Tab ⑥：單一 ETF 深度診斷
# ═══════════════════════════════════════════════════════════════

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



def _etf_ai_hokei(gemini_fn, ticker, name, cur_yield, bias240, k_val, d_val):
    """ETF AI 存股決策總結 — 買跌不買漲（左側交易）鐵血紀律"""
    import re as _re, json as _json

    st.markdown('---')
    st.markdown('### 🤖 AI ETF 存股決策總結')
    st.caption('嚴守「買跌不買漲（左側交易）」紀律，以年線乖離率＋殖利率＋KD 三維度研判定期定額節奏。')

    # ── 規則引擎先行判定 ──────────────────────────────────────
    kd_high = (k_val is not None and k_val > 80) or (d_val is not None and d_val > 80)
    if bias240 is None:
        _sig, _col, _bg = '資料不足（< 240 日）', '#8b949e', '#161b22'
    elif bias240 <= 0 and cur_yield >= 6:
        _sig, _col, _bg = '極佳買點 (加速扣款)', '#3fb950', '#0d2818'
    elif bias240 <= 0:
        _sig, _col, _bg = '極佳買點 (加速扣款)', '#3fb950', '#0d2818'
    elif bias240 < 10:
        _sig, _col, _bg = '正常存股 (紀律扣款)', '#d29922', '#1c1500'
    elif kd_high:
        _sig, _col, _bg = '停止買進 (暫停扣款)', '#f85149', '#2a0d0d'
    else:
        _sig, _col, _bg = '謹慎觀望 (減少扣款)', '#d29922', '#1c1500'

    _b240_str = f'{bias240:+.2f}%' if bias240 is not None else 'N/A（資料不足 240 日）'
    _k_str    = f'{k_val:.1f}' if k_val is not None else 'N/A'
    _d_str    = f'{d_val:.1f}' if d_val is not None else 'N/A'
    _kd_label = f'K:{_k_str} / D:{_d_str}' + (' 🔴 高檔' if kd_high else '')

    # ── 資料概覽卡 ────────────────────────────────────────────
    st.markdown(
        f'<div style="background:{_bg};border:2px solid {_col};border-radius:12px;'
        f'padding:20px 24px;margin:8px 0;">'
        f'<div style="font-size:22px;font-weight:900;color:{_col};">{_sig}</div>'
        f'<div style="display:flex;gap:32px;margin-top:14px;flex-wrap:wrap;">'
        f'<div><div style="font-size:11px;color:#8b949e;">年線乖離率 (BIAS240)</div>'
        f'<div style="font-size:18px;font-weight:700;color:#c9d1d9;">{_b240_str}</div></div>'
        f'<div><div style="font-size:11px;color:#8b949e;">KD 指標</div>'
        f'<div style="font-size:18px;font-weight:700;color:#c9d1d9;">{_kd_label}</div></div>'
        f'<div><div style="font-size:11px;color:#8b949e;">現金殖利率</div>'
        f'<div style="font-size:18px;font-weight:700;color:#c9d1d9;">{cur_yield:.2f}%</div></div>'
        f'</div></div>',
        unsafe_allow_html=True)

    # ── LLM 精煉研判按鈕 ──────────────────────────────────────
    _sess_key = f'etf_hokei_{ticker}'
    if st.button('🤖 AI 精煉研判（存股節奏）', key='etf_hokei_btn'):
        _news_str = _fetch_news_for(ticker, name, 4)
        _prompt = (
            "你是嚴格執行「買跌不買漲（左側交易）」紀律的ETF存股顧問。\n"
            "根據以下數據，套用判定邏輯，只輸出 JSON，不含其他文字：\n\n"
            f"ETF: {name} ({ticker})\n"
            f"年線乖離率(BIAS240): {_b240_str}\n"
            f"K值: {_k_str}  D值: {_d_str}  KD高檔(>80): {'是' if kd_high else '否'}\n"
            f"現金殖利率: {cur_yield:.2f}%\n\n"
            f"【近期ETF相關新聞】\n{_news_str}\n\n"
            "判定邏輯：\n"
            "【極佳買點(加速扣款)】年線乖離率<=0% 且 殖利率>=6%\n"
            "【正常存股(紀律扣款)】0%<年線乖離率<10%\n"
            "【停止買進(暫停扣款)】年線乖離率>=10% 且 KD高檔(>80)\n\n"
            '輸出格式（嚴格JSON）：\n'
            '{"signal":"極佳買點|正常存股|停止買進","reading":"50字以內精煉解讀","action":"行動指令10字內"}'
        )
        with st.spinner('AI 存股研判中...'):
            raw = gemini_fn(_prompt, max_tokens=300)
        if raw and not raw.startswith('⚠️'):
            _m = _re.search(r'\{[^{}]+\}', raw, _re.DOTALL)
            try:
                _j = _json.loads(_m.group()) if _m else {}
                if not _j.get('signal'):
                    _j = {'signal': _sig, 'reading': raw[:200], 'action': ''}
            except Exception:
                _j = {'signal': _sig, 'reading': raw[:200], 'action': ''}
            st.session_state[_sess_key] = _j
            st.rerun()
        else:
            st.warning(raw or 'AI 回傳為空，請確認 GEMINI_API_KEY')

    # ── 顯示已快取結果 ────────────────────────────────────────
    _saved = st.session_state.get(_sess_key)
    if _saved:
        _s  = _saved.get('signal', _sig)
        _r  = _saved.get('reading', '')
        _a  = _saved.get('action', '')
        _sc = '#3fb950' if '極佳' in _s else ('#f85149' if '停止' in _s else '#d29922')
        _sb = '#0d2818' if '極佳' in _s else ('#2a0d0d' if '停止' in _s else '#1c1500')
        st.markdown(
            f'<div style="background:{_sb};border-left:4px solid {_sc};border-radius:8px;'
            f'padding:16px 20px;margin:8px 0;">'
            f'<div style="font-size:15px;font-weight:700;color:{_sc};">{_s}</div>'
            f'<div style="font-size:13px;color:#c9d1d9;margin-top:8px;line-height:1.7;">{_r}</div>'
            + (f'<div style="font-size:12px;color:#8b949e;margin-top:10px;'
               f'border-top:1px solid #30363d;padding-top:8px;">'
               f'📌 行動指令：<b style="color:{_sc};">{_a}</b></div>' if _a else '')
            + '</div>',
            unsafe_allow_html=True)
        if st.button('🔄 清除結果', key='etf_hokei_clear'):
            st.session_state.pop(_sess_key, None)
            st.rerun()

# ETF → GICS 類股對照（僅涵蓋常見 ETF，未知 ETF 歸入「其他」）
_ETF_SECTOR_MAP = {
    'XLK': '資訊科技', 'QQQ': '資訊科技', '00631L.TW': '資訊科技',
    'XLF': '金融', 'KBE': '金融',
    'XLE': '能源',
    'XLV': '醫療保健',
    'XLI': '工業',
    'XLP': '必需消費', 'XLY': '非必需消費',
    'XLU': '公用事業',
    'XLB': '原材料',
    'XLRE': '房地產', '00712.TW': '房地產',
    'XLC': '通訊服務',
    'SPY': '廣泛市場', 'IVV': '廣泛市場', 'VOO': '廣泛市場',
    '0050.TW': '廣泛市場', '00646.TW': '廣泛市場',
    'BND': '債券', 'AGG': '債券', 'TLT': '債券',
    '00678.TW': '債券', '00720B.TW': '債券',
    '00878.TW': '高股息', '00713.TW': '高股息', '0056.TW': '高股息',
    'GLD': '黃金/原物料', 'IAU': '黃金/原物料',
}

def _check_sector_exposure(rows: list, total_value: float) -> None:
    """計算各 GICS 類股曝險，標記超過 30% 的集中風險"""
    sector_vals: dict = {}
    for r in rows:
        sector = _ETF_SECTOR_MAP.get(r['ticker'], '其他')
        sector_vals[sector] = sector_vals.get(sector, 0) + r['current_value']

    sector_rows = []
    warnings = []
    for sec, val in sorted(sector_vals.items(), key=lambda x: -x[1]):
        pct = val / total_value * 100
        flag = '⚠️ 超限' if pct > 30 else '✅'
        sector_rows.append({'類股': sec, '合計現值(元)': f'{val:,.0f}',
                             '佔比': f'{pct:.1f}%', '狀態': flag})
        if pct > 30:
            warnings.append((sec, pct))

    st.dataframe(pd.DataFrame(sector_rows), use_container_width=True, hide_index=True)
    if warnings:
        for sec, pct in warnings:
            _colored_box(
                f'⚠️ <b>{sec}</b> 類股佔比 <b>{pct:.1f}%</b> 超過 30% 上限，'
                f'建議分散至其他類股或降低持倉', 'red')
    else:
        _colored_box('✅ 所有類股曝險均在 30% 以內，產業分散度良好', 'green')


def _etf_ai_portfolio(gemini_fn, rows, rebal_actions, regime, loss_pct):
    with st.expander('🤖 AI 組合評斷（展開）', expanded=False):
        row_txt = '\n'.join(
            f'  {r["ticker"]}：目標{r["target_pct"]}% 實際{r["actual_pct"]}% 偏離{r["deviation"]:+.1f}%'
            for r in rows)
        act_txt = '\n'.join(
            f'  {a["動作"]} {a["ETF"]} {a["金額(元)"]:,.0f}元'
            for a in rebal_actions) if rebal_actions else '  無需再平衡'
        if st.button('🤖 生成組合AI評斷', key='etf_ai_p_btn'):
            # 為組合中每檔 ETF 抓取新聞（最多各 2 則）
            _p_news_lines = []
            for _r in rows[:4]:
                _tk = _r.get('ticker', '')
                _nn = _fetch_news_for(_tk, _tk, 2)
                if _nn and _nn != '（暫無相關新聞）':
                    _p_news_lines.append(f'[{_tk}]\n{_nn}')
            _p_news_str = '\n'.join(_p_news_lines) if _p_news_lines else '（暫無相關新聞）'
            prompt = (
                f"你是ETF組合管理專家，依據以下資料給出精準建議，每項不超過200字，嚴禁捏造：\n"
                f"市場狀態：{regime}\n"
                f"組合明細：\n{row_txt}\n"
                f"再平衡指令：\n{act_txt}\n"
                f"壓力測試損失：{loss_pct:.1f}%（S&P500下跌20%模擬）\n\n"
                f"【近期各ETF相關新聞】\n{_p_news_str}\n\n"
                f"輸出：\n"
                f"1.【組合健康度】分散度、集中風險點\n"
                f"2.【再平衡必要性】是否緊急，原因\n"
                f"3.【總經視角】依{regime}市場狀態，調整方向\n"
                f"4.【一句話結論】立即行動 or 繼續觀察\n"
                f"⚠️ 僅供學術研究，非投資建議"
            )
            with st.spinner('AI 分析中...'):
                result = gemini_fn(prompt, max_tokens=900)
            if result and not result.startswith('⚠️'):
                st.session_state['etf_ai_p_result'] = result
                st.rerun()
            else:
                st.session_state['etf_ai_p_result'] = None
                st.warning(result or 'AI 回傳為空')
        _p_saved = st.session_state.get('etf_ai_p_result')
        if _p_saved:
            st.markdown(_p_saved)
            if st.button('🔄 清除', key='etf_ai_p_clear'):
                st.session_state.pop('etf_ai_p_result', None)
                st.rerun()

def _render_monte_carlo(port_val: pd.Series, initial: float, ann_vol: float,
                        n_paths: int = 10_000, n_days: int = 252) -> None:
    """
    蒙地卡羅模擬 10,000 路徑，1 年期
    使用歷史年化波動率計算日報酬標準差，幾何布朗運動隨機遊走
    顯示 10th/50th/90th percentile 區間與最終分布直方圖
    """
    try:
        daily_ret  = port_val.pct_change().dropna()
        mu_daily   = float(daily_ret.mean())
        sig_daily  = float(daily_ret.std())
        if sig_daily == 0:
            st.info('波動率為 0，無法執行蒙地卡羅模擬')
            return

        rng      = np.random.default_rng(42)
        # shape: (n_paths, n_days)
        shocks   = rng.normal(mu_daily, sig_daily, size=(n_paths, n_days))
        paths    = np.cumprod(1 + shocks, axis=1) * float(port_val.iloc[-1])

        p10  = np.percentile(paths[:, -1], 10)
        p50  = np.percentile(paths[:, -1], 50)
        p90  = np.percentile(paths[:, -1], 90)
        prob_profit = float((paths[:, -1] > float(port_val.iloc[-1])).mean() * 100)

        ca, cb, cc, cd = st.columns(4)
        ca.metric('P10（悲觀）',  f'{(p10/float(port_val.iloc[-1])-1)*100:+.1f}%')
        cb.metric('P50（中位）',  f'{(p50/float(port_val.iloc[-1])-1)*100:+.1f}%')
        cc.metric('P90（樂觀）',  f'{(p90/float(port_val.iloc[-1])-1)*100:+.1f}%')
        cd.metric('獲利機率',     f'{prob_profit:.1f}%')

        # 繪製路徑分布（取前100條 + 百分位帶）
        days_axis = list(range(n_days))
        sample_paths = paths[:100]
        fig = go.Figure()
        for i, sp in enumerate(sample_paths):
            fig.add_trace(go.Scatter(
                x=days_axis, y=sp.tolist(),
                mode='lines',
                line=dict(color='rgba(88,166,255,0.05)', width=1),
                showlegend=False,
            ))
        for label, pct, color in [
            ('P10', 10, '#f85149'), ('P50', 50, '#e3b341'), ('P90', 90, '#3fb950'),
        ]:
            band = np.percentile(paths, pct, axis=0)
            fig.add_trace(go.Scatter(
                x=days_axis, y=band.tolist(),
                mode='lines', name=label,
                line=dict(color=color, width=2),
            ))
        fig.add_hline(y=float(port_val.iloc[-1]),
                      line_dash='dot', line_color='#ffffff',
                      annotation_text='目前淨值')
        fig.update_layout(
            template='plotly_dark', height=320,
            xaxis_title='交易日', yaxis_title='資產價值（元）',
            margin=dict(l=0, r=0, t=20, b=0),
            paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
            legend=dict(orientation='h', yanchor='bottom', y=1.01),
        )
        st.plotly_chart(fig, width='stretch')
        st.caption(f'模擬條件：{n_paths:,} 路徑，日均報酬 μ={mu_daily*100:.4f}%，σ={sig_daily*100:.3f}%（基於歷史資料）⚠️ 僅供參考')
    except Exception as e:
        st.warning(f'蒙地卡羅模擬失敗：{e}')


def _etf_ai_backtest(gemini_fn, cagr, sharpe, mdd, vol, weights, regime):
    with st.expander('🤖 AI 回測評斷（展開）', expanded=False):
        w_txt  = ' | '.join(f'{t}: {w*100:.0f}%' for t, w in weights.items())
        if st.button('🤖 生成回測AI評斷', key='etf_ai_bt_btn'):
            # 為回測組合中每檔 ETF 抓取新聞（最多各 2 則）
            _bt_news_lines = []
            for _tk in list(weights.keys())[:4]:
                _nn = _fetch_news_for(_tk, _tk, 2)
                if _nn and _nn != '（暫無相關新聞）':
                    _bt_news_lines.append(f'[{_tk}]\n{_nn}')
            _bt_news_str = '\n'.join(_bt_news_lines) if _bt_news_lines else '（暫無相關新聞）'
            prompt = (
                f"你是回測績效分析師，依據以下數字給出精準評斷，不超過300字，嚴禁捏造：\n"
                f"組合：{w_txt}\n"
                f"CAGR：{cagr:.2f}%\n"
                f"夏普值：{sharpe:.2f}\n"
                f"最大回撤：{mdd:.1f}%\n"
                f"年化波動率：{vol:.2f}%\n"
                f"當前市場狀態：{regime}\n\n"
                f"【近期各ETF相關新聞】\n{_bt_news_str}\n\n"
                f"輸出：\n"
                f"1.【績效評級】優秀/良好/普通/劣（請說明標準）\n"
                f"2.【風險評估】MDD和波動率是否在可接受範圍\n"
                f"3.【改善建議】基於春哥/郭俊宏/孫慶龍觀點，如何優化配置\n"
                f"4.【前瞻建議】在{regime}環境下，此組合的下一步行動\n"
                f"⚠️ 僅供學術研究，非投資建議"
            )
            with st.spinner('AI 分析中...'):
                result = gemini_fn(prompt, max_tokens=900)
            if result and not result.startswith('⚠️'):
                st.session_state['etf_ai_bt_result'] = result
                st.rerun()
            else:
                st.session_state['etf_ai_bt_result'] = None
                st.warning(result or 'AI 回傳為空')
        _bt_saved = st.session_state.get('etf_ai_bt_result')
        if _bt_saved:
            st.markdown(_bt_saved)
            if st.button('🔄 清除', key='etf_ai_bt_clear'):
                st.session_state.pop('etf_ai_bt_result', None)
                st.rerun()

# ═══════════════════════════════════════════════════════════════
# Tab ⑨：ETF AI 綜合評斷
# ═══════════════════════════════════════════════════════════════

def render_etf_ai(gemini_fn=None):
    mkt_info = st.session_state.get('mkt_info', {})
    regime   = mkt_info.get('regime', 'neutral')
    macro_allocation_banner(regime)

    st.markdown('### 🤖 ETF AI 綜合評斷')
    st.caption('整合 Tab ⑥⑦⑧ 分析結果，生成跨模組綜合建議。請先在各分頁執行分析。')

    # 讀取各 Tab 存入的資料
    single_d  = st.session_state.get('etf_single_data')
    port_d    = st.session_state.get('etf_portfolio_data')
    backtest_d= st.session_state.get('etf_backtest_data')

    has_data  = any([single_d, port_d, backtest_d])

    # ── 已有資料：顯示摘要 ───────────────────────────────────
    if has_data:
        st.markdown('#### 📊 已載入分析摘要')
        summary_rows = []
        if single_d:
            summary_rows.append({
                '來源': 'Tab⑥ 單支診斷',
                '內容': f'{single_d["ticker"]} | 殖利率:{single_d["cur_yield"]:.1f}% | 總報酬:{single_d["total_ret"]:.1f}% | VCP:{single_d["vcp"]["signal"]}',
            })
        if port_d:
            summary_rows.append({
                '來源': 'Tab⑦ 組合配置',
                '內容': f'總資產:{port_d["total_value"]:,.0f}元 | 壓力測試損失:{port_d["loss_pct"]:.1f}% | 再平衡:{len(port_d["rebal_actions"])}筆',
            })
        if backtest_d:
            summary_rows.append({
                '來源': 'Tab⑧ 回測',
                '內容': f'CAGR:{backtest_d["cagr"]:.1f}% | Sharpe:{backtest_d["sharpe"]:.2f} | MDD:{backtest_d["mdd"]:.1f}% | 期間:{backtest_d["period"]}',
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        # 建立綜合 prompt
        sections = [
            f"你是頂尖ETF投資策略師，整合以下多維度資料，給出綜合評斷。",
            f"每個評斷項目不超過300字，條列式，嚴禁捏造未提供的數據。",
            f"\n當前總經市場狀態：{regime}",
            f"建議配置：{MACRO_ALLOC.get(regime, {})}",
        ]
        if single_d:
            sections.append(
                f"\n【Tab⑥ 單支ETF診斷】{single_d['ticker']} ({single_d['name']})\n"
                f"  含息總報酬={single_d['total_ret']:.1f}% | 殖利率={single_d['cur_yield']:.1f}% | "
                f"5年均殖利率={single_d['avg_yield']:.1f}% | VCP信號={single_d['vcp']['signal']} | "
                f"折溢價={single_d['premium']['premium_pct']}% | 追蹤誤差={single_d['te']}%"
            )
        if port_d:
            acts = ', '.join(f'{a["動作"]}{a["ETF"]}' for a in port_d['rebal_actions'])
            sections.append(
                f"\n【Tab⑦ 組合配置】{len(port_d['rows'])}檔ETF | 總資產={port_d['total_value']:,.0f}元\n"
                f"  壓力測試預估損失={port_d['loss_pct']:.1f}% | 再平衡指令：{acts or '無需調整'}"
            )
        if backtest_d:
            w_txt = ' | '.join(f'{t}:{w*100:.0f}%' for t, w in backtest_d['weights'].items())
            sections.append(
                f"\n【Tab⑧ 回測績效】{backtest_d['period']} 期間 | 組合：{w_txt}\n"
                f"  CAGR={backtest_d['cagr']:.1f}% | 夏普值={backtest_d['sharpe']:.2f} | "
                f"最大回撤={backtest_d['mdd']:.1f}% | 年化波動率={backtest_d['vol']:.1f}%"
            )
        sections += [
            f"\n請輸出：",
            f"1.【整體ETF組合評級】A+/A/B/C（綜合以上所有數據）",
            f"2.【最大機會點】目前最值得加碼的方向（附理由）",
            f"3.【最大風險點】需要立即處理的警示",
            f"4.【行動清單】依優先序列出3項具體行動",
            f"5.【總經連動建議】在{regime}市場下，ETF佈局應如何因應",
            f"⚠️ 僅供學術研究與教育用途，非投資建議，盈虧自負",
        ]
        _base_prompt = '\n'.join(sections)

        if st.button('🤖 生成 ETF 綜合 AI 評斷', key='etf_ai_comp_btn', use_container_width=True):
            if not gemini_fn:
                st.warning('⚠️ 請設定 GEMINI_API_KEY 才能使用 AI 功能')
            else:
                # 收集本頁所有 ETF ticker，抓取各自新聞
                _comp_tickers = []
                if single_d:
                    _comp_tickers.append((single_d['ticker'], single_d.get('name', '')))
                if port_d:
                    for _rr in port_d.get('rows', [])[:3]:
                        _tk = _rr.get('ticker', '')
                        if _tk and (_tk, '') not in _comp_tickers:
                            _comp_tickers.append((_tk, ''))
                if backtest_d:
                    for _tk in list(backtest_d.get('weights', {}).keys())[:3]:
                        if (_tk, '') not in _comp_tickers:
                            _comp_tickers.append((_tk, ''))
                _comp_news_lines = []
                for _tk, _nm in _comp_tickers[:4]:
                    _nn = _fetch_news_for(_tk, _nm, 2)
                    if _nn and _nn != '（暫無相關新聞）':
                        _comp_news_lines.append(f'[{_tk}]\n{_nn}')
                _comp_news_str = '\n'.join(_comp_news_lines) if _comp_news_lines else '（暫無相關新聞）'
                full_prompt = _base_prompt + f'\n\n【近期各ETF相關新聞】\n{_comp_news_str}'
                with st.spinner('AI 整合分析中...'):
                    result = gemini_fn(full_prompt, max_tokens=1500)
                if result and not result.startswith('⚠️'):
                    st.session_state['etf_ai_comp_result'] = result
                    st.rerun()
                else:
                    st.error(result or 'AI 回傳為空，請確認 API Key')

        saved_result = st.session_state.get('etf_ai_comp_result')
        if saved_result:
            st.markdown('---')
            st.markdown(saved_result)
            if st.button('🔄 清除結果', key='etf_ai_comp_clear'):
                st.session_state.pop('etf_ai_comp_result', None)
                st.rerun()
    else:
        st.info(
            '📋 尚未有分析資料\n\n'
            '請先到以下頁面執行分析：\n'
            '- **Tab ⑥** 單一 ETF 深度診斷\n'
            '- **Tab ⑦** ETF 組合配置\n'
            '- **Tab ⑧** ETF 歷史回測\n\n'
            '分析完成後回到此頁，即可生成跨模組綜合評斷。'
        )

    # ── 自由提問區 ────────────────────────────────────────────
    st.markdown('---')
    st.markdown('#### 💬 ETF 自由提問')
    st.caption('不需要先執行分析，直接輸入任何ETF相關問題')
    question = st.text_area('輸入問題', height=80, key='etf_ai_question',
                             placeholder='例如：台灣高股息ETF和美國債券ETF如何搭配？')
    if st.button('💬 提問', key='etf_ai_ask_btn', use_container_width=True):
        if not question.strip():
            st.warning('請輸入問題')
        elif not gemini_fn:
            st.warning('⚠️ 請設定 GEMINI_API_KEY')
        else:
            q_prompt = (
                f"你是ETF投資教育顧問，以春哥VCP、郭俊宏以息養股、孫慶龍7%估值框架回答，"
                f"不超過300字，嚴禁捏造數據：\n\n問題：{question}\n"
                f"⚠️ 僅供學術研究，非投資建議"
            )
            with st.spinner('AI 回答中...'):
                answer = gemini_fn(q_prompt, max_tokens=600)
            if answer and not answer.startswith('⚠️'):
                st.markdown(answer)
            else:
                st.warning(answer or 'AI 回傳為空')

# ── 美股 11 大 GICS 類股 ETF ─────────────────────────────────
_US_SECTORS = {
    'XLK':  {'name': '科技',        'sub': ['AAPL','MSFT','NVDA','AVGO','AMD']},
    'XLF':  {'name': '金融',        'sub': ['JPM','BAC','WFC','GS','MS']},
    'XLE':  {'name': '能源',        'sub': ['XOM','CVX','COP','SLB','MPC']},
    'XLV':  {'name': '醫療',        'sub': ['LLY','UNH','JNJ','ABBV','MRK']},
    'XLI':  {'name': '工業',        'sub': ['GE','CAT','HON','UPS','BA']},
    'XLP':  {'name': '必需消費',    'sub': ['PG','KO','PEP','COST','WMT']},
    'XLU':  {'name': '公用事業',    'sub': ['NEE','SO','DUK','AEP','D']},
    'XLB':  {'name': '原物料',      'sub': ['LIN','APD','ECL','NEM','FCX']},
    'XLRE': {'name': '房地產',      'sub': ['PLD','AMT','EQIX','CCI','SPG']},
    'XLY':  {'name': '非必需消費',  'sub': ['AMZN','TSLA','HD','MCD','NKE']},
    'XLC':  {'name': '通訊服務',    'sub': ['META','GOOGL','NFLX','DIS','T']},
}

# ── 台股類股代表 ETF/指數成分 ────────────────────────────────
_TW_SECTORS = {
    '2330.TW': {'name': '半導體',    'sub': ['2303.TW','2308.TW','2454.TW','3711.TW','2379.TW']},
    '2317.TW': {'name': '電子製造',  'sub': ['2354.TW','2356.TW','3008.TW','2382.TW','3034.TW']},
    '2412.TW': {'name': '電信',      'sub': ['3045.TW','4904.TW','2409.TW']},
    '2882.TW': {'name': '金融',      'sub': ['2881.TW','2883.TW','2884.TW','2886.TW','2891.TW']},
    '1301.TW': {'name': '塑化',      'sub': ['1303.TW','1326.TW','1402.TW']},
    '2002.TW': {'name': '鋼鐵',      'sub': ['2006.TW','2007.TW','2010.TW']},
    '1216.TW': {'name': '食品',      'sub': ['1201.TW','1210.TW','1225.TW']},
    '2603.TW': {'name': '航運',      'sub': ['2609.TW','2615.TW','2617.TW']},
    '9910.TW': {'name': '觀光',      'sub': ['2706.TW','2707.TW','2727.TW']},
    '3008.TW': {'name': '光電',      'sub': ['2409.TW','3481.TW','2475.TW']},
}

_PERIOD_MAP = {'1日': '5d', '5日': '1mo', '1月': '3mo', '3月': '6mo'}

@st.cache_data(ttl=1800, max_entries=10)
def _fetch_sector_returns(tickers: tuple, period: str) -> dict:
    """批次抓取類股漲跌幅，回傳 {ticker: pct_change}"""
    result = {}
    try:
        raw = yf.download(list(tickers), period=period,
                          auto_adjust=True, progress=False, threads=True)
        if raw.empty:
            return result
        # yf.download 多 ticker 時 Close 為 MultiIndex
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw['Close'] if 'Close' in raw.columns.get_level_values(0) else raw.xs('Close', axis=1, level=0)
        else:
            close = raw[['Close']] if 'Close' in raw.columns else raw
        close = close.ffill().dropna(how='all')
        for t in tickers:
            if t in close.columns:
                series = close[t].dropna()
                if len(series) >= 2:
                    pct = round((float(series.iloc[-1]) / float(series.iloc[0]) - 1) * 100, 2)
                    result[t] = pct
    except Exception as e:
        st.warning(f'類股資料抓取部分失敗：{e}')
    return result

def _build_treemap_data(sectors: dict, returns: dict, market: str) -> go.Figure:
    """建立 Plotly Treemap 熱力圖"""
    ids, labels, parents, values, texts, colors = [], [], [], [], [], []

    # root
    ids.append(market)
    labels.append(market)
    parents.append('')
    values.append(0)
    texts.append('')
    colors.append(0)

    for ticker, meta in sectors.items():
        sec_ret = returns.get(ticker)
        sec_label = f"{meta['name']}<br>{sec_ret:+.1f}%" if sec_ret is not None else meta['name']
        ids.append(ticker)
        labels.append(sec_label)
        parents.append(market)
        values.append(max(abs(sec_ret) if sec_ret is not None else 1, 0.5))
        texts.append(ticker)
        colors.append(sec_ret if sec_ret is not None else 0)

        # sub-items
        for sub in meta.get('sub', []):
            sub_ret = returns.get(sub)
            sub_label = f"{sub.replace('.TW','')}<br>{sub_ret:+.1f}%" if sub_ret is not None else sub
            ids.append(f'{ticker}/{sub}')
            labels.append(sub_label)
            parents.append(ticker)
            values.append(max(abs(sub_ret) if sub_ret is not None else 0.5, 0.3))
            texts.append(sub)
            colors.append(sub_ret if sub_ret is not None else 0)

    # 顏色：最大值對稱
    max_abs = max(abs(c) for c in colors if c != 0) or 5
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents,
        values=values, text=texts,
        textinfo='label',
        marker=dict(
            colors=colors,
            colorscale=[[0, '#0f5132'], [0.35, '#1a6e36'], [0.5, '#1e2530'],
                        [0.65, '#c0392b'], [1, '#7b1212']],  # 台灣慣例：漲=紅 跌=綠
            cmid=0, cmin=-max_abs, cmax=max_abs,
            colorbar=dict(title='漲跌%', thickness=12),
            line=dict(width=1, color='#0d1117'),
        ),
        hovertemplate='<b>%{text}</b><br>漲跌：%{marker.color:+.2f}%<extra></extra>',
    ))
    fig.update_layout(
        template='plotly_dark',
        height=600,
        margin=dict(l=0, r=0, t=30, b=0),
        paper_bgcolor='#0d1117',
    )
    return fig

def render_sector_heatmap():
    st.markdown('### 🗺️ 產業熱力圖')
    st.caption('即時抓取各類股漲跌幅，紅=漲 / 綠=跌（台灣慣例）。點選區塊可展開子類股。')

    col_m, col_p, col_r = st.columns([2, 2, 1])
    market = col_m.selectbox('市場', ['🇺🇸 美股（GICS 11大類）', '🇹🇼 台股（主要類股）'],
                              key='heatmap_market')
    period_label = col_p.selectbox('計算區間', list(_PERIOD_MAP.keys()),
                                    index=0, key='heatmap_period')
    col_r.markdown('<br>', unsafe_allow_html=True)
    refresh = col_r.button('🔄 刷新', key='heatmap_refresh', use_container_width=True)

    is_us = '美股' in market
    sectors = _US_SECTORS if is_us else _TW_SECTORS
    period  = _PERIOD_MAP[period_label]

    # 收集所有需抓取的 ticker（類股代表 + 子成分）
    all_tickers = list(sectors.keys())
    for meta in sectors.values():
        all_tickers.extend(meta.get('sub', []))
    all_tickers = tuple(set(all_tickers))

    if refresh:
        _fetch_sector_returns.clear()

    with st.spinner(f'抓取 {len(all_tickers)} 個標的資料（{period_label}）...'):
        returns = _fetch_sector_returns(all_tickers, period)

    if not returns:
        st.error('❌ 無法取得任何類股資料，請確認網路連線')
        return

    # ── Treemap 主圖 ──────────────────────────────────────────
    market_label = '美股 GICS' if is_us else '台股類股'
    fig = _build_treemap_data(sectors, returns, market_label)
    st.plotly_chart(fig, width='stretch')

    # ── 數值排行表（補充用）──────────────────────────────────
    st.markdown(f'#### 📊 {market_label} 類股漲跌排行（{period_label}）')
    rank_rows = []
    for ticker, meta in sectors.items():
        ret = returns.get(ticker)
        rank_rows.append({
            '類股': meta['name'],
            '代號': ticker,
            f'{period_label}漲跌%': ret if ret is not None else 'N/A',
            '方向': ('📈 上漲' if ret and ret > 0 else ('📉 下跌' if ret and ret < 0 else '➡️ 持平')),
        })
    rank_rows.sort(key=lambda x: x[f'{period_label}漲跌%']
                   if isinstance(x[f'{period_label}漲跌%'], float) else 0, reverse=True)
    rank_df = pd.DataFrame(rank_rows)
    st.dataframe(rank_df, use_container_width=True, hide_index=True)

    # 覆蓋率說明
    fetched = sum(1 for t in sectors if returns.get(t) is not None)
    total_s = len(sectors)
    if fetched < total_s:
        _colored_box(
            f'⚠️ 僅取得 {fetched}/{total_s} 個類股資料，部分可能因 yfinance 限速或市場休市而缺失',
            'yellow')
    else:
        _colored_box(f'✅ 全部 {total_s} 個類股資料取得完整', 'green')



# ════════════════════════════════════════════════════════════════
# P2-B Phase 6-A/B/C: render_etf_single / portfolio / backtest 已抽出
# 此處 re-export 維持 app.py 既有 import 不變
# ════════════════════════════════════════════════════════════════
from etf_tab_single import render_etf_single  # noqa: E402,F401
from etf_tab_portfolio import render_etf_portfolio  # noqa: E402,F401
from etf_tab_backtest import render_etf_backtest  # noqa: E402,F401
