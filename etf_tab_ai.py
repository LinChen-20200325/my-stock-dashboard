"""ETF AI 首席顧問 TAB — 對齊「總經 AI」風格的 Markdown 戰情報告

依賴策略
========
- Top-level: streamlit
- 函式內 late import：
  * etf_dashboard.py 內部 helper: MACRO_ALLOC, _fetch_news_for, macro_allocation_banner

呼叫端
======
- app.py 經 etf_dashboard re-export 取用
"""
from __future__ import annotations

import streamlit as st


def render_etf_ai(gemini_fn=None):
    from etf_dashboard import MACRO_ALLOC, _fetch_news_for, macro_allocation_banner

    mkt_info = st.session_state.get('mkt_info', {})
    regime   = mkt_info.get('regime', 'neutral')
    macro_allocation_banner(regime)

    st.markdown('### 🤖 ETF AI 首席策略師')
    st.caption('依組合配置 + 健康燈號 + 回測 + 總經 + 新聞，生成結構化戰情報告。'
               '個股的 AI 評斷請至「🔬 個股」Tab，本區聚焦 ETF 組合層級決策。')

    # ── 讀取資料（不再讀 etf_single_data，個股有自己的 AI）──────
    port_d     = st.session_state.get('etf_portfolio_data')
    backtest_d = st.session_state.get('etf_backtest_data')

    if not port_d:
        st.info(
            '📋 尚未載入組合資料\n\n'
            '請先到上方「📋 輸入持股組合」區塊輸入持股並點「計算組合」，'
            'AI 首席策略師會根據你的真實持股 + 健康燈號 + 總經狀態給出組合層級建議。'
        )
        # 自由提問仍開放（無持股也能問通用問題）
        _render_free_qa(gemini_fn)
        return

    # ── 顯示生成按鈕（不再有 dataframe 摘要表，避免雜訊）──────
    st.markdown(
        f'<div style="background:#0d1117;border-left:3px solid #76e3ea;padding:10px 14px;'
        f'border-radius:0 6px 6px 0;margin:8px 0;font-size:12px;color:#c9d1d9;">'
        f'📊 將分析 <b>{len(port_d.get("rows", []))} 檔持股</b> '
        f'｜總現值 <b>{port_d.get("total_value", 0):,.0f} 元</b>'
        f'｜總經狀態 <b>{regime}</b>'
        + (f'｜回測 CAGR <b>{backtest_d["cagr"]:.1f}%</b> / Sharpe <b>{backtest_d["sharpe"]:.2f}</b>'
           if backtest_d else '')
        + '</div>', unsafe_allow_html=True)

    if st.button('🤖 生成 ETF 組合戰情研判報告', key='etf_ai_comp_btn',
                 use_container_width=True, type='primary'):
        if not gemini_fn:
            st.warning('⚠️ 請設定 GEMINI_API_KEY 才能使用 AI 功能')
        else:
            _generate_report(gemini_fn, port_d, backtest_d, regime, MACRO_ALLOC,
                             _fetch_news_for, mkt_info)

    # ── 顯示已生成報告 ────────────────────────────────────────
    saved = st.session_state.get('etf_ai_comp_result')
    if saved:
        st.markdown('---')
        st.markdown(
            '<div style="margin:14px 0 8px;padding:8px 16px;'
            'background:linear-gradient(90deg,#76e3ea18,#0d1117);'
            'border-left:4px solid #76e3ea;border-radius:0 6px 6px 0;">'
            '<span style="font-size:15px;font-weight:900;color:#76e3ea;">'
            '📊 AI 組合戰情研判報告</span></div>',
            unsafe_allow_html=True)
        st.markdown(saved)
        if st.button('🔄 清除結果', key='etf_ai_comp_clear'):
            st.session_state.pop('etf_ai_comp_result', None)
            st.rerun()

    _render_free_qa(gemini_fn)


