import streamlit as st
import pandas as pd
import datetime
import os
import re
import time
import requests
import json
import pickle
import hashlib
import sys

# ── Streamlit Cloud 防護（PR #82/#86 升級版）────────────────
# tab_*.py 用 `from app import X`，Python 走 sys.modules['app'] 找模組。
# Cloud 上 sys.modules['__main__'] 是 Streamlit CLI binary 不是 script，
# 所以 PR #82 的 `setdefault('app', sys.modules[__name__])` 指錯模組。
# PR #86 用 ModuleType proxy + closure，但 closure 經 method.__globals__
# 解析 `_app_globals` 名稱對 Streamlit rerun 行為有依賴。
# 改為把 globals dict 塞 proxy.__dict__，每次都 refresh，徹底解耦。
import types as _types  # noqa: E402

class _AppProxy(_types.ModuleType):
    """Proxy：`from app import X` → 從 proxy 自己 dict 拿 live globals。"""
    def __getattr__(self, name):
        g = self.__dict__.get('__app_globals__')
        if g is None:
            raise AttributeError(f"module 'app' proxy uninitialized; missing {name!r}")
        try:
            return g[name]
        except KeyError:
            raise AttributeError(
                f"module 'app' has no attribute {name!r} "
                f"(globals has {len(g)} keys)"
            ) from None

_existing = sys.modules.get('app')
if isinstance(_existing, _AppProxy):
    _existing.__dict__['__app_globals__'] = globals()
else:
    _proxy = _AppProxy('app')
    _proxy.__dict__['__app_globals__'] = globals()
    sys.modules['app'] = _proxy

# ── 台灣時間（UTC+8）─────────────────────────────────────
_TW_TZ = datetime.timezone(datetime.timedelta(hours=8))
def _tw_now(): return datetime.datetime.now(_TW_TZ)
def _tw_now_str(): return _tw_now().strftime('%Y-%m-%d %H:%M')

def _bps():
    try:
        from tw_stock_data_fetcher import build_proxy_session as _b
        s = _b()
    except Exception:
        s = requests.Session()
    s.verify = False
    return s
import yfinance as yf  # noqa: E402

print('[INFO] main.py v3.0 戰情室 載入完成')

from data_loader import StockDataLoader, _LOADER_VERSION  # noqa: E402
# ── 新增模組（根據說明書 v1.0）──────────────────────────────
# ── v3.0 新增模組（§5-§11）──────────────────────────────────
from etf_dashboard import (  # noqa: E402
    render_etf_single, render_etf_portfolio,
    render_etf_backtest, render_etf_ai,
    render_sector_heatmap,
)
from health_inspector import render_data_health_raw  # noqa: E402
from api_diagnostic import render_api_diagnostic  # noqa: E402
from grape_ladder import render_grape_ladder  # noqa: E402
from persona import TAIWAN_ADVISOR_PERSONA as _PERSONA  # noqa: E402

api_key       = st.secrets.get('GEMINI_API_KEY', os.environ.get('GEMINI_API_KEY', ''))  # [Fixed] st.secrets 優先
FINMIND_TOKEN = st.secrets.get('FINMIND_TOKEN',  os.environ.get('FINMIND_TOKEN', ''))   # [Fixed] st.secrets 優先

# [Fixed] 同步到 os.environ，讓子模組頂層讀取能拿到正確值
if FINMIND_TOKEN:
    os.environ['FINMIND_TOKEN'] = FINMIND_TOKEN
if api_key:
    os.environ['GEMINI_API_KEY'] = api_key

def _get_fm_token():
    """每次動態讀取最新 Token：st.secrets > os.environ"""
    _tok = (getattr(st, 'secrets', {}).get('FINMIND_TOKEN')
            or os.environ.get('FINMIND_TOKEN', ''))
    return _tok

st.set_page_config(page_title='台股AI戰情室 v3.0', layout='wide',
                   page_icon='📊', initial_sidebar_state='collapsed')

# ── OAuth callback：URL 帶 ?code= 時自動換 token（必須早於其他 query_params 操作）
try:
    from oauth_state import handle_oauth_callback as _oauth_cb
    _oauth_cb()
except Exception as _oauth_err:
    print(f'[oauth callback] {_oauth_err}')

# ── App 初始化閘門（每個 Session 僅執行一次，防重複迴圈）────────────
if '_app_boot_done' not in st.session_state:
    st.session_state['_app_boot_done'] = True
    # 首次啟動清除舊快取，後續 rerun 不再執行（防 API Storm）
    try:
        st.cache_data.clear()
    except Exception:
        pass
    # [Phase 3] 從 URL query_params 恢復關鍵狀態（手機斷線重連可保留設定）
    try:
        _qp = st.query_params
        if _qp.get('chips') == '1':
            st.session_state['chips_loaded'] = True
        _qp_sid = _qp.get('sid')
        if _qp_sid and isinstance(_qp_sid, str) and _qp_sid.isdigit():
            st.session_state['_qp_sid'] = _qp_sid  # 個股 Tab 啟動時讀取
    except Exception as _qpe:
        print(f'[query_params restore] {_qpe}')

# [Phase 3] 雙向同步：session_state → query_params（讓重連後 URL 仍帶狀態）
try:
    _qp_w = st.query_params
    if st.session_state.get('chips_loaded') and _qp_w.get('chips') != '1':
        _qp_w['chips'] = '1'
    elif not st.session_state.get('chips_loaded') and _qp_w.get('chips') == '1':
        del _qp_w['chips']
except Exception:
    pass

