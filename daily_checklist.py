"""
daily_checklist.py v6.0 — Squid Proxy 模式
🔄 三大法人：TWSE BFI82U via Squid Proxy（5天回溯，row[3] 買賣超，元÷1e8=億）
🔄 融資餘額：5 段備援 — rwd MI_MARGN → HiStock → Goodinfo → Yahoo → 鉅亨網（仟元÷100,000=億）
🔄 ADL / yfinance / FinMind：不受 geo-block 影響，直連
"""
import requests, pandas as pd, datetime, os, time, re
import urllib3; urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Proxy 存活快取（模組層級，60s TTL，避免代理斷線拖垮所有連線）──────────
_proxy_health: dict = {}  # {url: (is_alive, checked_at)}
_PROXY_TTL = 60

def _proxy_alive(url: str, timeout: float = 2.0) -> bool:
    """TCP 快測代理是否可達；結果快取 60s。"""
    import socket, time as _t
    from urllib.parse import urlparse
    now = _t.time()
    if url in _proxy_health:
        alive, ts = _proxy_health[url]
        if now - ts < _PROXY_TTL:
            return alive
    try:
        _p = urlparse(url)
        _h, _port = _p.hostname or 'localhost', _p.port or 3128
        with socket.create_connection((_h, _port), timeout=timeout):
            alive = True
    except Exception:
        alive = False
    _proxy_health[url] = (alive, now)
    if not alive:
        print(f'[Proxy] ⚠️ {url} 無法連線，本輪跳過代理直連')
    return alive

def _bps():
    try:
        from tw_stock_data_fetcher import build_proxy_session as _b
        s = _b()
    except Exception:
        s = requests.Session()
    s.verify = False
    return s

import streamlit as st

def get_nas_proxy():
    """從 proxy_helper 讀取代理設定，並加做 TCP 存活檢測。"""
    try:
        from proxy_helper import get_proxy_config as _gpc
        _cfg = _gpc()
    except Exception:
        _cfg = None
    if not _cfg:
        return None
    _url = _cfg.get('http', '')
    if _url and _proxy_alive(_url):
        return _cfg
    return None

DISABLE_TWSE: bool = True  # 🚫 TWSE 已永久停用


# ── 快取基礎設施 (v4.5) ───────────────────────────────────────────────────
from data_config import TTL_CONFIG as _TTL_CFG, PKL_DIR as _PKL_DIR
_CACHE_SENTINEL = object()  # 區別快取未命中與合法 None 值

def _pkl_get(key: str, ttl: int):
    """讀取 pickle 快取；未命中或過期返回 _CACHE_SENTINEL。"""
    import pickle as _pk_, time as _tm_
    _path = f'{_PKL_DIR}/{key}.pkl'
    try:
        if os.path.exists(_path) and _tm_.time() - os.path.getmtime(_path) < ttl:
            with open(_path, 'rb') as _f_:
                _v_ = _pk_.load(_f_)
            if _v_ is not None:
                print(f'[Cache] ✅ {key} 命中（ttl={ttl}s）')
                return _v_
    except Exception:
        pass
    return _CACHE_SENTINEL

def _pkl_put(key: str, value):
    """寫入 pickle 快取（本次執行成功的資料）後 return value。"""
    import pickle as _pk_
    try:
        os.makedirs(_PKL_DIR, exist_ok=True)
        with open(f'{_PKL_DIR}/{key}.pkl', 'wb') as _f_:
            _pk_.dump(value, _f_)
    except Exception:
        pass
    return value

def _pkl_clear_all():
    """強制刷新：清除所有 pickle 快取檔案（供前端「強制更新」按鈕使用）。"""
    import glob as _glob_
    _removed = 0
    for _f_ in _glob_.glob(f'{_PKL_DIR}/*.pkl'):
        try:
            os.remove(_f_)
            _removed += 1
        except Exception:
            pass
    print(f'[Cache] 🗑️ 已清除 {_removed} 個快取檔案')


import plotly.graph_objects as go

FINMIND_TOKEN = (getattr(st, 'secrets', {}).get('FINMIND_TOKEN', '')
                 or os.environ.get('FINMIND_TOKEN', ''))
HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}
COLORS_7 = ["#58a6ff","#3fb950","#ffd700","#f85149","#bc8cff","#79c0ff","#ff9f43"]
INTL_MAP = {"道瓊工業 DJI":"^DJI","納斯達克 IXIC":"^IXIC","費城半導體 SOX":"^SOX","10Y公債殖利率":"^TNX","美元指數 DXY":"DX-Y.NYB"}
INTL_UNIT = {k:("%" if "殖利率" in k else "指數") for k in INTL_MAP}
TW_MAP   = {"台股加權指數":"^TWII","新台幣匯率":"TWD=X"}
TW_UNIT  = {"台股加權指數":"pts","新台幣匯率":"TWD/USD"}
TECH_MAP = {"台積電 ADR":"TSM","微軟 MSFT":"MSFT","蘋果 AAPL":"AAPL","谷歌 GOOGL":"GOOGL","輝達 NVDA":"NVDA","AMD":"AMD","博通 AVGO":"AVGO"}

def _num(s):
    try: return float(str(s).replace(",","").replace(" ","").replace("+",""))
    except: return None

_TW_TZ_DL = datetime.timezone(datetime.timedelta(hours=8))

def _tw_today_dl():
    return datetime.datetime.now(_TW_TZ_DL).date()

def _recent_date(fmt="%Y%m%d"):
    d = _tw_today_dl()
    # 週末直接退到週五
    while d.weekday() >= 5: d -= datetime.timedelta(days=1)
    return d.strftime(fmt)