def _generate_report(gemini_fn, port_d, backtest_d, regime, MACRO_ALLOC,
                     fetch_news_fn, mkt_info):
    """組裝 Markdown prompt 並呼叫 Gemini 生成結構化戰情報告。"""
    rows     = port_d.get('rows', [])
    war_rows = port_d.get('war_rows', [])
    rebal    = port_d.get('rebal_actions', [])

    # ── 持股明細（含資本利得、配息、role）─────────────────────
    _hold_lines = []
    for r in rows:
        _hold_lines.append(
            f'  - {r["ticker"]} ({r.get("role","—")})：'
            f'持有 {int(r.get("shares",0)):,} 股｜均價 {r.get("avg_price",0):.2f}｜'
            f'現價 {r.get("current_price",0):.2f}｜'
            f'資本利得 {r.get("capital_gain_pct",0):+.2f}%（{r.get("capital_gain",0):+,.0f}元）｜'
            f'近1年已領配息 {r.get("dividend_received",0):,.0f}元｜'
            f'希望比例 {r.get("target_pct",0):.1f}% / 實際 {r.get("actual_pct",0):.1f}%'
            f'（偏離 {r.get("deviation",0):+.1f}pp）'
        )
    _hold_str = '\n'.join(_hold_lines) if _hold_lines else '（無持股）'

    # ── 健康燈號 + 動作建議（來自 _compute_etf_warroom_row）────
    _war_lines = []
    for w in war_rows:
        _war_lines.append(
            f'  - {w.get("代號","?")}：健康燈號 {w.get("健康燈號","—")}｜'
            f'σ位階 {w.get("σ位階","—")}｜'
            f'距MA20 {w.get("距月線%","—")}%｜距MA60 {w.get("距季線%","—")}%｜'
            f'折溢價 {w.get("折溢價%","—")}%｜年化配息率 {w.get("年化配息率%","—")}%｜'
            f'1年含息報酬 {w.get("1年含息報酬%","—")}%｜'
            f'動作建議：{w.get("動作建議","—")}'
        )
    _war_str = '\n'.join(_war_lines) if _war_lines else '（無健檢資料）'

    # ── 再平衡指令 ────────────────────────────────────────────
    _rebal_str = '；'.join(
        f'{a["動作"]} {a["ETF"]} {a["金額(元)"]:,.0f}元（偏離 {a["偏離度%"]:+.1f}%）'
        for a in rebal) if rebal else '無需再平衡'

    # ── 回測（可選）──────────────────────────────────────────
    _bt_str = '（尚未執行回測）'
    if backtest_d:
        _w_txt = ', '.join(f'{t}:{w*100:.0f}%' for t, w in backtest_d['weights'].items())
        _bt_str = (
            f'期間 {backtest_d["period"]}｜權重 {_w_txt}｜'
            f'CAGR {backtest_d["cagr"]:.2f}%｜Sharpe {backtest_d["sharpe"]:.2f}｜'
            f'MDD {backtest_d["mdd"]:.2f}%｜年化波動率 {backtest_d["vol"]:.2f}%'
        )

    # ── 總經數據快照 ─────────────────────────────────────────
    _macro_lines = [f'• 大盤狀態：{regime}']
    _alloc = MACRO_ALLOC.get(regime, {})
    if _alloc:
        _macro_lines.append(
            f'• regime 建議配置：股票型 {_alloc.get("股票型ETF",0)}% / '
            f'債券型 {_alloc.get("債券型ETF",0)}% / 現金 {_alloc.get("貨幣/現金",0)}%'
        )
    for _k, _v in mkt_info.items():
        if _k in ('regime', 'exposure_pct'):
            continue
        if isinstance(_v, (int, float)):
            _macro_lines.append(f'• {_k}: {_v}')
    _macro_str = '\n'.join(_macro_lines)

    # ── 為每檔 ETF 抓近期新聞（最多前 4 檔，各 2 則）────────
    _news_lines = []
    for r in rows[:4]:
        _tk = r.get('ticker', '')
        _nn = fetch_news_fn(_tk, _tk, 2)
        if _nn and _nn != '（暫無相關新聞）':
            _news_lines.append(f'[{_tk}]\n{_nn}')
    _news_str = '\n\n'.join(_news_lines) if _news_lines else '（暫無相關新聞）'

    # ── 組裝 Markdown prompt（對齊總經 AI 風格）───────────────
    prompt = (
        '你是一位擁有 20 年台股 ETF 與資產配置經驗的「台股AI戰情室」首席 ETF 策略師。'
        '你的分析風格冷靜、精準，強調風險控管與紀律換股。\n\n'

        '## 資訊隔離約束（絕對遵守）\n'
        '- 禁止使用預訓練知識中的具體數字，所有解讀必須 100% 基於下方 Input Data\n'
        '- 「需要更換的 ETF」段落必須具體點出持股中的代號（因這是使用者自己的組合）\n'
        '- 但「替代方向」只能以類別 / 屬性描述（如「轉向低波動高股息台股 ETF」），不指定具體新 ticker\n'
        '- 數字直接引用 Input Data，禁止四捨五入或虛構\n\n'

        '## 🚨 系統性風險前置檢核（最高優先級，先掃再寫）\n'
        '掃描【近期 ETF 新聞】是否命中黑天鵝關鍵字：\n'
        '  • 戰爭/軍事衝突/飛彈/制裁/sanctions\n'
        '  • 升降息/央行緊急政策/emergency rate\n'
        '  • 金融危機/銀行倒閉/bank run/bailout\n'
        '  • 主權違約/sovereign default/信評降等\n'
        '若任一新聞命中，在報告開頭加 `🚨 系統性風險警報觸發` 紅色橫幅，'
        '並在「警示旗語」首位列出觸發新聞與其對此組合的傳導路徑。\n\n'

        '## Input Data\n\n'

        f'### 【總經狀態與規則引擎建議配置】\n{_macro_str}\n\n'

        f'### 【持股明細】共 {len(rows)} 檔｜總現值 {port_d.get("total_value",0):,.0f} 元'
        f'｜壓力測試（S&P -20%）預估損失 {port_d.get("loss_pct",0):.1f}%\n'
        f'{_hold_str}\n\n'

        f'### 【ETF 健檢燈號（核衛分流邏輯）】\n'
        f'核心資產判讀：🔴 賺息賠本（總報酬<殖利率，換股）｜🟡 趨勢轉弱（跌破 MA60）｜🟢 體質健康\n'
        f'衛星資產判讀：🟢🟢🟢 股災價（<-3σ 大買50%）｜🟢🟢 超跌(<-2σ 買30%)｜🟢 便宜(<-1σ 買20%)｜🔴 停利(≥+2σ)\n'
        f'{_war_str}\n\n'

        f'### 【再平衡指令】\n{_rebal_str}\n\n'

        f'### 【回測績效】\n{_bt_str}\n\n'

        f'### 【近期 ETF 新聞】\n{_news_str}\n\n'

        '## 輸出格式\n'
        '使用 Markdown 語法，生成以下結構的 ETF 組合戰情研判報告：\n\n'

        '## 📊 ETF 組合戰情研判報告\n\n'

        '### 一、組合健康度五維診斷（0-10 評分）\n'
        '- **核衛分散度**：（得分/10，依 role 比例與 regime 目標差距）\n'
        '- **資產類別覆蓋**：（得分/10，股/債/現金/海外的多元程度）\n'
        '- **個股集中風險**：（得分/10，單一 ETF 占比是否過高，>30% 扣分）\n'
        '- **配息穩定度**：（得分/10，依已領配息 + 月配覆蓋）\n'
        '- **回測風報比**：（得分/10，依 CAGR/Sharpe/MDD，無回測資料則註明 N/A）\n\n'

        '### 二、核心洞察（50 字以內）\n'
        '（當前組合最大優勢與最大盲點，一句話結論）\n\n'

        '### 三、現金流分析\n'
        '- **已領配息**：（彙總所有持股近 1 年配息）\n'
        '- **預估年現金流**：（用持股股數 × 年化配息率推估）\n'
        '- **現金流穩健度**：（是否依賴單一檔，月份覆蓋是否分散）\n\n'

        '### 四、需要更換的 ETF（基於健康燈號邏輯）\n'
        '針對所有「🔴 賺息賠本」/「🔴 停利」/「🟡 趨勢轉弱」/「破發/溢價過高」的持股：\n'
        '- **標的**：（具體代號）\n'
        '- **為什麼換**：（引用 Input Data 中該檔的具體數據，如「資本利得 -32.5%、總報酬<殖利率」）\n'
        '- **換成什麼方向**：（類別屬性，如「轉向低波動高股息台股 ETF」「移至投資級美債」，不點 ticker）\n'
        '- **何時換**：（搭配 regime + 新聞時間窗，給出觸發條件，如「待 KD<20 反彈時換手」）\n'
        '若全部持股健康（無 🔴/⛔/破發），明確寫「✅ 目前所有持股健康燈號正常，無需換股」。\n\n'

        '### 五、整體資產配置建議\n'
        '- **核衛比現況 vs 目標**：（比較實際 role 比例與 regime 目標）\n'
        '- **資產類別缺口**：（股/債/現金哪邊超標、哪邊不足）\n'
        '- **補強方向**：（不點具體 ticker，只給方向，如「增加 5-10% 投資級美債部位」）\n\n'

        '### 六、警示旗語\n'
        '（列出可能破壞此組合假設的風險因子：總經逆風、單檔黑天鵝、新聞中的負面事件）\n\n'

        '### 結語\n'
        '⚠️ 本報告僅供學術研究與教育用途，非投資建議，盈虧自負。'
        '所有換股 / 配置建議須結合個人風險承受度與資金狀況自行判斷。\n\n'

        '【語言規範】統一使用繁體中文。引用數字必須與 Input Data 完全一致。'
    )

    with st.spinner('AI 首席策略師生成戰情報告中（約 8-12 秒）...'):
        result = gemini_fn(prompt, max_tokens=2200)
    if result and not result.startswith('⚠️'):
        st.session_state['etf_ai_comp_result'] = result
        st.rerun()
    else:
        st.error(result or 'AI 回傳為空，請確認 GEMINI_API_KEY')