st.markdown("""<style>
.main{background:#0e1117;}
[data-testid="stSidebar"]{background:#161b22;}
.stTabs [data-baseweb="tab-list"]{gap:2px;}
.stTabs [data-baseweb="tab"]{background:#161b22;color:#8b949e;border-radius:6px 6px 0 0;padding:8px 16px;font-size:13px;}
.stTabs [aria-selected="true"]{background:linear-gradient(135deg,#1f6feb,#0d4faa);color:#fff;font-weight:700;}
.teacher-card{background:#0d1117;border-left:3px solid #ffd700;border-radius:0 8px 8px 0;padding:10px 14px;margin:6px 0;}
.health-A{background:linear-gradient(90deg,#0d2818,#0d1117);border:2px solid #3fb950;border-radius:12px;padding:16px;text-align:center;}
.health-B{background:linear-gradient(90deg,#2a1f00,#0d1117);border:2px solid #d29922;border-radius:12px;padding:16px;text-align:center;}
.health-C{background:linear-gradient(90deg,#2a0d0d,#0d1117);border:2px solid #f85149;border-radius:12px;padding:16px;text-align:center;}
</style>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════
def parse_stocks(raw):
    stocks = re.split(r'[,\s\n；，]+', raw.strip())
    return [s.strip() for s in stocks if s.strip() and re.match(r'^\d{4,6}[A-Z]?$', s.strip())]

# ── Gemini 金鑰池（做法 B：多帳號 key 自動換手，分散額度 / 速率限制）──────
# 讀 GEMINI_API_KEY + GEMINI_API_KEY_2 .. _6（st.secrets 優先，os.environ fallback）。
# gemini_call 以 round-robin 起手 key（不同呼叫/不同 tab 從不同把 key 開始 → 分散負載），
# 任一把遇到 429（速率/額度滿）或 403（無效）時自動換下一把，全部用盡才報錯。
_GEMINI_KEY_NAMES = ['GEMINI_API_KEY'] + [f'GEMINI_API_KEY_{_i}' for _i in range(2, 7)]
_gemini_rr = [0]  # round-robin 起手索引（每次呼叫遞增）


def _gemini_keys() -> list:
    """收集所有可用 Gemini API key（去重保序）。st.secrets 優先，os.environ fallback。"""
    _keys = []
    for _n in _GEMINI_KEY_NAMES:
        try:
            _v = st.secrets.get(_n, '') or os.environ.get(_n, '')
        except Exception:
            _v = os.environ.get(_n, '')
        _v = str(_v or '').strip()
        if _v and _v not in _keys:
            _keys.append(_v)
    if api_key and api_key not in _keys:
        _keys.append(api_key)
    return _keys


def gemini_call(prompt, max_tokens=2048):
    _keys = _gemini_keys()
    if not _keys:
        return '⚠️ 請設定 GEMINI_API_KEY（可另加 GEMINI_API_KEY_2 ~ _6 分散額度）'
    # round-robin 起手：不同呼叫從不同把 key 開始，自然把負載分散到各帳號
    _start = _gemini_rr[0] % len(_keys)
    _gemini_rr[0] = (_gemini_rr[0] + 1) % 1_000_000
    _keys = _keys[_start:] + _keys[:_start]
    # 2026-03 有效模型：1.5系列全部退役，2.5為主力
    _models = ['gemini-2.5-flash-lite', 'gemini-2.5-flash',
               'gemini-2.0-flash', 'gemini-2.0-flash-lite']
    for _model in _models:
        # Gemini 2.5 預設開「思考模式」，思考 token 會跟輸出共用 maxOutputTokens 額度
        # → 常導致回覆只生成一半就被截斷。白話摘要不需深度推理，關閉思考（thinkingBudget=0）。
        _gen_cfg = {'temperature': 0.3, 'maxOutputTokens': max_tokens}
        if _model.startswith('gemini-2.5'):
            _gen_cfg['thinkingConfig'] = {'thinkingBudget': 0}
        for _ki, _key in enumerate(_keys):
            try:
                _r = requests.post(
                    f'https://generativelanguage.googleapis.com/v1beta/models/{_model}:generateContent',
                    params={'key': _key},
                    json={'systemInstruction': {'parts': [{'text': _PERSONA}]},
                          'contents': [{'parts': [{'text': prompt}]}],
                          'generationConfig': _gen_cfg},
                    timeout=120
                )
                if _r.status_code == 200:
                    _d = _r.json()
                    _cands = _d.get('candidates', [])
                    if _cands:
                        _parts = _cands[0].get('content', {}).get('parts', [])
                        if _parts and _parts[0].get('text'):
                            return _parts[0]['text']
                    # safety 攔截：換 key 無助益 → 直接換下一個 model
                    if _cands and _cands[0].get('finishReason', '') == 'SAFETY':
                        break
                    continue  # 空回覆 → 試下一把 key
                elif _r.status_code == 400:
                    _err_msg = (_r.json() if _r.text else {}).get('error', {}).get('message', _r.text[:100])
                    print(f'[Gemini/{_model}] 400 Bad Request: {_err_msg}')
                    break  # 設定/prompt 問題，換 key 無用 → 換下一個 model
                elif _r.status_code == 403:
                    print(f'[Gemini/{_model}] 403 第 {_ki+1} 把 key 無效/無權限 → 換下一把')
                    continue  # 換 key
                elif _r.status_code == 404:
                    break  # 此 model 不存在 → 換下一個 model
                elif _r.status_code == 429:
                    print(f'[Gemini/{_model}] 429 第 {_ki+1} 把 key 額度/速率滿 → 換下一把')
                    continue  # 換 key（做法 B 核心：分散到別把帳號）
                else:
                    print(f'[Gemini/{_model}] HTTP {_r.status_code}: {_r.text[:200]}')
                    continue  # 換 key
            except Exception as _ge:
                print(f'[Gemini/{_model}] key#{_ki+1} {type(_ge).__name__}: {_ge}')
                continue  # 換 key
    return ('⚠️ AI 服務暫時無法使用（所有 key 與模型都試過了）—— '
            '請確認各把金鑰額度，或稍後再試')

# ── 本地快取（SQLite + Pickle 雙軌）───────────────────────
_CACHE_DIR = '/tmp/stock_cache'
os.makedirs(_CACHE_DIR, exist_ok=True)

def _cache_key(prefix, sid, extra=''):
    raw = f'{prefix}_{sid}_{extra}_{datetime.date.today()}'
    return os.path.join(_CACHE_DIR, hashlib.md5(raw.encode()).hexdigest() + '.pkl')

def _load_cache(prefix, sid, extra='', ttl_hours=6):
    path = _cache_key(prefix, sid, extra)
    if os.path.exists(path):
        age = (time.time() - os.path.getmtime(path)) / 3600
        if age < ttl_hours:
            try:
                with open(path,'rb') as f:
                    return pickle.load(f)
            except Exception:
                pass
    return None

def _save_cache(prefix, sid, data, extra=''):
    path = _cache_key(prefix, sid, extra)
    try:
        with open(path,'wb') as f:
            pickle.dump(data, f)
    except Exception:
        pass

@st.cache_resource
def _get_loader(_v: str = _LOADER_VERSION):
    """快取單一 StockDataLoader 實例，避免每次 cache miss 都重新 login。

    `_v` 綁定 `data_loader._LOADER_VERSION`：改動 loader 邏輯並 bump 版本後，
    cache key 隨之改變 → 自動建立新實例，避免 Streamlit hot-reload 後仍用到
    舊實例的舊方法碼（stale @st.cache_resource，PR #44 NoneType 殘留即此故）。
    """
    return StockDataLoader()

def _expected_latest_trading_date():
    d = datetime.date.today()
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d

@st.cache_data(ttl=1800, max_entries=10)
def fetch_price_data(sid, days):
    _c = _load_cache('price', sid, str(days), ttl_hours=0.5)
    if _c is not None:
        df_c, name_c = _c
        if df_c is not None and not df_c.empty and float(df_c['close'].max()) > 0:
            try:
                _latest = df_c['date'].iloc[-1]
                if hasattr(_latest, 'date'):
                    _latest = _latest.date()
                elif isinstance(_latest, str):
                    _latest = datetime.datetime.strptime(str(_latest)[:10], '%Y-%m-%d').date()
                # 5 個 calendar day 內視為新鮮（涵蓋週末 + 1 個連假）；超過 → 強制重抓
                if (_expected_latest_trading_date() - _latest).days <= 5:
                    return df_c, name_c, None
            except Exception:
                return df_c, name_c, None
    loader = _get_loader()
    df, err, name = loader.get_combined_data(sid, days + 60, True)
    if err or df is None:
        return None, None, err
    result = df.tail(days).reset_index(drop=True)
    _save_cache('price', sid, (result, name), str(days))
    return result, name, None

@st.cache_data(ttl=1800, max_entries=10)
def fetch_dividend_data(sid):
    avg_div, yearly, source = 0.0, [], ''
    try:
        try:
            from FinMind.data import DataLoader as FM
        except ImportError:
            from finmind.data import DataLoader as FM
        dl = FM()
        _fm_tok_div = _get_fm_token()
        if _fm_tok_div:
            try:
                dl.login_by_token(api_token=_fm_tok_div)
            except Exception:
                pass
        end = datetime.date.today()
        # First try REST API with proper auth
        _div_resp = _bps().get('https://api.finmindtrade.com/api/v4/data',
            params={'dataset':'TaiwanStockDividend','data_id':sid,
                    'start_date':(end-datetime.timedelta(days=365*6)).strftime('%Y-%m-%d')},
            headers={'Authorization':f'Bearer {_get_fm_token()}'},timeout=20)
        _div_jd = _div_resp.json()
        print(f'[股利REST] {sid} status={_div_jd.get("status")}')
        ddf = pd.DataFrame(_div_jd['data']) if _div_jd.get('status')==200 and _div_jd.get('data') else None
        if ddf is None or ddf.empty:
            ddf = dl.taiwan_stock_dividend(stock_id=sid,
                                           start_date=(end-datetime.timedelta(days=365*6)).strftime('%Y-%m-%d'))
        if ddf is not None and not ddf.empty:
            cash_col = next((c for c in ['CashDividend','cash_dividend','StockEarningsDistribution']
                             if c in ddf.columns), None)
            if cash_col is None:
                nums = ddf.select_dtypes(include='number').columns.tolist()
                if nums:
                    cash_col = nums[0]
            if cash_col:
                ddf['date'] = pd.to_datetime(ddf['date'], errors='coerce')
                ddf['year'] = ddf['date'].dt.year
                ddf['cash'] = pd.to_numeric(ddf[cash_col], errors='coerce').fillna(0)
                yr = ddf.groupby('year')['cash'].sum().reset_index().tail(5)
                avg_div = float(yr['cash'].mean()) if len(yr) > 0 else 0
                yearly = yr.to_dict('records')
                source = 'FinMind'
    except Exception:
        pass
    # ── 備援2: yfinance ──
    if avg_div == 0:
        try:
            import os as _os_div
            try:
                from tw_stock_data_fetcher import _load_proxy_config as _lpc_div
                _px_div = ((_lpc_div() or {}).get('https') or (_lpc_div() or {}).get('http') or None)
            except Exception:
                _px_div = None
            _ek_div = ('HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy')
            _bak_div = {k: _os_div.environ.get(k) for k in _ek_div}
            if _px_div:
                for k in _ek_div:
                    _os_div.environ[k] = _px_div
            try:
                tk = yf.Ticker(f'{sid}.TW')
                divs = tk.dividends
            finally:
                for k, v in _bak_div.items():
                    if v is None:
                        _os_div.environ.pop(k, None)
                    else:
                        _os_div.environ[k] = v
            if divs is not None and len(divs) > 0:
                divs.index = pd.DatetimeIndex(divs.index).tz_localize(None)
                rec = divs[divs.index >= pd.Timestamp.now()-pd.DateOffset(years=5)]
                if len(rec) > 0:
                    ann = rec.resample('YE').sum().reset_index()
                    ann.columns = ['date','cash']
                    ann['year'] = pd.to_datetime(ann['date']).dt.year
                    yr = ann[['year','cash']].tail(5)
                    avg_div = float(yr['cash'].mean())
                    yearly = yr.to_dict('records')
                    source = 'yfinance'
        except Exception:
            pass

    # ── 備援3: TWSE 除權息資料（官方，免Token）──
    if avg_div == 0:
        try:
            _tw_div_url = 'https://www.twse.com.tw/rwd/zh/exRight/TWT49U'
            _start_dt_div = (datetime.date.today()-datetime.timedelta(days=365*6)).strftime('%Y%m%d')
            _end_dt_div   = datetime.date.today().strftime('%Y%m%d')
            _tw_div_r = _bps().get(
                _tw_div_url,
                params={'response': 'json', 'strDate': _start_dt_div,
                        'endDate': _end_dt_div, 'stockNo': sid},
                headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                         'Referer':'https://www.twse.com.tw/',
                         'Accept':'application/json, text/javascript, */*; q=0.01',
                         'Accept-Language':'zh-TW,zh;q=0.9,en;q=0.8',
                         'X-Requested-With':'XMLHttpRequest'},
                timeout=15)
            _tw_div_j = _tw_div_r.json()
            if _tw_div_j.get('stat') == 'OK' and _tw_div_j.get('data'):
                _tw_div_rows = []
                for _dr in _tw_div_j['data']:
                    # 欄位：[日期, 股票代號, 名稱, 除權息前收盤, 開始交易基準價, 現金股利, 股票股利, ...]
                    try:
                        _yr_div = int(str(_dr[0]).split('/')[0])
                        if _yr_div < 1000:
                            _yr_div += 1911
                        _cash_d = float(str(_dr[5]).replace(',','')) if len(_dr) > 5 else 0
                        if _cash_d > 0:
                            _tw_div_rows.append({'year': _yr_div, 'cash': _cash_d})
                    except Exception:
                        pass
                if _tw_div_rows:
                    _tw_div_df = pd.DataFrame(_tw_div_rows)
                    yr = _tw_div_df.groupby('year')['cash'].sum().reset_index().tail(5)
                    avg_div = float(yr['cash'].mean())
                    yearly = yr.to_dict('records')
                    source = 'TWSE'
        except Exception as _eTD:
            pass

    return avg_div, yearly, source

@st.cache_data(ttl=3600, max_entries=10)
def fetch_financials(sid, industry: str = ""):
    """
    合約負債 + 固定資產 + 資本支出 — v3.35 簡化版
    100% FinMind（免費版已確認 status=200）
    type 欄位為主鍵，比 origin_name 更可靠。
    """
    import datetime as _dtf
    try:
        from tw_stock_data_fetcher import build_proxy_session as _bps_fin
        _rq_f = _bps_fin()
    except Exception:
        import requests as _rq_f_fallback
        _rq_f = _rq_f_fallback.Session()
    _rq_f.verify = False

    cl = cx = _capex = None
    cl_src = cx_src = cx_src_capex = ""
    fetch_errors = []
    _tok = _get_fm_token()
    _start = (_dtf.date.today() - _dtf.timedelta(days=365*3)).strftime('%Y-%m-%d')

    # ── Step 1: BalanceSheet → 合約負債 + 固定資產 ──────────────
    try:
        _params = {"dataset":"TaiwanStockBalanceSheet","data_id":sid,"start_date":_start}
        if _tok:
            _params["token"] = _tok
        _hdrs = {"User-Agent":"Mozilla/5.0","Accept":"application/json"}
        if _tok:
            _hdrs["Authorization"] = f"Bearer {_tok}"
        _r = _rq_f.get("https://api.finmindtrade.com/api/v4/data",
                        params=_params, headers=_hdrs, timeout=20)
        _j = _r.json()
        _rows = _j.get("data", [])
        _fm_status = _j.get("status")
        _fm_msg = _j.get("msg","")
        print(f"[FM-BS] {sid} HTTP {_r.status_code} status={_fm_status} rows={len(_rows)}")
        if _fm_status != 200:
            fetch_errors.append(f"FinMind-BS:HTTP{_r.status_code}:{_fm_msg or _fm_status}")
        if _fm_status == 200 and _rows:
            # 取最新一季
            _dates = sorted(set(r.get("date","") for r in _rows), reverse=True)
            _latest_dt = _dates[0] if _dates else None
            _latest = [r for r in _rows if r.get("date") == _latest_dt]
            print(f"[FM-BS] Latest={_latest_dt} rows={len(_latest)}")

            # 合約負債
            _CL_TYPES = ["CurrentContractLiabilities","ContractLiabilities"]
            _CL_NAMES = ["合約負債","契約負債","預收款項"]
            _cl_total = 0.0
            for _row in _latest:
                _t = str(_row.get("type",""))
                if any(_t == _ct or _t.startswith(_ct) for _ct in _CL_TYPES):
                    _v = float(str(_row.get("value",0)).replace(",","") or 0)
                    if _v > 0:
                        _cl_total += _v
            if _cl_total == 0:  # fallback: origin_name
                for _row in _latest:
                    _n = str(_row.get("origin_name",""))
                    if any(_k in _n for _k in _CL_NAMES):
                        _v = float(str(_row.get("value",0)).replace(",","") or 0)
                        if _v > 0:
                            _cl_total += _v
            if _cl_total > 0:
                cl = _cl_total
                cl_src = "FinMind"
                print(f"[FM-BS] ✅ 合約負債={cl/1e8:.2f}億")

            # 固定資產
            _FA_TYPE = "PropertyPlantAndEquipment"
            for _row in _latest:
                _t = str(_row.get("type",""))
                if _t == _FA_TYPE or (_FA_TYPE in _t and "_per" not in _t):
                    _v = float(str(_row.get("value",0)).replace(",","") or 0)
                    if _v > 0:
                        cx = _v
                        cx_src = "FinMind"
                        break
            if cx is None:
                for _row in _latest:
                    _n = str(_row.get("origin_name",""))
                    if any(_k in _n for _k in ["不動產、廠房及設備","固定資產"]):
                        _v = float(str(_row.get("value",0)).replace(",","") or 0)
                        if _v > 0:
                            cx = _v
                            cx_src = "FinMind-name"
                            break
            if cx:
                print(f"[FM-BS] ✅ 固定資產={cx/1e8:.2f}億")
    except Exception as _e_bs:
        err_msg = f"FinMind-BS:{type(_e_bs).__name__}:{_e_bs}"
        fetch_errors.append(err_msg)
        print(f"[FM-BS] ❌ {err_msg}")

    # ── Step 2: CashFlowsStatement → 資本支出 ────────────────────
    try:
        _params2 = {"dataset":"TaiwanStockCashFlowsStatement","data_id":sid,"start_date":_start}
        if _tok:
            _params2["token"] = _tok
        _hdrs2 = {"User-Agent":"Mozilla/5.0","Accept":"application/json"}
        if _tok:
            _hdrs2["Authorization"] = f"Bearer {_tok}"
        _r2 = _rq_f.get("https://api.finmindtrade.com/api/v4/data",
                         params=_params2, headers=_hdrs2, timeout=20)
        _j2 = _r2.json()
        _rows2 = _j2.get("data",[])
        _fm2_status = _j2.get("status")
        _fm2_msg = _j2.get("msg","")
        print(f"[FM-CF] {sid} HTTP {_r2.status_code} status={_fm2_status} rows={len(_rows2)}")
        if _fm2_status != 200:
            fetch_errors.append(f"FinMind-CF:HTTP{_r2.status_code}:{_fm2_msg or _fm2_status}")
        if _fm2_status == 200 and _rows2:
            _dates2 = sorted(set(r.get("date","") for r in _rows2), reverse=True)
            _latest2 = [r for r in _rows2 if r.get("date") == (_dates2[0] if _dates2 else None)]
            _CX_TYPES = ["PropertyAndPlantAndEquipment","AcquisitionOfPropertyPlantAndEquipment"]
            _CX_NAMES = ["取得不動產、廠房及設備","購置不動產、廠房及設備","資本支出"]
            _cx2 = None
            for _row in _latest2:
                _t = str(_row.get("type",""))
                if any(_ct in _t for _ct in _CX_TYPES):
                    _v = float(str(_row.get("value",0)).replace(",","") or 0)
                    if _v != 0:
                        _cx2 = abs(_v)
                        break
            if _cx2 is None:
                for _row in _latest2:
                    _n = str(_row.get("origin_name",""))
                    if any(_k in _n for _k in _CX_NAMES):
                        _v = float(str(_row.get("value",0)).replace(",","") or 0)
                        if _v != 0:
                            _cx2 = abs(_v)
                            break
            if _cx2 and _cx2 > 0:
                _capex = _cx2
                cx_src_capex = "FinMind-CF"
                if cx is None:
                    cx = _capex
                    cx_src = "FinMind-CF"
                print(f"[FM-CF] ✅ 資本支出={_capex/1e8:.2f}億")
    except Exception as _e_cf:
        fetch_errors.append(f"FinMind-CF:{type(_e_cf).__name__}:{_e_cf}")
        print(f"[FM-CF] ❌ {_e_cf}")

    def _fmt(v): return f"{v/1e8:.1f}" if v else "-"
    print(f"[FIN] {sid}: cl={_fmt(cl)}億  cx={_fmt(cx)}億  capex={_fmt(_capex)}億")
    return cl, cx, _capex, cl_src, cx_src, cx_src_capex, fetch_errors


def fetch_revenue(sid):
    try:
        loader = _get_loader()
        result = loader.get_monthly_revenue(sid)
        if result is None:
            return None, '月營收：內部回傳None'
        if isinstance(result, tuple):
            return result
        return result, None  # single value
    except Exception as e:
        print(f"[fetch_revenue] {e}")
        return None, str(e)

@st.cache_data(ttl=3600, max_entries=10)
def fetch_quarterly(sid, _ver=4):   # _ver 改變即清除舊快取
    try:
        loader = _get_loader()
        result = loader.get_quarterly_data(sid)
        if result is None:
            return None, '季財報：內部回傳None'
        if isinstance(result, tuple):
            return result
        return result, None
    except Exception as e:
        print(f"[fetch_quarterly] {e}")
        return None, str(e)

@st.cache_data(ttl=3600, show_spinner=False, max_entries=10)
def fetch_quarterly_extra(sid, _ver=2):   # _ver 改變即清除舊快取
    """取得近 12 季資產負債表 + 現金流量時序（合約負債、存貨、資本支出），用於前瞻動能分數"""
    try:
        loader = _get_loader()
        result = loader.get_quarterly_bs_cf(sid)
        if result is None:
            return None, 'BS/CF：內部回傳None'
        if isinstance(result, tuple):
            return result
        return result, None
    except Exception as e:
        print(f"[fetch_quarterly_extra] {e}")
        return None, str(e)

# ════════════════════════════════════════════════════════════════
# 技術指標計算 — 已抽出至 tech_indicators.py（PR P2-B Phase 1）
# ════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════
# 健康度評分（0~100）— 已抽出至 scoring_helpers.py（PR P2-B Phase 3）
# ════════════════════════════════════════════════════════════════
from scoring_helpers import (  # noqa: E402
    health_grade,
)

# ════════════════════════════════════════════════════════════════
# 初學者友善說明系統 — 已抽出至 ui_widgets.py（PR P2-B Phase 2）
# ════════════════════════════════════════════════════════════════
from ui_widgets import (  # noqa: E402
    traffic_light, show_term_help,
)
# P2-B Phase 5 A/B/C/D: 4 個 TAB 全部已抽到獨立模組（app.py 9208→1394 行，−85%）
from tab_edu import render_tab_edu  # noqa: E402
from tab_stock_grp import render_stock_grp  # noqa: E402
from tab_stock import render_tab_stock  # noqa: E402
from tab_macro import render_tab_macro  # noqa: E402

# 在先行指標 section 使用
_TERM_HELP_LI = show_term_help('PCR') + show_term_help('ADL') + show_term_help('M1B-M2')

# ════════════════════════════════════════════════════════════════
# generate_ai_comment：Rule-based 個股文字建議（無需 AI API）
# 輸入：dict 含財報/技術/籌碼數據
# 輸出：多行建議文字
# ════════════════════════════════════════════════════════════════

# ── 資本支出累計制還原（v4.0 修正）──────────────────────────
def generate_ai_comment(data: dict) -> str:
    """
    決策樹文字建議產生器
    data 鍵值：
      health, rsi, vcp_ok, bias_240, bias_20
      val_label (357評價), trend, cl (合約負債億), cx (資本支出億)
      foreign_buy, trust_buy (三大法人, 億), score (多因子總分)
      m1b_diff (M1B-M2 差距%)
    """
    lines = []
    score  = data.get('score', 0)
    rsi    = data.get('rsi') or 50
    val    = str(data.get('val_label', ''))
    trend  = str(data.get('trend', ''))
    cl     = data.get('cl') or 0
    cx     = data.get('cx') or 0
    fb     = data.get('foreign_buy') or 0   # 外資買賣億
    tb     = data.get('trust_buy') or 0     # 投信
    vcp_ok = data.get('vcp_ok', False)
    b240   = data.get('bias_240') or 0
    b20    = data.get('bias_20') or 0
    m1b    = data.get('m1b_diff') or 0      # M1B-M2 差距

    # ── 景氣環境前綴 ──────────────────────────────────────────
    if m1b < 0:
        lines.append('🌐 【景氣環境】M1B-M2為負，目前處於資金縮減期。'
                     '建議維持低持股（30%以下），優先選擇低位階、高股利標的。')
    elif m1b > 2:
        lines.append('🌐 【景氣環境】M1B-M2為正且強勁，資金行情啟動中，可積極持股。')

    # ── 財報評估 ─────────────────────────────────────────────
    fin_msg = []
    # 合約負債包含「流動」+「非流動」，別名有「預收款項」
    if cl > 0:
        fin_msg.append(f'合約負債{cl:.1f}億（流動+非流動合計；含預收款項）')
    if cx > 0:
        fin_msg.append(f'資本支出{cx:.1f}億（大規模擴廠，2-3年後營收爆發可期）')
    if fin_msg:
        lines.append('📊 【財報訊號】' + '；'.join(fin_msg) + '。')

    # ── 強烈買入條件（≥85分）────────────────────────────────
    if score >= 85 and '便宜' in val and '多頭' in trend:
        lines.append('🚀 【強烈買入】評分≥85 + 357便宜價 + 多頭排列。'
                     '建議突破60日箱頂時分批進場，回測紅K低點不破可加碼。')
    elif score >= 75 and '便宜' in val:
        lines.append('✅ 【積極買入】評分≥75且位於357便宜區，可分批布局。')
    elif score >= 75:
        lines.append('✅ 【評分優良】多因子評分≥75，技術面健康，可考慮建立底倉。')

    # ── 籌碼評估 ─────────────────────────────────────────────
    if fb > 5 and tb > 0:
        lines.append(f'💰 【籌碼共振】外資+{fb:.1f}億 & 投信+{tb:.1f}億，主力共同買進，訊號強烈。')
    elif fb > 5:
        lines.append(f'💰 【外資買進】外資+{fb:.1f}億，跟著大戶走（宏爺策略）。')
    elif fb < -10:
        lines.append(f'⚠️ 【外資賣超】外資-{abs(fb):.1f}億，籌碼面轉弱，建議等待。')

    # ── VCP 進場訊號 ─────────────────────────────────────────
    if vcp_ok:
        lines.append('🎯 【VCP籌碼安定】波幅持續收縮，籌碼集中於強手。'
                     '建議帶量突破高點時以30~50%建立底倉（策略3）。')

    # ── 技術面評估 ───────────────────────────────────────────
    if rsi < 30:
        lines.append(f'📉 RSI={rsi:.0f}（超賣區），短線反彈機率高，可小量試單。')
    elif rsi > 75:
        lines.append(f'📈 RSI={rsi:.0f}（超買區），注意短線回調風險，不宜追高。')

    # ── 乖離率評估 ───────────────────────────────────────────
    if b240 > 25:
        lines.append(f'🔴 【過熱警告】年線正乖離{b240:.0f}%（>25%），策略1：開始分批減碼。'
                     '建議回收本金，剩餘部位守10週線（≈50MA）。')
    elif b240 < -20:
        lines.append(f'✅ 【低估機會】年線負乖離{abs(b240):.0f}%（<-20%），'
                     '策略1：左側布局最佳時機，分批進場（2008/2020模式）。')

    # ── 分批減碼條件 ─────────────────────────────────────────
    if b240 > 25 and b20 > 10:
        lines.append('🟠 【分批減碼】年線乖離>25% + 月線乖離>10%雙重過熱，'
                     '建議先減50%部位，剩餘守5MA停利。')

    # ── 絕對停損觸發 ─────────────────────────────────────────
    if score < 60 and '空頭' in trend:
        lines.append('🛑 【絕對停損警示】多因子評分<60 + 空頭排列，理由消失即出場。'
                     '出清後觀望，等待評分重返60以上再考慮回補。')

    # ── 357估值提示 ─────────────────────────────────────────
    if '便宜' in val:
        lines.append('💎 【357估值】位於7%殖利率線以下（便宜區），策略1認定的必買送分題。')
    elif '昂貴' in val or '超貴' in val:
        lines.append('⚠️ 【357估值】位於3%殖利率線以上（昂貴區），不宜追高，等待回調。')

    if not lines:
        lines.append('⚪ 目前無明顯買賣訊號，建議繼續觀察。')

    return '\n'.join(f'• {_ln}' for _ln in lines)

# ── kpi / teacher_conclusion / signal_box 已抽至 ui_widgets.py ──

# ════════════════════════════════════════════════════════════════
# 健康度分數顯示元件
# ════════════════════════════════════════════════════════════════
def render_health_score(score, details, sid='', fund_scores=None, tech_alerts=None):
    """個股健診 v2：SVG量表 + 四維評分 + 技術警示 + 因子條形圖"""
    grade, color, css_class, emoji = health_grade(score)
    import math as _mh

    # ① SVG 半圓量表
    angle = (-180 + score * 1.8) * _mh.pi / 180
    cx, cy, r = 100, 90, 70
    nx = cx + r * _mh.cos(angle)
    ny = cy + r * _mh.sin(angle)
    gauge = (
        '<div style="text-align:center;padding:4px 0;">'
        '<svg viewBox="0 0 200 110" style="width:175px;height:92px;">'
        '<path d="M20,90 A80,80 0 0,1 60,22" stroke="#4c1d95" stroke-width="14" fill="none" stroke-linecap="round"/>'
        '<path d="M60,22 A80,80 0 0,1 100,10" stroke="#1e3a5f" stroke-width="14" fill="none" stroke-linecap="round"/>'
        '<path d="M100,10 A80,80 0 0,1 140,22" stroke="#1a4a1a" stroke-width="14" fill="none" stroke-linecap="round"/>'
        '<path d="M140,22 A80,80 0 0,1 180,90" stroke="#3d2000" stroke-width="14" fill="none" stroke-linecap="round"/>'
        f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>'
        f'<circle cx="{cx}" cy="{cy}" r="5" fill="{color}"/>'
        '<text x="14" y="103" fill="#8b949e" font-size="8">注意</text>'
        '<text x="48" y="18" fill="#8b949e" font-size="8">較差</text>'
        '<text x="88" y="8" fill="#8b949e" font-size="8">普通</text>'
        '<text x="127" y="18" fill="#8b949e" font-size="8">良好</text>'
        f'<text x="100" y="82" text-anchor="middle" fill="{color}" font-size="26" font-weight="900">{score}</text>'
        f'<text x="100" y="97" text-anchor="middle" fill="{color}" font-size="10">{grade}</text>'
        '</svg></div>'
    )

    # ② 四維評分
    fund_html = ''
    if fund_scores:
        _cat_ic = {'profit':'💰','growth':'📈','dividend':'🎁','valuation':'⚖️'}
        _sc_cl  = {0:'#8b949e',1:'#d29922',2:'#3fb950',3:'#2ea043'}
        fund_html = '<div style="display:flex;gap:4px;margin:10px 0;">'
        for cat in ['profit','growth','dividend','valuation']:
            fs  = fund_scores.get(cat,{})
            sc  = fs.get('score',0)
            lb  = fs.get('label',cat)
            ic=_cat_ic.get(cat,'')
            cl  = _sc_cl.get(min(sc,3),'#8b949e')
            chk = ''
            for cn,cv,cp in fs.get('checks',[])[:3]:
                cc = '#3fb950' if cp else '#f85149'
                chk += f'<div style="font-size:9px;color:{cc};margin-top:1px;">{"✓" if cp else "✗"} {cn}</div>'
            fund_html += (
                f'<div style="flex:1;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:7px 4px;text-align:center;">'
                f'<div style="font-size:20px;font-weight:900;color:{cl};">{sc}</div>'
                f'<div style="font-size:9px;color:#8b949e;">{ic} {lb}</div>'
                f'{chk}</div>'
            )
        fund_html += '</div>'

    # ③ 技術警示
    tech_html = ''
    if tech_alerts:
        _pc = {'🔴':'#f85149','🟡':'#d29922','🟢':'#3fb950'}
        tech_html = '<div style="margin:8px 0;"><div style="font-size:11px;color:#8b949e;margin-bottom:4px;">⚡ 技術警示</div>'
        for pri,name,sig,desc in tech_alerts[:5]:
            bc = _pc.get(pri,'#484f58')
            sc2 = '#f85149' if any(k in sig for k in ['看跌','空頭','超賣']) else ('#3fb950' if any(k in sig for k in ['看漲','多頭']) else '#d29922')
            tech_html += (
                f'<div style="display:flex;align-items:center;gap:6px;margin:3px 0;background:#0d1117;border-left:3px solid {bc};padding:4px 8px;border-radius:0 4px 4px 0;">'
                f'<span style="font-size:10px;">{pri}</span>'
                f'<div style="flex:1;">'
                f'<span style="font-size:11px;font-weight:700;color:#c9d1d9;">{name}</span>'
                f'<span style="font-size:9px;background:{sc2}33;color:{sc2};padding:1px 4px;border-radius:3px;margin-left:5px;">{sig}</span>'
                f'<div style="font-size:9px;color:#8b949e;">{desc}</div>'
                f'</div></div>'
            )
        tech_html += '</div>'

    # ④ 因子條形圖
    breakdown = '<div style="margin-top:8px;">'
    for factor, (desc, got, total) in details.items():
        pct = got / total * 100
        bc  = '#3fb950' if pct>=70 else ('#d29922' if pct>=40 else '#f85149')
        breakdown += (
            f'<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">'
            f'<div style="width:45px;font-size:10px;color:#8b949e;text-align:right;">{factor}</div>'
            f'<div style="flex:1;background:#21262d;border-radius:4px;height:7px;">'
            f'<div style="width:{pct:.0f}%;background:{bc};border-radius:4px;height:7px;"></div></div>'
            f'<div style="width:85px;font-size:9px;color:{bc};">{got}/{total} {desc[:8]}</div>'
            f'</div>'
        )
    breakdown += '</div>'
    return gauge + fund_html + tech_html + breakdown


primary_stock = '2330'

# ── Sidebar: 整合 AI 分析 ───────────────────────────────────────
with st.sidebar:
    st.markdown('<div style="text-align:center;padding:8px 0;font-size:15px;font-weight:900;color:#e6edf3;">&#128202; 台股AI戰情室 v3.0</div>', unsafe_allow_html=True)
    st.markdown('---')
    _today_sb = datetime.date.today()
    _wd_sb = {0:'一',1:'二',2:'三',3:'四',4:'五',5:'六',6:'日'}[_today_sb.weekday()]
    _trade_sb = '✅ 交易日' if _today_sb.weekday() < 5 else '❌ 非交易日'
    st.caption(f'{_today_sb.strftime("%Y/%m/%d")} 週{_wd_sb}  {_trade_sb}')
    st.markdown('---')
    st.markdown('### 🤖 AI 分析')
    st.caption('頁面底部有 AI 整合報告面板')
    ai_run = False  # AI button moved to bottom panel
    st.markdown('---')
    st.success('🟢 系統正常運作中')

    # ── Google 帳號（OAuth）— ETF 組合雲端存取用 ─────────────────
    st.markdown('---')
    st.markdown('### 🔐 Google 帳號')
    try:
        from oauth_state import (
            get_oauth_cfg as _sb_get_cfg,
            _gsa_secret as _sb_gsa,
            _sheet_id_secret as _sb_sid,
        )
        from infra.oauth import build_authorize_url as _sb_buildurl
        # 每次 rerun 動態解析，避免 module-level cache 過期
        _sb_cfg = _sb_get_cfg()
        _sb_oc = _sb_cfg is not None
    except Exception:
        _sb_oc, _sb_cfg, _sb_gsa, _sb_sid, _sb_buildurl = False, None, None, '', None
    _sb_logged = bool(st.session_state.get('gsheet_tokens'))
    if _sb_oc:
        if _sb_logged:
            st.success('🟢 已登入')
            if st.button('🚪 登出', key='btn_oauth_logout_sb',
                          use_container_width=True):
                st.session_state.pop('gsheet_tokens', None)
                st.rerun()
            # ── Google Sheet ID（集中於帳號區；ETF 組合面板可從 Drive 挑選/新建）──
            _sb_sid_cur = str(st.session_state.get('portfolio_sheet_id', '') or '').strip()
            _sb_sid_raw = st.text_input(
                'Google Sheet ID 或完整 URL（系統會自動解析 ID）',
                value=_sb_sid_cur, key='sb_portfolio_sheet_id_input',
                placeholder='貼上 https://docs.google.com/spreadsheets/d/...',
                help='貼 URL/ID 設定投組資料庫；或到「ETF 組合」Tab 從 Drive 挑選 / 一鍵新建')
            _sb_m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', _sb_sid_raw)
            _sb_sid_new = _sb_m.group(1) if _sb_m else _sb_sid_raw.strip()
            if _sb_sid_new and _sb_sid_new != _sb_sid_cur:
                st.session_state['portfolio_sheet_id'] = _sb_sid_new
            if _sb_sid_new:
                st.caption(f'✅ Sheet ID：`{_sb_sid_new}`')
            else:
                st.caption('💡 未設定 — 貼上 URL/ID 或到「ETF 組合」Tab 挑選')
        elif _sb_buildurl and _sb_cfg:
            _sb_url = _sb_buildurl(_sb_cfg['client_id'], _sb_cfg['redirect_uri'])
            st.link_button('🔐 用 Google 登入', _sb_url, use_container_width=True)
            st.caption('登入後 ETF 組合 Tab 可雲端存取')
    elif _sb_gsa and _sb_sid:
        st.caption('ℹ️ 使用 Service Account（舊版部署）')
    else:
        st.caption('⚙️ OAuth 尚未設定 — 至「ETF 組合」Tab 展開「💾 雲端儲存」設定')

    st.markdown('---')
    st.markdown('### 🔌 連線狀態')
    # [Fixed] 與 line 73-74 對齊：st.secrets 優先，os.environ fallback
    _fm_tok  = str(st.secrets.get('FINMIND_TOKEN',  os.environ.get('FINMIND_TOKEN',  '')))
    _gm_key  = str(st.secrets.get('GEMINI_API_KEY', os.environ.get('GEMINI_API_KEY', '')))
    _px_host = str(st.secrets.get('PROXY_HOST',     os.environ.get('PROXY_HOST',     '')))
    # PROXY_URL 與 PROXY_HOST 二擇一即可亮 ✅
    if not _px_host:
        _px_host = str(st.secrets.get('PROXY_URL', os.environ.get('PROXY_URL', '')))
    _sb_c1, _sb_c2, _sb_c3 = st.columns(3)
    with _sb_c1:
        if _fm_tok:
            st.success('FinMind ✅')
        else:
            st.error('FinMind ❌')
    with _sb_c2:
        if _gm_key:
            st.success('Gemini ✅')
        else:
            st.error('Gemini ❌')
    with _sb_c3:
        if _px_host:
            st.success('Proxy ✅')
        else:
            st.warning('Proxy —')
    if _px_host:
        _px_port = str(st.secrets.get('PROXY_PORT', os.environ.get('PROXY_PORT', '')))
        st.caption(f'🔒 {_px_host}:{_px_port}' if _px_port else '🔒 PROXY_URL 已設定')
        st.caption('💡 詳細診斷請看「🔎 資料診斷」Tab 的 API Key 診斷面板')
    if st.button('🔍 測試連線', key='sb_conn_test', use_container_width=True):
        import requests as _rq_sb
        import urllib3 as _ul3
        _ul3.disable_warnings(_ul3.exceptions.InsecureRequestWarning)
        _test_targets = [
            ('FinMind', 'https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo&stock_id=2330&date=2024-01-01', False),
            ('TWSE',    'https://openapi.twse.com.tw/v1/opendata/t187ap03_L', True),
            ('Yahoo',   'https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?range=1d&interval=1d', False),
        ]
        _conn_res = []
        for _tn, _tu, _skip_ssl in _test_targets:
            try:
                _tr = _rq_sb.get(_tu, timeout=6, verify=not _skip_ssl,
                                  headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
                _conn_res.append((_tn, _tr.status_code, _tr.status_code < 400))
            except Exception as _te:
                _conn_res.append((_tn, type(_te).__name__, False))
        st.session_state['_sb_conn_results'] = _conn_res
    for _rn, _rc, _rok in st.session_state.get('_sb_conn_results', []):
        if _rok:
            st.success(f'✅ {_rn} 可達！HTTP {_rc}')
        else:
            st.error(f'❌ {_rn} 失敗：{_rc}')

    st.markdown('---')
    st.caption('⚠️ 僅供學術研究，非投資建議，盈虧自負')

# v3.0 RENDER FUNCTIONS (§9.3)
# ════════════════════════════════════════════════════════════════

# ── 旌旗指數計算（站上 MA20/MA60/MA120/MA240 的家數比例）──────
def calc_jingqi(scan_results):
    """
    傳入 Tab5 掃描結果 list，計算旌旗指數
    scan_results: [{代碼, 趨勢, 健康度, ...}, ...]
    """
    if not scan_results:
        return {}
    total = len(scan_results)
    # P4修正：四個維度統一用「健康度門檻」，並附上語意說明
    # pct20 = 健康度>=40（基本健康，可觀察）
    # pct60 = 健康度>=60（中等強勢）
    # pct120= 健康度>=70（強勢）
    # pct240= 健康度>=80（優質強勢）
    above_ma20  = sum(1 for r in scan_results if r.get('健康度',0) >= 40)
    above_ma60  = sum(1 for r in scan_results if r.get('健康度',0) >= 60)
    above_ma120 = sum(1 for r in scan_results if r.get('健康度',0) >= 70)
    above_ma240 = sum(1 for r in scan_results if r.get('健康度',0) >= 80)
    pct20  = round(above_ma20  / total * 100, 1) if total else 0
    pct60  = round(above_ma60  / total * 100, 1) if total else 0
    pct120 = round(above_ma120 / total * 100, 1) if total else 0
    pct240 = round(above_ma240 / total * 100, 1) if total else 0
    avg    = round((pct20+pct60+pct120+pct240)/4, 1)

    # 動態倉位建議（弘爺策略）
    if avg >= 60:
        pos = '80~100%'
        regime = 'bull'
        color = '#3fb950'
        label = '🟢 多頭積極'
    elif avg >= 40:
        pos = '50~70%'
        regime = 'neutral'
        color = '#d29922'
        label = '🟡 中性均衡'
    elif avg >= 20:
        pos = '20~40%'
        regime = 'caution'
        color = '#f85149'
        label = '🟠 保守防禦'
    else:
        pos = '0~20%'
        regime = 'bear'
        color = '#c00000'
        label = '🔴 極度保守'

    return {
        'pct20':pct20,'pct60':pct60,'pct120':pct120,'pct240':pct240,
        'avg':avg,'pos':pos,'regime':regime,'color':color,'label':label,
        'total':total
    }

def render_market_overview(market_info: dict):
    """首頁市場狀態卡 (§9.2)"""
    if not market_info:
        st.warning('⚠️ 無法取得大盤數據')
        return
    regime   = market_info.get('regime', 'neutral')
    label    = market_info.get('label', '─')
    score    = market_info.get('score', 0)
    mx       = market_info.get('max_score', 4)
    idx      = market_info.get('index_price', 0)
    exposure = market_info.get('exposure_pct', '50%')
    signals  = market_info.get('signals', [])
    color_map = {'bull': '#3fb950', 'neutral': '#d29922', 'bear': '#f85149'}
    bg_map    = {'bull': '#0d2818', 'neutral': '#2a1f00', 'bear': '#2a0d0d'}
    color = color_map.get(regime, '#8b949e')
    bg    = bg_map.get(regime, '#161b22')
    st.markdown(f"""
<div style="background:{bg};border:2px solid {color};border-radius:12px;padding:16px 20px;margin-bottom:12px;">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <div>
      <span style="font-size:22px;font-weight:900;color:{color};">{label}</span>
      <span style="font-size:13px;color:#8b949e;margin-left:10px;">評分 {score}/{mx} ｜ 大盤 {idx:,.0f}</span>
    </div>
    <div style="text-align:right;">
      <span style="font-size:15px;color:#e6edf3;">建議持股 <b style="color:{color};">{exposure}</b></span>
    </div>
  </div>
  <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:6px;">
    {"".join('<span style="background:#161b22;border-radius:6px;padding:3px 8px;font-size:12px;color:#e6edf3;">' + str(s) + '</span>' for s in signals)}
  </div>
</div>""", unsafe_allow_html=True)

def render_top_rankings(results: list, top_n: int = 10):
    """股票評分排行榜 (§9.1)"""
    if not results:
        st.info('尚無評分資料')
        return
    from scoring_engine import rank_stocks as _rank
    ranked = _rank(results)[:top_n]
    if not ranked:
        st.info('尚無有效評分資料')
        return
    rows = []
    for i, r in enumerate(ranked):
        rows.append({
            '排名': i + 1, '代碼': r.get('stock_id', ''), '名稱': r.get('stock_name', ''),
            '總分': f"{r.get('total', 0):.1f}", '趨勢': f"{r.get('trend', 0):.0f}",
            '動能': f"{r.get('momentum', 0):.0f}", '籌碼': f"{r.get('chip', 0):.0f}",
            '量價': f"{r.get('volume', 0):.0f}", '風險': f"{r.get('risk', 0):.0f}",
            '評級': r.get('grade', '-'), '動能訊號': '⚡' if r.get('momentum_signal') else '─',
        })
    df_rank = pd.DataFrame(rows)
    st.dataframe(df_rank, use_container_width=True, hide_index=True,
                 column_config={'總分': st.column_config.ProgressColumn('總分', min_value=0, max_value=100, format='%.1f')})

# ════════════════════════════════════════════════════════════════
# TABS: 3 主頁籤
# ════════════════════════════════════════════════════════════════
# ── Sidebar ────────────────────
with st.sidebar:
    st.markdown('<div style="text-align:center;padding:8px 0;font-size:15px;font-weight:900;color:#e6edf3;">&#128202; 台股AI戰情室 v3.0</div>', unsafe_allow_html=True)
    st.markdown('---')
    _today_sb = datetime.date.today()
    _wd_sb = {0:'一',1:'二',2:'三',3:'四',4:'五',5:'六',6:'日'}[_today_sb.weekday()]
    _trade_sb = '✅ 交易日' if _today_sb.weekday() < 5 else '❌ 非交易日'
    st.caption(f'{_today_sb.strftime("%Y/%m/%d")} 週{_wd_sb}  {_trade_sb}')
    st.markdown('---')
    if st.button('🔄 強制刷新數據', key='_sb_force_refresh', use_container_width=True,
                 help='清除所有快取並重新抓取最新資料'):
        st.cache_data.clear()
        st.rerun()
    st.markdown('---')

# 主標題
st.markdown(
    '<div style="display:flex;align-items:center;gap:10px;padding:4px 0 8px;">'    '<span style="font-size:22px;font-weight:900;color:#e6edf3;">&#128202; 台股 AI 戰情室</span>'    '<span style="font-size:10px;color:#484f58;background:#161b22;border-radius:10px;padding:2px 8px;">v4.0 Pro</span>'    '</div>',
    unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# 🧭 總經指南針 (Top-Down Macro) — Phase 1 規格頂部三大美股指標
# ══════════════════════════════════════════════════════
def _render_compass_card(col, info, title, ticker, fmt='{:.2f}', unit='', show_ma=False):
    """單張指標卡：值 + Phase 1 訊號燈 + 60D sparkline。info=None 顯示降級訊息。"""
    if info is None:
        col.markdown(
            f'<div style="background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:10px;height:84px;">'
            f'<div style="font-size:11px;color:#8b949e;">{title}（{ticker}）</div>'
            f'<div style="font-size:13px;color:#8b949e;margin-top:6px;">🔴 未取得（yfinance 暫時失敗）</div>'
            f'</div>', unsafe_allow_html=True)
        return
    val = info.get('value')
    sig = info.get('signal') or ('⚪', '無訊號', '#8b949e')
    light, label, color = sig[0], sig[1], sig[2]
    val_str = fmt.format(val) + unit if val is not None else 'N/A'
    extra = ''
    if show_ma and info.get('ma60') is not None:
        extra = f' <span style="font-size:10px;color:#8b949e;font-weight:400;">/ 60MA {fmt.format(info["ma60"])}</span>'
    col.markdown(
        f'<div style="background:#0d1117;border:1px solid {color};border-radius:8px;padding:10px;">'
        f'<div style="font-size:11px;color:#8b949e;">{title}（{ticker}）</div>'
        f'<div style="font-size:22px;font-weight:900;color:#e6edf3;margin:2px 0;">{val_str}{extra}</div>'
        f'<div style="font-size:11px;font-weight:700;color:{color};">{light} {label}</div>'
        f'</div>', unsafe_allow_html=True)
    ser = info.get('series') or []
    if ser:
        try:
            import pandas as _pd_mc
            col.line_chart(_pd_mc.Series(ser, name=title), height=80, use_container_width=True)
        except Exception:
            pass

def render_macro_compass():
    """頂部三卡：VIX 恐慌指數 × 美 10Y 殖利率 × S&P 500 vs 60MA。
    預設不抓資料（避免顯示過時值誤判），按「📡 抓取最新」按鈕才打 yfinance。"""
    import datetime as _dt_mc

    def _do_fetch():
        try:
            from macro_core import fetch_macro_compass as _fmc
            _data = _fmc()
        except Exception as e:
            print(f'[render_macro_compass] fetch failed: {e}')
            _data = {}
        st.session_state['_macro_compass_cache'] = {
            '_ts': _dt_mc.datetime.now(), 'data': _data,
        }

    _cache = st.session_state.get('_macro_compass_cache')
    _has_data = bool(_cache and _cache.get('data'))
    _ts_str = (_cache.get('_ts').strftime('%H:%M:%S')
               if _has_data and _cache.get('_ts') else '尚未抓取')

    _header = st.columns([6, 1])
    _header[0].markdown(
        '<div style="font-size:14px;font-weight:900;color:#e6edf3;margin:4px 0 4px;">'
        '🧭 總經指南針 (Top-Down Macro)'
        '<span style="font-size:10px;color:#8b949e;font-weight:400;margin-left:8px;">'
        f'VIX × 10Y × S&amp;P 500 — {"即將抓取（無快取）" if not _has_data else f"更新於 {_ts_str}"}'
        '</span></div>',
        unsafe_allow_html=True)
    _header[1].button('📡 抓取最新' if not _has_data else '🔄 重抓',
                       key='_compass_fetch_btn', on_click=_do_fetch,
                       use_container_width=True)

    if not _has_data:
        st.info('💡 點擊右上「📡 抓取最新」按鈕載入即時 VIX / 10Y / S&P 500')
        return

    data = _cache.get('data') or {}
    c1, c2, c3 = st.columns(3)
    _render_compass_card(c1, data.get('vix'),  'VIX 恐慌指數',     '^VIX',  fmt='{:.2f}')
    _render_compass_card(c2, data.get('tnx'),  '美 10Y 殖利率',    '^TNX',  fmt='{:.2f}', unit='%')
    _render_compass_card(c3, data.get('gspc'), 'S&P 500 vs 60MA',  '^GSPC', fmt='{:,.2f}', show_ma=True)

render_macro_compass()

tab_macro, tab_heatmap, tab_stock, tab_stock_grp, tab_screener, tab_etf, tab_etf_grp, tab_diag, tab_edu = st.tabs([
    '🌍 總經', '🗺️ 產業熱力圖', '🔬 個股', '🏆 個股組合',
    '💎 高息網', '🏦 ETF', '⚖️ ETF組合', '🔎 資料診斷', '📚 教學',
])

# ══════════════════════════════════════════════════════════════
# TAB 1: 總體經濟
# ══════════════════════════════════════════════════════════════

# ── 全域多空紅綠燈（頁面最頂端）─────────────────────────────
_mkt_top  = st.session_state.get('mkt_info', {})
_jq_top   = st.session_state.get('jingqi_info', {})
_ts_top   = st.session_state.get('cl_ts', '')
if (_mkt_top or _jq_top) and not st.session_state.get('_is_refreshing', False):
    _reg   = _mkt_top.get('regime', 'neutral')
    _jqpct = _jq_top.get('avg', 50) if _jq_top else None
    # 綜合信號
    _gl_color, _gl_label = traffic_light(
        None,
        _reg == 'bull' and (_jqpct is None or _jqpct >= 40),
        _reg == 'bear' or (_jqpct is not None and _jqpct < 20),
        '多頭市場（可積極操作）', '空頭市場（先觀望保守）', '🟡 震盪整理（謹慎操作）'
    )
    _gl_pos = _mkt_top.get('exposure_pct', '80%' if _reg=='bull' else ('20%' if _reg=='bear' else '50%'))

    st.markdown(
        f'<div style="background:#0d1117;border:1px solid {_gl_color};border-radius:8px;'
        f'padding:8px 14px;margin-bottom:8px;display:flex;align-items:center;gap:16px;">'
        f'<span style="font-size:16px;font-weight:900;color:{_gl_color};">{_gl_label}</span>'
        f'<span style="font-size:12px;color:#c9d1d9;">建議持股 <b>{_gl_pos}</b></span>'
        + (f'<span style="font-size:12px;color:#8b949e;">旌旗均值 {_jqpct:.0f}%</span>'
           if _jqpct is not None else '') +
        f'<span style="font-size:11px;color:#484f58;margin-left:auto;">更新：{_ts_top}</span>'
        f'</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# AI 總經戰情 — 新聞抓取 + LLM 研判 工具函數
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=1800, show_spinner=False, max_entries=10)
def _fetch_macro_news(n: int = 5) -> list:
    """抓取全球總經財經新聞 — 中英雙語多源（系統性風險偵測用）。
    來源：CNYES鉅亨 / 經濟日報 / Google News(中) / Google News(英) /
          Yahoo Finance / Reuters Biz / CNBC Economy / Bloomberg Markets
    策略：每源最多取 3 則 → 全池去重（依標題）→ 不依時間排序（部分 RSS 無 published），
          採「每源 round-robin」混合產出，確保中英來源都被納入 AI 判讀。
    ttl=1800：每 30 分鐘自動更新一次快取。
    """
    try:
        import feedparser as _fp
        import html as _h
        import re as _re2
    except ImportError:
        print('[AI-News] ⚠️ feedparser 未安裝，跳過新聞抓取')
        return []
    try:
        from proxy_helper import fetch_url as _furl_news
    except ImportError:
        _furl_news = None

    # 中文優先（在地系統性風險解讀），英文補強（黑天鵝國際同步）
    _feeds = [
        ('鉅亨網',       'https://www.cnyes.com/rss/cat/headline'),
        ('經濟日報',     'https://money.udn.com/rssfeed/news/1001/5589/12017?ch=money'),
        ('Google中文',   'https://news.google.com/rss/search'
                         '?q=%E5%8F%B0%E8%82%A1+%E8%81%AF%E6%BA%96%E6%9C%83+%E5%88%A9%E7%8E%87+%E5%B9%B3%E5%84%B9'
                         '&hl=zh-TW&gl=TW&ceid=TW:zh-Hant'),
        ('Google英文',   'https://news.google.com/rss/search'
                         '?q=stock+market+economy+fed+interest+rate'
                         '&hl=en-US&gl=US&ceid=US:en'),
        ('Yahoo Finance','https://finance.yahoo.com/news/rssindex'),
        ('Reuters Biz',  'https://feeds.reuters.com/reuters/businessNews'),
        ('CNBC Economy', 'https://search.cnbc.com/rs/search/combinedcms/view.xml'
                         '?partnerId=wrss01&id=20910258'),
        ('Bloomberg',    'https://feeds.bloomberg.com/markets/news.rss'),
    ]
    _per_src = 3  # 每源上限，避免單一來源洗版
    _by_src: dict[str, list] = {}
    for _src, _url in _feeds:
        _by_src[_src] = []
        try:
            # 走 NAS Squid proxy 抓 RSS 文字（Streamlit Cloud IP 多被 RSS 來源封鎖）
            _fd = None
            if _furl_news is not None:
                _r_rss = _furl_news(_url, timeout=10)
                if _r_rss is not None:
                    _fd = _fp.parse(_r_rss.content)  # 餵 bytes：避免 str+encoding 宣告被 feedparser 拒解析
            if _fd is None or not getattr(_fd, 'entries', None):
                # 降級直連（proxy 失效時）
                _fd = _fp.parse(_url)
            for _e in _fd.entries:
                _title = _h.unescape(_e.get('title', '')).strip()
                _summ  = _h.unescape(_e.get('summary', _e.get('description', ''))).strip()
                _summ  = _re2.sub(r'<[^>]+>', '', _summ)[:300].strip()
                _pub   = str(_e.get('published', ''))[:16]
                if _title:
                    _by_src[_src].append({'title': _title, 'summary': _summ,
                                          'source': _src, 'published': _pub})
                if len(_by_src[_src]) >= _per_src:
                    break
            print(f'[AI-News/{_src}] ✅ {len(_by_src[_src])} 則')
        except Exception as _ne:
            print(f'[AI-News/{_src}] ❌ {_ne}')

    # round-robin 混合各源，依序去重
    _seen: set[str] = set()
    _out: list = []
    _max_round = max((len(v) for v in _by_src.values()), default=0)
    for _i in range(_max_round):
        for _src, _items in _by_src.items():
            if _i < len(_items):
                _t = _items[_i]['title']
                if _t and _t not in _seen:
                    _seen.add(_t)
                    _out.append(_items[_i])
                    if len(_out) >= n:
                        return _out
    return _out[:n]


def _rss_items_from_bytes(_content) -> list:
    """從 RSS bytes 抽 item：feedparser 主、ElementTree 備援（規避 feedparser 對
    含 encoding 宣告 / 特殊命名空間 RSS 的怪癖）。回傳 dict list。"""
    if not _content:
        return []
    _cb = _content if isinstance(_content, bytes) else str(_content).encode('utf-8', 'ignore')
    try:
        import feedparser as _fp2
        _e = list(getattr(_fp2.parse(_cb), 'entries', []) or [])
        if _e:
            return _e
    except Exception:
        pass
    if b'<item' not in _cb:
        return []
    try:
        import xml.etree.ElementTree as _ET
        import email.utils as _eu
        _items = []
        for _it in _ET.fromstring(_cb).iter('item'):
            _title = (_it.findtext('title') or '').strip()
            if not _title:
                continue
            _pub = (_it.findtext('pubDate') or '').strip()
            _items.append({'title': _title, 'link': (_it.findtext('link') or '').strip(),
                           'summary': (_it.findtext('description') or '').strip(),
                           'published': _pub, 'published_parsed': _eu.parsedate(_pub) if _pub else None})
        return _items
    except Exception:
        return []


def _fetch_stock_news(stock_id: str, stock_name: str = "", n: int = 5, recency: str = "", _diag=None) -> list:
    """抓取個股相關新聞（Google News RSS 中英文雙搜尋）。失敗時回傳空串列。
    透過 NAS Squid proxy 路由（Streamlit Cloud IP 易被 Google News RSS 限速/封鎖）。
    recency：Google News 時間運算子（如 '6m' 近半年 / '7d'），空字串=不限。
    每則含 link 與排序用 _ts，並依發布時間新→舊排序。
    _diag：傳入 list 時逐 feed 記錄抓取狀態（proxy/直連 · HTTP · entries · 錯誤）供 UI 診斷。
    """
    try:
        import feedparser as _fp
        import html as _h
        import re as _re2
        import time as _time_sn
        from urllib.parse import quote as _uq
    except ImportError:
        if _diag is not None:
            _diag.append('feedparser/urllib 匯入失敗')
        return []
    try:
        from proxy_helper import fetch_url as _furl_sn, nas_relay_fetch as _nas_rf
    except ImportError:
        _furl_sn = None
        _nas_rf = None
        if _diag is not None:
            _diag.append('proxy_helper 未載入 → 僅能直連（雲端易 403）')
    # 不用 Google News `when:` 運算子（RSS 不穩、常回空 channel）；改吃預設近期排序
    _q_tw = f"{stock_id} {stock_name}".strip()
    _q_en = f"Taiwan stock {stock_id} {stock_name}".strip()
    _feeds = [
        ('Google新聞(中文)', f'https://news.google.com/rss/search?q={_uq(_q_tw)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant'),
        ('Google新聞(英文)', f'https://news.google.com/rss/search?q={_uq(_q_en)}&hl=en-US&gl=US&ceid=US:en'),
    ]
    _news_hdr = {
        'Cookie': 'CONSENT=YES+cb; SOCS=CAI',  # 繞過 Google 同意頁（保險）
        'Accept': 'application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5',
    }
    _out = []
    for _src, _url in _feeds:
        _via = ''
        _content = None
        try:
            # 路徑①：NAS FastAPI 中繼站（家用台灣 IP）
            if _nas_rf is not None:
                _rr = _nas_rf(_url, timeout=15)
                if _rr is not None:
                    _content = _rr.content
                    _via = f'NAS中繼 HTTP {getattr(_rr, "status_code", "?")}'
                else:
                    _via = 'NAS中繼未設定或失敗'
            # 路徑②：Squid proxy
            if not _content and _furl_sn is not None:
                _rs = _furl_sn(_url, headers=_news_hdr, timeout=10)
                if _rs is not None:
                    _content = _rs.content
                    _via += f' | Squid HTTP {getattr(_rs, "status_code", "?")}'
                else:
                    _via += ' | Squid回None'
            # 解析：feedparser → ElementTree 備援（餵 bytes）
            _items = _rss_items_from_bytes(_content)
            # 路徑③：直連（前兩路徑都沒 item 才試；雲端機房 IP 多 403）
            if not _items:
                try:
                    _items = list(getattr(_fp.parse(_url, request_headers=_news_hdr), 'entries', []) or [])
                    _via += f' | 直連{len(_items)}則'
                except Exception:
                    _via += ' | 直連失敗'
            _itag = _content.count(b'<item') if _content else 0
            _via += f'｜item標籤={_itag}/解析{len(_items)}則'
            if not _items and _content:
                _via += f'｜body[:100]={_content[:100].decode("utf-8", "ignore").strip()!r}'
            for _e in _items:
                _title = _h.unescape(_e.get('title', '')).strip()
                _summ  = _h.unescape(_e.get('summary', _e.get('description', ''))).strip()
                _summ  = _re2.sub(r'<[^>]+>', '', _summ)[:150].strip()
                _pub   = str(_e.get('published', ''))[:16]
                _pp    = _e.get('published_parsed')
                try:
                    _ts = _time_sn.mktime(_pp) if _pp else 0.0
                except Exception:
                    _ts = 0.0
                if _title:
                    _out.append({'title': _title, 'summary': _summ, 'source': _src,
                                 'published': _pub, 'link': _e.get('link', ''), '_ts': _ts})
                if len(_out) >= n:
                    break
            if _diag is not None:
                _diag.append(f'{_src}: {_via} → 收 {len(_out)} 則')
            print(f'[StockNews/{_src}] ✅ {stock_id} 累計 {len(_out)} 則')
        except Exception as _ne:
            if _diag is not None:
                _diag.append(f'{_src}: ❌ {_via} {type(_ne).__name__}: {str(_ne)[:80]}')
            print(f'[StockNews/{_src}] ❌ {_ne}')
        if len(_out) >= n:
            break
    _out.sort(key=lambda _x: _x.get('_ts', 0.0), reverse=True)  # 新→舊
    return _out[:n]


def _build_llm_context(macro_info: dict) -> str:
    """將 session_state 中的量化總經數據格式化為純文字供 LLM 使用"""
    _vix = macro_info.get('vix') or {}
    _exp = macro_info.get('tw_export') or {}
    _pmi = macro_info.get('ism_pmi') or {}
    _cpi = macro_info.get('us_core_cpi') or {}
    _ndc = macro_info.get('ndc_signal') or {}
    _mi  = st.session_state.get('m1b_m2_info') or {}
    _bi  = st.session_state.get('bias_info') or {}
    _lines = []
    if _vix.get('current'):
        _lines.append(f'• VIX 恐慌指數：{_vix["current"]} (MA20={_vix.get("ma20","N/A")})')
    if _exp.get('yoy') is not None:
        _lines.append(f'• 台灣外銷訂單 YoY：{_exp["yoy"]:+.1f}%  ({_exp.get("date","")})')
    if _pmi.get('value') is not None:
        _lines.append(f'• 🇹🇼 台灣 PMI：{_pmi["value"]}  ({_pmi.get("date","")}，>50 擴張)')
    if _cpi.get('yoy') is not None:
        _lines.append(f'• 美國核心 CPI YoY：{_cpi["yoy"]:+.1f}%  ({_cpi.get("date","")})')
    if _ndc.get('score') is not None:
        _lines.append(f'• NDC 景氣燈號分數：{_ndc["score"]:.0f}/45')
    if _mi.get('m1b_yoy') is not None and _mi.get('m2_yoy') is not None:
        _gap = round(float(_mi['m1b_yoy']) - float(_mi['m2_yoy']), 2)
        _lines.append(f'• 台灣 M1B={_mi["m1b_yoy"]:.1f}%  M2={_mi["m2_yoy"]:.1f}%  Gap={_gap:+.2f}%')
    if _bi.get('bias_240') is not None:
        _lines.append(f'• 台股大盤年線乖離率 BIAS240：{_bi["bias_240"]:+.1f}%')
    return '\n'.join(_lines) if _lines else '（量化數據載入中，請先點擊更新總經拼圖）'


def _run_llm_analysis(macro_info: dict, news: list) -> dict:
    """呼叫 Gemini API 進行總經研判，回傳解析後的 dict。
    使用既有的 gemini_call() 函數（支援 2.5-flash-lite/2.5-flash/2.0-flash 自動 fallback）。
    錯誤時回傳 {'error': '...'}，不拋出例外。
    """
    _macro_str = _build_llm_context(macro_info)
    _news_lines = []
    for i, _nw in enumerate(news, 1):
        _news_lines.append(f'{i}. [{_nw["source"]}] {_nw["title"]}')
        if _nw.get('summary'):
            _news_lines.append(f'   {_nw["summary"][:150]}')
    _news_str = '\n'.join(_news_lines) if _news_lines else '（無法取得今日新聞，請依量化數據判斷）'

    _prompt = (
        '你是一位管理百億規模的資深量化基金經理，擁有 20 年台股與全球宏觀投資經驗。'
        '任務：整合量化總經指標與即時財經新聞，為台股投資人提供精確的戰術研判。'
        '分析需立足於提供的數據事實，避免空泛描述。\n\n'
        f'分析時間：{_tw_now_str()}（台北時間）\n\n'
        f'## 當前量化總經數據\n{_macro_str}\n\n'
        f'## 今日國際財經重大新聞\n{_news_str}\n\n'
        '## 輸出指令\n'
        '請整合上述數據與新聞，輸出台股投資研判。\n'
        '規則：① stock_pct + cash_pct = 100 ② 所有字串值使用繁體中文\n'
        '③ risk_level：VIX≥30或重大地緣風險→high；VIX 20~30或通膨偏高→medium；其餘→low\n'
        '只輸出 JSON，不要任何說明文字或 markdown 標記：\n'
        '{\n'
        '  "sentiment": "極度恐慌|警戒|中性|樂觀|極度狂熱",\n'
        '  "sentiment_reason": "市場情緒判定的核心依據（15字以內）",\n'
        '  "macro_reading": "整合數據與新聞的總經現況精煉解讀（50字以內）",\n'
        '  "stock_pct": 建議持股水位整數,\n'
        '  "cash_pct": 建議現金水位整數,\n'
        '  "action": "一句話具體操作方針，含理由（35字以內）",\n'
        '  "risk_level": "high|medium|low",\n'
        '  "key_risk": "當前最大下行風險（20字以內）",\n'
        '  "opportunity": "當前最大投資機會（20字以內）"\n'
        '}'
    )

    _raw = gemini_call(_prompt, max_tokens=600)
    print(f'[AI-LLM/Gemini] raw={_raw[:120]}')
    if _raw.startswith('⚠️'):
        return {'error': _raw}
    try:
        _match = re.search(r'\{[\s\S]*\}', _raw)
        if _match:
            _parsed = json.loads(_match.group())
            _s = int(_parsed.get('stock_pct', 50))
            _parsed['stock_pct'] = max(0, min(100, _s))
            _parsed['cash_pct']  = 100 - _parsed['stock_pct']
            return _parsed
        return {'error': f'JSON 解析失敗，原始回應：{_raw[:100]}'}
    except Exception as _le:
        print(f'[AI-LLM/Gemini] ❌ {_le}')
        return {'error': str(_le)[:150]}




with tab_macro:
    render_tab_macro()




with tab_stock:
    render_tab_stock()


with tab_stock_grp:
    render_stock_grp()




with tab_edu:
    render_tab_edu()


# ══════════════════════════════════════════════════════════════
# TAB: ETF 單一深度診斷
# ══════════════════════════════════════════════════════════════
with tab_etf:
    render_etf_single(gemini_fn=gemini_call)

# ══════════════════════════════════════════════════════════════
# TAB: ETF 組合戰情室（4 區段整合：組合配置 + 歷史回測 + AI + 葡萄串）
# ══════════════════════════════════════════════════════════════
with tab_etf_grp:
    # ── ① 組合配置與再平衡（唯一輸入來源，下游模組共享 etf_portfolio_rows）──
    render_etf_portfolio(gemini_fn=gemini_call)
    st.markdown('<hr style="margin:32px 0;border-color:#30363d;">', unsafe_allow_html=True)

    # ── ② 歷史回測 ──
    render_etf_backtest(gemini_fn=gemini_call)
    st.markdown('<hr style="margin:32px 0;border-color:#30363d;">', unsafe_allow_html=True)

    # ── ③ 葡萄串領息法（自動讀取持股做月配息評估）──
    render_grape_ladder(gemini_fn=gemini_call)
    st.markdown('<hr style="margin:32px 0;border-color:#30363d;">', unsafe_allow_html=True)

    # ── ④ AI 綜合評斷 + 自由提問（壓軸區，整合所有上方分析）──
    render_etf_ai(gemini_fn=gemini_call)

# ══════════════════════════════════════════════════════════════
# TAB: 7% 高殖利率防禦網（Screener Mode）
# ══════════════════════════════════════════════════════════════
with tab_screener:
    from yield_screener import render_yield_screener
    _picker_candidates = render_yield_screener()

    # ── 🎯 智慧選股（三階段濾網 + AI 三型建議）— 接續高息網候選清單 ──
    st.markdown('---')
    from tab_stock_picker import render_tab_stock_picker
    render_tab_stock_picker(gemini_fn=gemini_call, candidates=_picker_candidates)

# ══════════════════════════════════════════════════════════════
# TAB: 資料診斷（Raw Data only）
# ══════════════════════════════════════════════════════════════
with tab_diag:
    render_api_diagnostic()
    st.markdown('---')
    render_data_health_raw()

# ══════════════════════════════════════════════════════════════
# TAB: 產業熱力圖
# ══════════════════════════════════════════════════════════════
with tab_heatmap:
    render_sector_heatmap(gemini_fn=gemini_call)

st.markdown('<div style="text-align:center;font-size:10px;color:#484f58;padding:8px 0;">⚠️ 台股AI戰情室 v3.0 · 僅供學術研究，非投資建議，盈虧自負</div>', unsafe_allow_html=True)