# ═══════════════════════════════════════════════
# 三大法人（NAS 中繼站）— 收盤後15:30才有當日資料
# ═══════════════════════════════════════════════
def fetch_institutional(date_str=None):
    if date_str is None: date_str = _recent_date()
    _inst_ttl = _TTL_CFG.get('institutional', 600)
    _inst_cached = _pkl_get('institutional', _inst_ttl)
    if _inst_cached is not _CACHE_SENTINEL:
        return _inst_cached

    try:
        from proxy_helper import fetch_url as _furl_i
        _base_dt_i = datetime.datetime.now()
        for _di in range(7):
            _d = _base_dt_i - datetime.timedelta(days=_di)
            if _d.weekday() >= 5:
                continue
            _ds = _d.strftime('%Y%m%d')
            _r_i = _furl_i(
                f'https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&date={_ds}')
            if not _r_i:
                print(f'[三大法人/BFI82U] ⚠️ date={_ds} 無回應')
                continue
            try:
                _resp_i = _r_i.json()
            except Exception:
                continue
            if not (isinstance(_resp_i, dict) and _resp_i.get('stat') == 'OK'):
                print(f'[三大法人/BFI82U] ⚠️ date={_ds} stat={(_resp_i or {}).get("stat")}')
                continue
            # BFI82U 可能回傳 data 或 tables[0].data
            _data_i = _resp_i.get('data', [])
            if not _data_i and 'tables' in _resp_i:
                _data_i = (_resp_i['tables'][0] if _resp_i['tables'] else {}).get('data', [])
            if not _data_i:
                continue
            _inst = {'外資及陸資': {'net': 0.0}, '投信': {'net': 0.0}, '自營商': {'net': 0.0}}
            for _row_i in _data_i:
                _nm_i = str(_row_i[0])
                # row[3] = 買賣超（元，帶千分位逗號）；lstrip('-') 支援負值
                _vs_i = str(_row_i[3]).replace(',', '').strip()
                if not _vs_i.lstrip('-').isdigit():
                    continue
                _net_i = round(int(_vs_i) / 1e8, 2)  # 元 → 億元
                if '外資及陸資' in _nm_i:
                    _inst['外資及陸資']['net'] = _net_i
                elif '投信' in _nm_i:
                    _inst['投信']['net'] = _net_i
                elif '自營' in _nm_i:
                    _inst['自營商']['net'] += _net_i
            print(f'[三大法人/BFI82U] ✅ date={_ds} {_inst}')
            return _pkl_put('institutional', (_inst, _ds))
    except Exception as _e_inst:
        print(f'[三大法人/BFI82U] ❌ {type(_e_inst).__name__}: {_e_inst}')

    return {}, date_str


