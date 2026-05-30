"""
tw_macro.py — 台灣金融資料抓取核心 v1.0

設計目標
========
1. 把 stock-dashboard 與 fund-dashboard 中所有「台灣資料源」的抓取邏輯
   集中到此模組,避免雙邊重複。資料源涵蓋:
   - TWSE OpenAPI(漲跌家數)
   - FinMind 免費 API(三大法人籌碼)
   - 中央銀行 ms1.json / SDMX EF15M01(M1B / M2)
2. **所有抓取統一透過 proxy_helper.fetch_url(),確保走家用 NAS 中繼站**,
   解決雲端境外 IP 被擋(TWSE 對境外 IP 有限制)、被限流的問題。

範圍邊界
========
✅ 收錄:台灣資料抓取(TWSE / FinMind / CBC)
✅ 收錄:Tier 3 ^TWII 動能代理(透過 macro_core.fetch_yf_close,亦走 NAS proxy)
❌ 不收錄:全球指標(放在 macro_core.py)
❌ 不收錄:下游決策(放在各 repo 自己的引擎)

依賴限制
========
- 不依賴 streamlit
- 不依賴 yfinance(統一打 REST API,經 NAS 中繼)
"""
from __future__ import annotations

import datetime as _dt
import re as _re
from typing import Optional

import pandas as pd

from proxy_helper import fetch_url

__version__ = "1.0.0"

# ── 各端點 URL ────────────────────────────────────────────
TWSE_MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
FINMIND_BASE      = "https://api.finmindtrade.com/api/v4/data"
CBC_MS1_URLS      = [
    "https://www.cbc.gov.tw/public/data/ms1.json",
    "https://www.cbc.gov.tw/tw/public/data/ms1.json",
]
CBC_EF15M01_URL   = "https://cpx.cbc.gov.tw/API/DataAPI/Get"


# ══════════════════════════════════════════════════════════════
# TWSE 市場寬度
# ══════════════════════════════════════════════════════════════

def fetch_twse_breadth() -> dict:
    """
    從 TWSE MI_INDEX 抓上漲/下跌家數,計算市場寬度。

    Returns
    -------
    dict
        {
            'adv':        int | None,    上漲家數
            'dec':        int | None,    下跌家數
            'breadth':    float | None,  (adv-dec)/(adv+dec) × 100
            'z_breadth':  float | None,  max(-3, min(3, breadth/20))
            'date':       str,
            'error':      str | None,
        }
    """
    result = {'adv': None, 'dec': None, 'breadth': None,
              'z_breadth': None, 'date': '', 'error': None}

    r = fetch_url(TWSE_MI_INDEX_URL,
                  params={'response': 'json', 'type': 'MS'}, timeout=12)
    if r is None:
        result['error'] = "TWSE 抓取失敗(NAS proxy + 直連都失敗)"
        return result
    try:
        d = r.json()
    except Exception as e:
        result['error'] = f"TWSE JSON 解析失敗: {e}"
        return result

    result['date'] = d.get('date', '')
    for tbl in (d.get('tables') or []):
        if not isinstance(tbl, dict):
            continue
        rows = tbl.get('data', [])
        if not any('上漲' in str(row) for row in rows):
            continue
        adv = dec = 0
        for row in rows:
            row_s = str(row[0]) if row else ""
            mkt_s = str(row[1]) if len(row) > 1 else ""
            nums  = _re.findall(r"[\d,]+", mkt_s)
            val   = int(nums[0].replace(",", "")) if nums else 0
            if "上漲" in row_s:
                adv = val
            elif "下跌" in row_s:
                dec = val
        if adv + dec > 0:
            result['adv']        = adv
            result['dec']        = dec
            result['breadth']    = round((adv - dec) / (adv + dec) * 100, 2)
            result['z_breadth']  = max(-3.0, min(3.0, result['breadth'] / 20.0))
        break
    return result


# ══════════════════════════════════════════════════════════════
# FinMind 三大法人籌碼
# ══════════════════════════════════════════════════════════════