def _render_free_qa(gemini_fn):
    """ETF 自由提問區（不需先載入組合資料）"""
    st.markdown('---')
    st.markdown('#### 💬 ETF 自由提問')
    st.caption('不需先載入組合，直接輸入任何 ETF 相關問題（適合策略諮詢、新標的研究）。')
    question = st.text_area(
        '輸入問題', height=80, key='etf_ai_question',
        placeholder='例如：台灣高股息 ETF 和美國債券 ETF 如何搭配？升息循環尾聲該加碼長債嗎？')
    if st.button('💬 提問', key='etf_ai_ask_btn', use_container_width=True):
        if not question.strip():
            st.warning('請輸入問題')
        elif not gemini_fn:
            st.warning('⚠️ 請設定 GEMINI_API_KEY')
        else:
            q_prompt = (
                f'你是 ETF 投資教育顧問，以春哥 VCP、郭俊宏以息養股、孫慶龍 7% 估值框架回答，'
                f'不超過 300 字，嚴禁捏造數據：\n\n問題：{question}\n'
                f'⚠️ 僅供學術研究，非投資建議'
            )
            with st.spinner('AI 回答中...'):
                answer = gemini_fn(q_prompt, max_tokens=600)
            if answer and not answer.startswith('⚠️'):
                st.markdown(answer)
            else:
                st.warning(answer or 'AI 回傳為空')