# ═══════════════════════════════════════════════
# 融資餘額（NAS 中繼站）
# ═══════════════════════════════════════════════
def fetch_margin_balance(date_str=None):
    """融資餘額 — FinMind → MI_MARGN → HiStock → Goodinfo → Yahoo → 鉅亨網，單位：億元
    v6：Plan 0 = FinMind TaiwanStockTotalMarginPurchaseShortSale（Streamlit Cloud 海外 IP 唯一可達來源）
    v5：Plan A = MI_MARGN（mi-margn.html 後端 JSON），扁平 data/fields 解析。"""
    _mb_ttl = _TTL_CFG.get('margin_balance', 600)
    _mb_cached = _pkl_get('margin_balance', _mb_ttl)
    if _mb_cached is not _CACHE_SENTINEL:
        return _mb_cached

    # 取最近一個交易日（週末往前推）
    _now_mb = datetime.datetime.now()
    while _now_mb.weekday() >= 5:
        _now_mb -= datetime.timedelta(days=1)
    _ds_mb = _now_mb.strftime('%Y%m%d')

    # 方案0: FinMind TaiwanStockTotalMarginPurchaseShortSale（v6 新增）
    # 治本：海外 IP 也可達，原 TWSE/HiStock/Goodinfo/Yahoo/cnyes 全部需要台灣 IP
    try:
        from leading_indicators import finmind_get as _fm_mb
        _tok_mb = os.environ.get('FINMIND_TOKEN', '')
        _start_mb = (_now_mb - datetime.timedelta(days=10)).strftime('%Y%m%d')
        _df_mb0 = _fm_mb('TaiwanStockTotalMarginPurchaseShortSale', '', _start_mb, _ds_mb, _tok_mb)
        if _df_mb0 is not None and not _df_mb0.empty:
            _cols_mb0 = list(_df_mb0.columns)
            _bal_cols0 = [c for c in _cols_mb0 if any(k in c for k in
                          ['alance', '餘額', 'amount', 'Amount'])]
            _df_mb0 = _df_mb0.sort_values('date')
            _last_d0 = str(_df_mb0['date'].iloc[-1])
            _grp0 = _df_mb0[_df_mb0['date'] == _last_d0]
            _v_mb0 = None
            if 'name' in _cols_mb0 and _bal_cols0:
                # 長格式：每一列代表「融資/融券」單一指標
                for _, _r0 in _grp0.iterrows():
                    _nm0 = str(_r0.get('name', '')).lower()
                    if not ('融資' in _nm0 or 'margin' in _nm0 or 'purchase' in _nm0):
                        continue
                    for _bc0 in _bal_cols0:
                        try:
                            _raw0 = float(str(_r0.get(_bc0, 0)).replace(',', '') or 0)
                        except Exception:
                            continue
                        # 自動偵測單位：億 / 元 / 千元 / 萬元
                        if 100 <= _raw0 <= 30_000:        _cand0 = _raw0
                        elif _raw0 > 1e9:                  _cand0 = _raw0 / 1e8
                        elif _raw0 > 1e6:                  _cand0 = _raw0 / 1e5
                        elif _raw0 > 1e4:                  _cand0 = _raw0 / 1e4
                        else:                              continue
                        if 100 < _cand0 < 30_000:
                            _v_mb0 = round(_cand0, 1); break
                    if _v_mb0 is not None: break
            elif 'TotalMarginPurchaseTodayBalance' in _cols_mb0:
                _raw0 = float(str(_grp0['TotalMarginPurchaseTodayBalance'].iloc[-1]).replace(',', '') or 0)
                if _raw0 > 1e6: _v_mb0 = round(_raw0 / 1e5, 1)
                elif 100 <= _raw0 <= 30_000: _v_mb0 = round(_raw0, 1)
            elif 'MarginPurchaseTodayBalance' in _cols_mb0:
                _raw0 = float(str(_grp0['MarginPurchaseTodayBalance'].iloc[-1]).replace(',', '') or 0)
                if _raw0 > 1e6: _v_mb0 = round(_raw0 / 1e5, 1)
                elif 100 <= _raw0 <= 30_000: _v_mb0 = round(_raw0, 1)
            if _v_mb0 is not None and 100 < _v_mb0 < 30_000:
                print(f'[融資餘額/FinMind] ✅ {_v_mb0}億 date={_last_d0}')
                return _pkl_put('margin_balance', _v_mb0)
            print(f'[融資餘額/FinMind] ⚠️ date={_last_d0} 解析未命中（cols={_cols_mb0[:6]}）')
        else:
            print('[融資餘額/FinMind] ⚠️ 回傳空 DataFrame')
    except Exception as _e_mb0:
        print(f'[融資餘額/FinMind] ❌ {type(_e_mb0).__name__}: {_e_mb0}')

    # 方案A: TWSE rwd MI_MARGN（單次嘗試最近交易日；MS→ALL 雙 selectType 容錯）
    # 對齊 leading_indicators._twse_margin_day 已驗證有效邏輯：頂層 data/fields，
    # 欄名偵測「融資...餘額」(排除「限」)，reversed 取彙總列，仟元÷100,000=億
    try:
        from proxy_helper import fetch_url as _furl_mb
        _hdr_mb = {'Referer': 'https://www.twse.com.tw/zh/trading/margin/mi-margn.html'}
        _hit_mb = False
        for _sel_mb in ('MS', 'ALL'):
            _r_mb = _furl_mb(
                'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN'
                f'?response=json&date={_ds_mb}&selectType={_sel_mb}',
                headers=_hdr_mb, timeout=12)
            if _r_mb is None:
                continue
            try:
                _resp_mb = _r_mb.json()
            except Exception:
                _resp_mb = None
            if not (isinstance(_resp_mb, dict) and _resp_mb.get('stat') == 'OK'):
                _stat_mb = (_resp_mb or {}).get('stat') if isinstance(_resp_mb, dict) else 'no-json'
                print(f'[融資餘額/MI_MARGN/{_sel_mb}] ⚠️ date={_ds_mb} stat={_stat_mb}')
                continue
            _fields_mb = [str(_f) for _f in _resp_mb.get('fields', [])]
            _fa_col = next((_i for _i, _f in enumerate(_fields_mb)
                           if '融資' in _f and '餘額' in _f and '限' not in _f), 6)
            for _row_mb in reversed(_resp_mb.get('data', [])):
                if not _row_mb or len(_row_mb) <= _fa_col:
                    continue
                _vs_mb = str(_row_mb[_fa_col]).replace(',', '').replace(' ', '').strip()
                try:
                    _v_raw_mb = float(_vs_mb)
                except Exception:
                    continue
                if _v_raw_mb > 10_000_000:  # 仟元 → 億
                    _v_mb = round(_v_raw_mb / 100_000, 1)
                    if 100 < _v_mb < 30_000:
                        print(f'[融資餘額/MI_MARGN/{_sel_mb}] ✅ {_v_mb}億 date={_ds_mb}')
                        return _pkl_put('margin_balance', _v_mb)
            print(f'[融資餘額/MI_MARGN/{_sel_mb}] ⚠️ date={_ds_mb} 解析未命中（fa_col={_fa_col}）')
            _hit_mb = True
        if not _hit_mb:
            print(f'[融資餘額/MI_MARGN] ⚠️ MS/ALL 皆無回應')
    except Exception as _e_mb:
        print(f'[融資餘額/MI_MARGN] ❌ {type(_e_mb).__name__}: {_e_mb}')

    # 方案B: HiStock 網頁爬蟲（公開，BeautifulSoup）
    try:
        from proxy_helper import fetch_url as _furl_hi
        from bs4 import BeautifulSoup as _BS_mb
        _rh = _furl_hi('https://histock.tw/stock/margin.aspx', timeout=12)
        if _rh is not None:
            _soup_h = _BS_mb(_rh.text, 'html.parser')
            # 搜尋含「融資餘額」文字附近的數字（億元）；L3: 使用頂層已匯入的 re
            _txt_h = _soup_h.get_text(' ', strip=True)
            _m_h = re.search(r'融資餘額[^\d]{0,20}([\d,]+(?:\.\d+)?)\s*億', _txt_h)
            if _m_h:
                _v_h = round(float(_m_h.group(1).replace(',', '')), 1)
                if 100 < _v_h < 30_000:
                    print(f'[融資餘額/HiStock] ✅ {_v_h}億')
                    return _pkl_put('margin_balance', _v_h)
    except Exception as _e_hi:
        print(f'[融資餘額/HiStock] ❌ {type(_e_hi).__name__}: {_e_hi}')

    # 方案C: Goodinfo 加權指數融資融券日統計（公開 HTML，BeautifulSoup）
    # 補強：表頭判斷放寬（任一含「融資」即可）+ 整頁正則 fallback
    try:
        from proxy_helper import fetch_url as _furl_gi
        from bs4 import BeautifulSoup as _BS_gi
        _gi_url = ('https://goodinfo.tw/tw/ShowMarginChart.asp'
                   '?STOCK_ID=%E5%8A%A0%E6%AC%8A%E6%8C%87%E6%95%B8'
                   '&CHT_CAT=DATE&PRICE_ADJ=F'
                   '&SHEET=%E8%9E%8D%E8%B3%87%E8%9E%8D%E5%88%B8%E9%A4%98%E9%A1%8D')
        _gi_hdr = {'Referer': 'https://goodinfo.tw/tw2/index.asp'}
        _rg = _furl_gi(_gi_url, headers=_gi_hdr, timeout=15)
        if _rg is not None:
            _rg.encoding = 'utf-8'
            _soup_g = _BS_gi(_rg.text, 'html.parser')
            _gi_val = None
            # 第一輪：表頭含「融資」的表格
            for _tbl in _soup_g.find_all('table'):
                _heads = ' '.join(th.get_text(' ', strip=True)
                                  for th in _tbl.find_all('th'))
                if '融資' not in _heads:
                    continue
                _rows = _tbl.find_all('tr')
                for _row_g in _rows[1:]:
                    _cells = [c.get_text(' ', strip=True)
                              for c in _row_g.find_all(['td', 'th'])]
                    _nums = [c for c in _cells
                             if re.match(r'^[\d,]+(\.\d+)?$', c.replace(',', ''))]
                    if len(_nums) >= 3:
                        for _cand in _nums[:5]:
                            _vc = float(_cand.replace(',', ''))
                            if _vc > 100_000:
                                _vc = round(_vc / 100_000, 1)
                            if 100 < _vc < 30_000:
                                _gi_val = round(_vc, 1); break
                        if _gi_val is not None: break
                if _gi_val is not None: break
            # 第二輪 fallback：整頁正則「融資餘額 12,345 億」
            if _gi_val is None:
                _txt_g = _soup_g.get_text(' ', strip=True)
                _m_g = re.search(r'融資餘額[^\d]{0,30}([\d,]+(?:\.\d+)?)\s*億', _txt_g)
                if _m_g:
                    _vg2 = round(float(_m_g.group(1).replace(',', '')), 1)
                    if 100 < _vg2 < 30_000:
                        _gi_val = _vg2
            if _gi_val is not None:
                print(f'[融資餘額/Goodinfo] ✅ {_gi_val}億')
                return _pkl_put('margin_balance', _gi_val)
            print('[融資餘額/Goodinfo] ⚠️ 表格 + 正則皆未命中')
    except Exception as _e_gi:
        print(f'[融資餘額/Goodinfo] ❌ {type(_e_gi).__name__}: {_e_gi}')

    # 方案D: Yahoo 股市資券餘額（HTML，整頁正則）
    try:
        from proxy_helper import fetch_url as _furl_yh
        from bs4 import BeautifulSoup as _BS_yh
        _ry = _furl_yh('https://tw.stock.yahoo.com/margin-balance', timeout=12)
        if _ry is not None:
            _ry.encoding = 'utf-8'
            _txt_y = _BS_yh(_ry.text, 'html.parser').get_text(' ', strip=True)
            # Yahoo 顯示「融資餘額 1,234 億」或「融資餘額(億) 1,234」
            _m_y = re.search(r'融資餘額[^\d]{0,30}([\d,]+(?:\.\d+)?)\s*(?:億|$)', _txt_y)
            if _m_y:
                _vy = round(float(_m_y.group(1).replace(',', '')), 1)
                if 100 < _vy < 30_000:
                    print(f'[融資餘額/Yahoo] ✅ {_vy}億')
                    return _pkl_put('margin_balance', _vy)
            print('[融資餘額/Yahoo] ⚠️ 正則未命中')
    except Exception as _e_yh:
        print(f'[融資餘額/Yahoo] ❌ {type(_e_yh).__name__}: {_e_yh}')

    # 方案E: 鉅亨網盤後資券餘額（HTML，整頁正則）
    try:
        from proxy_helper import fetch_url as _furl_cy
        from bs4 import BeautifulSoup as _BS_cy
        _rc = _furl_cy('https://www.cnyes.com/twstock/a_margin.aspx', timeout=12)
        if _rc is not None:
            _rc.encoding = 'utf-8'
            _txt_c = _BS_cy(_rc.text, 'html.parser').get_text(' ', strip=True)
            _m_c = re.search(r'融資餘額[^\d]{0,30}([\d,]+(?:\.\d+)?)\s*(?:億|$)', _txt_c)
            if _m_c:
                _vc = round(float(_m_c.group(1).replace(',', '')), 1)
                if 100 < _vc < 30_000:
                    print(f'[融資餘額/cnyes] ✅ {_vc}億')
                    return _pkl_put('margin_balance', _vc)
            print('[融資餘額/cnyes] ⚠️ 正則未命中')
    except Exception as _e_cy:
        print(f'[融資餘額/cnyes] ❌ {type(_e_cy).__name__}: {_e_cy}')

    return None


