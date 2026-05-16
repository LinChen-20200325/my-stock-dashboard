"""yield_screener.py — 7% 高殖利率防禦網（漏斗篩選器 / Screener Mode）

資料來源：
  ① 全市場本益比 + 殖利率 + 股價淨值比：TWSE OpenAPI BWIBBU_d（單次抓全市場）
  ② 單檔配息歷史：yfinance Ticker.dividends（僅在用戶選定後觸發）

架構：
  • 全部走既有 proxy_helper.fetch_url() → NAS Squid Proxy（自動降級直連）
  • @st.cache_data(ttl=86400) 一日快取，減少對 NAS 中繼站的負擔
  • Slider 動態篩選：最低殖利率(%) + 最高本益比
  • max_retries / timeout / 防迴圈：fetch_url 內建 3 次重試 + 20s timeout + Storm Shield 快取
"""
from __future__ import annotations
import streamlit as st
import pandas as pd

TWSE_BWIBBU_URL = 'https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d'


# ══════════════════════════════════════════════════════════════════════════════
# ① 全市場 — TWSE BWIBBU_d 單次抓取
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def fetch_twse_yield_pe() -> pd.DataFrame:
    """從 TWSE OpenAPI 一次取得全市場本益比 / 殖利率 / 股價淨值比。

    Returns:
        DataFrame with columns: 代碼 / 名稱 / 本益比 / 殖利率(%) / 股價淨值比
        失敗回傳空 DataFrame（呼叫端用 .empty 檢查）
    """
    from proxy_helper import fetch_url
    try:
        _resp = fetch_url(TWSE_BWIBBU_URL, timeout=15)
        if _resp is None or getattr(_resp, 'status_code', 0) != 200:
            print('[yield_screener] TWSE BWIBBU 回傳非 200 或 None')
            return pd.DataFrame()
        _data = _resp.json()
        if not isinstance(_data, list) or not _data:
            print('[yield_screener] TWSE BWIBBU 回傳格式異常')
            return pd.DataFrame()
        _df = pd.DataFrame(_data).rename(columns={
            'Code':          '代碼',
            'Name':          '名稱',
            'PEratio':       '本益比',
            'DividendYield': '殖利率(%)',
            'PBratio':       '股價淨值比',
        })
        for _c in ['本益比', '殖利率(%)', '股價淨值比']:
            if _c in _df.columns:
                _df[_c] = pd.to_numeric(_df[_c], errors='coerce')
        return _df.dropna(subset=['殖利率(%)']).reset_index(drop=True)
    except Exception as _e:
        print(f'[yield_screener] TWSE BWIBBU 解析失敗：{_e}')
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# ② 單檔配息歷史 — yfinance Ticker.dividends（透過 NAS proxy）
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def fetch_dividend_history(ticker: str) -> pd.Series:
    """取得單檔股票的歷史配息（按年合計）。

    Args:
        ticker: 純台股代碼如 '2330' / '6770'，自動補 .TW

    Returns:
        Series：index=西元年, values=該年現金配息合計（元）；無資料回傳空 Series
    """
    import os as _os
    try:
        import yfinance as yf
    except ImportError:
        print('[yield_screener] yfinance 未安裝')
        return pd.Series(dtype=float)

    # 注入 NAS proxy 至 env（yfinance/requests 會自動讀取）
    _ek = ('HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy')
    _bak = {k: _os.environ.get(k) for k in _ek}
    try:
        from proxy_helper import get_proxy_config
        _proxy_dict = get_proxy_config() or {}
        _px_url = _proxy_dict.get('https') or _proxy_dict.get('http')
        if _px_url:
            for k in _ek:
                _os.environ[k] = _px_url
    except Exception:
        pass

    _t = ticker.strip().upper()
    if not _t.endswith('.TW') and not _t.endswith('.TWO'):
        _t = f'{_t}.TW'

    try:
        _y = yf.Ticker(_t)
        _div = _y.dividends
        if _div is None or len(_div) == 0:
            return pd.Series(dtype=float)
        _annual = _div.groupby(_div.index.year).sum()
        return _annual.astype(float)
    except Exception as _e:
        print(f'[yield_screener] dividend fetch 失敗 {ticker}: {_e}')
        return pd.Series(dtype=float)
    finally:
        # 還原環境變數，避免污染其他模組
        for k, v in _bak.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v


