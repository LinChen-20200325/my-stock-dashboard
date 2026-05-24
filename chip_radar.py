"""chip_radar.py — 💠 集保籌碼大戶雷達（自建爬蟲版）

資料來源：norway.twsthr.info `StockHolders.aspx?stock={代號}`（集保戶股權分散表，每週更新）

設計重點
========
- 連線：走既有 `proxy_helper.fetch_url()`（NAS Squid Proxy → 自動降級直連 +
  3 次重試 + 20s timeout + Storm Shield 300s 快取），外加隨機 User-Agent 防爬。
- 解析：`pandas.read_html` 取所有表格 → **自適應**用關鍵字偵測「大戶比例 / 散戶人數 /
  日期」欄位（不硬編脆弱欄名，網站改版也能盡量存活）。
- 快取：`@st.cache_data(ttl=86400)` 一日一抓，降低中繼站負擔。
- 防呆：任何失敗一律回「空 df + 錯誤訊息 + 診斷資料」，UI 端顯示提示，**不拋例外、不死迴圈**。
- 診斷：回傳 read_html 原始表格結構（shape / columns / 前幾列），雲端跑一次即可
  讓使用者/開發者看到實際欄位、必要時再把自適應解析改成精準解析。

回傳契約（dict，cache-safe — 不依賴 DataFrame.attrs 在快取後存活）
    {
        'df':        DataFrame（欄位：日期 / 大戶比例 / 散戶人數；失敗為空）,
        'err':       str（''=成功）,
        'tables':    list[dict]（診斷：每個 read_html 表格的 shape/columns/preview）,
        'html_head': str（read_html 失敗時保留 HTML 開頭片段）,
    }
"""
from __future__ import annotations

import streamlit as st
import pandas as pd

TWSTHR_URL = 'https://norway.twsthr.info/StockHolders.aspx?stock={ticker}'

_UA_POOL = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
    '(KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
)


# ══════════════════════════════════════════════════════════════════════════════
# 解析輔助（純函式）
# ══════════════════════════════════════════════════════════════════════════════
def _flatten_cols(df: pd.DataFrame) -> pd.DataFrame:
    """攤平 MultiIndex 欄位成單層字串，並去頭尾空白。"""
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [
            ' '.join(str(x) for x in tup if str(x) not in ('nan', 'None')).strip()
            for tup in out.columns
        ]
    else:
        out.columns = [str(c).strip() for c in out.columns]
    return out


def _to_num(v) -> float:
    """把 '12.3%' / '1,234' / ' 56 ' 之類字串轉為 float；無法解析回 NaN。"""
    import re as _re
    s = str(v).strip()
    if not s or s.lower() in ('nan', 'none', '-', '--'):
        return float('nan')
    s = _re.sub(r'[^0-9.\-]', '', s)
    if s in ('', '-', '.', '-.'):
        return float('nan')
    try:
        return float(s)
    except ValueError:
        return float('nan')


def _find_col(cols: list[str], keywords: tuple[str, ...]) -> str | None:
    for c in cols:
        if any(k in str(c) for k in keywords):
            return c
    return None


def _find_major_col(cols: list[str]) -> str | None:
    """大戶持股『比例』欄：優先同時含大戶關鍵字 + 比例/率/% 字樣，再退而求其次。"""
    _major = ('大股東', '大戶', '400張', '1000張', '千張', '集中')
    _ratio = ('比例', '率', '%', '占', '佔', '百分比', '百分點')
    # pass1：大戶 + 比例
    for c in cols:
        cl = str(c)
        if any(m in cl for m in _major) and any(r in cl for r in _ratio):
            return c
    # pass2：純大戶關鍵字（可能就是比例欄）
    return _find_col(cols, _major)


def _parse_date_series(s: pd.Series) -> pd.Series:
    """盡量把日期欄轉 datetime：先一般解析，命中率低時退 %Y%m%d（純數字）。"""
    raw = s.astype(str).str.strip()
    out = pd.to_datetime(raw, errors='coerce')
    if out.notna().sum() < max(1, len(raw)) * 0.5:
        digits = raw.str.replace(r'[^0-9]', '', regex=True)
        out2 = pd.to_datetime(digits, format='%Y%m%d', errors='coerce')
        if out2.notna().sum() > out.notna().sum():
            out = out2
    return out