def fetch_finmind_foreign_investor(days_back: int = 7) -> dict:
    """
    從 FinMind 抓最近 N 天的外資買賣超(免費 API,無需 token)。

    Parameters
    ----------
    days_back : int
        回看天數,預設 7 天。

    Returns
    -------
    dict
        {
            'fii_net':  int | None,    外資淨買超(元)
            'z_fii':    float | None,  max(-3, min(3, fii_net / 5e9))
            'date':     str,
            'error':    str | None,
        }
    """
    result = {'fii_net': None, 'z_fii': None, 'date': '', 'error': None}

    today    = _dt.date.today()
    end_dt   = today.strftime("%Y-%m-%d")
    start_dt = (today - _dt.timedelta(days=days_back)).strftime("%Y-%m-%d")

    r = fetch_url(FINMIND_BASE, params={
        'dataset':    'TaiwanStockTotalInstitutionalInvestors',
        'start_date': start_dt,
        'end_date':   end_dt,
    }, timeout=12)
    if r is None:
        result['error'] = "FinMind 抓取失敗"
        return result
    try:
        rows = r.json().get('data', [])
    except Exception as e:
        result['error'] = f"FinMind JSON 解析失敗: {e}"
        return result

    fi_rows = [r for r in rows if r.get('name') == 'Foreign_Investor']
    if not fi_rows:
        result['error'] = "FinMind 無 Foreign_Investor 資料"
        return result

    fi_rows.sort(key=lambda x: x.get('date', ''), reverse=True)
    latest = fi_rows[0]
    fii_net = int(latest.get('buy', 0)) - int(latest.get('sell', 0))
    result['fii_net'] = fii_net
    result['z_fii']   = max(-3.0, min(3.0, fii_net / 5_000_000_000))
    result['date']    = latest.get('date', '')
    return result


# ══════════════════════════════════════════════════════════════
# 中央銀行 M1B / M2(三層備援)
# ══════════════════════════════════════════════════════════════

def _try_cbc_ms1(url: str) -> Optional[tuple]:
    """嘗試抓 CBC ms1.json,回傳 (m1b_yoy, m2_yoy) 或 None。"""
    r = fetch_url(url, timeout=12)
    if r is None:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    if not isinstance(data, list) or len(data) < 13:
        return None
    df = pd.DataFrame(data)
    c1 = next((c for c in df.columns
               if 'M1B' in str(c).upper() or '貨幣供給額M1B' in str(c)), None)
    c2 = next((c for c in df.columns
               if str(c).strip().upper() == 'M2' or '貨幣供給額M2' in str(c)), None)
    if not (c1 and c2):
        return None
    s1 = pd.to_numeric(df[c1], errors='coerce').dropna()
    s2 = pd.to_numeric(df[c2], errors='coerce').dropna()
    if len(s1) < 13 or len(s2) < 13:
        return None
    return (
        round((s1.iloc[-1] / s1.iloc[-13] - 1) * 100, 2),
        round((s2.iloc[-1] / s2.iloc[-13] - 1) * 100, 2),
    )


def _try_cbc_ef15m01() -> Optional[tuple]:
    """嘗試抓 CBC SDMX EF15M01,回傳 (m1b_yoy, m2_yoy) 或 None。"""
    r = fetch_url(CBC_EF15M01_URL, params={'FileName': 'EF15M01'}, timeout=15)
    if r is None:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    rows = data.get('DataSet', [])
    if not rows:
        return None
    dims = (data.get('Structure') or {}).get('Dimensions', [])
    cmap: dict = {}
    for dim in (dims if isinstance(dims, list) else []):
        if isinstance(dim, dict):
            cmap[str(dim.get('id', ''))] = str(dim.get('name', ''))
    if not cmap:
        cmap = {k: k for k in (rows[0] if isinstance(rows[0], dict) else {})}
    ck1 = next((k for k, v in cmap.items() if 'M1B' in v.upper()), None)
    ck2 = next((k for k, v in cmap.items()
                if v.strip().upper() in ('M2', 'M2 ')), None)
    if not ck1:
        ck1 = next((k for k in (rows[0] if isinstance(rows[0], dict) else {})
                    if 'M1B' in k.upper()), None)
    if not ck2:
        ck2 = next((k for k in (rows[0] if isinstance(rows[0], dict) else {})
                    if k.strip().upper() == 'M2'), None)
    if not (ck1 and ck2) or len(rows) < 13:
        return None
    sv1, sv2 = [], []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            sv1.append(float(str(row.get(ck1, '')).replace(',', '')))
            sv2.append(float(str(row.get(ck2, '')).replace(',', '')))
        except Exception:
            pass
    if len(sv1) < 13 or len(sv2) < 13:
        return None
    return (
        round((sv1[-1] / sv1[-13] - 1) * 100, 2),
        round((sv2[-1] / sv2[-13] - 1) * 100, 2),
    )