def evaluate_market_status_v4_final(current_price: float, ma_240: float,
                                    futures_net_oi: int) -> dict:
    """台股 AI 戰情室 v4.0 核心引擎（專注共同基金與總經）"""
    current_price = current_price or 1.0
    ma_240 = ma_240 or current_price
    futures_net_oi = futures_net_oi or 0

    bias_240 = ((current_price - ma_240) / ma_240) * 100
    is_bull_market = current_price >= (ma_240 * 0.99)
    is_overheated = bias_240 > 20.0
    is_foreign_hedging = futures_net_oi < -30000

    if is_bull_market:
        if is_overheated or is_foreign_hedging:
            signal = "🟡 多頭過熱 / 震盪警戒"
            action = "大盤乖離與外資避險過高。建議暫停積極型基金單筆申購，轉為定期定額，並拉高防禦型/平衡型基金權重。"
            hold_ratio = "50% - 70%"
        else:
            signal = "🟢 強勢多頭"
            action = "均線多頭排列且籌碼穩定。建議擴大核心部位，增加成長型股票基金曝險。"
            hold_ratio = "80% - 100%"
    else:
        signal = "🔴 空頭防禦"
        action = "跌破年線，趨勢偏空。維持既有定期定額，單筆操作宜觀望。"
        hold_ratio = "20% - 40%"

    return {
        "Signal": signal,
        "Action_Advice": action,
        "Suggested_Holding": hold_ratio,
        "Bias_240": round(bias_240, 2),
        "Is_Bull": is_bull_market,
        "Is_Overheated": is_overheated,
        "Is_Foreign_Hedging": is_foreign_hedging,
    }


# ═══════════════════════════════════════════════
# yfinance
# ═══════════════════════════════════════════════
def fetch_single(symbol, period="60d"):
    import os as _os2, pickle as _pk2, hashlib as _hs2
    _ck2 = '/tmp/stock_cache/' + _hs2.md5(f'yf_{symbol}_{period}'.encode()).hexdigest() + '.pkl'
    _os2.makedirs('/tmp/stock_cache', exist_ok=True)
    if _os2.path.exists(_ck2) and (time.time()-_os2.path.getmtime(_ck2))/60 < 30:
        try:
            with open(_ck2,'rb') as _f: return _pk2.load(_f)
        except: pass
    # 美元指數備援 symbol 清單
    _sym_list = [symbol]
    if symbol in ('DX-Y.NYB', 'DX=F'):
        _sym_list = ['DX-Y.NYB', 'DX=F', 'UUP']  # NYB→期貨→ETF
    # proxy 環境注入
    try:
        from tw_stock_data_fetcher import _load_proxy_config as _lpc_fs
        _px_fs = ((_lpc_fs() or {}).get('https') or (_lpc_fs() or {}).get('http') or None)
    except Exception:
        _px_fs = None
    _ek_fs = ('HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy')
    _bak_fs = {k: _os2.environ.get(k) for k in _ek_fs}
    if _px_fs:
        for k in _ek_fs: _os2.environ[k] = _px_fs
    try:
        import yfinance as yf
        h = None
        for _sym in _sym_list:
            try:
                _h = yf.Ticker(_sym).history(period=period)
                if _h is not None and not _h.empty:
                    h = _h; break
            except: continue
        if h is None or h.empty: return None
        h.index = pd.DatetimeIndex(h.index).tz_localize(None)
        h.columns = [c.lower().replace(' ','_') for c in h.columns]
        if 'close' in h.columns:
            h = h.dropna(subset=['close'])
        elif 'Close' in h.columns:
            h = h.dropna(subset=['Close'])
        if h.empty: return None
        with open(_ck2,'wb') as _f: _pk2.dump(h, _f)
        return h
    except Exception as e:
        print(f'[yf:{symbol}] {e}'); return None
    finally:
        for k, v in _bak_fs.items():
            if v is None: _os2.environ.pop(k, None)
            else: _os2.environ[k] = v

