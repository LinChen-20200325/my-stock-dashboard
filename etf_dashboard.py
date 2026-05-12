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


def render_etf_single(gemini_fn=None):
    mkt_info = st.session_state.get('mkt_info', {})
    regime   = mkt_info.get('regime', 'neutral')
    macro_allocation_banner(regime)

    st.markdown('#### 🔍 輸入 ETF 代號')
    col_l, col_r = st.columns([2, 1])
    ticker    = col_l.text_input('ETF 代號（台灣加 .TW，如 0050.TW | 美國：SPY、QQQ）',
                                  value='0050.TW', key='etf_s_ticker').strip().upper()
    benchmark = col_r.text_input('對照基準（留空自動偵測）',
                                  value='', key='etf_s_bench').strip().upper()
    if not benchmark:
        benchmark = auto_detect_benchmark(ticker)

    if st.button('🔍 開始診斷', key='etf_s_btn', use_container_width=True):
        st.session_state['etf_s_active'] = ticker

    if st.session_state.get('etf_s_active') != ticker:
        st.info('💡 輸入 ETF 代號後點擊「開始診斷」')
        return

    with st.spinner(f'載入 {ticker} 資料中...'):
        df       = fetch_etf_price(ticker)
        divs     = fetch_etf_dividends(ticker)
        info     = fetch_etf_info(ticker)
        bench_df = fetch_etf_price(benchmark)

    if df.empty:
        st.error(f'❌ 找不到 {ticker}，請確認代號（台灣ETF需加 .TW）')
        st.session_state.pop('etf_s_active', None)
        return

    etf_name = info.get('longName') or info.get('shortName') or ticker
    # 費用率走 SITCA primary（台股 ETF 官方，海外 IP 走 NAS proxy）→ yfinance fallback
    expense  = get_etf_expense_ratio_safe(ticker)
    beta     = info.get('beta') or info.get('beta3Year')
    aum      = info.get('totalAssets')

    st.markdown(f'### 🏦 {etf_name} ({ticker})')

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('最新收盤', f'{df["Close"].iloc[-1]:.2f}')
    c2.metric('內扣費用率', f'{expense*100:.2f}%' if expense else 'N/A')
    c3.metric('Beta', f'{float(beta):.2f}' if beta else 'N/A')
    c4.metric('AUM', f'{aum/1e9:.1f}B USD' if aum and aum > 1e6 else 'N/A')

    # ── 自製品質評等（4 因子：AUM / 費用率 / 殖利率穩定度 / Beta）──
    try:
        from etf_quality import compute_etf_quality, render_quality_badge
        _quality = compute_etf_quality(ticker)
        render_quality_badge(_quality)
    except Exception as _e_q:
        st.caption(f'⚪ 品質評等載入失敗：{type(_e_q).__name__}')

    st.markdown('---')

    # ── 策略一：MK 郭俊宏 ─────────────────────────────────────
    st.markdown('#### 🧠 策略一：MK 郭俊宏 — 以息養股避雷策略')
    total_ret = calc_total_return_1y(df, divs)
    cur_yield = calc_current_yield(df, divs)
    ca, cb    = st.columns(2)
    ca.metric('近1年含息總報酬', f'{total_ret:.2f}%')
    cb.metric('現金殖利率（近12M）', f'{cur_yield:.2f}%')
    if cur_yield > 0 and total_ret < cur_yield:
        _colored_box('⚠️ <b>紅燈警示</b>：賺了股息賠了價差，侵蝕本金中，<b>不宜作為核心資產</b>', 'red')
        _teacher_conclusion('郭俊宏',
                            f'含息總報酬 {total_ret:.1f}% < 殖利率 {cur_yield:.1f}%',
                            '本金侵蝕中，高息陷阱',
                            '換標的，找總報酬為正的 ETF')
    elif cur_yield > 0:
        _colored_box(f'✅ 含息總報酬({total_ret:.1f}%) > 殖利率({cur_yield:.1f}%)，核心資產條件通過', 'green')
        _teacher_conclusion('郭俊宏',
                            f'含息總報酬 {total_ret:.1f}%，殖利率 {cur_yield:.1f}%',
                            '價差 + 配息雙贏，核心資產條件通過',
                            '可列入長期核心持倉')
    else:
        st.info('ℹ️ 無配息紀錄（成長型ETF），以價差報酬評估')
        _teacher_conclusion('郭俊宏',
                            f'近1年總報酬 {total_ret:.1f}%，無配息',
                            '成長型ETF，以價差報酬衡量',
                            '衡量 CAGR 是否超過大盤')

    # ── MK 框架 #1+#2+#7：配息健康度 + 3Y 年化報酬（汰弱五項中前兩項 + 留強 3-3-3 第二項）──
    st.markdown('#### 💧 配息健康度 + 年化報酬（MK 框架燈號）')
    _now2 = df.index[-1]
    _12m_div = float(divs[(divs.index >= _now2 - timedelta(days=365))].sum()) if not divs.empty else 0.0
    _prev12m_div = float(divs[(divs.index >= _now2 - timedelta(days=730))
                              & (divs.index < _now2 - timedelta(days=365))].sum()) if not divs.empty else 0.0
    _div_yoy = ((_12m_div - _prev12m_div) / _prev12m_div * 100) if _prev12m_div > 0 else None
    _3y_cutoff = _now2 - timedelta(days=365 * 3)
    _df_3y = df[df.index >= _3y_cutoff]
    _cagr3 = calc_cagr(_df_3y) if len(_df_3y) >= 30 else None
    # MK 框架 #6：成立年數（yfinance firstTradeDateEpochUtc primary，df span fallback）
    _incept_yrs = None
    try:
        _ep = info.get('firstTradeDateEpochUtc') if isinstance(info, dict) else None
        if _ep:
            import datetime as _dt_inc
            _incept_yrs = (_dt_inc.datetime.now()
                           - _dt_inc.datetime.fromtimestamp(int(_ep))).days / 365.25
    except Exception:
        pass
    if _incept_yrs is None and len(df) > 0:
        _incept_yrs = (df.index[-1] - df.index[0]).days / 365.25

    _mc1, _mc2, _mc3, _mc4 = st.columns(4)
    if _div_yoy is None:
        _mc1.metric('配息 12M YoY', 'N/A', delta='—')
    elif _div_yoy < -10:
        _mc1.metric('配息 12M YoY', f'{_div_yoy:+.1f}%', delta='⚠️ 衰退 > 10%', delta_color='inverse')
    elif _div_yoy < 0:
        _mc1.metric('配息 12M YoY', f'{_div_yoy:+.1f}%', delta='略減（< 10%）', delta_color='inverse')
    else:
        _mc1.metric('配息 12M YoY', f'{_div_yoy:+.1f}%', delta='✅ 增長 / 持平', delta_color='normal')
    if cur_yield > 0 and total_ret < cur_yield:
        _mc2.metric('含息報酬 − 殖利率', f'{total_ret - cur_yield:+.1f}pp',
                    delta='🔴 本金侵蝕', delta_color='inverse')
    elif cur_yield > 0:
        _mc2.metric('含息報酬 − 殖利率', f'{total_ret - cur_yield:+.1f}pp',
                    delta='✅ 雙贏', delta_color='normal')
    else:
        _mc2.metric('含息報酬 − 殖利率', 'N/A', delta='無配息')
    if _cagr3 is None:
        _mc3.metric('近 3Y 年化報酬', 'N/A', delta='資料不足 < 90 日')
    elif _cagr3 >= 7:
        _mc3.metric('近 3Y 年化報酬', f'{_cagr3:.1f}%',
                    delta='✅ 達 7% 定存替代', delta_color='normal')
    else:
        _mc3.metric('近 3Y 年化報酬', f'{_cagr3:.1f}%',
                    delta='🟡 不及 7% 門檻', delta_color='inverse')
    if _incept_yrs is None:
        _mc4.metric('成立年數', 'N/A')
    elif _incept_yrs >= 3:
        _mc4.metric('成立年數', f'{_incept_yrs:.1f} 年',
                    delta='✅ ≥ 3 年（多空考驗）', delta_color='normal')
    else:
        _mc4.metric('成立年數', f'{_incept_yrs:.1f} 年',
                    delta='🟡 未滿 3 年（選舊不選新）', delta_color='inverse')
    st.caption(
        '⚠️ 配息來源「**平準金佔比**」需 ETF 公開說明書揭露，本期暫不顯示（下輪計畫加 SITCA 抓取）。'
        '\n\n💡 **MK 老師標準**：4 項指標若有 ≥ 2 項 🔴/🟡 警示 → 建議汰弱換強。'
    )

    # ── 策略二：孫慶龍 7% ─────────────────────────────────────
    st.markdown('#### 🧠 策略二：孫慶龍 — 7% 存股聖經估值買賣點')
    avg_yield = calc_avg_yield(df, divs, years=5)
    cc, cd    = st.columns(2)
    cc.metric('近5年平均殖利率', f'{avg_yield:.2f}%' if avg_yield else 'N/A')
    cd.metric('現今殖利率', f'{cur_yield:.2f}%')
    if avg_yield > 0:
        if cur_yield >= 7:
            _colored_box('🟢 <b>強烈買進（特價）</b>：殖利率 ≥ 7%，現值低估，值得分批佈局', 'green')
            _teacher_conclusion('孫慶龍',
                                f'現金殖利率 {cur_yield:.1f}%（5年均 {avg_yield:.1f}%）',
                                '殖利率 ≥ 7%，低估特價區，強烈買進',
                                '分批佈局，停損設 -15%')
        elif cur_yield <= 3:
            _colored_box('🔴 <b>獲利了結（昂貴）</b>：殖利率 ≤ 3%，現值高估，考慮減碼', 'red')
            _teacher_conclusion('孫慶龍',
                                f'現金殖利率 {cur_yield:.1f}%（5年均 {avg_yield:.1f}%）',
                                '殖利率 ≤ 3%，高估昂貴區，獲利了結',
                                '分批出清，等待殖利率回升到 5% 以上')
        elif cur_yield <= 5:
            _colored_box('🟡 <b>適度減碼（合理）</b>：殖利率 ≤ 5%，估值合理偏高', 'yellow')
            _teacher_conclusion('孫慶龍',
                                f'現金殖利率 {cur_yield:.1f}%（5年均 {avg_yield:.1f}%）',
                                '殖利率 3%~5%，估值合理偏高，適度減碼',
                                '不宜重倉，等待 5% 以上再加碼')
        else:
            st.info(f'殖利率 {cur_yield:.1f}% 位於 5%~7% 合理區間，中性持有')
            _teacher_conclusion('孫慶龍',
                                f'現金殖利率 {cur_yield:.1f}%（5年均 {avg_yield:.1f}%）',
                                '殖利率 5%~7% 合理區間，中性持有',
                                '可持有，待殖利率 ≥ 7% 再加碼')
    else:
        st.info('ℹ️ 無充足配息歷史，套用回測頁評估價差績效')
        _teacher_conclusion('孫慶龍',
                            '配息歷史不足',
                            '無法套用 7% 存股聖經，改看回測 CAGR',
                            '前往「ETF回測」確認年化報酬是否 ≥ 8%')

    # ── 策略三：春哥 VCP ──────────────────────────────────────
    st.markdown('#### 🧠 策略三：春哥（Stan Weinstein）— VCP 波幅收縮突破')
    vcp = check_vcp_signal(df)
    ce, cf, cg = st.columns(3)
    ce.metric('站上 50MA',  '✅' if vcp['above_ma50']  else '❌')
    cf.metric('站上 200MA', '✅' if vcp['above_ma200'] else '❌')
    cg.metric('量能確認',   '✅' if vcp['vol_confirm'] else '❌')
    if vcp['weekly_ranges']:
        st.caption('近5週波幅：' + ' → '.join(f'{r}%' for r in vcp['weekly_ranges']))
    if vcp['signal']:
        _colored_box(f'🚀 <b>VCP 突破買訊！</b> 嚴守 8% 停損線：{vcp["stop_loss"]}', 'green')
        _teacher_conclusion('春哥',
                            f'50MA ✅ | 200MA ✅ | 量能 ✅',
                            'VCP 三條件全過，突破買進',
                            f'停損設 {vcp["stop_loss"]}（-8%），突破後嚴守紀律')
    else:
        missing = []
        if not vcp['above_ma50']:  missing.append('未站上50MA')
        if not vcp['above_ma200']: missing.append('未站上200MA')
        if not vcp['vol_confirm']: missing.append('量能不足')
        if len(df) < 210:         missing.append('資料不足210天')
        _miss_str = ' | '.join(missing) if missing else '波幅尚未收縮'
        st.info('⏳ VCP 條件未滿足：' + _miss_str)
        _teacher_conclusion('春哥',
                            f'VCP 缺：{_miss_str}',
                            '條件未齊，耐心等候突破訊號',
                            '加入觀察清單，條件滿足再進場')

    # ── ETF 防呆：折溢價 + 追蹤誤差 + 建議買賣時機 ──────────
    st.markdown('#### 🛡️ ETF 折溢價 — 建議買賣時機')
    prem = calc_premium_discount(info, df, ticker)   # 傳入 ticker 以使用 FinMind/TWSE NAV
    te   = calc_tracking_error(df, bench_df)

    # 折溢價建議邏輯
    _pct = prem['premium_pct']
    if _pct is not None:
        if _pct <= -2:
            _prem_color  = '#3fb950'
            _prem_action = '🟢 強烈買進時機'
            _prem_reason = f'折價 {abs(_pct):.2f}%，低於 NAV 買入，立即為你創造安全邊際'
        elif _pct <= -0.5:
            _prem_color  = '#58a6ff'
            _prem_action = '🔵 合理買進'
            _prem_reason = f'折價 {abs(_pct):.2f}%，略低於 NAV，可正常分批買入'
        elif _pct <= 1.0:
            _prem_color  = '#d29922'
            _prem_action = '🟡 中性觀望'
            _prem_reason = f'溢價 {_pct:.2f}%（±1% 正常範圍），無需急追'
        elif _pct <= 3.0:
            _prem_color  = '#f85149'
            _prem_action = '🔴 暫緩買進'
            _prem_reason = f'溢價 {_pct:.2f}%，高於 NAV，追高風險較大，等待回落'
        else:
            _prem_color  = '#f85149'
            _prem_action = '🔴 嚴禁追高'
            _prem_reason = f'溢價 {_pct:.2f}%，嚴重高溢價，等待折價或換標的'
    elif prem.get('stale_nav'):
        _prem_color  = '#8b949e'
        _prem_action = '⏳ NAV 資料延遲'
        _prem_reason = 'NAV 資料早於前一交易日（FinMind/yfinance 同步延遲），暫不顯示折溢價以免誤判'
    else:
        _prem_color  = '#8b949e'
        _prem_action = 'ℹ️ 無 NAV 資料'
        _prem_reason = 'yfinance 未提供 NAV，建議至官網確認折溢價'

    st.markdown(
        f'<div style="background:#0d1117;border:2px solid {_prem_color};border-radius:10px;'
        f'padding:14px 18px;margin-bottom:10px;">'
        f'<div style="font-size:20px;font-weight:900;color:{_prem_color};">{_prem_action}</div>'
        f'<div style="font-size:13px;color:#c9d1d9;margin-top:4px;">{_prem_reason}</div>'
        + (f'<div style="font-size:12px;color:#8b949e;margin-top:6px;">折溢價率：'
           f'<b style="color:{_prem_color};">{_pct:+.2f}%</b>'
           + (f'　<span style="color:#6e7681;">（資料日：{prem.get("data_date")}）</span>'
              if prem.get('data_date') else '')
           + '</div>' if _pct is not None else '')
        + '</div>',
        unsafe_allow_html=True)

    if _pct is not None:
        _prem_concl = ('折價買進，獲得安全邊際' if _pct <= -0.5
                       else '中性，無需急追' if _pct <= 1.0
                       else '高溢價，追高風險大，等待回落')
        _prem_act2  = ('分批買進' if _pct <= -0.5
                       else '持有觀望' if _pct <= 1.0
                       else '暫緩或換標的')
        _teacher_conclusion('宏爺', f'{ticker} 折溢價 {_pct:+.2f}%', _prem_concl, _prem_act2)

    ch, ci = st.columns(2)
    ch.metric('折溢價率', f'{_pct:+.2f}%' if _pct is not None else 'N/A')
    if te is not None:
        ci.metric(f'追蹤誤差 vs {benchmark}', f'{te:.2f}%')
        if te > 1.5:
            ci.markdown('<small style="color:#d29922;">⚠️ 追蹤誤差 >1.5%，注意隱藏成本</small>',
                        unsafe_allow_html=True)
    else:
        ci.metric('追蹤誤差', 'N/A')

    # ── 歷史淨值及折溢價表 ────────────────────────────────────
    import pandas as _pd_navtbl
    _nav_hist = fetch_etf_nav_history(ticker, days=35)
    if not _nav_hist.empty and 'nav' in _nav_hist.columns and not df.empty:
        try:
            _price_s = df[['Close']].copy()
            _price_s.index = _pd_navtbl.to_datetime(_price_s.index).normalize()
            _nav_hist2 = _nav_hist.copy()
            _nav_hist2['date'] = _pd_navtbl.to_datetime(_nav_hist2['date'])
            _nav_hist2 = _nav_hist2.set_index('date')
            _merged = _nav_hist2.join(_price_s, how='inner').dropna()
            if not _merged.empty:
                _merged['折溢價']  = (_merged['Close'] - _merged['nav']).round(2)
                _merged['折溢價%'] = ((_merged['Close'] - _merged['nav']) / _merged['nav'] * 100).round(2)
                _display = _merged.reset_index()[['date','Close','nav','折溢價','折溢價%']].tail(20)
                _display.columns = ['日期','市價','淨值','折溢價','折溢價%']
                _display['日期'] = _display['日期'].dt.strftime('%Y/%m/%d')
                st.markdown(f'**{ticker} 近期淨值及折溢價**（折溢價% = (市價-淨值)/淨值×100）')
                st.dataframe(_display.sort_values('日期', ascending=False),
                             use_container_width=True, hide_index=True)
        except Exception as _ne:
            print(f'[ETF NAV Table] {_ne}')

    # ── BIAS 乖離率 ───────────────────────────────────────────
    st.markdown('#### 📐 BIAS 乖離率（均線偏離程度）')
    _render_bias(df, ticker)

    # ── 年線乖離率(MA240) + KD — 供存股 AI 使用 ──────────────
    _close_ai = df['Close'] if 'Close' in df.columns else df.get('close', pd.Series(dtype=float))
    _bias240_ai = None
    _kv_ai = _dv_ai = None
    if len(_close_ai) >= 240:
        _ma240_ai   = float(_close_ai.rolling(240).mean().iloc[-1])
        _bias240_ai = round((float(_close_ai.iloc[-1]) - _ma240_ai) / _ma240_ai * 100, 2)
    if 'High' in df.columns and 'Low' in df.columns and len(df) >= 9:
        _h9  = df['High'].rolling(9).max()
        _l9  = df['Low'].rolling(9).min()
        _rsv = ((df['Close'] - _l9) / (_h9 - _l9).replace(0, float('nan')) * 100).fillna(50)
        _k_s = _rsv.ewm(com=2, adjust=False).mean()
        _d_s = _k_s.ewm(com=2, adjust=False).mean()
        _kv_ai = round(float(_k_s.iloc[-1]), 1)
        _dv_ai = round(float(_d_s.iloc[-1]), 1)

    # ── MK 框架 #11：標準差 σ 量化買點（年線 ± σ 位階分級）──────
    st.markdown('#### 🎯 標準差量化買點（MK 框架：跌了就買）')
    if len(df) >= 252:
        _ret_252 = df['Close'].pct_change().tail(252).dropna()
        _sigma_pct = (float(_ret_252.std()) * (252 ** 0.5) * 100) if not _ret_252.empty else 0.0
        _cur_p = float(df['Close'].iloc[-1])
        _ma240 = float(df['Close'].rolling(240).mean().iloc[-1]) if len(df) >= 240 else None
        if _ma240 and _sigma_pct > 0:
            _bias_pct = (_cur_p - _ma240) / _ma240 * 100
            _z = _bias_pct / _sigma_pct
            if _z <= -2:
                _label, _color, _action = '🟢 極佳買點（≤ -2σ）', 'green', '大跌大買 — 大幅加碼，剩餘資金主力投入'
            elif _z <= -1:
                _label, _color, _action = '🟢 進場買點（-2σ ~ -1σ）', 'green', '小跌小買 — 投入 20–30% 資金'
            elif _z <= 1:
                _label, _color, _action = '🟡 持平區（±1σ 內）', 'yellow', '保留現金，等待 ≤ -1σ 進場'
            elif _z <= 2:
                _label, _color, _action = '🟠 偏高（+1σ ~ +2σ）', 'yellow', '不追高；衛星部位可考慮停利'
            else:
                _label, _color, _action = '🔴 極端偏高（≥ +2σ）', 'red', '建議減碼；勿在 +2σ 以上加碼'
            _colored_box(
                f'<b>{_label}</b><br>'
                f'目前 {_cur_p:.2f} vs MA240 {_ma240:.2f} → '
                f'偏離 {_bias_pct:+.2f}%（年化 σ ≈ {_sigma_pct:.1f}%，z = {_z:+.2f}）<br>'
                f'<b>建議</b>：{_action}',
                _color,
            )
            _teacher_conclusion('郭俊宏',
                                f'位階 z={_z:+.2f}σ',
                                _label.split('（')[0],
                                _action)
        else:
            st.info('ℹ️ MA240 或 σ 不足，無法分級')
    else:
        st.info(f'ℹ️ 資料不足 252 日（目前 {len(df)} 日），無法計算 σ 位階')

    # ── MK 框架 #5：季線 × 趨勢 聯合警示燈號（跌破 + 下彎 = 趨勢轉弱）──
    st.markdown('#### 📉 季線 × 趨勢 聯合警示（MK 框架：技術面防禦）')
    if len(df) >= 80:
        _close_now = float(df['Close'].iloc[-1])
        _ma60_series = df['Close'].rolling(60).mean()
        _ma60_now = float(_ma60_series.iloc[-1])
        _ma60_20d = float(_ma60_series.iloc[-21])
        _above_ma60 = _close_now > _ma60_now
        _ma60_slope = (_ma60_now - _ma60_20d) / _ma60_20d * 100 if _ma60_20d > 0 else 0.0
        _ma60_up = _ma60_slope > 0
        if _above_ma60 and _ma60_up:
            _t5_label, _t5_color, _t5_action = '🟢 健康（站上季線且 MA60 上彎）', 'green', '正常持有，不需動作'
        elif _above_ma60 and not _ma60_up:
            _t5_label, _t5_color, _t5_action = '🟡 上漲乏力（站上但 MA60 下彎）', 'yellow', '觀察 MA60 是否止跌；衛星部位降槓桿'
        elif not _above_ma60 and _ma60_up:
            _t5_label, _t5_color, _t5_action = '🟡 短線回測（跌破但 MA60 仍上彎）', 'yellow', '可逢低分批布局，等回上 MA60 確認'
        else:
            _t5_label, _t5_color, _t5_action = '🔴 趨勢轉弱（跌破 MA60 且下彎）', 'red', '建議減碼或觀望，等趨勢翻轉'
        _colored_box(
            f'<b>{_t5_label}</b><br>'
            f'Close {_close_now:.2f} vs MA60 {_ma60_now:.2f}（'
            f'{(_close_now-_ma60_now)/_ma60_now*100:+.2f}%）<br>'
            f'MA60 20 日斜率：{_ma60_slope:+.2f}%（{"上彎 ↗" if _ma60_up else "下彎 ↘"}）<br>'
            f'<b>建議</b>：{_t5_action}',
            _t5_color,
        )
        _teacher_conclusion('郭俊宏',
                            f'季線 {("站上" if _above_ma60 else "跌破")}+'
                            f'{("上彎" if _ma60_up else "下彎")}',
                            _t5_label.split('（')[0],
                            _t5_action)
    else:
        st.info(f'ℹ️ 資料不足 80 日（目前 {len(df)} 日），無法計算季線 × 斜率')

    # ── MK 規格三大訊號：破發 ｜ 跌破均線買點 ｜ 死亡交叉 ────────
    st.markdown('#### 🚨 MK 規格三大訊號（破發檢測 ｜ 跌了就買 ｜ 趨勢警示）')
    _cur_price = float(df['Close'].iloc[-1]) if len(df) > 0 else None

    # ① 條件 B：破發檢測（市價 < 發行價 → 法規限制配資本利得 → 配息必縮水）
    _launch_price = _get_etf_launch_price(ticker, df)
    _vs_launch_pct = None
    _broken_issue = False
    if _launch_price and _cur_price:
        _vs_launch_pct = (_cur_price - _launch_price) / _launch_price * 100
        _broken_issue = _cur_price < _launch_price
        if _broken_issue:
            _colored_box(
                f'🔴 <b>條件 B 警訊：破發狀態</b><br>'
                f'最新市價 {_cur_price:.2f} &lt; 發行價 {_launch_price:.2f}'
                f'（{_vs_launch_pct:+.2f}%）<br>'
                f'<b>MK 提醒</b>：法規規定 ETF 淨值低於發行價時不能配發資本利得，'
                f'配息率「一定會縮水」；若同時觸發條件 A（吃本金）→ 標準汰弱訊號',
                'red')
            _teacher_conclusion('郭俊宏',
                                f'市價 {_cur_price:.2f} < 發行價 {_launch_price:.2f}',
                                '破發 → 配資本利得受限，配息將縮水',
                                '若搭配條件 A → 換股汰弱')
        else:
            _colored_box(
                f'✅ <b>條件 B 通過：未破發</b><br>'
                f'市價 {_cur_price:.2f} ≥ 發行價 {_launch_price:.2f}'
                f'（{_vs_launch_pct:+.2f}%）',
                'green')
    else:
        st.info('ℹ️ 無發行價資料（非台股 ETF 或代號未收錄）→ 跳過條件 B')

    # ② 跌了就買：跌破月線 / 季線（規格版直球買點訊號）
    _ma20 = _ma60_v = None
    _below_ma20 = _below_ma60 = False
    if len(df) >= 60 and _cur_price:
        _ma20   = float(df['Close'].rolling(20).mean().iloc[-1])
        _ma60_v = float(df['Close'].rolling(60).mean().iloc[-1])
        _below_ma20 = _cur_price < _ma20
        _below_ma60 = _cur_price < _ma60_v
        if _below_ma60:
            _colored_box(
                f'🟢🟢 <b>跌破季線：波段大買點（超跌）</b><br>'
                f'市價 {_cur_price:.2f} &lt; MA60 {_ma60_v:.2f}'
                f'（{(_cur_price-_ma60_v)/_ma60_v*100:+.2f}%）<br>'
                f'<b>MK 提醒</b>：跌破季線視為波段超跌，分批加碼黃金區',
                'green')
            _teacher_conclusion('郭俊宏',
                                f'市價 {_cur_price:.2f} < MA60 {_ma60_v:.2f}',
                                '波段超跌進場區',
                                '剩餘資金分批加碼')
        elif _below_ma20:
            _colored_box(
                f'🟢 <b>跌破月線：短線小買點</b><br>'
                f'市價 {_cur_price:.2f} &lt; MA20 {_ma20:.2f}'
                f'（{(_cur_price-_ma20)/_ma20*100:+.2f}%）<br>'
                f'<b>MK 提醒</b>：跌破月線可小量加碼',
                'green')
            _teacher_conclusion('郭俊宏',
                                f'市價 {_cur_price:.2f} < MA20 {_ma20:.2f}',
                                '短線小買點',
                                '投入 20–30% 資金小量加碼')
        else:
            _colored_box(
                f'⚪ <b>站上月線/季線</b>：市價 {_cur_price:.2f} ≥ '
                f'MA20 {_ma20:.2f} / MA60 {_ma60_v:.2f}<br>'
                f'未進入「跌了就買」區間，維持紀律扣款或觀望',
                'yellow')

        # ③ 死亡交叉：MA20 < MA60 → 趨勢偏空
        if _ma20 < _ma60_v:
            _colored_box(
                f'🟡 <b>趨勢偏空：MA20 &lt; MA60（死亡交叉）</b><br>'
                f'MA20 {_ma20:.2f} &lt; MA60 {_ma60_v:.2f}'
                f'（差 {(_ma20-_ma60_v)/_ma60_v*100:+.2f}%）<br>'
                f'<b>MK 提醒</b>：均線死叉 → 注意風險，衛星部位降槓桿',
                'yellow')
            _teacher_conclusion('郭俊宏',
                                f'MA20 {_ma20:.2f} < MA60 {_ma60_v:.2f}',
                                '均線死叉 → 趨勢偏空',
                                '衛星部位停利或減碼，核心紀律扣款')
        else:
            st.caption(f'✅ 黃金交叉狀態：MA20 {_ma20:.2f} ≥ MA60 {_ma60_v:.2f}（趨勢偏多）')
    else:
        st.info(f'ℹ️ 資料不足 60 日（目前 {len(df)} 日），無法計算月線/季線交叉')

    # ── 同儕近 3M/6M/1Y 排名 ──────────────────────────────────
    _peer_rank = compute_etf_peer_ranking(ticker)
    if _peer_rank.get('_err'):
        st.caption(f'⚪ 同儕排名：{_peer_rank["_err"]}（分類 {_peer_rank.get("category") or "未分類"}）')
    else:
        _cat = _peer_rank.get('category', '')
        st.markdown(f'#### 🏆 {ticker} 同儕排名（vs {_cat} 類）')
        _c3m, _c6m, _c1y = st.columns(3)
        for _col, _lbl, _key in [(_c3m, '近 3M', 63), (_c6m, '近 6M', 126), (_c1y, '近 1Y', 252)]:
            _data = _peer_rank.get(_key) or {}
            with _col:
                if _data.get('_err'):
                    st.metric(_lbl, 'N/A', help=_data['_err'])
                    continue
                _self = _data['self_ret']
                _med = _data['peer_median']
                _pct = _data['percentile']
                _n = _data['peer_count']
                _icon = '🟢' if _pct >= 75 else ('🟡' if _pct >= 25 else '🔴')
                _color = '#3fb950' if _pct >= 75 else ('#d29922' if _pct >= 25 else '#f85149')
                st.markdown(
                    f"<div style='border:1px solid {_color};border-left:4px solid {_color};"
                    f"border-radius:0 6px 6px 0;padding:8px 14px;background:#0d1117'>"
                    f"<div style='color:#8b949e;font-size:11px'>{_lbl}　{_icon} PR {_pct:.0f}</div>"
                    f"<div style='color:{_color};font-size:22px;font-weight:700;margin-top:2px'>"
                    f"{_self:+.2f}%</div>"
                    f"<div style='color:#6e7681;font-size:11px;margin-top:4px'>"
                    f"vs 同類 {_n} 檔（中位數 {_med:+.2f}%）</div>"
                    f"</div>", unsafe_allow_html=True)
        st.caption('PR = 百分位排名（越高代表勝率越好）；報酬已含息（yfinance auto_adjust）。'
                   '🟢 PR≥75　🟡 25-75　🔴 <25')

    # ── 走勢圖 ────────────────────────────────────────────────
    st.markdown(f'#### 📈 {ticker} 近5年走勢')
    _plot_etf_chart(df, ticker, benchmark, bench_df)

    # ── 存入 session_state 供 Tab⑨ 使用 ─────────────────────
    # 海外 ETF 偵測：ticker 非 4-6 碼台灣代號（如 VOO/SCHD/QQQ）→ 本系統 NAV/費用率
    # 5 源僅限台灣 ETF（SITCA / FinMind / TWSE / goodinfo / MoneyDJ），標 ⚪ 非異常
    import re as _re_etf
    _is_overseas = not bool(_re_etf.match(r'^\d{4,6}\.(TW|TWO)$', ticker))
    _err_expense = None if (expense or _is_overseas) else (
        'SITCA + MoneyDJ + yfinance.info[expenseRatio] 3 源全失敗'
        '（私募 / 已下市可能）'
    )
    _err_nav = None if ((prem or {}).get('nav') is not None or _is_overseas) else (
        'FinMind ETF NAV + goodinfo + TWSE OpenAPI + MoneyDJ + yfinance 5 源全失敗'
    )
    st.session_state['etf_single_data'] = {
        'ticker': ticker, 'name': etf_name,
        'cur_yield': cur_yield, 'avg_yield': avg_yield,
        'total_ret': total_ret, 'vcp': vcp,
        'premium': prem, 'te': te, 'regime': regime,
        'price_df': df,
        'expense': expense, 'beta': beta, 'aum': aum,
        'k_val': _kv_ai, 'd_val': _dv_ai,
        'bias240': _bias240_ai,
        # MK 規格三大訊號
        'launch_price':   _launch_price,
        'vs_launch_pct':  _vs_launch_pct,
        'broken_issue':   _broken_issue,
        'below_ma20':     _below_ma20,
        'below_ma60':     _below_ma60,
        'dead_cross':     (_ma20 is not None and _ma60_v is not None
                           and _ma20 < _ma60_v),
        '_is_overseas': _is_overseas,
        '_err_expense': _err_expense,
        '_err_nav':     _err_nav,
    }

    # ── AI ETF 存股決策總結 ───────────────────────────────────
    if gemini_fn:
        _etf_ai_hokei(gemini_fn, ticker, etf_name, cur_yield, _bias240_ai, _kv_ai, _dv_ai)

    # ── 統一投資決策分析模組 ──────────────────────────────────
    render_unified_decision(gemini_fn, {
        'type': 'etf',
        'id':   ticker,
        'data': {
            'ETF':              f'{etf_name} ({ticker})',
            '現金殖利率':        f'{cur_yield:.2f}%',
            '近5年平均殖利率':   f'{avg_yield:.2f}%',
            '近1年含息總報酬':   f'{total_ret:.2f}%',
            '年線乖離率BIAS240': f'{_bias240_ai:+.2f}%' if _bias240_ai is not None else 'N/A（< 240日）',
            'KD': (f'K:{_kv_ai:.1f} D:{_dv_ai:.1f}' if _kv_ai is not None else 'N/A'),
            'VCP突破':           vcp.get('signal', False) if isinstance(vcp, dict) else False,
            '折溢價率':          f'{prem["premium_pct"]}%' if prem.get("premium_pct") is not None else 'N/A',
            '追蹤誤差':          f'{te:.2f}%' if te is not None else 'N/A',
            '大盤狀態':          regime,
        },
    })

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