def _try_twii_proxy() -> Optional[tuple]:
    """Tier 3:^TWII 動能代理(走 macro_core 經 NAS proxy)。"""
    try:
        from macro_core import fetch_yf_close
    except ImportError:
        return None
    twii = fetch_yf_close("^TWII", range_="6mo")
    if len(twii) < 60:
        return None
    chg20 = round((twii.iloc[-1] / twii.iloc[-20] - 1) * 100, 2)
    chg60 = round((twii.iloc[-1] / twii.iloc[-60] - 1) * 100, 2)
    return (chg20, round(chg60 / 3, 2))


def fetch_cbc_m1b_m2() -> dict:
    """
    抓中央銀行 M1B / M2 月資料 YoY 變動率。三層備援:

    - Tier 1: CBC public/data/ms1.json(官方公開 JSON)
    - Tier 2: cpx.cbc.gov.tw SDMX EF15M01
    - Tier 3: ^TWII 動能代理(走 macro_core 經 NAS proxy)

    Returns
    -------
    dict
        {
            'm1b_yoy':        float | None,
            'm2_yoy':         float | None,
            'gap':            float | None,    m1b_yoy - m2_yoy
            'tier_used':      1 | 2 | 3 | None,
            'is_proxy_tier':  bool,            tier 3 才為 True
            'error':          str | None,
        }
    """
    result = {
        'm1b_yoy': None, 'm2_yoy': None, 'gap': None,
        'tier_used': None, 'is_proxy_tier': False, 'error': None,
    }

    # ── Tier 1 ──
    for url in CBC_MS1_URLS:
        out = _try_cbc_ms1(url)
        if out is not None:
            result['m1b_yoy'], result['m2_yoy'] = out
            result['gap']        = round(out[0] - out[1], 2)
            result['tier_used']  = 1
            return result

    # ── Tier 2 ──
    out = _try_cbc_ef15m01()
    if out is not None:
        result['m1b_yoy'], result['m2_yoy'] = out
        result['gap']       = round(out[0] - out[1], 2)
        result['tier_used'] = 2
        return result

    # ── Tier 3 ──
    out = _try_twii_proxy()
    if out is not None:
        result['m1b_yoy'], result['m2_yoy'] = out
        result['gap']            = round(out[0] - out[1], 2)
        result['tier_used']      = 3
        result['is_proxy_tier']  = True
        return result

    result['error'] = "三層備援全部失敗"
    return result


# ══════════════════════════════════════════════════════════════
# v1.1 拐點偵測資料源（景氣對策信號 / 領先指標 / 外資連續日數）
# ══════════════════════════════════════════════════════════════

# FinMind TaiwanMacroEconomics 指標名（中央銀行/國發會公開資料）
_NDC_SIGNAL_KEYS  = ('景氣對策信號(分)', '景氣對策信號')
_NDC_LI_KEYS      = ('領先指標綜合指數', '領先指標', '領先指標(綜合指數)')