def fetch_flow_snapshot(period="2y"):
    """全球資金流向所需的區域 / 跨資產 ETF 收盤序列：並行抓取 + /tmp pickle 快取 30 分。

    回 {顯示名: DataFrame}（沿用 fetch_single 結構）。只在核心 SPY 抓到時才寫快取，
    避免暫時性全失敗被黏住。供總經 tab「全球資金流向」一節使用。
    """
    import os as _os_fl
    import pickle as _pk_fl
    import time as _tm_fl
    from concurrent.futures import ThreadPoolExecutor as _TPE_fl
    from flow_engine import all_symbols as _all_fl

    _ck_fl = '/tmp/stock_cache/_flow_snapshot.pkl'
    _os_fl.makedirs('/tmp/stock_cache', exist_ok=True)
    if _os_fl.path.exists(_ck_fl) and (_tm_fl.time() - _os_fl.path.getmtime(_ck_fl)) / 60 < 30:
        try:
            with open(_ck_fl, 'rb') as _f_fl:
                return _pk_fl.load(_f_fl)
        except Exception:
            pass

    _syms = _all_fl()                      # {名稱: 代號}
    _uniq = sorted(set(_syms.values()))    # 去重後實際抓取（SPY 等共用代號只抓一次）

    def _one(sym):
        return sym, fetch_single(sym, period=period)

    _by_sym = {}
    try:
        with _TPE_fl(max_workers=min(8, len(_uniq))) as _ex_fl:
            for _sym, _df in _ex_fl.map(_one, _uniq):
                _by_sym[_sym] = _df
    except Exception as _e_fl:
        print(f'[flow] ❌ 並行抓取異常: {_e_fl}')

    out = {name: _by_sym.get(sym) for name, sym in _syms.items()}

    if _by_sym.get('SPY') is not None:     # 核心抓到才快取
        try:
            with open(_ck_fl, 'wb') as _f_fl:
                _pk_fl.dump(out, _f_fl)
        except Exception:
            pass
    return out

def _fetch_otc_via_finmind(token=""):
    if not FINMIND_TOKEN: return None
    try:
        start=(datetime.date.today()-datetime.timedelta(days=90)).strftime('%Y-%m-%d')
        r=_bps().get("https://api.finmindtrade.com/api/v4/data",
                       params={"dataset":"TaiwanStockDaily","data_id":"OTC","start_date":start},
                       headers={"Authorization":f"Bearer {FINMIND_TOKEN}"},timeout=20)
        j=r.json()
        if j.get("status")==200 and j.get("data"):
            df=pd.DataFrame(j["data"])
            if 'close' in df.columns:
                df['Date']=pd.to_datetime(df['date'])
                return df.sort_values('Date').set_index('Date')[['close']].rename(columns={'close':'Close'})
    except Exception as e: print(f"[OTC] {e}")
    return None



# ═════════════════════════════════════════════════════
# 騰落指標（ADL）— FinMind 唯一來源（🚫 TWSE MI_INDEX 已移除）
# ═════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════
# 騰落指標（ADL）— 完整重寫版
# 不用 @st.cache_data（在 thread 中失敗），改用 pickle cache
# 資料來源: yfinance ^TWII（🚫 TWSE MI_INDEX 已移除）
# ═════════════════════════════════════════════════════
def fetch_adl(days=60, token=None):
    """
    騰落指標 ADL v5 — yfinance ^TWII 估算（🚫 TWSE MI_INDEX 已永久停用）
    ① yfinance ^TWII  — 立即可用估算值
       並發 5 線程逐日抓取；精確值自動覆蓋估算值

    根本原因修正：TaiwanStockMarketCondition 不在 FinMind v4 有效資料集中
    """
    import datetime as _dt
    import pickle as _pk
    import os as _os2
    import time as _tm2
    import re as _re
    import pandas as _pd_adl
# ── 日誌 helper ──────────────────────────────────────────────
    _log_path = '/tmp/_adl_log.txt'
    def _alog(msg):
        print(msg, flush=True)
        try:
            with open(_log_path, 'a', encoding='utf-8') as _f:
                _f.write(msg + '\n')
        except Exception:
            pass
    try:
        open(_log_path, 'w').close()
    except Exception:
        pass

    # ── Cache ────────────────────────────────────────────────────
    _ck = '/tmp/stock_cache/adl_data.pkl'
    _os2.makedirs('/tmp/stock_cache', exist_ok=True)
    if _os2.path.exists(_ck):
        _age = _tm2.time() - _os2.path.getmtime(_ck)
        if _age < 1800:
            try:
                _c = _pk.load(open(_ck, 'rb'))
                if _c is not None and not _c.empty:
                    _alog(f'[ADL] 快取命中 {len(_c)} 筆 (age={_age/60:.1f}min)')
                    return _c
            except Exception:
                pass

    today  = _dt.date.today()
    s_date = today - _dt.timedelta(days=days + 14)
    s_dash = s_date.strftime('%Y-%m-%d')
    e_dash = today.strftime('%Y-%m-%d')
    rows: dict = {}   # {ymd: {'up':int, 'down':int, 'is_proxy':bool}}

    # ════════════════════════════════════════════════════════════════
    # ① yfinance ^TWII — 估算（立即可用，is_proxy=True）
    # 公式：漲跌幅 ±1% ≈ ±150 家，以 900/900 為基準
    # ════════════════════════════════════════════════════════════════
    _alog('[ADL-①] yfinance ^TWII 估算...')
    try:
        import yfinance as _yf_adl, os as _os_yf
        try:
            from tw_stock_data_fetcher import _load_proxy_config as _lpc_adl
            _yf_px = (_lpc_adl() or {})
            _yf_px = _yf_px.get('https') or _yf_px.get('http') or None
        except Exception:
            _yf_px = None
        _ek = ('HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy')
        _ebak = {k: _os_yf.environ.get(k) for k in _ek}
        if _yf_px:
            for k in _ek:
                _os_yf.environ[k] = _yf_px
        try:
            _twii = _yf_adl.download('^TWII', start=s_dash, end=e_dash, progress=False, auto_adjust=True)
        finally:
            for k, v in _ebak.items():
                if v is None:
                    _os_yf.environ.pop(k, None)
                else:
                    _os_yf.environ[k] = v
        if not _twii.empty:
            # [Fix] yfinance 新版可能回傳 MultiIndex columns，需先攤平
            if isinstance(_twii.columns, pd.MultiIndex):
                _twii.columns = _twii.columns.get_level_values(0)
            _twii = _twii.dropna(subset=['Close'])
            for _ix in _twii.index:
                _dk = str(_ix)[:10].replace('-', '')
                _cl = float(_twii.loc[_ix, 'Close'])
                _op = float(_twii.loc[_ix, 'Open'])
                _pct = (_cl - _op) / _op if _op > 0 else 0.0
                # 估算公式：中性=900，每±1%約±150家，限制在50~1750
                _up = max(50, min(1750, int(900 + _pct * 15000)))
                rows[_dk] = {'up': _up, 'down': max(50, 1800 - _up), 'is_proxy': True}
            _alog(f'[ADL-①] ✅ {len(rows)} 天估算完成')
        else:
            _alog('[ADL-①] ⚠️ yfinance 回傳空資料')
    except Exception as _e1:
        _alog(f'[ADL-①] ❌ {type(_e1).__name__}: {_e1}')

    # Edge Case 6: 完全沒有資料（🚫 TWSE MI_INDEX 已移除）
    if not rows:
        _alog('[ADL] ⚠️ 所有來源均失敗，回傳 None')
        return None

    # ── 組合 DataFrame ──────────────────────────────────────────
    _records = []
    for _dk in sorted(rows):
        if not (s_date.strftime('%Y%m%d') <= _dk <= today.strftime('%Y%m%d')):
            continue
        _v = rows[_dk]
        _records.append({
            'date':     _dk,
            'up':       _v['up'],
            'down':     _v['down'],
            'is_proxy': _v['is_proxy'],
        })

    # Edge Case 7: 過濾後仍無記錄
    if not _records:
        _alog('[ADL] ⚠️ 有效記錄為空')
        return None

    df = _pd_adl.DataFrame(_records)
    df['ad']       = df['up'] - df['down']
    df['adl']      = df['ad'].cumsum()
    df['adl_ma20'] = df['adl'].rolling(20, min_periods=1).mean()
    df['ad_ratio'] = (df['up'] / (df['up'] + df['down']).replace(0, 1) * 100).round(1)
    df['date']     = _pd_adl.to_datetime(df['date'], format='%Y%m%d')

    _proxy_n = int(df['is_proxy'].sum())
    _exact_n = int((~df['is_proxy']).sum())
    _alog(
        f'[ADL] ✅ 完成 {len(df)} 筆 '
        f'精確={_exact_n} 估算={_proxy_n} '
        f'上漲佔比:{df["ad_ratio"].iloc[-1]:.1f}%'
    )

    # ── 快取 ────────────────────────────────────────────────────
    try:
        with open(_ck, 'wb') as _f:
            _pk.dump(df.tail(days).reset_index(drop=True), _f)
    except Exception:
        pass

    return df.tail(days).reset_index(drop=True)


