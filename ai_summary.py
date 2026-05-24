"""ai_summary.py — 🤖 統一「AI 智能解盤模組」(v5.0 Core Task 3)

設計：每個 Tab 最下方統一呼叫 `render_ai_summary()`：
    資料收集器（caller 傳入畫面上已有數據，不重抓）
    → fetch_latest_news(ticker)（時事新聞，FinMind TaiwanStockNews，失敗優雅降級）
    → 組 prompt（量化數據 + 新聞標題）
    → gemini_fn(prompt)（LLM）
    → st.success 輸出「綜合解盤報告」（數據解讀 / 新聞情緒 / 客觀總結）

原則
====
- **不重抓**：collector 只整理「已在畫面上的數據」，避免 API 風暴。
- **按鈕觸發**：避免每次 rerun 都打 LLM；結果存 session_state 跨 rerun 保留。
- **新聞可選**：抓不到新聞（premium / 斷線 / 海外 IP）→ 回 []，解盤仍照跑並標「資料不足」。
- **防呆**：無 gemini_fn / 無數據 / LLM 例外 → 友善提示，絕不崩潰。
- **可重用**：`render_ai_summary(tab_name, data, ticker, gemini_fn, key_prefix)` 任何 tab 可呼叫；
  本檔附 `render_stock_ai_summary()` 為「🔬 個股」tab 的 thin collector 範例。
"""
from __future__ import annotations

import streamlit as st


# ══════════════════════════════════════════════════════════════════════════════
# 時事新聞介接 — FinMind TaiwanStockNews（失敗回 []，新聞為可選輸入）
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_latest_news(ticker: str, limit: int = 5) -> list[dict]:
    """抓單檔近期新聞標題（FinMind TaiwanStockNews）。

    Returns:
        list[{'date','title','source','link'}]（由新到舊）；任何失敗一律回 []。
        欄位以啟發式偵測，FinMind schema 變動或免費 token 無此資料集時自動降級。
    """
    import os as _os
    import datetime as _dt
    import requests as _rq

    _tk = ''.join(c for c in str(ticker) if c.isalnum())
    if not _tk:
        return []

    def _g(row: dict, keys: tuple[str, ...]) -> str:
        for k in keys:
            if k in row and row[k] not in (None, ''):
                return str(row[k])
        return ''

    try:
        _tok = _os.environ.get('FINMIND_TOKEN', '')
        _start = (_dt.date.today() - _dt.timedelta(days=14)).strftime('%Y-%m-%d')
        _p = {'dataset': 'TaiwanStockNews', 'data_id': _tk, 'start_date': _start}
        if _tok:
            _p['token'] = _tok
        _r = _rq.get('https://api.finmindtrade.com/api/v4/data',
                     params=_p, timeout=12)
        if _r.status_code != 200:
            return []
        _data = _r.json().get('data', [])
        if not _data:
            return []
        _items = []
        for _row in _data:
            if not isinstance(_row, dict):
                continue
            _title = _g(_row, ('title', 'news_title', 'description'))
            if not _title:
                continue
            _items.append({
                'date':   _g(_row, ('date', 'datetime', 'publish_date')),
                'title':  _title[:120],
                'source': _g(_row, ('source', 'media', 'source_name')),
                'link':   _g(_row, ('link', 'url')),
            })
        _items.sort(key=lambda x: x['date'], reverse=True)
        return _items[:max(1, limit)]
    except Exception as _e:
        print(f'[ai_summary/news] {ticker}: {type(_e).__name__}: {_e}')
        return []


# ══════════════════════════════════════════════════════════════════════════════
# Prompt 生成（純函式，可單測）
# ══════════════════════════════════════════════════════════════════════════════
def _build_prompt(tab_name: str, data: dict, news: list[dict]) -> str:
    """把量化數據 + 新聞標題組成結構化解盤 prompt。"""
    _lines = [f'【{tab_name} — 當前關鍵數據】']
    for _k, _v in data.items():
        _lines.append(f'- {_k}：{_v}')
    if news:
        _lines.append('\n【近期新聞標題（由新到舊）】')
        for _n in news:
            _src = f'（{_n["source"]}）' if _n.get('source') else ''
            _lines.append(f'- ({_n.get("date", "")}) {_n["title"]}{_src}')
    else:
        _lines.append('\n【近期新聞】查無公開新聞資料 — 請於「新聞情緒」段明確標示'
                      '「資料不足」，**嚴禁捏造任何新聞或數據**。')

    return (
        '你是「台股AI戰情室」的首席策略師，擁有 20 年實戰經驗。'
        '請根據以下量化數據與新聞，輸出一段精簡務實的綜合解盤報告'
        '（繁體中文、Markdown、約 250–400 字），嚴禁捏造數據：\n\n'
        + '\n'.join(_lines)
        + '\n\n請務必依序包含以下三段標題：\n'
        '### 📊 數據解讀\n'
        '（綜合健康評分 / 均線趨勢 / 技術指標 / 殖利率，研判目前位階與短中期多空）\n'
        '### 📰 新聞情緒影響\n'
        '（若有新聞 → 判斷偏多 / 偏空 / 中性並說明理由；無新聞 → 明確標「資料不足」）\n'
        '### 🎯 客觀總結\n'
        '（點出觀察重點與主要風險；不直接喊買賣，結尾提醒投資人盈虧自負）'
    )


