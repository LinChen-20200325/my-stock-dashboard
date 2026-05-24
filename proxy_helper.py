"""
proxy_helper.py — NAS Squid 代理統一入口
  get_proxies()        → {"http": url, "https": url} 或 None（標準 requests proxies 格式）
  get_proxy_config()   → 同 get_proxies()（別名，向下相容）
  reset_proxy_cache()  → 手動清除 TTL 快取
  make_retry_session() → urllib3 指數退避 Session
  fetch_url()          → 通用抓取（NAS proxy → 自動降級直連）
"""
import requests
import urllib3
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_PROXY_CFG_CACHE = None
_PROXY_CFG_TS    = 0.0
_PROXY_CFG_TTL   = 300

# ── URL 回應快取（API Storm Shield：300s TTL，防重複衝擊 NAS/外部 API）──
_URL_CACHE: dict = {}   # key=(url, params_frozen) → (timestamp, response_text, status_code)
_URL_CACHE_TTL = 300


def get_proxies() -> dict | None:
    """
    標準 requests proxies 字典，供 requests.get(..., proxies=get_proxies()) 使用。
    優先讀取 os.environ["PROXY_URL"]，其次 st.secrets["PROXY_URL"]。
    格式：http://帳號:密碼@yourname.synology.me:3128
    """
    import os as _os2
    _url = _os2.environ.get('PROXY_URL') or _os2.environ.get('NAS_PROXY_URL')
    if not _url:
        try:
            import streamlit as _st2
            _sec2 = getattr(_st2, 'secrets', {})
            _url = _sec2.get('PROXY_URL') or _sec2.get('NAS_PROXY_URL')
            if not _url and 'proxy' in _sec2:
                _p2 = _sec2['proxy']
                _url = f"http://{_p2['username']}:{_p2['password']}@{_p2['endpoint']}"
        except Exception:
            pass
    if _url:
        return {'http': _url, 'https': _url}
    return None


def reset_proxy_cache():
    global _PROXY_CFG_CACHE, _PROXY_CFG_TS
    _PROXY_CFG_CACHE = None
    _PROXY_CFG_TS    = 0.0


def get_proxy_config() -> dict | None:
    """
    讀取 NAS Proxy 設定（優先 st.secrets，次選 os.environ）。
    支援兩種格式：
      新格式：PROXY_URL = "http://user:pwd@host:port"
      舊格式：[proxy] section with username/password/endpoint
    回傳：{"http": url, "https": url}  或  None（降級直連）
    """
    global _PROXY_CFG_CACHE, _PROXY_CFG_TS
    import time as _t
    if _PROXY_CFG_CACHE is not None and (_t.time() - _PROXY_CFG_TS) < _PROXY_CFG_TTL:
        return _PROXY_CFG_CACHE if _PROXY_CFG_CACHE else None

    import os as _os
    _url = None
    try:
        import streamlit as _st
        _sec = getattr(_st, 'secrets', {})
        if 'PROXY_URL' in _sec:
            _url = _sec['PROXY_URL']
        elif 'NAS_PROXY_URL' in _sec:
            _url = _sec['NAS_PROXY_URL']
        elif 'proxy' in _sec:
            _p   = _sec['proxy']
            _url = f"http://{_p['username']}:{_p['password']}@{_p['endpoint']}"
    except Exception:
        pass

    if not _url:
        _url = (_os.environ.get('PROXY_URL')
                or _os.environ.get('NAS_PROXY_URL')
                or _os.environ.get('HTTP_PROXY')
                or _os.environ.get('http_proxy'))

    _PROXY_CFG_CACHE = {'http': _url, 'https': _url} if _url else {}
    _PROXY_CFG_TS    = _t.time()
    return _PROXY_CFG_CACHE if _PROXY_CFG_CACHE else None


def make_retry_session() -> requests.Session:
    """urllib3 指數退避 Session：5xx 自動重試最多 3 次。"""
    _retry = Retry(
        total=3, backoff_factor=0.3,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False,
    )
    _s = requests.Session()
    _s.mount('https://', HTTPAdapter(max_retries=_retry))
    _s.mount('http://',  HTTPAdapter(max_retries=_retry))
    return _s