# ═══════════════════════════════════════════════════════════════
# Tab ⑦：ETF 組合配置與動態再平衡引擎
# ═══════════════════════════════════════════════════════════════

def render_etf_portfolio(gemini_fn=None):
    mkt_info = st.session_state.get('mkt_info', {})
    regime   = mkt_info.get('regime', 'neutral')
    macro_allocation_banner(regime)

    st.markdown('#### 📋 輸入組合（格式：代號,目標權重%,現值 元[,類型]）')
    st.caption('💡 第 4 欄「類型」可填「核心」或「衛星」（省略則依代號自動分類）。MK 框架核衛分離見下方燈號。')
    default_input = ("0050.TW,40,200000,核心\n"
                     "00713.TW,30,150000,核心\n"
                     "BND,20,100000,核心\n"
                     "00878.TW,10,50000,核心")
    raw       = st.text_area('組合輸入', value=default_input, height=130,
                              key='etf_p_input', label_visibility='collapsed')
    tolerance = st.slider('再平衡容忍偏離度（%）', 1, 15, 5, key='etf_p_tol')

    if st.button('📊 計算組合', key='etf_p_btn', use_container_width=True):
        st.session_state['etf_p_active'] = True

    if not st.session_state.get('etf_p_active'):
        st.info('💡 填入組合後點擊「計算組合」')
        return

    # MK 框架 #9：核心 / 衛星預設分類（高股息大型 / 全市場 / 債券 → 核心；其他 → 衛星）
    _CORE_TICKERS = {'0050','0051','0056','006208','00713','00878','00919','00929',
                     '00940','00946','00713B','00679B','00937B','BND','AGG','VTI',
                     'VOO','SPY','VT','SCHD','VEA','VWO','VNQ'}
    def _auto_role(tk: str) -> str:
        code = tk.replace('.TWO', '').replace('.TW', '').upper()
        return '核心' if code in _CORE_TICKERS else '衛星'

    # 解析輸入
    rows = []
    for line in raw.strip().splitlines():
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 3:
            try:
                _tk = parts[0].upper()
                _role = parts[3] if (len(parts) >= 4 and parts[3] in ('核心', '衛星')) else _auto_role(_tk)
                rows.append({'ticker': _tk,
                              'target_pct': float(parts[1]),
                              'current_value': float(parts[2]),
                              'role': _role})
            except ValueError:
                st.warning(f'⚠️ 無法解析：{line}')
    if not rows:
        st.error('❌ 請輸入有效的組合資料'); return

    total_value = sum(r['current_value'] for r in rows)
    for r in rows:
        r['actual_pct']  = round(r['current_value'] / total_value * 100, 2)
        r['deviation']   = round(r['actual_pct'] - r['target_pct'], 2)

    st.markdown(f'**總資產現值：{total_value:,.0f} 元**')
    # 查詢 ETF 名稱（去掉 .TW/.TWO 後綴後查 stock_names）
    try:
        from stock_names import get_stock_name as _gsn_etf
        def _etf_name(tk):
            code = tk.replace('.TWO','').replace('.TW','')
            n = _gsn_etf(code)
            return n if n and n != code else (fetch_etf_info(tk).get('shortName') or fetch_etf_info(tk).get('longName') or tk)
    except Exception:
        def _etf_name(tk): return tk
    overview_df = pd.DataFrame([{
        'ETF': r['ticker'],
        '名稱': _etf_name(r['ticker']),
        '類型': r.get('role', '—'),
        '目標權重%': r['target_pct'],
        '實際權重%': r['actual_pct'], '偏離度%': r['deviation'],
        '現值(元)': f'{r["current_value"]:,.0f}',
    } for r in rows])
    st.dataframe(overview_df, use_container_width=True, hide_index=True)

    # ── 🛰️ ETF 追蹤戰情室（核心/衛星分流燈號 + Sparkline）─────
    st.markdown('#### 🛰️ ETF 追蹤戰情室（核衛分流健檢）')
    st.caption('💡 **核心**看「總報酬 vs 殖利率 + MA60 趨勢」；**衛星**看「MA20 ± σ 五階分級買賣點」')
    with st.spinner('批次計算 ETF 健檢指標...'):
        _war_rows = [_compute_etf_warroom_row(r['ticker'], _etf_name(r['ticker']),
                                              r.get('role', '—'))
                     for r in rows]

    # 核心戰情室 column_config
    _core_cols = {
        '代號':         st.column_config.TextColumn('代號', width='small'),
        '名稱':         st.column_config.TextColumn('名稱', width='medium'),
        '市價':         st.column_config.NumberColumn('市價', format='%.2f'),
        '折溢價%':      st.column_config.NumberColumn('折溢價%', format='%+.2f%%',
                          help='> +1% 追高；< 0% 折價撿便宜（MK 條件 C）'),
        '年化配息率%':  st.column_config.NumberColumn('年化配息率%', format='%.2f%%'),
        '1年含息報酬%': st.column_config.NumberColumn('1年含息報酬%', format='%+.2f%%',
                          help='含息總報酬，與年化配息率比較'),
        '距季線%':      st.column_config.NumberColumn('距 MA60%', format='%+.2f%%',
                          help='負值=跌破季線 → 🟡 趨勢轉弱'),
        '走勢':         st.column_config.LineChartColumn('近30日走勢'),
        '健康燈號':     st.column_config.TextColumn('體質燈號', width='large',
                          help='🟢 體質健康 / 🔴 賺息賠本 / 🟡 趨勢轉弱'),
        '動作建議':     st.column_config.TextColumn('動作建議', width='medium'),
    }

    # 衛星戰情室 column_config：突顯 σ 位階 + 加碼比例
    _sat_cols = {
        '代號':         st.column_config.TextColumn('代號', width='small'),
        '名稱':         st.column_config.TextColumn('名稱', width='medium'),
        '市價':         st.column_config.NumberColumn('市價', format='%.2f'),
        '距月線%':      st.column_config.NumberColumn('距 MA20%', format='%+.2f%%',
                          help='相對月線乖離；σ 分級的基準'),
        'σ位階':        st.column_config.TextColumn('σ 位階', width='medium',
                          help='-3σ 股災 / -2σ 超跌 / -1σ 便宜 / +2σ 停利'),
        '1年含息報酬%': st.column_config.NumberColumn('1年含息報酬%', format='%+.2f%%'),
        '走勢':         st.column_config.LineChartColumn('近30日走勢'),
        '健康燈號':     st.column_config.TextColumn('σ 燈號', width='medium',
                          help='🟢🟢🟢 大買 50% / 🟢🟢 買 30% / 🟢 小買 20% / 🔴 停利'),
        '動作建議':     st.column_config.TextColumn('動作建議', width='medium',
                          help='依 σ 位階自動推導加碼/停利比例'),
    }

    # 其他角色簡表
    _other_cols = {
        '代號':         st.column_config.TextColumn('代號', width='small'),
        '名稱':         st.column_config.TextColumn('名稱', width='medium'),
        '市價':         st.column_config.NumberColumn('市價', format='%.2f'),
        '年化配息率%':  st.column_config.NumberColumn('年化配息率%', format='%.2f%%'),
        '1年含息報酬%': st.column_config.NumberColumn('1年含息報酬%', format='%+.2f%%'),
        '走勢':         st.column_config.LineChartColumn('近30日走勢'),
        '健康燈號':     st.column_config.TextColumn('燈號', width='medium'),
    }

    # ── 核心資產戰情室（佔比 80%）────────────────────────────
    _core_rows = [w for w in _war_rows if w.get('類型') == '核心']
    _sat_rows  = [w for w in _war_rows if w.get('類型') == '衛星']
    _other_rows = [w for w in _war_rows if w.get('類型') not in ('核心', '衛星')]

    if _core_rows:
        st.markdown('##### 🏛️ 核心資產戰情室（目標 80%）— 穩領息')
        st.caption('🔴 賺息賠本（總報酬<殖利率）→ 換股 ｜ 🟡 跌破 MA60 → 趨勢轉弱 ｜ 🟢 體質健康（雙條件全綠）')
        _core_df = pd.DataFrame(_core_rows)[
            ['代號', '名稱', '市價', '折溢價%', '年化配息率%',
             '1年含息報酬%', '距季線%', '走勢', '健康燈號', '動作建議']
        ]
        st.dataframe(_core_df, column_config=_core_cols,
                     use_container_width=True, hide_index=True)
    if _sat_rows:
        st.markdown('##### 🚀 衛星資產戰情室（目標 20%）— 跌了就買 σ 分級')
        st.caption('🟢🟢🟢 < MA20-3σ 股災價(大買 50%) ｜ 🟢🟢 < -2σ 超跌(30%) ｜ 🟢 < -1σ 便宜(20%) ｜ 🔴 ≥ +2σ 停利')
        _sat_df = pd.DataFrame(_sat_rows)[
            ['代號', '名稱', '市價', '距月線%', 'σ位階',
             '1年含息報酬%', '走勢', '健康燈號', '動作建議']
        ]
        st.dataframe(_sat_df, column_config=_sat_cols,
                     use_container_width=True, hide_index=True)
    if _other_rows:
        st.markdown('##### 📦 其他持倉（未分類）')
        _oth_df = pd.DataFrame(_other_rows)[
            ['代號', '名稱', '市價', '年化配息率%', '1年含息報酬%', '走勢', '健康燈號']
        ]
        st.dataframe(_oth_df, column_config=_other_cols,
                     use_container_width=True, hide_index=True)

    # ── MK 框架 #9：核心 / 衛星比例 vs regime 目標 ────────────
    _core_value = sum(r['current_value'] for r in rows if r.get('role') == '核心')
    _sat_value  = sum(r['current_value'] for r in rows if r.get('role') == '衛星')
    _core_pct = _core_value / total_value * 100 if total_value > 0 else 0.0
    _sat_pct  = _sat_value / total_value * 100 if total_value > 0 else 0.0
    try:
        from portfolio_manager import CoreSatelliteManager as _CSM
        _mgr = _CSM(total_value, regime=regime)
        _target_core_pct = _mgr.core_ratio * 100
        _target_sat_pct  = _mgr.satellite_ratio * 100
        _rebal_info = _mgr.check_rebalance(satellite_current_value=_sat_value)
        st.markdown('#### 🎯 核心 / 衛星 配置 vs MK regime 目標')
        _cs1, _cs2 = st.columns(2)
        _core_dev = _core_pct - _target_core_pct
        _sat_dev  = _sat_pct  - _target_sat_pct
        _cs1.metric(f'核心比 (目標 {_target_core_pct:.0f}%)', f'{_core_pct:.1f}%',
                    delta=f'{_core_dev:+.1f}pp',
                    delta_color='normal' if abs(_core_dev) <= 10 else 'inverse')
        _cs2.metric(f'衛星比 (目標 {_target_sat_pct:.0f}%)', f'{_sat_pct:.1f}%',
                    delta=f'{_sat_dev:+.1f}pp',
                    delta_color='normal' if abs(_sat_dev) <= 10 else 'inverse')
        if isinstance(_rebal_info, dict) and _rebal_info.get('rebalance_needed'):
            _excess = _rebal_info.get('excess_pct', 0) * 100 if _rebal_info.get('excess_pct', 0) < 1 else _rebal_info.get('excess_pct', 0)
            _colored_box(
                f'⚠️ <b>衛星超標</b> {_excess:.1f}pp（regime={regime} 目標衛星 {_target_sat_pct:.0f}%）<br>'
                f'<b>建議</b>：{_rebal_info.get("action", "考慮停利衛星部位轉入核心")}',
                'red')
            _teacher_conclusion('郭俊宏',
                                f'衛星 {_sat_pct:.1f}% > 目標 {_target_sat_pct:.0f}%',
                                '衛星部位超標，違背核衛宿命',
                                '停利衛星轉入核心（葡萄串閉環）')
        else:
            _colored_box(
                f'✅ 核衛比例符合 regime={regime} 目標範圍（±10pp 容忍）',
                'green')
            _teacher_conclusion('郭俊宏',
                                f'核 {_core_pct:.0f}% / 衛 {_sat_pct:.0f}%',
                                f'符合 regime={regime} 目標 {_target_core_pct:.0f}/{_target_sat_pct:.0f}',
                                '維持當前配置')
        st.caption('💡 **regime 目標**：多頭 60/40 / 中性 70/30 / 保守 80/20 / 空頭 85/15（核/衛）')
    except Exception as _csm_e:
        st.info(f'ℹ️ 核衛分離計算暫時不可用：{type(_csm_e).__name__}')

    # ── 再平衡交易指令（含具體股數）────────────────────────────
    st.markdown('#### ⚖️ 再平衡交易指令')
    # 抓取現價以計算股數
    _cur_prices = {}
    with st.spinner('取得現價...'):
        for r in rows:
            try:
                _df_tmp = fetch_etf_price(r['ticker'], period='5d')
                _cur_prices[r['ticker']] = float(_df_tmp['Close'].iloc[-1]) if not _df_tmp.empty else 0
            except Exception:
                _cur_prices[r['ticker']] = 0

    rebal_actions = []
    for r in rows:
        if abs(r['deviation']) > tolerance:
            target_val = total_value * r['target_pct'] / 100
            adj        = target_val - r['current_value']
            action     = '買進' if adj > 0 else '賣出'
            cur_price  = _cur_prices.get(r['ticker'], 0)
            shares     = int(abs(adj) / cur_price) if cur_price > 0 else 0
            rebal_actions.append({
                'ETF': r['ticker'], '動作': action,
                '金額(元)': abs(adj), '偏離度%': r['deviation'],
                '現價': cur_price, '建議股數': shares,
            })

    if rebal_actions:
        ra_df = pd.DataFrame([{
            'ETF':    a['ETF'],
            '動作':   a['動作'],
            '現價':   f'{a["現價"]:.2f}' if a['現價'] > 0 else '-',
            '建議股數': f'{a["建議股數"]:,}' if a['建議股數'] > 0 else '-',
            '金額(元)': f'{a["金額(元)"]:,.0f}',
            '偏離度%': a['偏離度%'],
        } for a in rebal_actions])
        st.dataframe(ra_df, use_container_width=True, hide_index=True)
        for act in rebal_actions:
            color = 'green' if act['動作'] == '買進' else 'red'
            icon  = '📈' if act['動作'] == '買進' else '📉'
            _share_txt = (f'約 <b>{act["建議股數"]:,} 股</b>（現價 {act["現價"]:.2f} 元）'
                          if act['建議股數'] > 0 else '（無法取得現價）')
            _colored_box(
                f'{icon} <b>{act["動作"]} {act["ETF"]}</b> {_share_txt}，'
                f'預估金額 <b>{act["金額(元)"]:,.0f} 元</b>（偏離 {act["偏離度%"]:+.1f}%）',
                color)
    else:
        _colored_box(f'✅ 所有標的偏離度均在 ±{tolerance}% 內，無需再平衡', 'green')

    # ── 產業曝險上限檢查（單一類股 ≤ 30%）─────────────────────
    st.markdown('#### 🏗️ 產業曝險上限檢查（單一 GICS 類股 ≤ 30%）')
    _check_sector_exposure(rows, total_value)

    # ── 相關係數矩陣 ──────────────────────────────────────────
    st.markdown('#### 🔗 相關係數矩陣（近1年）')
    tickers = [r['ticker'] for r in rows]
    ret_dict = {}
    with st.spinner('計算相關係數...'):
        for t in tickers:
            df_t = fetch_etf_price(t, period='1y')
            if not df_t.empty:
                ret_dict[t] = df_t['Close'].pct_change()
    if len(ret_dict) >= 2:
        ret_df = pd.DataFrame(ret_dict).ffill().dropna()
        corr   = ret_df.corr()
        _plot_correlation(corr)
        for i in range(len(corr)):
            for j in range(i + 1, len(corr)):
                val = corr.iloc[i, j]
                if val > 0.85:
                    _colored_box(
                        f'⚠️ <b>{corr.index[i]} × {corr.columns[j]}</b> '
                        f'相關係數 {val:.2f} > 0.85，資產同質性過高', 'red')
    else:
        st.warning('資料不足，無法計算相關係數')

    # ── 壓力測試（S&P500 下跌20%）────────────────────────────
    st.markdown('#### 🧨 壓力測試（模擬 S&P 500 下跌 20%）')
    stress_results = []
    total_stress   = 0.0
    for r in rows:
        info_i  = fetch_etf_info(r['ticker'])
        beta_i  = info_i.get('beta') or info_i.get('beta3Year') or 1.0
        try:
            beta_i = float(beta_i)
        except Exception:
            beta_i = 1.0
        est_loss       = r['actual_pct'] / 100 * beta_i * (-0.20) * total_value
        total_stress  += est_loss
        stress_results.append({
            'ETF': r['ticker'], 'Beta': round(beta_i, 2),
            '實際權重%': r['actual_pct'],
            '預估虧損(元)': f'{est_loss:,.0f}',
        })
    st.dataframe(pd.DataFrame(stress_results), use_container_width=True, hide_index=True)
    loss_pct = abs(total_stress) / total_value * 100
    color    = 'red' if loss_pct > 20 else 'green'
    _colored_box(
        f'組合預估總虧損：<b>{total_stress:,.0f} 元</b>（{loss_pct:.1f}%）'
        + ('&nbsp; ⚠️ 超過20%，建議增加避險部位' if loss_pct > 20 else '&nbsp; ✅ 風險可控'),
        color)
    if loss_pct > 20:
        _teacher_conclusion('孫慶龍',
                            f'S&P500↓20% 壓力測試損失 {loss_pct:.1f}%',
                            '尾部風險超標，組合過於進攻型',
                            '增加債券 ETF 或現金部位，降低整體 Beta')
    else:
        _teacher_conclusion('孫慶龍',
                            f'S&P500↓20% 壓力測試損失 {loss_pct:.1f}%',
                            '壓力測試風險可控，組合防禦性足夠',
                            '維持現有配置，定期再平衡')

    # ── VaR 風險值（歷史模擬法 + 參數法）────────────────────────
    st.markdown('#### 📉 VaR 風險值（Value at Risk）')
    st.caption('衡量正常市況下單日最大可能虧損：歷史模擬法取近1年最差分位數，參數法假設常態分布')
    _var_rets = {}
    with st.spinner('計算 VaR...'):
        for r in rows:
            _df_v = fetch_etf_price(r['ticker'], period='1y')
            if not _df_v.empty:
                _var_rets[r['ticker']] = _df_v['Close'].pct_change().dropna()
    if len(_var_rets) >= 1:
        # 組合日報酬（加權合并）
        _all_idx = sorted(set().union(*[s.index for s in _var_rets.values()]))
        _port_ret = pd.Series(0.0, index=_all_idx)
        for r in rows:
            if r['ticker'] in _var_rets:
                _w = r['actual_pct'] / 100
                _port_ret = _port_ret.add(
                    _var_rets[r['ticker']].reindex(_all_idx).ffill().fillna(0) * _w)
        _port_ret = _port_ret.dropna()
        if len(_port_ret) >= 20:
            # 歷史模擬法
            _h95 = float(_port_ret.quantile(0.05)) * total_value
            _h99 = float(_port_ret.quantile(0.01)) * total_value
            # 參數法
            _mu  = float(_port_ret.mean())
            _sig = float(_port_ret.std())
            _p95 = (_mu - 1.645 * _sig) * total_value
            _p99 = (_mu - 2.326 * _sig) * total_value
            # 月度 VaR（√21 近似）
            _m99 = _h99 * (21 ** 0.5)

            _vc1, _vc2 = st.columns(2)
            with _vc1:
                st.markdown('**📊 歷史模擬法**')
                st.metric('95% 日 VaR', f'{abs(_h95):,.0f} 元',
                          f'{abs(_h95)/total_value*100:.2f}% 組合市值')
                st.metric('99% 日 VaR', f'{abs(_h99):,.0f} 元',
                          f'{abs(_h99)/total_value*100:.2f}% 組合市值')
                st.caption('95% VaR：正常市況下100天中，95天的虧損不超過此值')
            with _vc2:
                st.markdown('**📐 參數法（常態分布）**')
                st.metric('95% 日 VaR', f'{abs(_p95):,.0f} 元',
                          f'{abs(_p95)/total_value*100:.2f}% 組合市值')
                st.metric('99% 日 VaR', f'{abs(_p99):,.0f} 元',
                          f'{abs(_p99)/total_value*100:.2f}% 組合市值')
                st.caption('金融市場有肥尾效應，歷史模擬法通常比參數法更保守')
            _var_warn = abs(_m99) / total_value > 0.10
            _colored_box(
                f'📅 月度 99% VaR（√21 近似）：<b>{abs(_m99):,.0f} 元</b>'
                f'（{abs(_m99)/total_value*100:.2f}%）'
                + ('&nbsp; ⚠️ 超過10%，尾部風險偏高，建議增加防禦部位'
                   if _var_warn else '&nbsp; ✅ 月度尾部風險在可接受範圍內'),
                'red' if _var_warn else 'green')
            if _var_warn:
                _teacher_conclusion('弘爺',
                                    f'月度 99% VaR {abs(_m99)/total_value*100:.2f}%',
                                    '月度尾部風險 > 10%，組合波動過大',
                                    '增加低相關資產（如 BND/AGGG），降低整體波動')
            else:
                _teacher_conclusion('弘爺',
                                    f'月度 99% VaR {abs(_m99)/total_value*100:.2f}%',
                                    '月度尾部風險在可接受範圍，組合穩健',
                                    '維持現有風險配置，按計畫再平衡')
        else:
            st.warning('歷史資料不足（<20筆），無法計算 VaR')
    else:
        st.warning('無法取得價格資料，跳過 VaR 計算')

    # ── 配息日曆 × 年度現金流預估 ──────────────────────────────
    st.markdown('#### 💰 配息日曆 × 年度現金流預估')
    st.caption('依過去12個月配息紀錄 × 持有股數（市值/現價）推估未來現金流入')
    _div_data = []
    _monthly_cf = {m: 0.0 for m in range(1, 13)}
    with st.spinner('抓取配息資料...'):
        for r in rows:
            _div_s  = fetch_etf_dividends(r['ticker'])
            _price  = _cur_prices.get(r['ticker'], 0)
            _shares = int(r['current_value'] / _price) if _price > 0 else 0
            if _div_s.empty or _shares == 0:
                continue
            _cutoff  = pd.Timestamp.now() - pd.DateOffset(years=1)
            _recent  = _div_s[_div_s.index >= _cutoff]
            if _recent.empty:
                continue
            _sum = _recent.sum()
            _annual_per_share = float(np.ravel(_sum)[0]) if hasattr(_sum, '__len__') else float(_sum)
            _n_pay = len(_recent)
            _est_income = _annual_per_share * _shares
            _div_data.append({
                'ETF': r['ticker'],
                '持有股數': _shares,
                '近1年每股配息': round(_annual_per_share, 4),
                '預估年收入(元)': round(_est_income),
                '配息次數/年': _n_pay,
            })
            # 月度分配（依歷史配息月份）
            _pay_months = sorted(set(_recent.index.month.tolist()))
            for _m in _pay_months:
                _ms = _recent[_recent.index.month == _m].sum()
                _month_div = (float(np.ravel(_ms)[0]) if hasattr(_ms, '__len__') else float(_ms)) * _shares
                _monthly_cf[_m] = _monthly_cf.get(_m, 0) + _month_div

    if _div_data:
        _div_df = pd.DataFrame(_div_data)
        _div_df['預估年收入(元)'] = _div_df['預估年收入(元)'].apply(lambda x: f'{x:,}')
        st.dataframe(_div_df, use_container_width=True, hide_index=True)
        _total_annual = sum(d['預估年收入(元)'].replace(',', '')
                            if isinstance(d['預估年收入(元)'], str)
                            else d['預估年收入(元)']
                            for d in _div_data
                            if isinstance(d.get('預估年收入(元)'), (int, float)))
        # recalc from raw
        _total_annual_raw = sum(
            d['近1年每股配息'] * d['持有股數'] for d in _div_data)
        _yoc = _total_annual_raw / total_value * 100 if total_value > 0 else 0
        _colored_box(
            f'💰 組合預估年度現金流入：<b>{_total_annual_raw:,.0f} 元</b>'
            f'（組合殖利率 {_yoc:.2f}%）'
            + ('&nbsp; ✅ 每年現金流穩定，適合存股策略'
               if _yoc >= 3 else '&nbsp; 🟡 殖利率偏低，可考慮增加高息ETF比例'),
            'green' if _yoc >= 3 else 'yellow')
        if _yoc >= 5:
            _teacher_conclusion('郭俊宏',
                                f'組合殖利率 {_yoc:.2f}%，年現金流 {_total_annual_raw:,.0f} 元',
                                '殖利率優異，現金流充沛，以息養股目標達成',
                                '持續持有，配息再投入複利滾動')
        elif _yoc >= 3:
            _teacher_conclusion('郭俊宏',
                                f'組合殖利率 {_yoc:.2f}%，年現金流 {_total_annual_raw:,.0f} 元',
                                '殖利率合格，現金流穩定',
                                '可維持，視需要提高高息 ETF 比例')
        else:
            _teacher_conclusion('郭俊宏',
                                f'組合殖利率 {_yoc:.2f}%，年現金流 {_total_annual_raw:,.0f} 元',
                                '殖利率偏低，現金流不足以息養股',
                                '增加 00878/00713 等高息 ETF 比例')

        # 月度現金流長條圖
        import plotly.graph_objects as _go_div
        _fig_div = _go_div.Figure(_go_div.Bar(
            x=[f'{m}月' for m in range(1, 13)],
            y=[_monthly_cf[m] for m in range(1, 13)],
            marker_color='#3fb950',
            text=[f'{_monthly_cf[m]:,.0f}' if _monthly_cf[m] > 0 else ''
                  for m in range(1, 13)],
            textposition='auto',
        ))
        _fig_div.update_layout(
            title='未來12個月預估配息現金流（元，依歷史月份分配）',
            template='plotly_dark', height=260,
            paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
            margin=dict(l=0, r=0, t=32, b=0),
            yaxis_title='配息金額（元）',
        )
        st.plotly_chart(_fig_div, width='stretch')
    else:
        st.info('⏳ 配息資料無法取得（可能為非配息型ETF或yfinance資料限制）')

    # 存入 session_state
    st.session_state['etf_portfolio_data'] = {
        'rows': rows, 'rebal_actions': rebal_actions,
        'total_value': total_value, 'regime': regime,
        'loss_pct': loss_pct,
    }

    if gemini_fn:
        _etf_ai_portfolio(gemini_fn, rows, rebal_actions, regime, loss_pct)

    # ── 統一投資決策分析模組 ──────────────────────────────────
    render_unified_decision(gemini_fn, {
        'type': 'portfolio',
        'id':   'etf_portfolio',
        'data': {
            '組合明細': [
                {'ETF': r['ticker'],
                 '目標%': r['target_pct'],
                 '實際%': r['actual_pct'],
                 '偏離%': round(r['deviation'], 1)}
                for r in rows
            ],
            '壓力測試損失(S&P500跌20%)': f'{loss_pct:.1f}%',
            '再平衡筆數':                len(rebal_actions),
            '大盤狀態':                  regime,
        },
    })

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