def _adaptive_parse(tables: list[pd.DataFrame]) -> pd.DataFrame:
    """從 read_html 的多個表格中挑最像「股權分散時序」的一張並抽三欄。

    回傳欄位：日期 / 大戶比例 / 散戶人數（缺的欄補 NaN）；找不到回空 DataFrame。
    """
    best = None
    best_score = -1.0
    for t in tables:
        if t is None or getattr(t, 'empty', True) or t.shape[1] < 2:
            continue
        ft = _flatten_cols(t)
        # read_html 未抓到表頭時欄名是整數索引（'0','1',…）→ 用第一列當表頭
        # （twsthr 時間序列表即此情況，真實欄名「資料日期 / >400張大股東持有百分比」在首列）
        if len(ft) >= 2 and all(str(c).strip().isdigit() for c in ft.columns):
            ft = ft.copy()
            ft.columns = [str(x).strip() for x in ft.iloc[0].tolist()]
            ft = ft.iloc[1:].reset_index(drop=True)
        cols = list(ft.columns)
        c_major = _find_major_col(cols)
        c_retail = _find_col(cols, ('股東人數', '散戶', '50張', '人數'))
        if not (c_major or c_retail):
            continue
        c_date = _find_col(cols, ('日期', '週', 'date', '時間')) or cols[0]
        # 有效日期比例（時間序列指標）— 分級分佈表/雜訊無有效日期，會被壓低分數
        _date_valid = 0.0
        if c_date in ft.columns:
            _dts = _parse_date_series(ft[c_date])
            _date_valid = float(_dts.notna().mean()) if len(_dts) else 0.0
        # 評分：有效日期(時序) > 大戶比例 > 散戶人數 > 列數
        score = (_date_valid * 3.0 + (2.0 if c_major else 0)
                 + (1.0 if c_retail else 0) + min(len(ft), 300) / 1000.0)
        if score > best_score:
            best_score = score
            best = (ft, c_date, c_major, c_retail)

    if best is None:
        return pd.DataFrame()

    ft, c_date, c_major, c_retail = best
    out = pd.DataFrame()
    out['日期'] = _parse_date_series(ft[c_date]) if c_date in ft.columns else pd.NaT
    out['大戶比例'] = ft[c_major].map(_to_num) if c_major else float('nan')
    out['散戶人數'] = ft[c_retail].map(_to_num) if c_retail else float('nan')

    # 清洗：丟掉兩個數值都缺的列；日期缺的列也丟
    out = out.dropna(how='all', subset=['大戶比例', '散戶人數'])
    if out['日期'].notna().any():
        out = out.dropna(subset=['日期']).sort_values('日期')
    out = out.reset_index(drop=True)
    return out


def _table_diag(tables: list[pd.DataFrame]) -> list[dict]:
    """壓縮成可快取的輕量診斷結構（shape / columns / 前 5 列）。"""
    diag = []
    for i, t in enumerate(tables):
        try:
            ft = _flatten_cols(t)
            diag.append({
                'idx': i,
                'shape': list(t.shape),
                'columns': [str(c) for c in ft.columns][:30],
                'preview': ft.head(5),
            })
        except Exception:
            diag.append({'idx': i, 'shape': list(getattr(t, 'shape', [0, 0])),
                         'columns': [], 'preview': pd.DataFrame()})
    return diag