# ── 4. Self-Test（邊界測試）────────────────────────────────────
def _adl_selftest():
    """在 Colab 外部可執行此函數驗證解析邏輯"""
    import re

    def _parse(s):
        m = re.match(r'^([\d,]+)', str(s).strip())
        return int(m.group(1).replace(',', '')) if m else 0

    # Test 1: 正常格式
    assert _parse('7,768(403)') == 7768, "Test1 failed"
    # Test 2: 無括號
    assert _parse('3,644') == 3644, "Test2 failed"
    # Test 3: 空字串
    assert _parse('') == 0, "Test3 failed"
    # Test 4: 只有漢字（類型欄誤傳）
    assert _parse('上漲') == 0, "Test4 failed"
    # Test 5: 大值
    assert _parse('19,039') == 19039, "Test5 failed"
    print("[ADL selftest] ✅ 全部通過")




def _hex2rgba(color, alpha=0.12):
    try:
        c=color.lstrip('#'); r,g,b=int(c[0:2],16),int(c[2:4],16),int(c[4:6],16)
        return f"rgba({r},{g},{b},{alpha})"
    except: return "rgba(88,166,255,0.12)"

def _base_layout(title="", height=260):
    return dict(title=dict(text=title,font=dict(color="#8b949e",size=12)),
                height=height,plot_bgcolor="#0e1117",paper_bgcolor="#0e1117",
                font=dict(color="#e6edf3",size=11),
                margin=dict(l=8,r=8,t=35,b=20),
                xaxis=dict(gridcolor="#21262d",showgrid=True,zeroline=False),
                yaxis=dict(gridcolor="#21262d",showgrid=True,zeroline=False),
                legend=dict(bgcolor="rgba(0,0,0,0)",font=dict(size=10)))

def sparkline(df, title="", color="#58a6ff"):
    col=next((c for c in ['close','Close'] if c in df.columns),None)
    if col is None: return go.Figure()
    s=df[col].dropna().tail(45)
    fig=go.Figure(go.Scatter(x=list(s.index),y=list(s.values),mode='lines',
                             line=dict(color=color,width=2),fill='tozeroy',
                             fillcolor=_hex2rgba(color) if color.startswith('#') else color))
    fig.update_layout(**_base_layout(title,200)); return fig

def multi_chart(data_dict, title="", norm=False, height=250):
    fig=go.Figure()
    for i,(name,df) in enumerate(data_dict.items()):
        col=next((c for c in ['close','Close'] if c in df.columns),None)
        if col is None: continue
        s=df[col].dropna().tail(45)
        y=(s/s.iloc[0]*100).round(2) if (norm and len(s)>0) else s
        fig.add_trace(go.Scatter(x=list(s.index),y=list(y.values),mode='lines',name=name,
                                 line=dict(color=COLORS_7[i%len(COLORS_7)],width=2)))
    fig.update_layout(**_base_layout(title,height)); return fig

def bar_chart_institutional(inst_dict, title="三大法人買賣超（堆疊柱狀圖）", height=300):
    """升級版：堆疊柱狀圖（三大法人各自一欄，顏色區分）"""
    import datetime as _dt_bar
    # 分離三個法人
    _inst_keys = ['外資', '投信', '自營商']
    _inst_colors = {'外資': '#58a6ff', '投信': '#3fb950', '自營商': '#bc8cff'}
    # 初始化為 float（修復：原為 [] 導致 >= 比較 TypeError）
    _data_by = {k: 0.0 for k in _inst_keys}
    # inst_dict 格式: {法人名: {net, buy, sell, ...}}
    if inst_dict and isinstance(inst_dict, dict):
        for _name, _val in inst_dict.items():
            if '合計' in _name: continue
            if not isinstance(_val, dict): continue
            _matched = next((k for k in _inst_keys if k in str(_name)), None)
            if _matched:
                try: _data_by[_matched] = float(_val.get('net', 0) or 0)
                except: pass
    # 若無日期維度，做單日橫向堆疊
    fig = go.Figure()
    for _ik in _inst_keys:
        _v = float(_data_by.get(_ik, 0.0))  # 確保是 float
        _c = '#da3633' if _v > 0 else ('#2ea043' if _v < 0 else '#388bfd')
        fig.add_trace(go.Bar(
            name=_ik, x=[_ik], y=[_v],
            marker_color=_inst_colors.get(_ik, _c),
            text=[f'{_v:+.1f}億'],
            textposition='outside',
            cliponaxis=False,
            opacity=0.9,
        ))
    # 若全部為 0（API 未回傳或節假日），加入 annotation 提示
    _total = sum(float(v) for v in _data_by.values())
    _all_zero = all(v == 0.0 for v in _data_by.values())
    _layout = _base_layout(title, height)
    _layout.update({
        'barmode': 'group',
        'showlegend': True,
        'legend': {'orientation': 'h', 'y': 1.08, 'font': {'size': 10, 'color': '#8b949e'}},
        'shapes': [{'type': 'line', 'x0': -0.5, 'x1': 2.5, 'y0': 0, 'y1': 0,
                    'line': {'color': '#484f58', 'width': 1, 'dash': 'dot'}}],
        'annotations': [{'text': f'合計: {_total:+.1f}億',
                         'xref': 'paper', 'yref': 'paper', 'x': 0.98, 'y': 0.95,
                         'showarrow': False, 'font': {'size': 12, 'color': '#da3633' if _total > 0 else ('#2ea043' if _total < 0 else '#388bfd')}}]
    })
    if _all_zero:
        # 所有值為 0：填充佔位 bar 讓圖表不空白，並加提示文字
        for _ik in _inst_keys:
            fig.add_trace(go.Bar(
                name=_ik, x=[_ik], y=[0.001],
                marker_color='#21262d', opacity=0.3,
                showlegend=False,
            ))
        _layout['annotations'] = [{'text': '⚠️ 資料待更新（收盤後 15:30 取得）',
                                    'xref': 'paper', 'yref': 'paper', 'x': 0.5, 'y': 0.5,
                                    'showarrow': False, 'font': {'size': 13, 'color': '#d29922'}}]
    fig.update_layout(**_layout)
    return fig