def _finmind_macro_series(indicator_keys: tuple, months_back: int = 18,
                          token: str = "") -> Optional[pd.DataFrame]:
    """通用：抓 FinMind TaiwanMacroEconomics 指定指標的月頻歷史。
    回傳 DataFrame[date, value] 由舊到新；找不到回 None。"""
    today    = _dt.date.today()
    end_dt   = today.strftime("%Y-%m-%d")
    # months_back 月轉日（多抓一倍緩衝）
    start_dt = (today - _dt.timedelta(days=int(months_back * 31))).strftime("%Y-%m-%d")
    params: dict = {
        'dataset':    'TaiwanMacroEconomics',
        'start_date': start_dt,
        'end_date':   end_dt,
    }
    if token:
        params['token'] = token
    r = fetch_url(FINMIND_BASE, params=params, timeout=15)
    if r is None:
        return None
    try:
        rows = r.json().get('data', [])
    except Exception:
        return None
    if not rows:
        return None
    df = pd.DataFrame(rows)
    # FinMind 欄位名可能是 indicator / name / metric
    cand_col = next((c for c in ('indicator', 'name', 'metric')
                     if c in df.columns), None)
    val_col  = next((c for c in ('value', 'data') if c in df.columns), None)
    if cand_col is None or val_col is None or 'date' not in df.columns:
        return None
    mask = df[cand_col].astype(str).isin(indicator_keys)
    if not mask.any():
        # 用 contains 兜底
        mask = df[cand_col].astype(str).apply(
            lambda x: any(k in x for k in indicator_keys))
    if not mask.any():
        return None
    sub = df.loc[mask, ['date', val_col]].copy()
    sub.columns = ['date', 'value']
    sub['value'] = pd.to_numeric(sub['value'], errors='coerce')
    sub = sub.dropna().sort_values('date').reset_index(drop=True)
    if sub.empty:
        return None
    return sub


def fetch_ndc_signal_history(months_back: int = 12,
                             token: str = "") -> dict:
    """抓景氣對策信號分數歷史（月頻），偵測連 2 月反轉拐點。

    Returns
    -------
    dict
        {
          'score_latest': int | None,    最新月份分數（9~45）
          'score_prev':   int | None,    上月分數
          'score_prev2':  int | None,    上上月分數
          'trend':        list[int],     近 6 月分數
          'inflection':   str,           '🚀 連2月翻多' / '⚠️ 連2月翻空' /
                                          '🟢 持續上升' / '🔴 持續下降' / '📊 持平' /
                                          '⬜ 資料不足'
          'date_latest':  str,
          'source':       'FinMind' | None,
          'error':        str | None,
        }
    """
    result: dict = {
        'score_latest': None, 'score_prev': None, 'score_prev2': None,
        'trend': [], 'inflection': '⬜ 資料不足',
        'date_latest': '', 'source': None, 'error': None,
    }
    sub = _finmind_macro_series(_NDC_SIGNAL_KEYS,
                                months_back=months_back, token=token)
    if sub is None or len(sub) < 3:
        result['error'] = 'FinMind TaiwanMacroEconomics 無景氣對策信號資料'
        return result
    vals = [int(round(v)) for v in sub['value'].tail(6).tolist()]
    cur, prev = vals[-1], vals[-2]
    prev2 = vals[-3] if len(vals) >= 3 else None
    result['score_latest'] = cur
    result['score_prev']   = prev
    result['score_prev2']  = prev2
    result['trend']        = vals
    result['date_latest']  = str(sub['date'].iloc[-1])[:10]
    result['source']       = 'FinMind'
    # 拐點判斷：連 2 月同向反轉
    if prev2 is not None:
        # 連 2 月由跌轉升（prev2 ≥ prev 且 prev < cur 且 cur > prev）
        if prev2 >= prev and cur > prev:
            result['inflection'] = '🚀 連2月翻多'
        elif prev2 <= prev and cur < prev:
            result['inflection'] = '⚠️ 連2月翻空'
        elif cur > prev > prev2:
            result['inflection'] = '🟢 連3月上升'
        elif cur < prev < prev2:
            result['inflection'] = '🔴 連3月下降'
        else:
            result['inflection'] = '📊 震盪持平'
    return result


