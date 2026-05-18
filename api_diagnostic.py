"""api_diagnostic.py — API Key & 連線根因診斷面板

掛在 tab_diag 第一格，用來釐清「Key 已設但全站抓不到資料」的常見根因：
1. st.secrets 是否能 parse（TOML 格式錯會整段 fallback 到空）
2. 每把 Key 的真實來源（st.secrets / os.environ）與遮罩預覽
3. PROXY_URL 是否把所有外連導去打不通的 NAS（最常見兇手）
4. 各 API endpoint「走 proxy vs 直連」雙跑比對

純 Streamlit 顯示，不寫入 session_state 以外的副作用。
"""
from __future__ import annotations

import os
import time
import streamlit as st


def _mask(val: str) -> str:
    """遮罩中段，保留前 4 + 後 4 字元 + 長度，避免在診斷頁洩漏完整 key。"""
    if not val:
        return '(空)'
    s = str(val)
    n = len(s)
    if n <= 8:
        return f'{"*" * n} (len={n})'
    return f'{s[:4]}…{s[-4:]} (len={n})'


def _safe_secret(key: str):
    """安全讀 st.secrets[key]。回傳 (value, error_str)。"""
    try:
        sec = getattr(st, 'secrets', None)
        if sec is None:
            return None, 'st.secrets 不存在'
        if key in sec:
            return sec[key], None
        return None, None
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'


def _resolve_key(key: str) -> dict:
    """回傳一把 key 的完整解析結果：來源、值、遮罩、錯誤。"""
    sec_val, sec_err = _safe_secret(key)
    env_val = os.environ.get(key, '')
    if sec_val:
        return {'name': key, 'source': 'st.secrets', 'val': sec_val,
                'preview': _mask(sec_val), 'sec_err': sec_err, 'env_preview': _mask(env_val)}
    if env_val:
        return {'name': key, 'source': 'os.environ', 'val': env_val,
                'preview': _mask(env_val), 'sec_err': sec_err, 'env_preview': _mask(env_val)}
    return {'name': key, 'source': '(無)', 'val': '',
            'preview': '(未設定)', 'sec_err': sec_err, 'env_preview': _mask(env_val)}


def _probe(label: str, url: str, params: dict | None = None,
           proxies: dict | None = None, timeout: int = 8) -> tuple[bool, str]:
    """輕量探測，回傳 (ok, msg)。不丟例外。"""
    import requests
    try:
        r = requests.get(url, params=params, proxies=proxies,
                         timeout=timeout, verify=False,
                         headers={'User-Agent': 'Mozilla/5.0'})
        snippet = (r.text or '')[:80].replace('\n', ' ')
        return (r.status_code < 400, f'HTTP {r.status_code} {snippet}')
    except Exception as e:
        return False, f'{type(e).__name__}: {str(e)[:120]}'