# ═══════════════════════════════════════════════════════════════
# Tab ⑧：ETF 歷史回測與績效視覺化
# ═══════════════════════════════════════════════════════════════

def render_etf_backtest(gemini_fn=None):
    mkt_info = st.session_state.get('mkt_info', {})
    regime   = mkt_info.get('regime', 'neutral')

    st.markdown('#### 📋 回測組合設定（格式：代號,權重%）')
    default_bt = "0050.TW,50\nBND,30\n00878.TW,20"
    raw_bt = st.text_area('回測組合', value=default_bt, height=100,
                           key='etf_bt_input', label_visibility='collapsed')
    col_p, col_i, col_b = st.columns(3)
    period  = col_p.selectbox('回測期間', ['3y', '5y', '10y', '1y'],
                               index=1, key='etf_bt_period')
    initial = col_i.number_input('初始資金（元）', value=100000,
                                  step=10000, key='etf_bt_init')
    col_b.markdown('<br>', unsafe_allow_html=True)
    if col_b.button('🚀 開始回測', key='etf_bt_btn', use_container_width=True):
        st.session_state['etf_bt_active'] = True

    if not st.session_state.get('etf_bt_active'):
        st.info('💡 設定組合與期間後點擊「開始回測」')
        return

    # 解析權重
    rows = []
    for line in raw_bt.strip().splitlines():
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 2:
            try:
                rows.append({'ticker': parts[0].upper(),
                              'weight': float(parts[1]) / 100})
            except ValueError:
                pass
    if not rows:
        st.error('❌ 請輸入有效的回測組合'); return

    # 正規化權重
    w_sum = sum(r['weight'] for r in rows)
    if abs(w_sum - 1.0) > 0.05:
        st.warning(f'⚠️ 權重合計 {w_sum*100:.0f}%，已自動正規化')
        for r in rows:
            r['weight'] /= w_sum

    # 載入資料
    with st.spinner('載入回測資料中（請稍候）...'):
        price_dict = {}
        for r in rows:
            df_t = fetch_etf_price(r['ticker'], period=period)
            if not df_t.empty:
                price_dict[r['ticker']] = df_t['Close']

    if not price_dict:
        st.error('❌ 無法取得任何ETF資料'); return

    # 對齊資料
    prices = pd.DataFrame(price_dict).ffill().dropna()
    if len(prices) < 20:
        st.error('❌ 有效資料不足，請確認代號或縮短回測期間'); return

    # ── 配息稅費磨損（台灣二代健保 × 0.95）─────────────────────
    # 所有含「.TW」的 ETF 配息乘以 0.95 扣除二代健保補充費
    apply_tax = any(t.endswith('.TW') for t in [r['ticker'] for r in rows])
    TAX_FACTOR = 0.95  # 二代健保補充費磨損（約 2.11%，取保守 5%）

    # 加權組合資產價值（含稅費磨損）
    norm     = prices / prices.iloc[0]
    weights  = {r['ticker']: r['weight'] for r in rows if r['ticker'] in norm.columns}

    # 計算各ETF配息貢獻並套用稅費磨損
    div_adjustment = {}
    for r in rows:
        t = r['ticker']
        if t not in norm.columns:
            continue
        if apply_tax and t.endswith('.TW'):
            try:
                divs_t = fetch_etf_dividends(t)
                if not divs_t.empty:
                    annual_div = float(divs_t.resample('Y').sum().mean())
                    avg_price  = float(prices[t].mean())
                    div_yield  = annual_div / avg_price if avg_price > 0 else 0
                    # 稅後磨損 = 配息 × (1 - TAX_FACTOR) 每年從報酬扣除
                    div_adjustment[t] = div_yield * (1 - TAX_FACTOR)
                else:
                    div_adjustment[t] = 0.0
            except Exception:
                div_adjustment[t] = 0.0
        else:
            div_adjustment[t] = 0.0

    port_val = sum(norm[t] * w for t, w in weights.items()) * initial

    # 套用稅費磨損（每日複利扣除）
    if apply_tax:
        n_years = len(prices) / 252
        for t, w in weights.items():
            loss_factor = (1 - div_adjustment.get(t, 0)) ** n_years
            port_val = port_val - (norm[t] * w * initial * (1 - loss_factor))

    total_tax_drag = sum(div_adjustment.get(t, 0) * w for t, w in weights.items()) * 100

    # 基準
    bench_ticker = '0050.TW' if any(t.endswith('.TW') for t in weights) else '^GSPC'
    with st.spinner(f'載入基準 {bench_ticker}...'):
        bench_df = fetch_etf_price(bench_ticker, period=period)
    bench_val = None
    if not bench_df.empty:
        bc = bench_df['Close'].reindex(prices.index).ffill().dropna()
        bench_val = bc / bc.iloc[0] * initial

    # ── 資金成長曲線 ──────────────────────────────────────────
    st.markdown('#### 📈 資金成長曲線')
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=port_val.index, y=port_val.values,
                              name='📦 ETF組合',
                              line=dict(color='#58a6ff', width=2.5)))
    if bench_val is not None:
        fig.add_trace(go.Scatter(x=bench_val.index, y=bench_val.values,
                                  name=f'📊 {bench_ticker}（基準）',
                                  line=dict(color='#3fb950', width=1.5, dash='dash')))
    fig.update_layout(
        template='plotly_dark', height=380,
        yaxis_title='資產價值（元）',
        margin=dict(l=0, r=0, t=20, b=0),
        paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
        legend=dict(orientation='h', yanchor='bottom', y=1.01),
    )
    st.plotly_chart(fig, width='stretch')

    # ── 年化績效指標 ──────────────────────────────────────────
    st.markdown('#### 🏆 年化績效指標')
    port_df    = pd.DataFrame({'Close': port_val})
    cagr       = calc_cagr(port_df)
    sharpe     = calc_sharpe(port_df)
    mdd        = calc_mdd(port_df)
    vol        = round(float(port_val.pct_change().dropna().std() * (252**0.5) * 100), 2)
    final_val  = float(port_val.iloc[-1])
    cum_ret    = round((final_val - initial) / initial * 100, 2)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric('累積報酬',    f'{cum_ret:.1f}%')
    c2.metric('CAGR（年化）', f'{cagr:.2f}%')
    c3.metric('年化波動率',   f'{vol:.2f}%')
    c4.metric('夏普值',       f'{sharpe:.2f}')
    c5.metric('最大回撤',     f'{mdd:.1f}%')

    # ── 績效評級總結卡（老師標準）──────────────────────────────
    _grade_pts = 0
    if cagr >= 10:   _grade_pts += 3
    elif cagr >= 6:  _grade_pts += 2
    elif cagr >= 3:  _grade_pts += 1
    if sharpe >= 1.0:  _grade_pts += 3
    elif sharpe >= 0.5: _grade_pts += 1
    if abs(mdd) <= 10: _grade_pts += 3
    elif abs(mdd) <= 20: _grade_pts += 1
    _grade_label = ('⭐⭐⭐ 優秀' if _grade_pts >= 7 else
                    '⭐⭐ 良好' if _grade_pts >= 4 else '⭐ 普通')
    _grade_color = ('#3fb950' if _grade_pts >= 7 else
                    '#d29922' if _grade_pts >= 4 else '#f85149')
    _sharpe_note = ('夏普值≥1.0，承擔風險有充分補償' if sharpe >= 1.0 else
                    '夏普值<0.5，波動大但報酬低，需檢視配置' if sharpe < 0.5 else
                    '夏普值介於0.5-1.0，風險報酬比尚可')
    _mdd_note = ('最大回撤≤10%，心理壓力小，適合長期持有' if abs(mdd) <= 10 else
                 '最大回撤>20%，空頭時需有足夠心理準備' if abs(mdd) > 20 else
                 '最大回撤10-20%，合理範圍，按計畫執行')
    st.markdown(
        f'<div style="background:#0d1117;border:2px solid {_grade_color};border-radius:10px;'
        f'padding:12px 16px;margin:10px 0;">'
        f'<div style="font-size:16px;font-weight:900;color:{_grade_color};">📊 績效評級：{_grade_label}</div>'
        f'<div style="font-size:12px;color:#c9d1d9;margin-top:6px;">'
        f'CAGR {cagr:.2f}% | 夏普值 {sharpe:.2f} | 最大回撤 {mdd:.1f}%</div>'
        f'<div style="font-size:11px;color:#8b949e;margin-top:4px;">💡 {_sharpe_note} ／ {_mdd_note}</div>'
        f'</div>', unsafe_allow_html=True)
    # 老師動態結論
    if cagr >= 10 and sharpe >= 1.0:
        _bt_concl = f'CAGR {cagr:.1f}% + 夏普值 {sharpe:.2f}，風報比頂尖，長期持有無疑'
        _bt_act   = '全倉持有，定期再平衡'
    elif cagr >= 6 and abs(mdd) <= 20:
        _bt_concl = f'CAGR {cagr:.1f}%，最大回撤 {mdd:.1f}%，穩健成長型組合'
        _bt_act   = '維持配置，夏普值 < 1.0 可優化標的'
    elif cagr < 3:
        _bt_concl = f'CAGR {cagr:.1f}%，報酬不如定存，需重新審視配置'
        _bt_act   = '更換低費率或高 CAGR 的 ETF，如 0050 / SPY'
    else:
        _bt_concl = f'CAGR {cagr:.1f}%，最大回撤 {mdd:.1f}%，表現普通'
        _bt_act   = '評估是否增加股票型 ETF 比例以提升 CAGR'
    _teacher_conclusion('春哥', f'回測評級 {_grade_label}', _bt_concl, _bt_act)

    # ── 個別 ETF 績效 ─────────────────────────────────────────
    st.markdown('#### 📋 個別 ETF 績效')
    indiv = []
    for t, w in weights.items():
        if t in prices.columns:
            df_i = pd.DataFrame({'Close': prices[t]})
            ret_series = prices[t].pct_change().dropna()
            indiv.append({
                'ETF': t, '權重': f'{w*100:.0f}%',
                'CAGR': f'{calc_cagr(df_i):.2f}%',
                '波動率': f'{round(float(ret_series.std()*(252**0.5)*100),2):.2f}%',
                '最大回撤': f'{calc_mdd(df_i):.1f}%',
                '夏普值': f'{calc_sharpe(df_i):.2f}',
            })
    st.dataframe(pd.DataFrame(indiv), use_container_width=True, hide_index=True)

    # ── 稅費磨損提示 ──────────────────────────────────────────
    if apply_tax and total_tax_drag > 0:
        _colored_box(
            f'💸 配息稅費磨損（台灣二代健保 ×0.95）：'
            f'加權年均磨損約 <b>{total_tax_drag:.3f}%</b>，'
            f'長期持有需列入報酬估算', 'yellow')

    # ── 蒙地卡羅模擬（延遲執行，避免頁面切換時自動佔用 CPU）──────
    st.markdown('#### 🎲 蒙地卡羅模擬（10,000 路徑，1 年）')
    _mc_key = f'etf_mc_done_{hash(str(weights))}'
    if st.session_state.get(_mc_key):
        _render_monte_carlo(port_val, initial, vol)
    else:
        st.info('點擊下方按鈕執行蒙地卡羅模擬（10,000 路徑）。此運算約需 3-5 秒，手動觸發以避免頁面切換卡頓。')
        if st.button('🎲 執行蒙地卡羅模擬', key='etf_mc_btn'):
            st.session_state[_mc_key] = True
            _render_monte_carlo(port_val, initial, vol)

    # 存入 session_state
    st.session_state['etf_backtest_data'] = {
        'weights': weights, 'period': period, 'initial': initial,
        'cagr': cagr, 'sharpe': sharpe, 'mdd': mdd, 'vol': vol,
        'cum_ret': cum_ret, 'regime': regime,
    }

    if gemini_fn:
        _etf_ai_backtest(gemini_fn, cagr, sharpe, mdd, vol, weights, regime)

    # ── 統一投資決策分析模組 ──────────────────────────────────
    render_unified_decision(gemini_fn, {
        'type': 'portfolio',
        'id':   'etf_backtest',
        'data': {
            '組合權重':   {t: f'{w*100:.0f}%' for t, w in weights.items()},
            'CAGR':       f'{cagr:.2f}%',
            'Sharpe比率': round(sharpe, 2),
            '最大回撤MDD': f'{mdd:.1f}%',
            '年化波動率':  f'{vol:.2f}%',
            '大盤狀態':    regime,
        },
    })

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