def fetch_ndc_leading_index(months_back: int = 18,
                            token: str = "") -> dict:
    """抓領先指標綜合指數歷史，計算 6M smoothed 變化率與翻揚拐點。

    Returns
    -------
    dict
        {
          'latest':   float | None,
          'prev':     float | None,
          'mom':      float | None,    最新月 MoM%
          'smooth6m': float | None,    最新 6M smoothed change（%）
          'prev_s6m': float | None,    前期 6M smoothed change
          'inflection': str,           '🚀 6M 由負轉正' / '🟢 持續擴張' /
                                       '🔴 持續收縮' / '⚠️ 由正轉負' / '⬜ 資料不足'
          'trend':    list[float],     近 8 月 6M smoothed change
          'date_latest': str,
          'source':   'FinMind' | None,
          'error':    str | None,
        }
    """
    result: dict = {
        'latest': None, 'prev': None, 'mom': None,
        'smooth6m': None, 'prev_s6m': None,
        'inflection': '⬜ 資料不足', 'trend': [],
        'date_latest': '', 'source': None, 'error': None,
    }
    sub = _finmind_macro_series(_NDC_LI_KEYS,
                                months_back=months_back, token=token)
    if sub is None or len(sub) < 8:
        result['error'] = 'FinMind TaiwanMacroEconomics 無領先指標歷史'
        return result
    s = sub.set_index('date')['value'].astype(float)
    cur = float(s.iloc[-1]); prev = float(s.iloc[-2])
    # 6M smoothed change：用 6 月移動平均的月變化率
    ma6 = s.rolling(6).mean().dropna()
    if len(ma6) < 2:
        result['error'] = '6M MA 樣本不足'
        return result
    s6m = ma6.pct_change().dropna() * 100  # 月變化率 %
    if len(s6m) < 2:
        result['error'] = '6M smoothed change 樣本不足'
        return result
    cur_s, prev_s = float(s6m.iloc[-1]), float(s6m.iloc[-2])
    trend = [round(v, 2) for v in s6m.tail(8).tolist()]
    result.update({
        'latest':   round(cur, 2),
        'prev':     round(prev, 2),
        'mom':      round((cur - prev) / prev * 100, 2) if prev else None,
        'smooth6m': round(cur_s, 2),
        'prev_s6m': round(prev_s, 2),
        'trend':    trend,
        'date_latest': str(s.index[-1])[:10],
        'source':   'FinMind',
    })
    if cur_s > 0 and prev_s <= 0:
        result['inflection'] = '🚀 6M 由負轉正'
    elif cur_s > 0:
        result['inflection'] = '🟢 持續擴張'
    elif cur_s < 0 and prev_s >= 0:
        result['inflection'] = '⚠️ 由正轉負'
    elif cur_s < 0:
        result['inflection'] = '🔴 持續收縮'
    else:
        result['inflection'] = '📊 持平'
    return result