def render_api_diagnostic():
    """主入口：顯示完整 API 診斷面板。"""
    st.markdown('### 🔑 API Key 與連線根因診斷')
    st.caption('排查「Key 都設了但全站抓不到資料」的標準工具：解析來源 → 遮罩比對 → 走 proxy 與直連雙跑。')

    # ── §1 環境基本資訊 ─────────────────────────────────────
    try:
        import streamlit as _st_v
        st_ver = getattr(_st_v, '__version__', 'unknown')
    except Exception:
        st_ver = 'unknown'

    sec_obj = getattr(st, 'secrets', None)
    sec_keys: list[str] = []
    sec_parse_err: str | None = None
    try:
        if sec_obj is not None:
            sec_keys = list(sec_obj.keys())
    except Exception as e:
        sec_parse_err = f'{type(e).__name__}: {e}'

    c1, c2, c3 = st.columns(3)
    c1.metric('Streamlit 版本', st_ver)
    c2.metric('st.secrets 可讀', '✅' if sec_parse_err is None else '❌')
    c3.metric('Secrets keys 數', len(sec_keys))

    if sec_parse_err:
        st.error(f'⚠️ st.secrets 解析失敗：{sec_parse_err}\n\n'
                 f'→ 通常是 TOML 格式錯（缺引號／用了 export／特殊字元未跳脫）。\n'
                 f'→ Streamlit Cloud 後台 App settings → Secrets 重貼一次，記得每個值都加雙引號。')
    if sec_keys:
        st.caption(f'已偵測到的 secrets keys：`{", ".join(sec_keys)}`')

    st.markdown('---')

    # ── §2 逐把 Key 解析 ───────────────────────────────────
    st.markdown('#### 📋 各 API Key 載入狀態')
    targets = ['GEMINI_API_KEY', 'FINMIND_TOKEN', 'FRED_API_KEY',
               'PROXY_URL', 'PROXY_HOST', 'PROXY_PORT']
    rows = [_resolve_key(k) for k in targets]
    st.table([
        {'Key': r['name'], '使用來源': r['source'],
         '實際值（遮罩）': r['preview'],
         'os.environ 同步': r['env_preview']}
        for r in rows
    ])
    st.caption('「使用來源」= 程式實際取用的位置。如果是 `(無)` 表示 st.secrets 與 os.environ 都沒有，'
               'fallback 會拿到空字串，下游 API 必然 401/403/missing token。')

    # ── §3 PROXY 配置診斷（最容易害死全站的兇手）─────────
    st.markdown('---')
    st.markdown('#### 🚧 Proxy 配置診斷（最常見的「全部抓不到」根因）')
    from proxy_helper import get_proxy_config
    proxy_cfg = get_proxy_config()
    if proxy_cfg:
        st.warning(
            f'⚠️ 偵測到 PROXY 設定：`{_mask(proxy_cfg.get("http", ""))}`\n\n'
            f'**警告**：Streamlit Cloud（美/歐機房）走家用 NAS proxy 經常不通——\n'
            f'- 你家寬頻沒 port forward / IP 變動 / NAS 防火牆封鎖外部連入\n'
            f'- `proxy_helper.fetch_url()` 只有在 `ProxyError` 或連續 403×2 才降級直連，'
            f'**Timeout 不會降級**，外連就全 timeout 卡死。\n\n'
            f'→ **快速驗證**：暫時到 Streamlit Cloud Secrets 把 `PROXY_URL` 整行刪掉重啟，'
            f'若所有 Key 立刻活過來，就是 proxy 兇手。')
    else:
        st.success('✅ 沒有設定 proxy，所有外連走直連（這是 Streamlit Cloud 推薦設定）')

    # ── §4 連線雙跑實測 ─────────────────────────────────────
    st.markdown('---')
    st.markdown('#### 🔬 端對端連線實測（走 proxy vs 直連 雙跑）')

    if st.button('🚀 開始診斷外連狀態', key='api_diag_run', use_container_width=True, type='primary'):
        keys = {r['name']: r['val'] for r in rows}
        tests = [
            ('FinMind (需 token)',
             'https://api.finmindtrade.com/api/v4/data',
             {'dataset': 'TaiwanStockInfo', 'stock_id': '2330',
              'token': keys.get('FINMIND_TOKEN', '')}),
            ('Gemini API (需 key)',
             'https://generativelanguage.googleapis.com/v1beta/models',
             {'key': keys.get('GEMINI_API_KEY', '')}),
            ('FRED API (需 key)',
             'https://api.stlouisfed.org/fred/series',
             {'series_id': 'GDP', 'api_key': keys.get('FRED_API_KEY', ''),
              'file_type': 'json'}),
            ('Yahoo Finance (免 key)',
             'https://query1.finance.yahoo.com/v8/finance/chart/2330.TW',
             {'range': '1d', 'interval': '1d'}),
            ('TWSE OpenAPI (免 key)',
             'https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_AVG_ALL',
             None),
        ]
        for label, url, params in tests:
            with st.spinner(f'測試 {label}…'):
                t0 = time.time()
                ok_p, msg_p = (False, '(skip)')
                if proxy_cfg:
                    ok_p, msg_p = _probe(label, url, params, proxies=proxy_cfg)
                t_p = time.time() - t0

                t0 = time.time()
                ok_d, msg_d = _probe(label, url, params, proxies=None)
                t_d = time.time() - t0

            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f'**{label} — 走 Proxy** ({t_p:.1f}s)')
                if not proxy_cfg:
                    st.info('未設定 proxy，略過')
                elif ok_p:
                    st.success(msg_p)
                else:
                    st.error(msg_p)
            with col2:
                st.markdown(f'**{label} — 直連** ({t_d:.1f}s)')
                if ok_d:
                    st.success(msg_d)
                else:
                    st.error(msg_d)

        st.markdown('---')
        st.markdown('#### 📌 結果判讀指南')
        st.markdown(
            '- **直連全綠 + 走 proxy 全紅** → 100% 是 proxy 兇手，到 Secrets 刪掉 `PROXY_URL` 即可\n'
            '- **直連也紅，但回應有 401/403** → Key 真的無效或過期，重新申請\n'
            '- **直連也紅，回應是 Timeout/ConnectionError** → Streamlit Cloud 對該域名被封 / DNS 問題\n'
            '- **Yahoo / TWSE 直連紅** → Streamlit Cloud 機房 IP 被該服務封鎖（常見），考慮改用其他資料源\n'
        )