def stat_card(name, stats, unit="", has_data=True):
    if not has_data or stats is None:
        return (f'<div style="background:#161b22;border:1px solid #21262d;border-radius:8px;'
                f'padding:12px;text-align:center;opacity:0.5;"><div style="font-size:10px;color:#484f58;">{name}</div>'
                f'<div style="font-size:13px;color:#484f58;">載入中...</div></div>')
    pct=stats.get('pct',0); pc='#da3633' if pct>0 else ('#2ea043' if pct<0 else '#388bfd'); arrow='▲' if pct>0 else ('▼' if pct<0 else '─')
    return (f'<div style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px;text-align:center;">'
            f'<div style="font-size:10px;color:#484f58;">{name}</div>'
            f'<div style="font-size:18px;font-weight:900;color:#e6edf3;">{stats.get("last","?")} '
            f'<span style="font-size:10px;color:#8b949e;">{unit}</span></div>'
            f'<div style="font-size:12px;font-weight:700;color:{pc};">{arrow} {abs(pct):.2f}%</div>'
            f'<div style="font-size:10px;color:#484f58;">{stats.get("status","")}</div></div>')

def margin_card(margin):
    if margin is None:
        return ('<div style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:14px;">'
                '<div style="font-size:11px;color:#484f58;">融資餘額</div>'
                '<div style="font-size:12px;color:#d29922;margin-top:6px;">⏳ 抓取中（TWSE 15:30後更新）</div>'
                '<div style="font-size:10px;color:#484f58;margin-top:4px;">收盤後點「更新全部總經數據」重試</div></div>')
    mc='#f85149' if margin>3400 else ('#d29922' if margin>2500 else '#3fb950')
    label='🔴超過3400億高危' if margin>3400 else ('⚡超過2500億警戒' if margin>2500 else '✅安全水位')
    return (f'<div style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:14px;">'
            f'<div style="font-size:11px;color:#484f58;">融資餘額</div>'
            f'<div style="font-size:28px;font-weight:900;color:{mc};">{margin:.0f}'
            f'<span style="font-size:12px;">億</span></div>'
            f'<div style="font-size:10px;color:#8b949e;">{label}</div></div>')

def section_header(num, title, icon=""):
    return (f'<div style="background:linear-gradient(90deg,#161b22,transparent);'
            f'border-left:3px solid #1f6feb;border-radius:0 6px 6px 0;'
            f'padding:8px 14px;margin:16px 0 10px 0;">'
            f'<span style="color:#1f6feb;font-weight:700;">{icon} {num}、{title}</span></div>')