def fetch_foreign_consecutive_days(days_back: int = 30,
                                   token: str = "") -> dict:
    """抓外資最近 N 日買賣超，計算連續同向日數與反轉拐點。

    Returns
    -------
    dict
        {
          'consec_days': int | None,    當前連續日數（+ 連買、- 連賣）
          'reversed':    bool,          昨日 vs 今日是否反轉
          'today_net':   int | None,    今日淨額（元）
          'prev_streak': int | None,    上一段連續日數（+ / -）
          'inflection':  str,           '🚀 連5賣→買' / '⚠️ 連5買→賣' /
                                        '🟢 連N買' / '🔴 連N賣' / '📊 震盪' /
                                        '⬜ 資料不足'
          'date_latest': str,
          'source':      'FinMind' | None,
          'error':       str | None,
        }
    """
    result: dict = {
        'consec_days': None, 'reversed': False, 'today_net': None,
        'prev_streak': None, 'inflection': '⬜ 資料不足',
        'date_latest': '', 'source': None, 'error': None,
    }
    today    = _dt.date.today()
    end_dt   = today.strftime("%Y-%m-%d")
    start_dt = (today - _dt.timedelta(days=days_back)).strftime("%Y-%m-%d")
    params: dict = {
        'dataset':    'TaiwanStockTotalInstitutionalInvestors',
        'start_date': start_dt,
        'end_date':   end_dt,
    }
    if token:
        params['token'] = token
    r = fetch_url(FINMIND_BASE, params=params, timeout=15)
    if r is None:
        result['error'] = 'FinMind 抓取失敗'
        return result
    try:
        rows = r.json().get('data', [])
    except Exception as e:
        result['error'] = f'FinMind JSON 解析失敗: {e}'
        return result
    fi_rows = [x for x in rows if x.get('name') == 'Foreign_Investor']
    if not fi_rows:
        result['error'] = 'FinMind 無 Foreign_Investor 資料'
        return result
    df = pd.DataFrame(fi_rows)
    df['net'] = pd.to_numeric(df.get('buy', 0), errors='coerce').fillna(0) - \
                pd.to_numeric(df.get('sell', 0), errors='coerce').fillna(0)
    df = df.sort_values('date').reset_index(drop=True)
    if len(df) < 2:
        result['error'] = '外資資料筆數不足'
        return result
    nets = df['net'].astype(float).tolist()
    # 連續日數計算：從尾巴往前數同號
    last_sign = 1 if nets[-1] > 0 else (-1 if nets[-1] < 0 else 0)
    consec = 0
    for v in reversed(nets):
        sign = 1 if v > 0 else (-1 if v < 0 else 0)
        if sign == last_sign and sign != 0:
            consec += 1
        else:
            break
    # 上一段連續日數（同樣由反方向掃描）
    prev_streak = 0
    if consec < len(nets):
        before = nets[:len(nets) - consec]
        if before:
            prev_sign = 1 if before[-1] > 0 else (-1 if before[-1] < 0 else 0)
            for v in reversed(before):
                sign = 1 if v > 0 else (-1 if v < 0 else 0)
                if sign == prev_sign and sign != 0:
                    prev_streak += 1
                else:
                    break
            prev_streak = prev_streak * prev_sign  # 帶號（- 表連賣）
    result['consec_days'] = consec * last_sign
    result['today_net']   = int(nets[-1])
    result['prev_streak'] = prev_streak
    result['date_latest'] = str(df['date'].iloc[-1])[:10]
    result['source']      = 'FinMind'
    result['reversed']    = (consec == 1 and prev_streak * last_sign < -5)
    # 拐點判斷
    if consec == 1 and prev_streak <= -5:
        result['inflection'] = f'🚀 連{-prev_streak}賣→買（拐點）'
    elif consec == 1 and prev_streak >= 5:
        result['inflection'] = f'⚠️ 連{prev_streak}買→賣（拐點）'
    elif consec >= 5 and last_sign > 0:
        result['inflection'] = f'🟢 連{consec}日買超'
    elif consec >= 5 and last_sign < 0:
        result['inflection'] = f'🔴 連{consec}日賣超'
    else:
        result['inflection'] = '📊 震盪'
    return result


# ══════════════════════════════════════════════════════════════
# 整合 API — 一次抓回三大台股總經因子
# ══════════════════════════════════════════════════════════════

def fetch_tw_market_snapshot(days_back: int = 7) -> dict:
    """
    一次抓回三大台股總經因子(寬度 / 外資 / M1B-M2),供 TPI 計算使用。

    Returns
    -------
    dict
        {
            'breadth': fetch_twse_breadth() 回傳值,
            'fii':     fetch_finmind_foreign_investor() 回傳值,
            'm1b_m2':  fetch_cbc_m1b_m2() 回傳值,
        }
    """
    return {
        'breadth': fetch_twse_breadth(),
        'fii':     fetch_finmind_foreign_investor(days_back=days_back),
        'm1b_m2':  fetch_cbc_m1b_m2(),
    }