# ══════════════════════════════════════════════════════════════════════════════
# ③ 連線狀態檢查 — 顯示 NAS Proxy 是否啟用
# ══════════════════════════════════════════════════════════════════════════════
def _proxy_status_badge() -> str:
    """回傳 HTML badge 顯示 NAS 中繼站狀態（不實際發送請求，僅看 secrets）。"""
    try:
        from proxy_helper import get_proxy_config
        _p = get_proxy_config()
        if _p:
            return ('<span style="background:#0a2818;color:#3fb950;padding:3px 10px;'
                    'border-radius:6px;font-size:11px;font-weight:700;">'
                    '🟢 NAS 中繼站 已啟用</span>')
        return ('<span style="background:#1f0d0d;color:#f85149;padding:3px 10px;'
                'border-radius:6px;font-size:11px;font-weight:700;">'
                '🔴 NAS 中繼站 未設定（直連模式）</span>')
    except Exception:
        return ('<span style="background:#2a1f00;color:#d29922;padding:3px 10px;'
                'border-radius:6px;font-size:11px;font-weight:700;">'
                '🟡 Proxy 狀態未知</span>')


# ══════════════════════════════════════════════════════════════════════════════
# ④ 主畫面渲染
# ══════════════════════════════════════════════════════════════════════════════
def render_yield_screener():
    """7% 高殖利率防禦網主畫面 — Screener Mode"""
    _hdr_cols = st.columns([4, 1])
    with _hdr_cols[0]:
        st.markdown('### 💎 7% 高殖利率防禦網')
        st.caption(
            '🎯 **漏斗篩選 (Screener Mode)**：先 TWSE 全市場一次抓殖利率/本益比，'
            '再依 Slider 條件過濾 → 對單檔做配息深度檢驗'
        )
    with _hdr_cols[1]:
        st.markdown(_proxy_status_badge(), unsafe_allow_html=True)

    with st.expander('📡 資料來源說明', expanded=False):
        st.markdown(
            '- **全市場掃描**：TWSE OpenAPI `BWIBBU_d`（每日更新，含本益比 / 殖利率 / 股價淨值比）\n'
            '- **單檔配息歷史**：`yfinance Ticker.dividends`（僅在選定股票後觸發）\n'
            '- **快取**：兩者皆 `@st.cache_data(ttl=86400)`，24 小時內重複查詢不打 API\n'
            '- **連線**：透過 `proxy_helper.fetch_url()` 走 NAS Squid Proxy；自動降級直連\n'
            '- **重試/逾時**：fetch_url 內建 3 次重試 + 20s timeout + Storm Shield 防呆'
        )

    # ── ① 抓全市場資料 ─────────────────────────────────────
    with st.spinner('正在透過 NAS 中繼站抓取 TWSE 全市場本益比 / 殖利率…'):
        _df_all = fetch_twse_yield_pe()

    if _df_all.empty:
        st.error(
            '🔴 **TWSE 全市場資料抓取失敗**\n\n'
            '可能原因：\n'
            '1. NAS Squid Proxy 未開機或 `PROXY_URL` secret 未設定\n'
            '2. TWSE OpenAPI 暫時維護中\n'
            '3. 網路連線異常\n\n'
            '👉 請至「🔎 資料診斷」Tab 檢查 API 金鑰狀態，或稍後重試（24 小時內快取保護）'
        )
        if st.button('🔄 強制重抓（清除快取）', key='ys_force_refresh'):
            fetch_twse_yield_pe.clear()
            st.rerun()
        return

    st.success(f'✅ TWSE 全市場資料就緒：共 **{len(_df_all)}** 檔上市股票')

    # ── ② 動態篩選器 ──────────────────────────────────────
    st.markdown('#### 🎚️ 篩選條件')
    _f1, _f2, _f3 = st.columns([2, 2, 1])
    with _f1:
        _min_yield = st.slider(
            '最低殖利率 (%)', 0.0, 15.0, 7.0, 0.5,
            help='只列出殖利率 ≥ 此門檻的標的（預設 7%，存股甜甜價區間）',
            key='ys_min_yield')
    with _f2:
        _max_pe = st.slider(
            '最高本益比', 5.0, 50.0, 15.0, 0.5,
            help='本益比過高代表股價偏貴；合理區間 10–15',
            key='ys_max_pe')
    with _f3:
        st.markdown('<br>', unsafe_allow_html=True)
        if st.button('🔄 重抓', key='ys_refresh', help='清除 24h 快取並重抓'):
            fetch_twse_yield_pe.clear()
            st.rerun()

    # 過濾條件：殖利率 ≥ min_yield 且本益比 ≤ max_pe（NaN 視為非常高，剔除）
    _df_filt = _df_all[
        (_df_all['殖利率(%)'] >= _min_yield) &
        (_df_all['本益比'].fillna(9_999) <= _max_pe)
    ].sort_values('殖利率(%)', ascending=False).reset_index(drop=True)

    if _df_filt.empty:
        st.warning(
            f'⚠️ 條件過嚴：殖利率 ≥ {_min_yield}% 且本益比 ≤ {_max_pe} '
            f'查無任何標的，請放寬條件'
        )
        return

    # ── ③ 候選清單 ────────────────────────────────────────
    st.markdown(f'#### 📋 候選清單（共 **{len(_df_filt)}** 檔通過篩選）')
    st.dataframe(
        _df_filt, use_container_width=True, hide_index=True,
        column_config={
            '代碼':       st.column_config.TextColumn('代碼',  width='small'),
            '名稱':       st.column_config.TextColumn('名稱',  width='medium'),
            '本益比':     st.column_config.NumberColumn('本益比', format='%.2f'),
            '殖利率(%)':  st.column_config.NumberColumn('殖利率', format='%.2f%%'),
            '股價淨值比': st.column_config.NumberColumn('PBR',   format='%.2f'),
        },
    )

    # ── ④ 單檔深度檢驗 ────────────────────────────────────
    st.markdown('---')
    st.markdown('#### 🔍 單檔深度檢驗（配息歷史）')
    st.caption('從候選清單下拉選擇 **或** 直接輸入代號（含不在清單內的股票，例：6770）')

    _options  = [f'{r["代碼"]} {r["名稱"]}' for _, r in _df_filt.iterrows()]
    _opt_none = '— 請選擇 —'
    _sel_col, _input_col = st.columns([2, 1])
    with _sel_col:
        _sel = st.selectbox(
            '從候選清單選擇',
            [_opt_none] + _options,
            key='ys_sel'
        )
    with _input_col:
        _typed = st.text_input(
            '或輸入代號',
            value='',
            key='ys_typed',
            placeholder='例：6770'
        )

    _ticker = ''
    if _typed.strip():
        _ticker = _typed.strip().split()[0]
    elif _sel and _sel != _opt_none:
        _ticker = _sel.split()[0]

    if not _ticker:
        st.info('💡 從上方表格挑一檔，或直接輸入代號（如 6770）查看歷史配息')
        return

    # ── ⑤ 抓配息歷史 ─────────────────────────────────────
    _disp_name = _ticker
    _row_match = _df_all[_df_all['代碼'] == _ticker]
    if not _row_match.empty:
        _disp_name = f'{_ticker} {_row_match.iloc[0]["名稱"]}'

    st.markdown(f'##### 📊 {_disp_name} — 歷史配息（近 10 年）')
    with st.spinner(f'正在抓取 {_ticker} 配息資料…'):
        _div_series = fetch_dividend_history(_ticker)

    if _div_series.empty:
        st.warning(
            f'⚠️ **該標的近期無穩定配息資料**\n\n'
            f'`{_ticker}` 在 yfinance 查無配息記錄。常見原因：\n'
            f'- 公司歷年虧損 / 配息斷層（如 6770 力積電部分年度）\n'
            f'- 新上市未滿一年\n'
            f'- 代號錯誤或非台股上市公司\n'
            f'- yfinance 海外資料源延遲'
        )
        return

    # 只保留近 10 年
    _div_recent = _div_series.tail(10)

    # ⑤a 長條圖
    _chart_df = pd.DataFrame({'年度': _div_recent.index.astype(str),
                              '現金配息(元)': _div_recent.values})
    st.bar_chart(_chart_df.set_index('年度'), use_container_width=True)

    # ⑤b 統計摘要
    _years_paid = int((_div_recent > 0).sum())
    _avg_div    = float(_div_recent.mean())
    _max_div    = float(_div_recent.max())
    _last_div   = float(_div_recent.iloc[-1]) if len(_div_recent) else 0.0
    _stat_c1, _stat_c2, _stat_c3, _stat_c4 = st.columns(4)
    with _stat_c1:
        st.metric('近 10 年配息年數', f'{_years_paid} 年')
    with _stat_c2:
        st.metric('平均配息', f'{_avg_div:.2f} 元')
    with _stat_c3:
        st.metric('歷史最高配息', f'{_max_div:.2f} 元')
    with _stat_c4:
        st.metric('最近一年', f'{_last_div:.2f} 元')

    # ⑤c 穩定度評等
    if _years_paid >= 8:
        st.success(f'✅ 近 10 年配息 {_years_paid} 年（≥8 年），配息穩定度極佳')
    elif _years_paid >= 5:
        st.success(f'✅ 近 10 年配息 {_years_paid} 年（≥5 年），配息穩定度佳')
    elif _years_paid >= 3:
        st.warning(f'🟡 近 10 年配息 {_years_paid} 年（3–4 年），穩定度中等，需再觀察')
    else:
        st.error(f'🔴 近 10 年配息僅 {_years_paid} 年（<3 年），配息不穩定，存股風險高')

    # ⑤d 原始資料表
    with st.expander('📑 原始配息資料表', expanded=False):
        _raw_df = pd.DataFrame({
            '年度': _div_recent.index.astype(int),
            '現金配息(元)': _div_recent.round(4).values,
        })
        st.dataframe(_raw_df, use_container_width=True, hide_index=True)