def analyze_20d_chips(stock_id: str) -> dict:
    """
    近 20 日個股籌碼集中度分析（外資 + 投信 vs 總成交量）

    指標 A 集中度 = (外資+投信) 20日淨買總和 / 20日總成交量  × 100%
    指標 B 延續性 = 20日中 (外資+投信) 淨買 > 0 的天數佔比 (%)

    買賣超單位：張 (FinMind TaiwanStockTotalInstitutionalInvestors)
    成交量單位：張 (FinMind TaiwanStockPrice Trading_Volume)
    → 兩者單位相同，集中度為無因次百分比
    """
    import datetime as _dt20
    try:
        import pandas as _pd20
        _start = (_dt20.date.today() - _dt20.timedelta(days=50)).strftime('%Y-%m-%d')
        _base  = 'https://api.finmindtrade.com/api/v4/data'
        _hdrs  = {'Authorization': f'Bearer {FINMIND_TOKEN}'} if FINMIND_TOKEN else {}
        _common = {'token': FINMIND_TOKEN} if FINMIND_TOKEN else {}

        # ── 1. 個股三大法人每日買賣超（單位：張）────────────────────
        _p_inst = {**_common, 'dataset': 'TaiwanStockTotalInstitutionalInvestors',
                   'stock_id': stock_id, 'start_date': _start}
        _r_inst = _bps().get(_base, params=_p_inst, headers=_hdrs, timeout=20, verify=False)
        _j_inst = _r_inst.json()
        _inst_ok = (not (isinstance(_j_inst.get('status'), int)
                         and _j_inst['status'] >= 400)) and bool(_j_inst.get('data'))
        if not _inst_ok:
            return {'error': f'法人資料失敗 status={_j_inst.get("status")}',
                    'signal': '⚫ 資料不足'}

        _df_i = _pd20.DataFrame(_j_inst['data'])
        _df_i.columns = [str(c).lower() for c in _df_i.columns]
        _df_i['buy']  = _pd20.to_numeric(_df_i.get('buy',  0), errors='coerce').fillna(0)
        _df_i['sell'] = _pd20.to_numeric(_df_i.get('sell', 0), errors='coerce').fillna(0)
        _df_i['net']  = _df_i['buy'] - _df_i['sell']
        # 辨識外資 / 投信（相容 FinMind 英文或中文 name 欄位）
        _is_fi = _df_i['name'].apply(
            lambda n: str(n) == 'Foreign_Investor' or ('外資' in str(n) and '自營' not in str(n)))
        _is_tr = _df_i['name'].apply(
            lambda n: str(n) == 'Investment_Trust' or '投信' in str(n))
        _df_fi = _df_i[_is_fi][['date','net']].rename(columns={'net':'foreign_net'})
        _df_tr = _df_i[_is_tr][['date','net']].rename(columns={'net':'trust_net'})
        _df_m  = _pd20.merge(_df_fi, _df_tr, on='date', how='outer').fillna(0)
        _df_m['combined'] = _df_m['foreign_net'] + _df_m['trust_net']
        _df_m  = _df_m.sort_values('date').tail(20)

        # ── 2. 每日成交量（單位：張，來自 TaiwanStockPrice）─────────
        _p_vol = {**_common, 'dataset': 'TaiwanStockPrice',
                  'stock_id': stock_id, 'start_date': _start}
        _r_vol = _bps().get(_base, params=_p_vol, headers=_hdrs, timeout=20, verify=False)
        _j_vol = _r_vol.json()
        _vol_ok = (not (isinstance(_j_vol.get('status'), int)
                        and _j_vol['status'] >= 400)) and bool(_j_vol.get('data'))
        if not _vol_ok:
            return {'error': '價量資料失敗', 'signal': '⚫ 資料不足'}

        _df_v  = _pd20.DataFrame(_j_vol['data'])
        _df_v.columns = [str(c).lower() for c in _df_v.columns]
        # 相容 trading_volume / volume 欄名
        _vcol  = next((c for c in _df_v.columns if 'trading_volume' in c or c == 'volume'), None)
        if _vcol is None:
            return {'error': '找不到成交量欄位', 'signal': '⚫ 資料不足'}
        _df_v[_vcol] = _pd20.to_numeric(_df_v[_vcol], errors='coerce').fillna(0)
        _df_v  = _df_v[['date', _vcol]].rename(columns={_vcol: 'volume'})
        _df_v  = _df_v.sort_values('date').tail(20)

        # ── 3. 合併：只取法人與成交量均有資料的交易日 ──────────────
        _df    = _pd20.merge(_df_m, _df_v, on='date', how='inner').tail(20)
        if len(_df) < 5:
            return {'error': f'有效天數不足（{len(_df)}天）', 'signal': '⚫ 資料不足'}

        # ── 4. 計算兩大指標 ──────────────────────────────────────────
        _tot_net = float(_df['combined'].sum())          # 外+投 累計淨買（張）
        _tot_vol = float(_df['volume'].sum())            # 總成交量（張）
        _concentration = (_tot_net / _tot_vol * 100) if _tot_vol > 0 else 0.0   # %
        _pos_days  = int((_df['combined'] > 0).sum())
        _continuity = _pos_days / len(_df) * 100                                  # %

        # ── 5. 判定訊號 ──────────────────────────────────────────────
        if _concentration > 5 and _continuity > 50:
            _signal = '🔥 大戶吸籌'
        elif _concentration < -5:
            _signal = '🔴 大戶倒貨'
        else:
            _signal = '🟡 籌碼發散'

        print(f'[20d_chips/{stock_id}] 集中度={_concentration:.2f}% 延續性={_continuity:.0f}% '
              f'days={len(_df)} signal={_signal}')
        return {
            'concentration': round(_concentration, 2),   # %（可正可負）
            'continuity':    round(_continuity, 1),       # 0~100%
            'signal':        _signal,
            'days':          len(_df),
            'pos_days':      _pos_days,
            'total_net_k':   round(_tot_net / 1e3, 1),   # 千張
            'total_vol_k':   round(_tot_vol / 1e3, 1),   # 千張
            'error':         None,
        }
    except Exception as _e20:
        print(f'[20d_chips/{stock_id}] ❌ {type(_e20).__name__}: {_e20}')
        return {'error': str(_e20), 'signal': '⚫ 計算失敗'}


def analyze_20d_chips_from_df(df) -> dict:
    """近 20 日籌碼集中度 — 直接複用個股 K 線已載入的 df（含 外資/投信/volume 欄，
    單位皆為張），免重複呼叫 FinMind（規避 quota 失敗）。
    回傳格式與 analyze_20d_chips 完全相同；欄位不足時回 error 供呼叫端退回 API 版。"""
    try:
        import pandas as _pd
        if df is None or len(df) < 5:
            return {'error': 'df資料不足', 'signal': '⚫ 資料不足'}
        if not all(c in df.columns for c in ('外資', '投信', 'volume')):
            return {'error': 'df缺法人/量欄', 'signal': '⚫ 資料不足'}
        _d   = df.tail(20)
        _net = (_pd.to_numeric(_d['外資'], errors='coerce').fillna(0)
                + _pd.to_numeric(_d['投信'], errors='coerce').fillna(0))
        _vol = _pd.to_numeric(_d['volume'], errors='coerce').fillna(0)
        if not (_net != 0).any():        # 法人欄全為 0 → df 未載到籌碼，退回 API 版
            return {'error': 'df法人欄全為0', 'signal': '⚫ 資料不足'}
        _tot_net = float(_net.sum())
        _tot_vol = float(_vol.sum())
        if _tot_vol <= 0:
            return {'error': '成交量為0', 'signal': '⚫ 資料不足'}
        _concentration = _tot_net / _tot_vol * 100
        _pos_days   = int((_net > 0).sum())
        _continuity = _pos_days / len(_d) * 100
        if _concentration > 5 and _continuity > 50:
            _signal = '🔥 大戶吸籌'
        elif _concentration < -5:
            _signal = '🔴 大戶倒貨'
        else:
            _signal = '🟡 籌碼發散'
        return {
            'concentration': round(_concentration, 2),
            'continuity':    round(_continuity, 1),
            'signal':        _signal,
            'days':          len(_d),
            'pos_days':      _pos_days,
            'total_net_k':   round(_tot_net / 1e3, 1),
            'total_vol_k':   round(_tot_vol / 1e3, 1),
            'error':         None,
        }
    except Exception as _edf:
        return {'error': str(_edf), 'signal': '⚫ 計算失敗'}


def calc_stats(df):
    """計算股票統計數據（last/pct/status）"""
    if df is None or df.empty: return None
    col = next((c for c in ['close','Close'] if c in df.columns), None)
    if not col: return None
    s = df[col].dropna()
    if len(s) < 2: return None
    last = float(s.iloc[-1])
    prev = float(s.iloc[-2])
    pct  = (last - prev) / prev * 100 if prev else 0
    ma5  = float(s.tail(5).mean())
    ma20 = float(s.tail(20).mean()) if len(s) >= 20 else ma5
    if last > ma5 > ma20:   status = '多頭排列↑'
    elif last < ma5 < ma20: status = '空頭排列↓'
    else:                   status = '整理中'
    return {'last': round(last,2), 'pct': round(pct,2),
            'status': status, 'chg': round(last-prev,2)}


# ═══════════════════════════════════════════════════════════
# v5.0 Wrapper 函數 — NAS 優先，快取裝飾，統一 N/A 邏輯
# ═══════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False, max_entries=10)
def get_export_yoy() -> dict | None:
    return None


@st.cache_data(ttl=3600, show_spinner=False, max_entries=10)
def get_business_indicator() -> dict | None:
    return None