def fetch_url(url: str, headers: dict = None,
              params: dict = None, timeout: int = 20,
              attempts: int = 3) -> requests.Response | None:
    """
    通用抓取（NAS Squid proxy → 自動降級直連）。
    - API Storm Shield: 300s TTL 快取，相同 URL+params 不重複衝擊 NAS
    - proxy 可用 → SSL verify=False，透過 NAS CONNECT 隧道
    - ProxyError / 403×2 → 自動降級直連
    - 407 → 立即回傳 None（帳密錯誤，不重試）
    - attempts: 外層重試次數（macro 等對延遲敏感的 caller 可傳 1 走 lean path，
      避免 fetch_url 自身吃掉 60s 把上層 as_completed timeout 拖爆）
    """
    import time as _t, random as _rnd
    # ── Storm Shield: 命中快取直接回傳 ─────────────────────────────
    _cache_key = (url, tuple(sorted((params or {}).items())))
    _now = _t.time()
    if _cache_key in _URL_CACHE:
        _ts, _cached_text, _cached_status = _URL_CACHE[_cache_key]
        if _now - _ts < _URL_CACHE_TTL:
            _mock = requests.models.Response()
            _mock.status_code = _cached_status
            _mock._content = _cached_text
            _mock.encoding = 'utf-8'
            return _mock
    _proxy  = get_proxy_config() or {}
    _verify = not bool(_proxy)
    _hdr = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
    }
    if headers:
        _hdr.update(headers)

    # attempts=1 時改用「無 5xx 重試」的純 Session，避免 urllib3 內層 Retry 再吃 ~2s
    if attempts <= 1:
        _sess = requests.Session()
    else:
        _sess = make_retry_session()
    _perr  = 0
    _block = 0

    for _attempt in range(max(1, attempts)):
        try:
            _r = _sess.get(url, headers=_hdr, params=params,
                           timeout=timeout, proxies=_proxy, verify=_verify)
            if _r.status_code == 407:
                print('[proxy] 407 Auth Failed — 請確認帳密正確')
                return None
            if _r.status_code == 403:
                _block += 1
                if _block >= 2 or attempts <= 1:
                    break
                _t.sleep(_rnd.uniform(2.5, 6.0))
                continue
            if _r.status_code == 200:
                _path = url.split('?')[0].split('/')[-1] or url.split('/')[2]
                print(f'[Proxy] 已透過 Synology NAS 成功抓取: {_path}')
                _URL_CACHE[_cache_key] = (_t.time(), _r.content, 200)
                return _r
        except requests.exceptions.ProxyError as _e:
            _perr += 1
            print(f'[proxy] ProxyError attempt {_attempt + 1}: {_e}')
            if attempts > 1 and _attempt < attempts - 1:
                _t.sleep(2)
        except requests.exceptions.Timeout:
            print(f'[proxy] Timeout attempt {_attempt + 1}: {url[:60]}')
            if attempts > 1 and _attempt < attempts - 1:
                _t.sleep(2)
        except Exception as _e:
            print(f'[proxy] Error: {_e}')
            break

    # 降級直連
    if _proxy and (_perr > 0 or _block >= 2):
        print(f'[proxy] 降級直連：{url[:80]}')
        try:
            _r_dc = _sess.get(url, headers=_hdr, params=params,
                              timeout=timeout, proxies={}, verify=True)
            if _r_dc.status_code == 200:
                _URL_CACHE[_cache_key] = (_t.time(), _r_dc.content, 200)
                return _r_dc
        except Exception as _e_dc:
            print(f'[proxy] 直連失敗：{_e_dc}')
    return None


def get_nas_relay() -> tuple[str, str] | None:
    """讀取 NAS FastAPI 中繼站設定 → (base_url, api_key)；未設定回 None。
    支援 env / st.secrets 的 NAS_BASE_URL（或 NAS_RELAY_URL）+ NAS_API_KEY。"""
    import os as _o
    _base = _o.environ.get('NAS_BASE_URL') or _o.environ.get('NAS_RELAY_URL')
    _key = _o.environ.get('NAS_API_KEY', '')
    if not _base:
        try:
            import streamlit as _s
            _sec = _s.secrets
            _base = _base or _sec.get('NAS_BASE_URL') or _sec.get('NAS_RELAY_URL')
            _key = _key or _sec.get('NAS_API_KEY', '')
        except Exception:
            pass
    if not _base:
        return None
    return (str(_base).rstrip('/'), str(_key or ''))


def nas_relay_fetch(url: str, timeout: int = 15) -> requests.Response | None:
    """透過 NAS FastAPI 中繼站 /proxy 端點，以家用台灣 IP 代為抓取 url。
    成功回 requests.Response（200），未設定/非200/例外回 None。"""
    _cfg = get_nas_relay()
    if _cfg is None:
        return None
    _base, _key = _cfg
    try:
        _r = requests.get(
            f'{_base}/proxy',
            params={'url': url},
            headers={'X-API-Key': _key} if _key else {},
            timeout=timeout,
            verify=False,
        )
        if _r.status_code == 200:
            print(f'[NAS中繼] ✅ {url[:70]} HTTP 200')
            return _r
        print(f'[NAS中繼] HTTP {_r.status_code} {url[:70]}')
    except Exception as _e:
        print(f'[NAS中繼] ❌ {type(_e).__name__}: {_e}')
    return None


get_proxies = get_proxy_config  # 向下相容別名（get_proxies 指向有 TTL 快取的版本）


def fetch_with_proxy(url: str, max_retries: int = 2, **kwargs) -> dict | list | None:
    """
    共用安全請求函式（spec proxy_client.py 相容介面）。
    自動套用 PROXY_URL，失敗捕捉後回傳 None，嚴禁死迴圈。
    """
    _proxies = get_proxies()
    _hdr = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/124.0.0.0 Safari/537.36'),
        'Accept': 'application/json, text/plain, */*',
    }
    for _i in range(max_retries):
        try:
            _r = requests.get(url, headers=_hdr, proxies=_proxies,
                              timeout=10, verify=False, **kwargs)
            if _r.status_code == 200:
                try:
                    return _r.json()
                except Exception:
                    return {'raw': _r.text, 'status': 200}
            print(f'[fetch_with_proxy] HTTP {_r.status_code} {url[:60]}')
        except Exception as _e:
            if _i == max_retries - 1:
                print(f'[fetch_with_proxy] ❌ {url[:60]}: {type(_e).__name__}')
    return None