# ══════════════════════════════════════════════════════════════════════════════
# 通用渲染（任何 tab 可呼叫）
# ══════════════════════════════════════════════════════════════════════════════
def render_ai_summary(tab_name: str, data: dict, ticker: str = '',
                      gemini_fn=None, key_prefix: str = 'ai_sum') -> None:
    """統一 AI 解盤區塊。

    Args:
        tab_name:   顯示用 tab 名（如「個股深掘」）
        data:       {標籤: 值} — caller 收集的畫面上既有關鍵數據（不重抓）
        ticker:     個股代號（有則抓新聞；無則純量化解盤）
        gemini_fn:  gemini_fn(prompt:str) -> str
        key_prefix: 區隔不同 tab 的 widget / session_state key
    """
    st.markdown(f'#### 🤖 AI 智能解盤（{tab_name}）')

    if not data:
        st.info('💡 先在上方載入 / 查詢資料，這裡才會生成 AI 解盤。')
        return

    with st.expander('💡 這份解盤根據哪些數據？', expanded=False):
        for _k, _v in data.items():
            st.markdown(f'- **{_k}**：{_v}')
        st.caption('（以上為目前畫面上的數據快照；AI 會結合近期新聞一起研判。）')

    if not gemini_fn:
        st.warning('⚠️ 未設定 GEMINI_API_KEY，無法生成 AI 解盤（其餘數據與圖表不受影響）。')
        return

    _state_key = f'{key_prefix}_report_{ticker or "_"}'
    if st.button('🤖 生成 AI 綜合解盤報告', key=f'{key_prefix}_btn',
                 use_container_width=True, type='primary'):
        with st.spinner('AI 解盤中（抓新聞 + 分析，約 8–12 秒）...'):
            _news = fetch_latest_news(ticker) if ticker else []
            _prompt = _build_prompt(tab_name, data, _news)
            try:
                _rep = gemini_fn(_prompt)
            except Exception as _e:
                _rep = f'❌ AI 生成失敗：{type(_e).__name__}: {_e}'
            st.session_state[_state_key] = {'report': _rep or '', 'news_n': len(_news)}

    _saved = st.session_state.get(_state_key)
    if _saved:
        if _saved.get('news_n'):
            st.caption(f'📰 已納入 {_saved["news_n"]} 則近期新聞')
        else:
            st.caption('📰 查無新聞資料 — 本次為純量化解盤')
        st.success(_saved.get('report') or '⚠️ AI 回傳為空，請確認 GEMINI_API_KEY')


# ══════════════════════════════════════════════════════════════════════════════
# 「🔬 個股」tab 的 thin collector（範例 / 試點）
# ══════════════════════════════════════════════════════════════════════════════
def _collect_stock_data(t2d: dict) -> dict:
    """從個股 tab 的 session_state['t2_data'] 整理 AI 解盤所需關鍵數據。"""
    _data: dict = {}
    _sid = str(t2d.get('sid', '') or '')
    _name = str(t2d.get('name', '') or '')
    _data['標的'] = f'{_sid} {_name}'.strip()

    _price = t2d.get('price')
    if _price:
        _data['現價'] = f'{float(_price):.2f}'

    _health = t2d.get('health')
    if _health is not None:
        _data['健康評分'] = f'{_health}/100'

    # 健康分數因子標籤（趨勢 / RSI動能 / 量比 / IBS位置 / KD排列 / 布林位置）
    _det = t2d.get('details') or {}
    for _fk, _fv in _det.items():
        if isinstance(_fv, (list, tuple)) and _fv:
            _data[_fk] = str(_fv[0])

    # 技術指標數值（補充因子標籤）
    if t2d.get('rsi') is not None:
        _data['RSI'] = f'{t2d["rsi"]}'
    if t2d.get('k') is not None and t2d.get('d') is not None:
        try:
            _data['KD'] = f'K={float(t2d["k"]):.1f} / D={float(t2d["d"]):.1f}'
        except (TypeError, ValueError):
            pass

    # 殖利率（近年均股利 / 現價）
    _avg_div = t2d.get('avg_div')
    if _avg_div:
        _data['近年均股利'] = f'{float(_avg_div):.2f} 元'
        if _price:
            try:
                _data['估算殖利率'] = f'{float(_avg_div) / float(_price) * 100:.2f}%'
            except (TypeError, ValueError, ZeroDivisionError):
                pass
    return _data


def render_stock_ai_summary(gemini_fn=None) -> None:
    """掛在「🔬 個股」tab 最下方的 AI 解盤（讀 t2_data，不重抓）。"""
    st.markdown('---')
    _t2d = st.session_state.get('t2_data')
    if not _t2d:
        st.markdown('#### 🤖 AI 智能解盤（個股）')
        st.info('💡 先在上方「🔍 載入完整分析」後，這裡會生成個股 AI 綜合解盤。')
        return
    _data = _collect_stock_data(_t2d)
    render_ai_summary('個股深掘', _data, ticker=str(_t2d.get('sid', '') or ''),
                      gemini_fn=gemini_fn, key_prefix='stock_ai')