# ══════════════════════════════════════════════════════════════════════════════
# 核心抓取（@st.cache_data — 回 dict，cache-safe）
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def fetch_chip_concentration(ticker: str) -> dict:
    """抓集保股權分散表並自適應解析。失敗回空 df + 錯誤訊息（不拋例外）。"""
    import io as _io
    import random as _rnd

    _empty = {'df': pd.DataFrame(), 'err': '', 'tables': [], 'html_head': ''}

    _tk = ''.join(c for c in str(ticker) if c.isalnum()).strip()
    if not _tk:
        _empty['err'] = '股票代號為空'
        return _empty

    _url = TWSTHR_URL.format(ticker=_tk)
    try:
        from proxy_helper import fetch_url
        _resp = fetch_url(_url, headers={'User-Agent': _rnd.choice(_UA_POOL)},
                          timeout=15, attempts=3)
    except Exception as _fe:
        _empty['err'] = f'連線例外（已重試）：{type(_fe).__name__}: {_fe}'
        return _empty

    if _resp is None:
        _empty['err'] = 'NAS 代理與直連皆失敗（重試 3 次後回空）'
        return _empty
    if getattr(_resp, 'status_code', 0) != 200:
        _empty['err'] = f'HTTP 非 200（status={getattr(_resp, "status_code", None)}）— 網站/代理異常'
        return _empty

    # ── 解碼（先 .text，過短再嘗試多編碼）──
    try:
        _html = _resp.text or ''
        if len(_html) < 200 and getattr(_resp, 'content', None):
            for _enc in ('utf-8', 'big5', 'cp950'):
                try:
                    _html = _resp.content.decode(_enc)
                    break
                except Exception:
                    continue
    except Exception:
        _empty['err'] = '回應內容解碼失敗'
        return _empty

    if not _html or len(_html) < 50:
        _empty['err'] = '回應內容為空或過短'
        return _empty

    # ── read_html ──
    try:
        _tables = pd.read_html(_io.StringIO(_html))
    except ValueError:
        _empty['err'] = 'pandas.read_html 在頁面找不到任何 HTML 表格（網站可能改版或回了錯誤頁）'
        _empty['html_head'] = _html[:600]
        return _empty
    except Exception as _pe:
        _empty['err'] = f'read_html 例外：{type(_pe).__name__}: {_pe}'
        _empty['html_head'] = _html[:600]
        return _empty

    if not _tables:
        _empty['err'] = 'read_html 回傳空清單'
        _empty['html_head'] = _html[:600]
        return _empty

    _parsed = _adaptive_parse(_tables)
    _diag = _table_diag(_tables)
    _err = '' if not _parsed.empty else \
        '找到表格但無法辨識「大戶比例 / 散戶人數」欄位 — 請展開下方診斷面板看實際欄位結構'
    return {'df': _parsed, 'err': _err, 'tables': _diag, 'html_head': ''}


# ══════════════════════════════════════════════════════════════════════════════
# Streamlit UI
# ══════════════════════════════════════════════════════════════════════════════
def _plot_chip(df: pd.DataFrame, ticker: str) -> None:
    """Plotly 雙 Y 軸：左=散戶人數(bar)、右=大戶比例(line)。"""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    _fig = make_subplots(specs=[[{'secondary_y': True}]])
    _has_retail = df['散戶人數'].notna().any()
    _has_major = df['大戶比例'].notna().any()
    _x = df['日期'] if df['日期'].notna().any() else list(range(len(df)))

    if _has_retail:
        _fig.add_trace(
            go.Bar(x=_x, y=df['散戶人數'], name='散戶持股人數',
                   marker_color='#4a9eff', opacity=0.55),
            secondary_y=False)
    if _has_major:
        _fig.add_trace(
            go.Scatter(x=_x, y=df['大戶比例'], name='大戶持股比例 (%)',
                       mode='lines+markers',
                       line=dict(color='#ff6b6b', width=2)),
            secondary_y=True)

    _fig.update_layout(
        title=f'{ticker} 集保籌碼分布（散戶人數 vs 大戶比例）',
        height=440, hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(t=60, b=40, l=10, r=10))
    _fig.update_yaxes(title_text='散戶持股人數', secondary_y=False)
    _fig.update_yaxes(title_text='大戶持股比例 (%)', secondary_y=True)
    st.plotly_chart(_fig, use_container_width=True)


