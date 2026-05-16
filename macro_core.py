"""
macro_core.py — 兩個 dashboard 共用的總經核心 v1.0

設計目標
========
1. 兩個 repo (my-stock-dashboard / my-fund-dashboard) 共用同一份檔案,
   消除指標重複實作與閾值不一致的維護成本。
2. **所有外部 HTTP 抓取統一透過 proxy_helper.fetch_url(),確保走家用 NAS
   中繼站**,避免雲端 IP 被台灣金融網站封鎖,且 yfinance 在境外節點
   常被限流的問題。

範圍邊界(v1.0 已釐清)
=====================
✅ 收錄:全球/美國總經指標(VIX / DXY / US10Y / CPI / Fed Rate / PMI /
        HY OAS / M2 / Fed BS / 殖利率利差),資料源 = FRED + Yahoo Chart
✅ 收錄:純數學工具(zscore / trend / recession_probability / spread_series)
✅ 收錄:統一 schema(make_indicator / flatten_snapshot)
❌ 不收錄:台灣獨有指標(台指選擇權 PCR、台灣 M1B/M2、外資期貨淨空、
          BIAS240、TWSE 漲跌家數、FinMind 籌碼)→ 留在 stock 端
          自有模組(leading_indicators.py / 後續 tw_macro.py)
❌ 不收錄:下游決策(台股曝險上限、基金資產配置)→ 留在各自的引擎

依賴限制
========
- 不依賴 streamlit(可在 CLI / pytest 環境直接 import)
- 不依賴 yfinance(改打 Yahoo Finance Chart API,走 proxy)
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from proxy_helper import fetch_url

__version__ = "1.0.0"

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
YF_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"


# ══════════════════════════════════════════════════════════════
# 統一閾值表 — 僅限「全球/美國」指標
#   兩邊共用一份標準,避免同一個 VIX 在兩個系統有兩套判讀。
#   台灣獨有指標(PCR / 外資期貨 / BIAS240 等)請放在 stock 端自有模組,
#   不要混進這張表,以免污染 fund 端的全球視角。
# ══════════════════════════════════════════════════════════════
MACRO_THRESHOLDS: dict = {
    "VIX":         {"green_below": 18, "yellow_above": 22, "red_above": 30},
    "CPI":         {"green_low": 1.5, "green_high": 2.5, "yellow_above": 3.5, "red_above": 4.0},
    "US10Y":       {"yellow_above": 4.5, "red_above": 5.0},
    "DXY":         {"yellow_above": 105, "red_above": 110},
    "PMI":         {"red_below": 46, "yellow_below": 50, "green_above": 52},
    "HY_SPREAD":   {"green_below": 4.0, "yellow_below": 6.0, "red_above": 6.0},
    "YIELD_10Y2Y": {"red_below": 0.0, "yellow_below": 0.5},
    "YIELD_10Y3M": {"red_below": 0.0, "yellow_below": 0.5},
    "M2_YOY":      {"red_below": 0.0, "green_above": 5.0},
    "FED_BS_YOY":  {"red_below": -5.0, "green_above": 5.0},
}


# ══════════════════════════════════════════════════════════════
# 資料抓取(全部走 NAS proxy)
# ══════════════════════════════════════════════════════════════

def fetch_fred(series_id: str, api_key: str, n: int = 250) -> pd.DataFrame:
    """
    抓取 FRED 經濟序列(透過 NAS proxy)。

    Returns
    -------
    pd.DataFrame  欄位: ['date' (Timestamp), 'value' (float)],已排序去除空值。
                  失敗時回傳空 DataFrame。
    """
    if not api_key:
        return pd.DataFrame()
    r = fetch_url(
        FRED_BASE,
        params={
            "series_id":  series_id,
            "api_key":    api_key,
            "file_type":  "json",
            "sort_order": "desc",
            "limit":      n,
        },
        timeout=20,
    )
    if r is None:
        return pd.DataFrame()
    try:
        obs = r.json().get("observations", [])
    except Exception as e:
        print(f"[macro_core/fred] {series_id} JSON 解析失敗: {e}")
        return pd.DataFrame()
    if not obs:
        return pd.DataFrame()
    df = pd.DataFrame(obs)
    df = df[df["value"] != "."].copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["date"]  = pd.to_datetime(df["date"])
    return df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)


def fetch_yf_close(ticker: str, range_: str = "2y", interval: str = "1d") -> pd.Series:
    """
    抓取 Yahoo Finance 收盤價序列(透過 NAS proxy 直打 Chart API)。

    為何不用 yfinance:yfinance 預設不走 proxy,且常因雲端節點 IP
    被 Yahoo 限流(429)而失敗。直接呼叫 Chart REST API + NAS 中繼,
    取得台灣 IP 出口,穩定許多。

    Returns
    -------
    pd.Series  index 為 DatetimeIndex,value 為收盤價。失敗時回傳空 Series。
    """
    url = f"{YF_CHART_BASE}/{ticker}"
    r = fetch_url(
        url,
        params={"interval": interval, "range": range_},
        timeout=15,
    )
    if r is None:
        return pd.Series(dtype=float, name=ticker)
    try:
        d = r.json()
        result = d["chart"]["result"][0]
        ts = result["timestamp"]
        close = result["indicators"]["quote"][0]["close"]
        s = pd.Series(close, index=pd.to_datetime(ts, unit="s"), dtype=float).dropna()
        s.name = ticker
        return s
    except Exception as e:
        print(f"[macro_core/yf] {ticker} 解析失敗: {e}")
        return pd.Series(dtype=float, name=ticker)


def fetch_yf_latest(tickers: tuple[str, ...]) -> dict[str, Optional[float]]:
    """批次抓多個 ticker 最新收盤(空值代表抓不到)。"""
    out: dict[str, Optional[float]] = {}
    for t in tickers:
        s = fetch_yf_close(t, range_="5d")
        out[t] = round(float(s.iloc[-1]), 4) if not s.empty else None
    return out


def fetch_yf_ohlcv(ticker: str, range_: str = "9mo", interval: str = "1d") -> pd.DataFrame:
    """
    抓取 Yahoo Finance OHLCV 序列(走 NAS proxy)。提供 Close + Volume 給
    需要量能判斷的場景(例如 market_strategy.get_market_assessment 需要
    rolling 20 日均量與當日成交量)。

    Returns
    -------
    pd.DataFrame
        index = DatetimeIndex
        columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        失敗時回傳空 DataFrame。
    """
    url = f"{YF_CHART_BASE}/{ticker}"
    r = fetch_url(url, params={"interval": interval, "range": range_}, timeout=15)
    if r is None:
        return pd.DataFrame()
    try:
        result = r.json()["chart"]["result"][0]
        ts = pd.to_datetime(result["timestamp"], unit="s")
        q  = result["indicators"]["quote"][0]
        df = pd.DataFrame({
            "Open":   q.get("open"),
            "High":   q.get("high"),
            "Low":    q.get("low"),
            "Close":  q.get("close"),
            "Volume": q.get("volume"),
        }, index=ts)
        return df.dropna(subset=["Close"])
    except Exception as e:
        print(f"[macro_core/yf_ohlcv] {ticker} 解析失敗: {e}")
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════
# 總經指南針 (Top-Down Macro Compass) — Phase 1 規格三大指標
#   VIX / TNX / GSPC + 60MA，固定於頁面頂部供新人秒懂市場大環境。
#   呼叫端：app.py 的 render_macro_compass()（在 st.tabs() 之前渲染）。
# ══════════════════════════════════════════════════════════════

def fetch_macro_compass(range_: str = "6mo") -> dict:
    """Phase 1 — 一次抓 ^VIX / ^TNX / ^GSPC 三大美股指標 + GSPC 60MA。

    所有抓取都走 macro_core.fetch_yf_close()（NAS proxy → Yahoo Chart REST API），
    避開 yfinance 直連被 Streamlit Cloud IP 限流。失敗欄位填 None，UI 端優雅降級。

    Returns dict:
      vix  : {'value', 'series', 'dates', 'signal':(light, label, color)} | None
      tnx  : 同上                                                          | None
      gspc : 同上 + {'ma60', 'ma60_series'}                                | None
    """
    out: dict = {'vix': None, 'tnx': None, 'gspc': None}

    def _sig_vix(v):
        # Phase 1 規格：>25 黃 / >30 綠（恐慌貪婪區=逢低加碼時機）
        if v > 30: return ('🟢', '恐慌貪婪區（準備跌深就買）', '#3fb950')
        if v > 25: return ('🟡', '波動加劇', '#d29922')
        return ('🟢', '市場平靜', '#3fb950')

    def _sig_tnx(t):
        # 估值壓力：≥4.5% 紅 / 3.5–4.5 黃 / <3.5 綠（寬鬆）
        if t >= 4.5: return ('🔴', '估值壓力（科技股不利）', '#f85149')
        if t >= 3.5: return ('🟡', '中性區', '#d29922')
        return ('🟢', '寬鬆有利', '#3fb950')

    def _sig_gspc(g, ma):
        # Phase 1 規格：站上 60MA=多頭、跌破=趨勢轉弱
        if ma is None or g is None:
            return ('⚪', '60MA 計算中', '#8b949e')
        if g >= ma: return ('🟢', '多頭格局（股優於債）', '#3fb950')
        return ('🔴', '趨勢轉弱（提高防禦）', '#f85149')

    # ── ^VIX ────────────────────────────────────────────────
    try:
        s = fetch_yf_close('^VIX', range_=range_)
        if not s.empty:
            v = round(float(s.iloc[-1]), 2)
            tail = s.tail(90)
            out['vix'] = {
                'value': v,
                'series': [round(float(x), 2) for x in tail.tolist()],
                'dates':  [d.strftime('%Y-%m-%d') for d in tail.index],
                'signal': _sig_vix(v),
            }
    except Exception as e:
        print(f'[macro_compass] VIX fetch failed: {e}')

    # ── ^TNX ────────────────────────────────────────────────
    try:
        s = fetch_yf_close('^TNX', range_=range_)
        if not s.empty:
            t = round(float(s.iloc[-1]), 3)
            tail = s.tail(90)
            out['tnx'] = {
                'value': t,
                'series': [round(float(x), 3) for x in tail.tolist()],
                'dates':  [d.strftime('%Y-%m-%d') for d in tail.index],
                'signal': _sig_tnx(t),
            }
    except Exception as e:
        print(f'[macro_compass] TNX fetch failed: {e}')

    # ── ^GSPC + 60MA ────────────────────────────────────────
    try:
        s = fetch_yf_close('^GSPC', range_=range_)
        if not s.empty:
            g = round(float(s.iloc[-1]), 2)
            ma60_ser = s.rolling(60).mean()
            ma60_last = ma60_ser.dropna()
            ma60 = round(float(ma60_last.iloc[-1]), 2) if not ma60_last.empty else None
            tail = s.tail(90)
            ma_tail = ma60_ser.tail(90)
            out['gspc'] = {
                'value': g,
                'ma60': ma60,
                'series': [round(float(x), 2) for x in tail.tolist()],
                'ma60_series': [None if pd.isna(x) else round(float(x), 2) for x in ma_tail.tolist()],
                'dates': [d.strftime('%Y-%m-%d') for d in tail.index],
                'signal': _sig_gspc(g, ma60),
            }
    except Exception as e:
        print(f'[macro_compass] GSPC fetch failed: {e}')

    return out


# ══════════════════════════════════════════════════════════════
# ISM 製造業 PMI — 5 段備援共用函式（v1.1 兩端統一）
#
# 為什麼 5 段？
#   FRED NAPM / ISPMANPMI 自 2016-08 ISM 收回授權後停更，但保留以防重啟；
#   MacroMicro / ISM World 為主存活源但 HTML 結構易變動；
#   DBnomics 為 ISM JSON 鏡像（無需 key）；
#   OECD US Business Confidence 在 FRED 上仍持續更新，作為「概念替代指標」，
#   值約 98–102（非 PMI 的 30–70 區間），與 ISM PMI 相關性 ~0.7。
# ══════════════════════════════════════════════════════════════

def fetch_ism_pmi(fred_api_key: str = "", *, max_age_days: int = 90) -> dict:
    """抓取 ISM 製造業 PMI（5 段備援，月頻）。

    Returns
    -------
    dict
      命中：{'value': float, 'date': 'YYYY-MM-DD', 'label': str,
             'source': str, 'is_proxy': bool, 'series_id': str,
             'dates': [...], 'values': [...], 'proxy_note'?: str}
      失敗：{'_err_pmi': str, 'value': None}
    """
    import datetime as _dt
    import re as _re
    today = _dt.date.today()
    errs: list[str] = []

    # ── 方案 1+2: FRED NAPM / ISPMANPMI（max_age_days 時效檢查）──
    if fred_api_key:
        for sid, lbl in [('NAPM', 'FRED NAPM'), ('ISPMANPMI', 'FRED ISPMANPMI')]:
            try:
                df = fetch_fred(sid, fred_api_key, n=36)
                if df.empty or len(df) < 5:
                    continue
                df = df.tail(24)
                last_date = pd.to_datetime(df['date'].iloc[-1]).date()
                age = (today - last_date).days
                if age > max_age_days:
                    print(f'[macro_core/PMI/FRED] ⚠️ {sid} 最新={last_date} '
                          f'已停更 {age} 天 > {max_age_days}，跳過')
                    continue
                v = round(float(df['value'].iloc[-1]), 1)
                print(f'[macro_core/PMI/FRED] ✅ {sid}={v} date={last_date}')
                return {
                    'value': v, 'date': str(last_date), 'label': lbl,
                    'source': 'FRED', 'is_proxy': False, 'series_id': sid,
                    'dates':  [str(pd.to_datetime(d).date()) for d in df['date']],
                    'values': [round(float(x), 1) for x in df['value']],
                }
            except Exception as e:
                errs.append(f'FRED.{sid}:{type(e).__name__}')
                print(f'[macro_core/PMI/FRED/{sid}] ❌ {e}')

    # ── 方案 3: MacroMicro 財經 M 平方（中文 HTML）──
    try:
        from bs4 import BeautifulSoup
        for url in ('https://www.macromicro.me/charts/950/us-ism-mfg-pmi',
                    'https://www.macromicro.me/charts/2/economic-monitor-pmi'):
            r = fetch_url(url, timeout=12, attempts=1)
            if r is None:
                continue
            r.encoding = 'utf-8'
            txt = BeautifulSoup(r.text, 'html.parser').get_text(' ', strip=True)
            m = _re.search(
                r'(?:ISM[^。]{0,40}?PMI|製造業\s*PMI)[^。]{0,200}?'
                r'(\d{2}\.\d)[^。]{0,80}?(20\d{2})[\s/年-]+(\d{1,2})',
                txt)
            if m:
                v = float(m.group(1)); yr = m.group(2); mo = int(m.group(3))
                if 30 <= v <= 70 and 1 <= mo <= 12:
                    date = f'{yr}-{mo:02d}-01'
                    print(f'[macro_core/PMI/MacroMicro] ✅ {v} date={date}')
                    return {'value': v, 'date': date,
                            'label': 'MacroMicro ISM PMI',
                            'source': 'MacroMicro', 'is_proxy': False,
                            'series_id': '950'}
    except Exception as e:
        errs.append(f'MacroMicro:{type(e).__name__}')
        print(f'[macro_core/PMI/MacroMicro] ❌ {e}')

    # ── 方案 4: ISM World 官方月報（英文 HTML，最一手）──
    try:
        from bs4 import BeautifulSoup
        url = ('https://www.ismworld.org/supply-management-news-and-reports/'
               'reports/ism-report-on-business/pmi/')
        r = fetch_url(url, timeout=12, attempts=1)
        if r is not None:
            r.encoding = 'utf-8'
            txt = BeautifulSoup(r.text, 'html.parser').get_text(' ', strip=True)
            m = _re.search(
                r'(?:Manufacturing\s+PMI[^.]{0,40}?(?:at|registered)|'
                r'PMI[^.]{0,15}?registered)[^\d]{0,15}(\d{2}\.\d)\s*(?:%|percent)',
                txt, _re.IGNORECASE)
            if m:
                v = float(m.group(1))
                if 30 <= v <= 70:
                    m_dt = _re.search(
                        r'(January|February|March|April|May|June|July|August|'
                        r'September|October|November|December)\s+(20\d{2})', txt)
                    date = ''
                    if m_dt:
                        MO = {'January':1,'February':2,'March':3,'April':4,
                              'May':5,'June':6,'July':7,'August':8,
                              'September':9,'October':10,'November':11,'December':12}
                        date = f'{m_dt.group(2)}-{MO[m_dt.group(1)]:02d}-01'
                    print(f'[macro_core/PMI/ISM] ✅ {v} date={date or "?"}')
                    return {'value': v, 'date': date,
                            'label': 'ISM World Official',
                            'source': 'ISM', 'is_proxy': False,
                            'series_id': 'ismworld.org'}
    except Exception as e:
        errs.append(f'ISM:{type(e).__name__}')
        print(f'[macro_core/PMI/ISM] ❌ {e}')

    # ── 方案 5: DBnomics（純 JSON,ISM 鏡像,無需 key）──
    try:
        url = 'https://api.db.nomics.world/v22/series/ISM/pmi/pm'
        r = fetch_url(url, params={'observations': '1', 'limit': '24'}, timeout=15, attempts=1)
        if r is not None:
            d = r.json()
            docs = d.get('series', {}).get('docs', []) or []
            if docs:
                periods = docs[0].get('period', []) or []
                values  = docs[0].get('value',  []) or []
                last_idx = -1
                for i in range(len(values) - 1, -1, -1):
                    vi = values[i]
                    if vi is None: continue
                    try:
                        if isinstance(vi, float) and (vi != vi):  # NaN
                            continue
                    except Exception:
                        pass
                    last_idx = i; break
                if last_idx >= 0:
                    v = round(float(values[last_idx]), 1)
                    period_str = str(periods[last_idx])
                    last_date = _dt.datetime.strptime(period_str[:7], '%Y-%m').date()
                    age = (today - last_date).days
                    if age <= max_age_days and 30 <= v <= 70:
                        date = f'{period_str[:7]}-01'
                        print(f'[macro_core/PMI/DBnomics] ✅ {v} date={date}')
                        return {'value': v, 'date': date,
                                'label': 'DBnomics ISM/pmi/pm',
                                'source': 'DBnomics', 'is_proxy': False,
                                'series_id': 'ISM/pmi/pm'}
                    else:
                        print(f'[macro_core/PMI/DBnomics] ⚠️ '
                              f'最新={period_str} v={v} age={age}d 不通過防呆')
    except Exception as e:
        errs.append(f'DBnomics:{type(e).__name__}')
        print(f'[macro_core/PMI/DBnomics] ❌ {e}')

    # ── 方案 6: Phil Fed 製造業擴散指數（FRED GACDFSA066MSFRBPHI）──
    #   FRED 上仍持續更新；範圍 -50~+50；數學轉換為 PMI 等價刻度：
    #   PMI_eq = 50 + diffusion / 3 → 區間 33~67，與 ISM PMI 歷史相關性 ~0.85。
    #   標 is_proxy=True，UI 顯示「Phil Fed 替代計」。
    if fred_api_key:
        try:
            df = fetch_fred('GACDFSA066MSFRBPHI', fred_api_key, n=36)
            if not df.empty and len(df) >= 5:
                df = df.tail(24).copy()
                last_date = pd.to_datetime(df['date'].iloc[-1]).date()
                age = (today - last_date).days
                if age <= max_age_days:
                    # 轉換為 PMI 等價刻度
                    df['value'] = 50.0 + df['value'] / 3.0
                    v = round(float(df['value'].iloc[-1]), 1)
                    print(f'[macro_core/PMI/PhilFed] ⚠️ 採用替代計 '
                          f'PMI_eq={v} (Phil Fed Diffusion 轉換) date={last_date}')
                    return {
                        'value': v, 'date': str(last_date),
                        'label': 'Phil Fed 製造業擴散（轉 PMI 刻度）',
                        'source': 'PhilFed-Proxy', 'is_proxy': True,
                        'series_id': 'GACDFSA066MSFRBPHI',
                        'dates':  [str(pd.to_datetime(d).date()) for d in df['date']],
                        'values': [round(float(x), 1) for x in df['value']],
                        'proxy_note': '⚠️ 替代指標：Phil Fed 製造業擴散指數，'
                                      '已用 PMI_eq = 50 + diffusion/3 轉換為 PMI 刻度。'
                                      '與 ISM PMI 歷史相關性 ~0.85。',
                    }
        except Exception as e:
            errs.append(f'PhilFed-Proxy:{type(e).__name__}')
            print(f'[macro_core/PMI/PhilFed] ❌ {e}')

    # ── 方案 7: OECD US Business Confidence（FRED BSCICP02USM460S, Proxy）──
    #   最後手段；非 ISM PMI；月頻；值 ~98–102（非 30–70）；與 ISM PMI 相關性 ~0.7。
    #   UI 必須以 is_proxy=True 標註，且分數刻度與 PMI 不同。
    if fred_api_key:
        try:
            df = fetch_fred('BSCICP02USM460S', fred_api_key, n=36)
            if not df.empty and len(df) >= 5:
                df = df.tail(24)
                last_date = pd.to_datetime(df['date'].iloc[-1]).date()
                age = (today - last_date).days
                if age <= max_age_days:
                    v = round(float(df['value'].iloc[-1]), 2)
                    print(f'[macro_core/PMI/OECD-Proxy] ⚠️ 採用替代指標 '
                          f'BSCICP02USM460S={v} date={last_date}')
                    return {
                        'value': v, 'date': str(last_date),
                        'label': 'OECD US Business Confidence (Proxy)',
                        'source': 'OECD-Proxy', 'is_proxy': True,
                        'series_id': 'BSCICP02USM460S',
                        'dates':  [str(pd.to_datetime(d).date()) for d in df['date']],
                        'values': [round(float(x), 2) for x in df['value']],
                        'proxy_note': '⚠️ 替代指標：OECD 美國商業信心指數。'
                                      '值域 ~98–102（100 為長期平均,非 50 榮枯線）。'
                                      '與 ISM PMI 相關性 ~0.7,請參考趨勢方向而非絕對位階。',
                    }
                else:
                    errs.append(f'OECD-Proxy:過時 {age} 天')
        except Exception as e:
            errs.append(f'OECD-Proxy:{type(e).__name__}')
            print(f'[macro_core/PMI/OECD-Proxy] ❌ {e}')

    err_msg = ' | '.join(errs) or 'all 7 stages failed'
    print(f'[macro_core/PMI] ❌ 7 段備援全失敗：{err_msg}')
    return {'_err_pmi': err_msg, 'value': None}


# ══════════════════════════════════════════════════════════════
# 台灣製造業 PMI — CIER 中華經濟研究院（Stock 端使用）
#
# 為什麼台灣 PMI 不放 fund 端？
#   Fund 端是全球視角（看美國 ISM 即可）；
#   Stock 端是台股視角，台灣景氣與本地 PMI 直接相關（CIER 是官方發布單位，
#   每月第一個工作日上午 10:00 公布前一個月數據）。
#
# 備援順序（4 段）：
#   1. MacroMicro 財經 M 平方（中文 HTML，圖表頁含最新值，較穩定）
#   2. CIER 官網最新公告（HTML 列表頁解析）
#   3. StockFeel 股感（搜尋頁）
#   4. 鉅亨網（HTML，PMI 公告新聞）
# ══════════════════════════════════════════════════════════════

def fetch_tw_pmi(*, max_age_days: int = 90) -> dict:
    """抓取台灣製造業 PMI（國發會 NDC 為主，CIER/MacroMicro 等為 fallback；月頻）。

    Returns
    -------
    dict
      命中：{'value': float, 'date': 'YYYY-MM-DD', 'label': str,
             'source': str, 'is_proxy': False, 'series_id': str}
      失敗：{'_err_pmi': str, 'value': None}
    """
    import datetime as _dt
    import re as _re
    today = _dt.date.today()
    errs: list[str] = []

    # ── 方案 0 (新 Primary v10.62.1): data.gov.tw dataset/6100 官方開放資料 ──
    # 政府資料開放平臺「臺灣採購經理人指數」(提供機關：國發會 NDC)。
    # 流程：① 試 metadata API 取 resources URL → ② 下載 CSV/JSON 解析末筆
    # 失敗就 fallback 到既有方案 0~6。
    try:
        import io as _io_dgw
        import csv as _csv_dgw
        # metadata API 端點（多個變體：v1/v2 + .json + 直查 dataset id）
        for _meta_url in (
            'https://data.gov.tw/api/v2/rest/dataset/6100',
            'https://data.gov.tw/api/v1/rest/dataset/6100',
            'https://data.gov.tw/dataset/6100/resource',
        ):
            try:
                _r_meta = fetch_url(_meta_url, timeout=10, attempts=1,
                                    headers={'Accept': 'application/json'})
                if _r_meta is None:
                    errs.append(f'dgtw.{_meta_url[-18:]}:無回應')
                    continue
                if _r_meta.status_code != 200:
                    errs.append(f'dgtw.{_meta_url[-18:]}:HTTP{_r_meta.status_code}')
                    continue
                try:
                    _j_meta = _r_meta.json()
                except Exception:
                    continue
                # 解析 resources：常見 shape `result.resources[]` / `resources[]`
                _res = (_j_meta.get('result', {}).get('resources')
                        or _j_meta.get('resources')
                        or _j_meta.get('data', {}).get('resources')
                        or [])
                if not _res:
                    continue
                # 找 CSV / JSON resource
                _csv_url = None
                for _it in _res:
                    _fmt = str(_it.get('format', '')).upper()
                    _url2 = _it.get('url') or _it.get('resourceDownloadUrl')
                    if _fmt in ('CSV', 'JSON') and _url2:
                        _csv_url = _url2
                        break
                if not _csv_url:
                    continue
                # 下載 CSV / JSON
                _r_csv = fetch_url(_csv_url, timeout=15, attempts=2)
                if _r_csv is None or _r_csv.status_code != 200:
                    continue
                _txt_csv = _r_csv.content.decode('utf-8-sig', errors='ignore')
                # CSV 路徑：解析最後一筆有效 row（含 PMI 欄位 + 年月）
                if _csv_url.lower().endswith('.csv') or 'csv' in _csv_url.lower():
                    _rdr = list(_csv_dgw.DictReader(_io_dgw.StringIO(_txt_csv)))
                    if _rdr:
                        # 找 PMI 欄位（常見 key：'PMI' / '製造業採購經理人指數' / '指數'）
                        _row_last = _rdr[-1]
                        _pmi_v = None; _pmi_d = None
                        for _k, _v_cell in _row_last.items():
                            _kl = str(_k)
                            if any(_x in _kl for _x in ('PMI', '採購經理', '製造業')):
                                try:
                                    _val = float(str(_v_cell).strip())
                                    if 30 <= _val <= 70:
                                        _pmi_v = _val
                                        break
                                except (ValueError, TypeError):
                                    pass
                        # 找日期欄位
                        for _k2, _v2 in _row_last.items():
                            _m_d = _re.search(r'(20\d{2})[-/年]?(\d{1,2})', str(_v2))
                            if _m_d:
                                _pmi_d = f'{_m_d.group(1)}-{int(_m_d.group(2)):02d}-01'
                                break
                        if _pmi_v is not None and _pmi_d:
                            print(f'[macro_core/TW-PMI/data.gov.tw] ✅ {_pmi_v} date={_pmi_d}')
                            return {'value': _pmi_v, 'date': _pmi_d,
                                    'label': '政府資料開放平臺 dataset/6100',
                                    'source': 'data.gov.tw', 'is_proxy': True,
                                    'series_id': 'dgtw-6100'}
            except Exception as _e_dg:
                errs.append(f'dgtw.{_meta_url[-15:]}:{type(_e_dg).__name__}')
    except Exception as _e_dg_outer:
        errs.append(f'dgtw_outer:{type(_e_dg_outer).__name__}')
        print(f'[macro_core/TW-PMI/data.gov.tw] ❌ outer {_e_dg_outer}')

    # ── 方案 0b (原 Primary): 國發會 NDC 景氣指標 API（鏡像現有 composite endpoint pattern）──
    # nas_server.py:218 已驗證 https://index.ndc.gov.tw/app/data/indicator/composite 走 JSON；
    # PMI 端點推測 /PMI 或 /pmi 或 /PMI/latest，多個 endpoint 變體 + 多 JSON shape parser
    # 都試一遍，attempts=1 走 lean path 不阻塞 macro pool 預算
    for ndc_url in (
        'https://index.ndc.gov.tw/app/data/indicator/PMI',
        'https://index.ndc.gov.tw/app/data/indicator/pmi',
        'https://index.ndc.gov.tw/app/data/PMI/latest',
        'https://index.ndc.gov.tw/app/data/indicator/PMI/latest',
    ):
        try:
            r = fetch_url(ndc_url, timeout=12, attempts=1,
                          headers={'Accept': 'application/json'})
            if r is None:
                errs.append(f'NDC.{ndc_url[-15:]}:無回應')
                continue
            if r.status_code != 200:
                errs.append(f'NDC.{ndc_url[-15:]}:HTTP{r.status_code}')
                continue
            try:
                j = r.json()
            except Exception:
                continue
            # 解析多種 JSON shape：list / {data:[...]} / {items:[...]} / 單筆 dict
            items = j if isinstance(j, list) else (j.get('data') or j.get('items') or [j])
            if not items:
                continue
            latest = items[-1] if isinstance(items, list) and items else items
            if not isinstance(latest, dict):
                continue
            # 數值欄位常見 key：value / score / pmi / index / composite
            v_raw = (latest.get('value') or latest.get('score')
                     or latest.get('pmi') or latest.get('index')
                     or latest.get('composite'))
            # 日期欄位：date / yearMonth / period / month
            d_raw = (latest.get('date') or latest.get('yearMonth')
                     or latest.get('period') or latest.get('month'))
            if v_raw is None or not d_raw:
                continue
            try:
                v = float(v_raw)
            except (TypeError, ValueError):
                continue
            if not (30 <= v <= 70):
                continue
            # 日期 normalize：'2026-04' / '202604' / '2026/04' → 'YYYY-MM-01'
            d_str = str(d_raw)
            m_d = _re.search(r'(20\d{2})[-/]?(\d{2})', d_str)
            if not m_d:
                continue
            date = f'{m_d.group(1)}-{m_d.group(2)}-01'
            try:
                last_d = _dt.date(int(m_d.group(1)), int(m_d.group(2)), 1)
                if (today - last_d).days > max_age_days:
                    continue
            except Exception:
                pass
            print(f'[macro_core/TW-PMI/NDC] ✅ {v} date={date} via {ndc_url[-30:]}')
            return {'value': v, 'date': date,
                    'label': '國發會 NDC 景氣指標',
                    'source': 'NDC', 'is_proxy': True,
                    'series_id': 'ndc-pmi'}
        except Exception as e:
            errs.append(f'NDC.{ndc_url[-15:]}:{type(e).__name__}')
            print(f'[macro_core/TW-PMI/NDC/{ndc_url[-15:]}] ❌ {e}')

    # ── 方案 1: MacroMicro 財經 M 平方（chart 22 = 台灣 PMI）──
    try:
        from bs4 import BeautifulSoup
        for url in ('https://www.macromicro.me/charts/22/taiwan-pmi',
                    'https://www.macromicro.me/charts/16/tw-pmi'):
            r = fetch_url(url, timeout=12, attempts=1)
            if r is None:
                errs.append(f'MacroMicro.{url[-20:]}:無回應')
                continue
            r.encoding = 'utf-8'
            txt = BeautifulSoup(r.text, 'html.parser').get_text(' ', strip=True)
            # 模式：「台灣 PMI ... 49.0」/「製造業 PMI 49.0 (2026/04)」
            m = _re.search(
                r'(?:台灣|TW|Taiwan)[^。]{0,40}?(?:PMI|採購經理[人]?指數)[^。]{0,200}?'
                r'(\d{2}\.\d)[^。]{0,80}?(20\d{2})[\s/年-]+(\d{1,2})',
                txt)
            if m:
                v = float(m.group(1)); yr = m.group(2); mo = int(m.group(3))
                if 30 <= v <= 70 and 1 <= mo <= 12:
                    date = f'{yr}-{mo:02d}-01'
                    print(f'[macro_core/TW-PMI/MacroMicro] ✅ {v} date={date}')
                    return {'value': v, 'date': date,
                            'label': 'MacroMicro 台灣 PMI',
                            'source': 'MacroMicro', 'is_proxy': False,
                            'series_id': '22'}
    except Exception as e:
        errs.append(f'MacroMicro:{type(e).__name__}')
        print(f'[macro_core/TW-PMI/MacroMicro] ❌ {e}')

    # ── 方案 2: CIER 官網最新公告列表（cid=21 為新聞稿/PMI 類別）──
    try:
        from bs4 import BeautifulSoup
        for cier_url in ('https://www.cier.edu.tw/news/list?cid=21',
                         'https://www.cier.edu.tw/'):
            r = fetch_url(cier_url, timeout=12, attempts=1)
            if r is None:
                errs.append(f'CIER.{cier_url[-15:]}:無回應')
                continue
            r.encoding = 'utf-8'
            txt = BeautifulSoup(r.text, 'html.parser').get_text(' ', strip=True)
            # 標題模式：「2026年4月製造業採購經理人指數 PMI 為 49.0」
            m = _re.search(
                r'(20\d{2})\s*年\s*(\d{1,2})\s*月.{0,30}?'
                r'製造業[^。]{0,40}?PMI[^。]{0,30}?(\d{2}\.\d)',
                txt)
            if m:
                yr, mo, v = m.group(1), int(m.group(2)), float(m.group(3))
                if 30 <= v <= 70 and 1 <= mo <= 12:
                    last_date = _dt.date(int(yr), mo, 1)
                    age = (today - last_date).days
                    if age <= max_age_days:
                        date = f'{yr}-{mo:02d}-01'
                        print(f'[macro_core/TW-PMI/CIER] ✅ {v} date={date}')
                        return {'value': v, 'date': date,
                                'label': 'CIER 中華經濟研究院',
                                'source': 'CIER', 'is_proxy': False,
                                'series_id': 'cier-pmi'}
                    else:
                        errs.append(f'CIER:過時 {age} 天')
    except Exception as e:
        errs.append(f'CIER:{type(e).__name__}')
        print(f'[macro_core/TW-PMI/CIER] ❌ {e}')

    # ── 方案 3: StockFeel 股感（搜尋頁）──
    try:
        from bs4 import BeautifulSoup
        sf_url = 'https://www.stockfeel.com.tw/?s=%E5%8F%B0%E7%81%A3+PMI'
        r = fetch_url(sf_url, timeout=12, attempts=1)
        if r is None:
            errs.append('StockFeel:無回應')
        else:
            r.encoding = 'utf-8'
            txt = BeautifulSoup(r.text, 'html.parser').get_text(' ', strip=True)
            m = _re.search(
                r'(20\d{2})\s*年\s*(\d{1,2})\s*月.{0,40}?'
                r'(?:台灣|TW)\s*(?:製造業)?[^。]{0,40}?PMI[^。]{0,30}?(\d{2}\.\d)',
                txt)
            if m:
                yr, mo, v = m.group(1), int(m.group(2)), float(m.group(3))
                if 30 <= v <= 70 and 1 <= mo <= 12:
                    last_date = _dt.date(int(yr), mo, 1)
                    if (today - last_date).days <= max_age_days:
                        date = f'{yr}-{mo:02d}-01'
                        print(f'[macro_core/TW-PMI/StockFeel] ✅ {v} date={date}')
                        return {'value': v, 'date': date,
                                'label': 'StockFeel 股感（台灣 PMI 搜尋）',
                                'source': 'StockFeel', 'is_proxy': False,
                                'series_id': 'stockfeel-tw-pmi'}
    except Exception as e:
        errs.append(f'StockFeel:{type(e).__name__}')
        print(f'[macro_core/TW-PMI/StockFeel] ❌ {e}')

    # ── 方案 4: 鉅亨網新聞（搜尋台灣 PMI）──
    try:
        from bs4 import BeautifulSoup
        cnyes_url = 'https://news.cnyes.com/api/v3/news/category/headline?limit=30&q=%E5%8F%B0%E7%81%A3+PMI'
        r = fetch_url(cnyes_url, timeout=12, attempts=1)
        if r is None:
            errs.append('Cnyes:無回應')
        else:
            try:
                d = r.json()
                items = (d.get('items', {}).get('data') or [])
                for it in items[:10]:
                    title = it.get('title', '') + ' ' + it.get('summary', '')
                    m = _re.search(
                        r'(20\d{2})\s*年\s*(\d{1,2})\s*月.{0,30}?'
                        r'(?:台灣|TW)\s*(?:製造業)?[^。]{0,40}?PMI[^。]{0,30}?(\d{2}\.\d)',
                        title)
                    if m:
                        yr, mo, v = m.group(1), int(m.group(2)), float(m.group(3))
                        if 30 <= v <= 70 and 1 <= mo <= 12:
                            last_date = _dt.date(int(yr), mo, 1)
                            if (today - last_date).days <= max_age_days:
                                date = f'{yr}-{mo:02d}-01'
                                print(f'[macro_core/TW-PMI/Cnyes] ✅ {v} date={date}')
                                return {'value': v, 'date': date,
                                        'label': '鉅亨網新聞',
                                        'source': 'Cnyes', 'is_proxy': False,
                                        'series_id': 'cnyes-tw-pmi'}
            except Exception:
                pass  # 鉅亨可能改 API，靜默失敗
    except Exception as e:
        errs.append(f'Cnyes:{type(e).__name__}')
        print(f'[macro_core/TW-PMI/Cnyes] ❌ {e}')

    # ── 方案 5: FinMind TaiwanEconomicIndicator（v10.62.0 新增）──
    # 抓 FinMind 官方總經指標 dataset，過濾「PMI」/「製造業」相關 series
    try:
        import os as _os_fm, requests as _rq_fm
        _tok = _os_fm.environ.get('FINMIND_TOKEN')
        if not _tok:
            try:
                import streamlit as _st_fm
                _tok = (_st_fm.secrets or {}).get('FINMIND_TOKEN')
            except Exception:
                pass
        if _tok:
            _start = (today - _dt.timedelta(days=180)).strftime('%Y-%m-%d')
            _r_fm = _rq_fm.get(
                'https://api.finmindtrade.com/api/v4/data',
                params={'dataset': 'TaiwanEconomicIndicator',
                        'start_date': _start, 'token': _tok},
                timeout=12)
            if _r_fm.status_code == 200:
                _j = _r_fm.json()
                _data = _j.get('data') or []
                # 篩出 name 含 PMI / 製造業採購 的 series，按 date 取最新
                _pmi_rows = [d for d in _data
                             if 'PMI' in str(d.get('name', '')) or '製造業' in str(d.get('name', ''))]
                if _pmi_rows:
                    _pmi_rows.sort(key=lambda x: str(x.get('date', '')), reverse=True)
                    _top = _pmi_rows[0]
                    _v = float(_top.get('value') or 0)
                    _d_str = str(_top.get('date', ''))
                    if 30 <= _v <= 70 and _d_str:
                        print(f"[macro_core/TW-PMI/FinMind] ✅ {_v} date={_d_str} ({_top.get('name')})")
                        return {'value': _v, 'date': _d_str[:10],
                                'label': f"FinMind TaiwanEconomicIndicator ({_top.get('name')})",
                                'source': 'FinMind', 'is_proxy': True,
                                'series_id': 'finmind-tw-pmi'}
        else:
            errs.append('FinMind:無 token')
    except Exception as e:
        errs.append(f'FinMind:{type(e).__name__}')
        print(f'[macro_core/TW-PMI/FinMind] ❌ {e}')

    # ── 方案 6: CIER cid=8（PMI 專屬類別，非 cid=21 新聞稿）──
    try:
        from bs4 import BeautifulSoup
        for cier_url in ('https://www.cier.edu.tw/news/list?cid=8',
                         'https://www.cier.edu.tw/news/list?cid=8&page=1'):
            r = fetch_url(cier_url, timeout=12, attempts=1)
            if r is None:
                errs.append(f'CIER-cid8.{cier_url[-15:]}:無回應')
                continue
            r.encoding = 'utf-8'
            txt = BeautifulSoup(r.text, 'html.parser').get_text(' ', strip=True)
            m = _re.search(
                r'(20\d{2})\s*年\s*(\d{1,2})\s*月.{0,40}?'
                r'PMI[^。]{0,30}?(\d{2}\.\d)',
                txt)
            if m:
                yr, mo, v = m.group(1), int(m.group(2)), float(m.group(3))
                if 30 <= v <= 70 and 1 <= mo <= 12:
                    last_date = _dt.date(int(yr), mo, 1)
                    if (today - last_date).days <= max_age_days:
                        date = f'{yr}-{mo:02d}-01'
                        print(f'[macro_core/TW-PMI/CIER-cid8] ✅ {v} date={date}')
                        return {'value': v, 'date': date,
                                'label': 'CIER 中華經濟研究院（PMI 專欄）',
                                'source': 'CIER', 'is_proxy': False,
                                'series_id': 'cier-pmi-cid8'}
    except Exception as e:
        errs.append(f'CIER-cid8:{type(e).__name__}')
        print(f'[macro_core/TW-PMI/CIER-cid8] ❌ {e}')

    # ── 方案 7: MoneyDJ 財經知識庫（搜尋頁，HTML 含 PMI 圖表 alt）──
    try:
        from bs4 import BeautifulSoup
        mdj_url = ('https://www.moneydj.com/KMDJ/Search/SearchListNew.aspx'
                   '?keyword=%E5%8F%B0%E7%81%A3PMI&type=knowledge')
        r = fetch_url(mdj_url, timeout=12, attempts=1)
        if r is None:
            errs.append('MoneyDJ:無回應')
        else:
            r.encoding = 'utf-8'
            txt = BeautifulSoup(r.text, 'html.parser').get_text(' ', strip=True)
            m = _re.search(
                r'(20\d{2})\s*年\s*(\d{1,2})\s*月.{0,40}?'
                r'(?:台灣|TW)\s*(?:製造業)?[^。]{0,40}?PMI[^。]{0,30}?(\d{2}\.\d)',
                txt)
            if m:
                yr, mo, v = m.group(1), int(m.group(2)), float(m.group(3))
                if 30 <= v <= 70 and 1 <= mo <= 12:
                    last_date = _dt.date(int(yr), mo, 1)
                    if (today - last_date).days <= max_age_days:
                        date = f'{yr}-{mo:02d}-01'
                        print(f'[macro_core/TW-PMI/MoneyDJ] ✅ {v} date={date}')
                        return {'value': v, 'date': date,
                                'label': 'MoneyDJ 財經知識庫',
                                'source': 'MoneyDJ', 'is_proxy': False,
                                'series_id': 'mdj-tw-pmi'}
    except Exception as e:
        errs.append(f'MoneyDJ:{type(e).__name__}')
        print(f'[macro_core/TW-PMI/MoneyDJ] ❌ {e}')

    err_msg = ' | '.join(errs) or 'all 8 stages failed'
    print(f'[macro_core/TW-PMI] ❌ 8 段備援全失敗：{err_msg}')
    return {'_err_pmi': err_msg, 'value': None}


# ══════════════════════════════════════════════════════════════
# 純數學工具(不需要網路,兩邊共用)
# ══════════════════════════════════════════════════════════════

def zscore(s: pd.Series) -> pd.Series:
    """標準分數(std=0 時回傳全 0,避免除零)。"""
    if s.empty:
        return s
    std = float(s.std())
    if std == 0 or np.isnan(std):
        return pd.Series([0.0] * len(s), index=s.index)
    return (s - s.mean()) / std


def trend_arrow(vals: list[float]) -> str:
    """
    依最近 N 點走勢給出口語化趨勢標記。
    回傳: '持續上升 ↑' / '持續下降 ↓' / '最近反彈 ↗' / '最近回落 ↘' / ''
    """
    if len(vals) < 3:
        return ""
    diffs = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    if pos >= len(diffs) - 1:
        return "持續上升 ↑"
    if neg >= len(diffs) - 1:
        return "持續下降 ↓"
    return "最近反彈 ↗" if diffs[-1] > 0 else "最近回落 ↘"


def recession_probability(spread_10y3m: Optional[float]) -> Optional[float]:
    """
    用 10Y-3M 利差做 logistic 回歸估算未來 12 個月衰退機率(%)。
    spread_10y3m 為 None 時回傳 None。
    """
    if spread_10y3m is None:
        return None
    logit = -1.5 * spread_10y3m - 0.8
    return round(1 / (1 + math.exp(-logit)) * 100, 1)


def spread_series(
    df_long: pd.DataFrame,
    df_short: pd.DataFrame,
    n_pts: int = 60,
) -> pd.Series:
    """
    計算兩個 FRED 序列的利差時序。
    優先用月頻對齊;若月頻 inner join 為空(例如 short 序列為日頻 TB3MS)
    則退回 merge_asof 容忍 40 天的回溯對齊。
    """
    if df_long.empty or df_short.empty:
        return pd.Series(dtype=float)

    dl = df_long[["date", "value"]].set_index("date").rename(columns={"value": "v_l"})
    ds = df_short[["date", "value"]].set_index("date").rename(columns={"value": "v_s"})
    dl_m = dl.resample("ME").last().ffill()
    ds_m = ds.resample("ME").last().ffill()
    merged = dl_m.join(ds_m, how="inner").dropna()
    if not merged.empty:
        return (merged["v_l"] - merged["v_s"]).tail(n_pts)

    dl2 = df_long[["date", "value"]].rename(columns={"value": "v_l"}).sort_values("date")
    ds2 = df_short[["date", "value"]].rename(columns={"value": "v_s"}).sort_values("date")
    m = pd.merge_asof(
        dl2, ds2, on="date",
        tolerance=pd.Timedelta("40d"), direction="backward",
    ).dropna().set_index("date")
    return (m["v_l"] - m["v_s"]).tail(n_pts)


# ══════════════════════════════════════════════════════════════
# 統一 snapshot schema 工具
# ══════════════════════════════════════════════════════════════

def make_indicator(
    key: str,
    name: str,
    value: float,
    *,
    prev: Optional[float] = None,
    unit: str = "",
    type_: str = "同時",
    date: str = "",
    series: Optional[pd.Series] = None,
    desc: str = "",
    weight: float = 1.0,
) -> dict:
    """
    建立統一格式的指標 dict。

    fund 端原本就用富 dict(value/prev/trend/series/...),stock 端用扁平 float。
    我們以富 dict 為共同 schema,扁平結構可由 flatten_snapshot() 動態產生。
    """
    trend = ""
    if series is not None and len(series) >= 3:
        trend = trend_arrow([float(x) for x in series.tail(6).tolist()])
    return {
        "key":    key,
        "name":   name,
        "value":  value,
        "prev":   prev,
        "unit":   unit,
        "type":   type_,
        "date":   date,
        "desc":   desc,
        "trend":  trend,
        "series": series,
        "weight": weight,
    }


def flatten_snapshot(rich: dict) -> dict:
    """
    將富 dict snapshot 轉為扁平 dict(key 小寫),方便相容 stock 端
    macro_alert.py / macro_state_locker.py 既有 API。

    rich = {"VIX": {"value": 28.3, ...}, "CPI": {"value": 3.1, ...}}
    →     {"vix": 28.3, "cpi": 3.1}
    """
    out: dict = {}
    for k, v in (rich or {}).items():
        if isinstance(v, dict) and v.get("value") is not None:
            out[k.lower()] = v["value"]
    return out