def _render_diag(result: dict) -> None:
    """解析診斷面板：read_html 原始表格結構（供雲端對齊欄位）。"""
    with st.expander('🔬 解析診斷（read_html 原始結構）', expanded=False):
        if result.get('html_head'):
            st.caption('HTML 開頭片段（read_html 失敗時保留）：')
            st.code(result['html_head'][:600])
        _tables = result.get('tables') or []
        if not _tables:
            st.info('無原始表格資料（多半是連線階段就失敗，未進到 read_html）。')
            return
        st.caption(f'read_html 共解析到 **{len(_tables)}** 個表格：')
        for _t in _tables:
            st.markdown(f"**表 #{_t['idx']}** — shape = {tuple(_t['shape'])}")
            if _t.get('columns'):
                st.write('欄位：', _t['columns'])
            _pv = _t.get('preview')
            if isinstance(_pv, pd.DataFrame) and not _pv.empty:
                st.dataframe(_pv, use_container_width=True, hide_index=True)


def render_chip_radar(ticker: str = '') -> str:
    """💠 集保籌碼大戶雷達。

    ticker 由呼叫端（個股 tab 主代碼 sid2）帶入，不再自建輸入框。
    回傳一段給「AI 首席顧問總結」引用的籌碼摘要字串（無資料回 ''）。
    """
    st.markdown('### 💠 集保籌碼大戶雷達')
    st.caption('資料來源：norway.twsthr.info 集保戶股權分散表（每週更新）；隨上方個股代碼自動查詢。')

    _tk = ''.join(c for c in str(ticker) if c.isalnum())
    if not _tk:
        st.info('💡 請在最上方輸入個股代碼並「載入完整分析」，這裡會自動顯示該檔集保籌碼。')
        return ''

    with st.spinner(f'抓取 {_tk} 集保股權分散表中…（NAS 代理 + 3 次重試）'):
        _result = fetch_chip_concentration(_tk)

    _df = _result.get('df', pd.DataFrame())
    _err = _result.get('err', '')

    if _df is None or _df.empty:
        st.warning('⚠️ 無法解析籌碼資料，請確認目標網站結構或連線狀態')
        if _err:
            st.caption(f'🛈 診斷訊息：{_err}')
        if st.button('🗑️ 清快取重試', key='chip_radar_clear'):
            fetch_chip_concentration.clear()
            st.rerun()
        _render_diag(_result)
        return ''

    # ── 摘要 metric ──
    _latest = _df.iloc[-1]
    _m1, _m2, _m3 = st.columns(3)
    with _m1:
        _d = _latest['日期']
        st.metric('最新資料日', _d.strftime('%Y-%m-%d') if pd.notna(_d) else '—')
    with _m2:
        _mj = _latest['大戶比例']
        st.metric('大戶持股比例', f'{_mj:.2f}%' if pd.notna(_mj) else '—')
    with _m3:
        _rt = _latest['散戶人數']
        st.metric('散戶持股人數', f'{int(_rt):,}' if pd.notna(_rt) else '—')

    # ── 雙 Y 軸圖 ──
    _plot_chip(_df, _tk)

    with st.expander('📑 原始解析資料表', expanded=False):
        st.dataframe(_df, use_container_width=True, hide_index=True)

    _render_diag(_result)

    # ── 給「AI 首席顧問總結」引用的籌碼摘要字串 ──
    _summary = ''
    try:
        _bits = []
        _mj_v = _latest['大戶比例']
        _rt_v = _latest['散戶人數']
        if pd.notna(_mj_v):
            _trend = ''
            if len(_df) >= 5 and pd.notna(_df['大戶比例'].iloc[-5]):
                _delta = float(_mj_v) - float(_df['大戶比例'].iloc[-5])
                _trend = f'（近5期{"↑增" if _delta > 0 else "↓減" if _delta < 0 else "持平"}{_delta:+.2f}%）'
            _bits.append(f'集保大戶持股比例={float(_mj_v):.2f}%{_trend}')
        if pd.notna(_rt_v):
            _bits.append(f'散戶人數={int(_rt_v):,}')
        if _bits:
            _summary = '集保籌碼：' + ' | '.join(_bits)
    except Exception:
        _summary = ''
    return _summary
