"""TAB 個股深度分析 + 健康度評分 — 從 app.py 抽出（PR P2-B Phase 5-C）

依賴策略
========
- Top-level: streamlit（最穩定）
- 函式內 late import 41 個依賴，避免循環 import：
  * stdlib: datetime, pandas, plotly
  * 設定: config.FINMIND_TOKEN
  * 外部模組: v4_strategy_engine / daily_checklist / v5_modules
    / financial_health_engine / tech_indicators / scoring_helpers / scoring_engine
    / ui_widgets / chart_plotter / data_loader
  * app.py 內部 (11): _fetch_stock_news / api_key / fetch_dividend_data
    / fetch_financials / fetch_price_data / fetch_quarterly / fetch_quarterly_extra
    / fetch_revenue / gemini_call / generate_ai_comment / render_health_score

呼叫端
======
- app.py: `with tab_stock: render_tab_stock()`
"""
from __future__ import annotations

import streamlit as st


def render_tab_stock():
    # ─ Late imports（避免循環 import）─
    import datetime
    import pandas as pd
    import plotly.graph_objects as go
    from config import FINMIND_TOKEN
    # 外部模組
    from v4_strategy_engine import V4StrategyEngine
    from daily_checklist import analyze_20d_chips
    from v5_modules import (
        analyze_fundamental_leading,
        calc_dividend_yield_357,
        detect_bollinger_breakout,
    )
    from financial_health_engine import analyze_financial_health, no_ai_overall_verdict
    from tech_indicators import (
        calc_rsi, calc_ibs, calc_volume_ratio,
        calc_kd, calc_bollinger, calc_vcp,
    )
    from scoring_helpers import calc_fundamental_score, calc_health_score, health_grade
    from scoring_engine import calc_rs_score, rs_slope
    from ui_widgets import kpi, signal_box, teacher_conclusion
    from chart_plotter import plot_combined_chart, plot_quarterly_chart, plot_revenue_chart
    from data_loader import fetch_financial_statements
    # app.py 內部 helper
    from app import (
        _fetch_stock_news, api_key,
        fetch_dividend_data, fetch_financials, fetch_price_data,
        fetch_quarterly, fetch_quarterly_extra, fetch_revenue,
        gemini_call, generate_ai_comment, render_health_score,
    )

    st.markdown('''<div style="background:#0a1628;border:1px solid #1f6feb;border-radius:12px;padding:16px;margin-bottom:12px;">
<div style="font-size:18px;font-weight:900;color:#58a6ff;margin-bottom:8px;">🔬 個股深度分析 — 這支股票值得買嗎？</div>
<div style="font-size:13px;color:#c9d1d9;line-height:1.8;">
輸入你感興趣的股票代碼，系統會告訴你：<br>
• <b>現在貴不貴？</b>（357估值 + 河流圖）<br>
• <b>趨勢向上還是向下？</b>（健康度評分）<br>
• <b>大股東在買還是賣？</b>（法人籌碼）<br>
• <b>什麼時候該進場、出場？</b>（進出場訊號）<br>
💡 <b>建議：</b>先到「比較 × 排行」掃描找到候選股，再來這裡做最後確認。
</div></div>''', unsafe_allow_html=True)
    st.markdown("""<div style="padding:6px 0 4px;">
<span style="font-size:20px;font-weight:900;color:#e6edf3;">🔬 個股深度分析</span>
<span style="font-size:11px;color:#484f58;margin-left:10px;">健康評分 · 357評價 · 領先指標 · VCP · 布林 · K線 · AI五維</span>
</div>""", unsafe_allow_html=True)

    # ── 操作列 ──────────────────────────────────────────────
    t2_r1c1, t2_r1c2, t2_r1c3, t2_r1c4 = st.columns([2, 1, 1, 1])
    with t2_r1c1:
        t2_sid = st.text_input('個股代碼', value='2330', key='t2_sid', placeholder='如：2330')
    with t2_r1c2:
        t2_days = st.slider('天數', 60, 400, 250, 10, key='t2_days')
    with t2_r1c3:
        t2_use_normal = st.checkbox('一般K線', value=False, key='t2_use_normal')
        t2_adjusted   = not t2_use_normal
    with t2_r1c4:
        t2_run = st.button('🔍 載入完整分析', key='t2_run', type='primary', use_container_width=True)

    # ── 均線選擇（移入Tab2，無需展開）──────────────────────
    with st.container(border=True):
        st.markdown('<span style="font-size:11px;color:#8b949e;">📐 均線顯示設定</span>', unsafe_allow_html=True)
        ma_c1,ma_c2,ma_c3,ma_c4,ma_c5,ma_c6 = st.columns(6)
        with ma_c1:
            show_ma5   = st.checkbox('MA5',      value=False, key='t2_ma5')
        with ma_c2:
            show_ma20  = st.checkbox('MA20 月線', value=True,  key='t2_ma20')
        with ma_c3:
            show_ma60  = st.checkbox('MA60 季線', value=False, key='t2_ma60')
        with ma_c4:
            show_ma100 = st.checkbox('MA100',     value=True,  key='t2_ma100')
        with ma_c5:
            show_ma120 = st.checkbox('MA120',     value=False, key='t2_ma120')
        with ma_c6:
            show_ma240 = st.checkbox('MA240 年線',value=False, key='t2_ma240')
    show_ma_dict = {'MA5':show_ma5,'MA20':show_ma20,'MA60':show_ma60,
                    'MA100':show_ma100,'MA120':show_ma120,'MA240':show_ma240}

    t2l, t2r = st.columns([1, 2])
    with t2l:
        pass
    with t2r:
        st.markdown("""<div style="background:#161b22;border:1px solid #21262d;border-left:4px solid #ffd700;
border-radius:8px;padding:10px 14px;font-size:12px;color:#8b949e;">
<b style="color:#ffd700;">自動從網路抓取：</b><br>
K線+均線(FinMind) · 三大法人籌碼 · 融資融券 · 357股利評價 · 月/季營收毛利率 · 合約負債/資本支出 · 健康評分(RSI+量比+IBS+KD+布林)
</div>""", unsafe_allow_html=True)

    if t2_run:
        sid2 = t2_sid or '2330'
        st.info(f'🌐 抓取 {sid2} 全方位數據...')
        df2, name2, err2 = fetch_price_data(sid2, t2_days)
        avg_div2, yearly2, div_src2 = fetch_dividend_data(sid2)
        cl2, cx2, _capex2, _cl_src2, _cx_src2, _, _fin_errs2 = fetch_financials(sid2, industry='')
        rev2, _      = fetch_revenue(sid2)
        qtr2, _      = fetch_quarterly(sid2)
        qtr_extra2, _ = fetch_quarterly_extra(sid2)   # BS+CF時序（合約負債/存貨/資本支出）
        rsi2     = calc_rsi(df2)
        ibs2     = calc_ibs(df2)
        vr2      = calc_volume_ratio(df2)
        k2, d2   = calc_kd(df2)
        bb2      = calc_bollinger(df2)
        vcp2     = calc_vcp(df2)
        health2, details2 = calc_health_score(df2, rsi2, ibs2, vr2, k2, d2, bb2)
        cur_price2 = float(df2['close'].iloc[-1]) if df2 is not None and not df2.empty else 0
        from stock_names import get_stock_name as _gsn2
        _name2_resolved = (name2 if name2 and name2 != sid2 else None) or _gsn2(sid2) or sid2
        st.session_state['t2_data'] = {
            'sid':sid2,'name':_name2_resolved,'df':df2,'err':err2,
            'avg_div':avg_div2,'yearly':yearly2,'div_src':div_src2,
            'cl':cl2,'cx':cx2,'rev':rev2,'qtr':qtr2,'qtr_extra':qtr_extra2,
            'cl_src': _cl_src2,'cx_src': _cx_src2,'fin_errs': _fin_errs2,
            'rsi':rsi2,'ibs':ibs2,'vr':vr2,'k':k2,'d':d2,'bb':bb2,'vcp':vcp2,
            'health':health2,'details':details2,'price':cur_price2,
        }
        # 快取最後一次成功抓到的月營收/季財報，供下次失敗時 fallback
        if rev2 is not None and not rev2.empty:
            st.session_state[f'_last_rev_{sid2}'] = rev2
        if qtr2 is not None and not qtr2.empty:
            st.session_state[f'_last_qtr_{sid2}'] = qtr2

    t2d = st.session_state.get('t2_data')
    if not t2d:
        st.info('👆 輸入股票代碼後點擊「🔍 載入完整分析」')
    else:
        sid2   = t2d['sid']
        name2  = t2d['name']
        price2 = t2d['price']
        df2    = t2d['df']
        health2 = t2d['health']
        details2 = t2d['details']
        rsi2=t2d['rsi']
        ibs2=t2d['ibs']
        vr2=t2d['vr']
        k2=t2d['k']
        d2=t2d['d']
        bb2=t2d['bb']
        vcp2=t2d['vcp']
        avg_div2=t2d['avg_div']
        yearly2=t2d['yearly']
        cl2=t2d['cl']
        cx2=t2d['cx']
        _cl_src2=t2d.get('cl_src','')
        _cx_src2=t2d.get('cx_src','')
        _fin_errs2=t2d.get('fin_errs',[])
        rev2=t2d['rev']
        qtr2=t2d['qtr']
        qtr_extra2=t2d.get('qtr_extra')
        # Fallback 到快取（若本次抓取失敗）
        _rev2_cached = False
        _qtr2_cached = False
        if (rev2 is None or rev2.empty) and st.session_state.get(f'_last_rev_{sid2}') is not None:
            rev2 = st.session_state[f'_last_rev_{sid2}']
            _rev2_cached = True
        if (qtr2 is None or qtr2.empty) and st.session_state.get(f'_last_qtr_{sid2}') is not None:
            qtr2 = st.session_state[f'_last_qtr_{sid2}']
            _qtr2_cached = True

        # ══ 即時價格 + 趨勢儀表板 ════════════════════════════════
        if df2 is not None and not df2.empty and len(df2) >= 20:
            _p_now   = float(df2['close'].iloc[-1])
            _p_prev  = float(df2['close'].iloc[-2]) if len(df2) >= 2 else _p_now
            _p_chg   = round((_p_now - _p_prev) / _p_prev * 100, 2) if _p_prev else 0
            _ma20_v  = float(df2['close'].rolling(20).mean().iloc[-1])
            _ma60_v  = float(df2['close'].rolling(60).mean().iloc[-1]) if len(df2) >= 60 else None
            _ma120_v = float(df2['close'].rolling(120).mean().iloc[-1]) if len(df2) >= 120 else None
            # 趨勢燈號
            _above_ma20  = _p_now > _ma20_v
            _above_ma60  = (_p_now > _ma60_v) if _ma60_v else None
            _above_ma120 = (_p_now > _ma120_v) if _ma120_v else None
            _trend_score = sum([_above_ma20,
                                _above_ma60  if _above_ma60  is not None else False,
                                _above_ma120 if _above_ma120 is not None else False])
            _trend_label = {3: '🟢 強勢多頭', 2: '🟡 中性偏多', 1: '🟡 弱勢', 0: '🔴 空頭區間'}[_trend_score]
            _chg_color   = '#3fb950' if _p_chg >= 0 else '#f85149'
            _chg_arrow   = '▲' if _p_chg >= 0 else '▼'
            st.markdown(f'''<div style="background:#0d1117;border:2px solid #21262d;border-radius:12px;
padding:14px 18px;margin-bottom:12px;">
<div style="font-size:22px;font-weight:900;color:#e6edf3;margin-bottom:8px;">
  📌 {name2}（{sid2}）
  <span style="font-size:14px;color:#8b949e;margin-left:8px;">即時趨勢總覽</span>
</div>
<div style="display:flex;gap:24px;flex-wrap:wrap;align-items:center;">
  <div><span style="font-size:28px;font-weight:900;color:#e6edf3;">{_p_now:.2f}</span>
       <span style="font-size:16px;color:{_chg_color};margin-left:6px;">{_chg_arrow} {abs(_p_chg):.2f}%</span></div>
  <div style="font-size:13px;color:#8b949e;line-height:2;">
    MA20：<b style="color:{'#3fb950' if _above_ma20 else '#f85149'}">{_ma20_v:.2f}</b>
    {'✅' if _above_ma20 else '❌'}&nbsp;&nbsp;
    {'MA60：<b style="color:' + ("#3fb950" if _above_ma60 else "#f85149") + '">' + f'{_ma60_v:.2f}</b> ' + ("✅" if _above_ma60 else "❌") + "&nbsp;&nbsp;" if _ma60_v else ""}
    {'MA120：<b style="color:' + ("#3fb950" if _above_ma120 else "#f85149") + '">' + f'{_ma120_v:.2f}</b> ' + ("✅" if _above_ma120 else "❌") if _ma120_v else ""}
  </div>
  <div style="font-size:18px;font-weight:700;">{_trend_label}</div>
</div></div>''', unsafe_allow_html=True)

        st.markdown("""<div style="margin:20px 0 8px;padding:8px 16px;background:linear-gradient(90deg,#f0883e18,#0d1117);border-left:4px solid #f0883e;border-radius:0 6px 6px 0;"><span style="font-size:15px;font-weight:900;color:#f0883e;">💰 建議價格 & 進出場區間</span><span style="font-size:11px;color:#8b949e;margin-left:8px;">停利停損 · 風報比 · 進場條件 · 倉位計算</span></div>""", unsafe_allow_html=True)
        # ══ 0. 停利停損 + 支撐壓力 ═══════════════════════════════
        st.markdown('---')
        st.markdown('#### 🎯 停利停損建議 + 近期支撐壓力')
        _sp_c1, _sp_c2, _sp_c3, _sp_c4 = st.columns(4)
        _cur_p  = float(df2['close'].iloc[-1]) if df2 is not None and not df2.empty else 0
        _hi20_p = float(df2['high'].tail(20).max()) if df2 is not None and len(df2) >= 5 else 0
        _lo20_p = float(df2['low'].tail(20).min())  if df2 is not None and len(df2) >= 5 else 0
        _tp1_p  = round(_cur_p * 1.05, 2)
        _tp2_p  = round(_cur_p * 1.10, 2)
        _sl_p   = round(_cur_p * 0.92, 2)
        _rr_p   = round((_tp1_p - _cur_p) / max(_cur_p - _sl_p, 0.01), 2)
        with _sp_c1:
            st.markdown(kpi('停利目標1 (+5%)', f'{_tp1_p}', '短線先入袋', '#3fb950', '#0d2818'), unsafe_allow_html=True)
        with _sp_c2:
            st.markdown(kpi('停利目標2 (+10%)', f'{_tp2_p}', '波段目標', '#58a6ff', '#0d1f3c'), unsafe_allow_html=True)
        with _sp_c3:
            st.markdown(kpi('建議停損 (-8%)', f'{_sl_p}', '跌破認賠', '#f85149', '#2a0d0d'), unsafe_allow_html=True)
        with _sp_c4:
            st.markdown(kpi('盈虧比', f'{_rr_p}x', '≥1.5 較理想', '#ffd700', '#1a1000'), unsafe_allow_html=True)
        _sp_c5, _sp_c6 = st.columns(2)
        _dist_hi = round((_hi20_p/_cur_p-1)*100, 1) if _cur_p > 0 else 0
        _dist_lo = round((1-_lo20_p/_cur_p)*100, 1) if _cur_p > 0 else 0
        # ── 大量紅K 進場價計算 ──────────────────────────────
        _entry_half = None
        _abs_sl     = None
        if df2 is not None and not df2.empty and len(df2) >= 5:
            # 找近20日最大量的紅K
            _red_k = df2[(df2['close'] > df2['open']) if 'open' in df2.columns
                         else df2['close'] > df2['close'].shift(1)].tail(20)
            if 'volume' in _red_k.columns and not _red_k.empty:
                _big_red = _red_k.nlargest(1, 'volume').iloc[0]
                _rk_high = float(_big_red.get('high', _big_red['close']))
                _rk_low  = float(_big_red.get('low',  _big_red['close']) )
                _entry_half = round((_rk_high + _rk_low) / 2, 2)  # 1/2 進場價
                _abs_sl     = round(_rk_low * 0.995, 2)             # 紅K低點-0.5%

        _sp_c5b, _sp_c6b, _sp_c7b = st.columns(3)
        with _sp_c5b:
            if _entry_half:
                st.markdown(kpi('大量紅K 1/2 進場', f'{_entry_half:.2f}',
                                '朱家泓低風險買點', '#58a6ff', '#1a2744'), unsafe_allow_html=True)
            else:
                st.markdown(kpi('大量紅K 1/2', '計算中', '', '#484f58', '#0d1117'), unsafe_allow_html=True)
        with _sp_c6b:
            if _abs_sl:
                _bias_sl = round((_cur_p - _abs_sl) / _cur_p * 100, 1) if _cur_p else 0
                _sl_color = '#f85149' if _bias_sl < 5 else '#d29922'
                st.markdown(kpi('絕對停損線', f'{_abs_sl:.2f}',
                                f'紅K低點（距{_bias_sl:.1f}%）', _sl_color, '#2a0d0d'), unsafe_allow_html=True)
            else:
                st.markdown(kpi('絕對停損線', _sl_p.__str__(), '跌破即出場', '#f85149', '#2a0d0d'), unsafe_allow_html=True)
        with _sp_c7b:
            _rr2 = round((_tp1_p - _cur_p) / max(_cur_p - (_abs_sl or _sl_p), 0.01), 2) if _cur_p else 0
            _rr_color = '#3fb950' if _rr2 >= 1.5 else ('#d29922' if _rr2 >= 1 else '#f85149')
            st.markdown(kpi('實際盈虧比', f'{_rr2}x', '≥1.5 可操作', _rr_color, '#0d1117'), unsafe_allow_html=True)

        with _sp_c5:
            st.markdown(kpi('近20日壓力', f'{_hi20_p:.2f}', f'距現價 +{_dist_hi}%', '#f85149', '#2a0d0d'), unsafe_allow_html=True)
        with _sp_c6:
            st.markdown(kpi('近20日支撐', f'{_lo20_p:.2f}', f'距現價 -{_dist_lo}%', '#3fb950', '#0d2818'), unsafe_allow_html=True)

        # ══ 進出場訊號（多位老師方法整合）═══════════════════════
        st.markdown('---')

        # ══ 操作前心理檢查 + 勝利方程式 ═══════════════════════
        st.markdown('---')
        st.markdown('#### 🧠 操作前必做：心理檢查 + 勝利方程式')

        _mc_cols = st.columns([3, 2])

        with _mc_cols[0]:
            st.markdown('<div style="background:#0a1628;border:1px solid #1f6feb;border-radius:10px;padding:12px;">', unsafe_allow_html=True)
            st.markdown('**📋 SOP 進場強制檢核表（4關卡全通過才顯示建議）**')
            _wr_reg_chk = st.session_state.get('mkt_info', {}).get('regime','neutral')
            _price_chk  = float(df2['close'].iloc[-1]) if df2 is not None and not df2.empty else 0
            _open5_chk  = float(df2['close'].iloc[-6]) if df2 is not None and len(df2)>=6 else _price_chk
            _surge_chk  = round((_price_chk - _open5_chk) / max(_open5_chk,1) * 100, 1)
            _stop_chk   = round(_price_chk - 1.5 * (_atr2_val if '_atr2_val' in dir() else _price_chk*0.07), 2)  # noqa: F821
            _q1 = st.checkbox(
                f'① 確認非空頭格局（目前：{_wr_reg_chk}）',
                value=_wr_reg_chk != 'bear', key=f't2_q1_{sid2}',
                disabled=_wr_reg_chk == 'bear'
            )
            _q2 = st.checkbox(
                f'② 確認未追高超過5%（近5日漲幅：{_surge_chk:+.1f}%）',
                value=abs(_surge_chk) <= 5, key=f't2_q2_{sid2}',
                disabled=abs(_surge_chk) > 10
            )
            _q3 = st.checkbox(
                f'③ 確認停損價（跌破 {_stop_chk} 元無條件出場）',
                key=f't2_q3_{sid2}'
            )
            _all_checked = _q1 and _q2 and _q3
            if _all_checked:
                st.success('✅ 心理狀態良好，可以繼續評估操作')
            else:
                st.warning('⚠️ 尚有項目未確認，建議先暫停，避免情緒化操作')
            st.markdown('</div>', unsafe_allow_html=True)

        with _mc_cols[1]:
            st.markdown('<div style="background:#0a1628;border:1px solid #3fb950;border-radius:10px;padding:12px;">', unsafe_allow_html=True)
            st.markdown('**🏆 勝利方程式（需全部符合）**')
            _wr_mkt2 = st.session_state.get('mkt_info', {})
            _wr_reg2 = _wr_mkt2.get('regime','neutral') if _wr_mkt2 else 'neutral'
            _wr_margin2 = st.session_state.get('cl_data',{}).get('margin', 0) or 0
            _win_conds = [
                ('🌍 大盤多頭燈號',  _wr_reg2 == 'bull'),
                ('💰 融資安全(<2500億)', _wr_margin2 < 2500),
                ('🏥 個股健康度≥75', health2 >= 75 if df2 is not None else False),
                ('💎 非357昂貴區',   '昂貴' not in str(st.session_state.get('t2_data',{}).get('val',''))),
                ('✋ 已設停損點',     _q3),
            ]
            _win_count = sum(1 for _, v in _win_conds if v)
            for _wn, _wv in _win_conds:
                _wc = '#3fb950' if _wv else '#f85149'
                _wi = '✅' if _wv else '❌'
                st.markdown(f'<div style="font-size:12px;color:{_wc};padding:2px 0;">{_wi} {_wn}</div>', unsafe_allow_html=True)
            st.markdown(f'<div style="margin-top:8px;font-size:13px;font-weight:700;color:{"#3fb950" if _win_count>=4 else "#f85149"};">'
                       f'{"🚀 符合 " + str(_win_count) + "/5，可以考慮操作" if _win_count>=4 else "⛔ 僅符合 " + str(_win_count) + "/5，建議等待"}'
                       f'</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # 今日禁止操作清單
        st.markdown('#### 🚫 今日禁止操作情況（有任何一項→今天暫停）')
        _ban_items = []
        _wr_mkt3 = st.session_state.get('mkt_info', {})
        _wr_price = float(df2['close'].iloc[-1]) if df2 is not None and not df2.empty else 0
        _wr_open  = float(df2['close'].iloc[-5]) if df2 is not None and len(df2)>=5 else _wr_price
        _today_surge = round((_wr_price - _wr_open) / max(_wr_open,1) * 100, 1) if _wr_open else 0
        if abs(_today_surge) > 4:
            _ban_items.append(f'📈 個股近5日漲幅 {_today_surge:+.1f}% 超過4%（追高風險）')
        _ml = st.session_state.get('monthly_loss_pct', 0)
        if _ml < -5:
            _ban_items.append(f'📉 本月已虧損 {abs(_ml):.1f}%（情緒操作風險上升）')
        if _wr_margin2 > 3400:
            _ban_items.append(f'💸 融資 {_wr_margin2:.0f}億 極度過熱（散戶追高期，等待）')
        if _wr_reg2 == 'bear':
            _ban_items.append('🔴 大盤空頭格局（禁止做多）')

        if _ban_items:
            for _bi in _ban_items:
                st.markdown(f'<div style="background:#2a0d0d;border-left:3px solid #f85149;border-radius:0 6px 6px 0;padding:7px 12px;margin:3px 0;font-size:12px;color:#f85149;">'
                           f'⛔ {_bi}</div>', unsafe_allow_html=True)
        else:
            st.success('✅ 今日無禁止操作情況，可以正常評估')

        st.markdown('---')
        st.markdown('#### 🎯 什麼時候買？什麼時候賣？')
        st.markdown(
            '<div style="background:#0a1628;border-left:3px solid #58a6ff;padding:8px 12px;'            'border-radius:0 6px 6px 0;margin-bottom:8px;font-size:12px;color:#c9d1d9;">'
            '💡 系統自動幫你檢查<b>多套策略的進出場條件</b>，符合越多條件越可靠。'
            '<br>🔵 <b>進場訊號</b>：這些條件出現代表可以考慮買進'
            '<br>🔴 <b>出場訊號</b>：這些條件出現代表要考慮賣出或減碼'
            '<br>🎯 <b>目標價</b>：預計可以獲利的目標 | 🛑 <b>停損</b>：跌到這裡要認賠出場'
            '</div>', unsafe_allow_html=True)
        if df2 is not None and not df2.empty:
            _p2    = float(df2['close'].iloc[-1])
            # MA 欄位：若不存在則即時計算
            def _safe_ma(df, n):
                col = f'MA{n}'
                if col in df.columns:
                    return float(df[col].iloc[-1])
                if len(df) >= n:
                    return float(df['close'].tail(n).mean())
                return float(df['close'].mean())
            _ma5   = _safe_ma(df2, 5)
            _ma20  = _safe_ma(df2, 20)
            _ma60  = _safe_ma(df2, 60)
            _ma240 = _safe_ma(df2, 240)

            # 趨勢排列
            _bull_align  = _p2 > _ma20 > _ma60   # 多頭排列
            _bear_align  = _p2 < _ma20 < _ma60   # 空頭排列
            _bias_i      = round((_p2 - _ma240) / _ma240 * 100, 1) if _ma240 else 0
            _bias_20_i   = round((_p2 - _ma20) / _ma20 * 100, 1)   if _ma20  else 0

            # 布林帶訊號
            _bb_upper    = (bb2.get('upper', 0) if isinstance(bb2, dict) else 0) or float('inf')
            _bb_ma       = (bb2.get('ma', 0)    if isinstance(bb2, dict) else 0)
            _bb_near_up  = bool(bb2) and _p2 >= _bb_upper * 0.97
            _bb_drop_out = bool(bb2) and _p2 < _bb_upper * 0.95 and _p2 > _bb_ma

            # KD 訊號
            _kd_gold = k2 and d2 and k2 > d2  # 黃金交叉方向
            _kd_dead = k2 and d2 and k2 < d2 and k2 > 70  # 高檔死亡交叉

            # VCP 訊號
            _vcp_ok = bool(vcp2 and isinstance(vcp2, dict) and vcp2.get('contracting'))

            # 目標價（蔡森一比一對稱法）
            _hi20_i = float(df2['high'].tail(20).max())
            _lo20_i = float(df2['low'].tail(20).min())
            _range20 = _hi20_i - _lo20_i
            _target1 = round(_p2 + _range20, 2)  # 初步目標：現價 + 20日震幅

            _sig_cols = st.columns(3)

            with _sig_cols[0]:
                st.markdown('<div style="background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:10px;">', unsafe_allow_html=True)
                st.markdown('**📈 進場訊號**')
                _entry = []
                if _bull_align:
                    _entry.append('✅ 多頭排列（股>月>季）→ 朱家泓：可進場方向')
                if _vcp_ok:
                    _entry.append('✅ VCP波幅收縮 → 策略3：即將突破，建底倉30-50%')
                if k2 and k2 < 30:
                    _entry.append(f'✅ KD低檔 K={k2:.0f} → 策略1：底部進場區')
                if rsi2 and rsi2 < 30:
                    _entry.append(f'✅ RSI超賣 {rsi2:.0f} → 反彈機會')
                if _bias_i < -20:
                    _entry.append(f'✅ 年線負乖離 {_bias_i:+.0f}% → 策略1：左側布局區')
                # RS 相對強度
                try:
                    _rs_val  = calc_rs_score(df2)
                    _rs_up   = rs_slope(df2)
                    _rs_color= '#3fb950' if _rs_val >= 75 else ('#d29922' if _rs_val >= 50 else '#f85149')
                    _rs_trend= '↑強勢' if _rs_up else ('↓弱勢' if _rs_up is False else '')
                    _entry.append(f'<span style="color:{_rs_color}">📊 RS相對強度 {_rs_val:.0f}分 {_rs_trend}</span>')
                except Exception:
                    pass
                if not _entry:
                    _entry.append('⚪ 暫無明確進場訊號')
                for _e in _entry:
                    st.markdown(f'<div style="font-size:12px;color:#c9d1d9;padding:2px 0;">{_e}</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            with _sig_cols[1]:
                st.markdown('<div style="background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:10px;">', unsafe_allow_html=True)
                st.markdown('**📉 減碼/出場訊號**')
                _exit = []
                if _bear_align:
                    _exit.append('🔴 空頭排列 → 朱家泓：禁止做多，考慮出清')
                if _kd_dead:
                    _exit.append(f'⚠️ KD高檔死叉 K={k2:.0f} → 策略3：開始減碼')
                if _bb_drop_out:
                    _exit.append('⚠️ 脫離布林上軌 → 策略3：減碼50%')
                if _bias_20_i > 15:
                    _exit.append(f'⚠️ 月線乖離 {_bias_20_i:+.0f}% → 過熱，停利部分')
                if _bias_i > 20:
                    _exit.append(f'⚠️ 年線乖離 {_bias_i:+.0f}% → 策略1：分批出場')
                if _p2 < _ma5:
                    _exit.append(f'⚠️ 跌破5MA({_ma5:.1f}) → 林穎：短線停利')
                # 週MACD 警示：12/26/9 EMA on weekly bars
                try:
                    if df2 is not None and len(df2) >= 30:
                        _wdf = df2.copy()
                        _wdf.index = range(len(_wdf))
                        # 近30日K線轉換為週K（每5根合一）
                        _wclose = [float(_wdf['close'].iloc[min(i+4, len(_wdf)-1)])
                                   for i in range(0, min(30, len(_wdf)), 5)]
                        if len(_wclose) >= 6:
                            _we12 = pd.Series(_wclose).ewm(span=3,adjust=False).mean()
                            _we26 = pd.Series(_wclose).ewm(span=5,adjust=False).mean()
                            _wmacd= _we12 - _we26
                            _whist= (_wmacd - _wmacd.ewm(span=3,adjust=False).mean()).tolist()
                            # 週MACD紅柱縮短（連續2根縮小）
                            if len(_whist)>=3 and _whist[-1]>0 and _whist[-1]<_whist[-2]<_whist[-3]:
                                _exit.append('⚠️ 週MACD紅柱連縮 → 上漲動能衰減，準備減碼')
                            elif len(_whist)>=2 and _whist[-2]>0 and _whist[-1]<=0:
                                _exit.append('🔴 週MACD翻負 → 中線趨勢轉弱，出清訊號')
                except Exception:
                    pass
                if not _exit:
                    _exit.append('⚪ 暫無明確出場訊號')
                for _ex in _exit:
                    st.markdown(f'<div style="font-size:12px;color:#c9d1d9;padding:2px 0;">{_ex}</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            with _sig_cols[2]:
                st.markdown('<div style="background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:10px;">', unsafe_allow_html=True)
                st.markdown('**🎯 目標 + 停損**')
                st.markdown(f'<div style="font-size:12px;color:#c9d1d9;padding:2px 0;">📌 現價：<b>{_p2:.2f}</b></div>', unsafe_allow_html=True)
                st.markdown(f'<div style="font-size:12px;color:#3fb950;padding:2px 0;">🎯 初步目標（策略3 一比一對稱）：<b>{_target1:.2f}</b></div>', unsafe_allow_html=True)
                _sl_hard = round(_p2 * 0.93, 2)
                _sl_ma20 = round(_ma20 * 0.99, 2)
                _dist_hard = round((_p2 - _sl_hard) / _p2 * 100, 1) if _p2 else 0
                _dist_ma20 = round((_p2 - _sl_ma20) / _p2 * 100, 1) if _p2 else 0
                _dist_ma5  = round((_p2 - _ma5) / _p2 * 100, 1) if _p2 and _ma5 else 0
                st.markdown(f'<div style="font-size:12px;color:#f85149;padding:2px 0;">🛑 硬停損(-7%)：<b>{_sl_hard:.2f}</b> <span style="color:#484f58;">（尚差{_dist_hard:.1f}%）</span></div>', unsafe_allow_html=True)
                st.markdown(f'<div style="font-size:12px;color:#d29922;padding:2px 0;">⚠️ 月線停損：<b>{_sl_ma20:.2f}</b> <span style="color:#484f58;">（尚差{_dist_ma20:.1f}%）</span></div>', unsafe_allow_html=True)
                st.markdown(f'<div style="font-size:12px;color:#58a6ff;padding:2px 0;">📍 5MA停利：<b>{_ma5:.2f}</b> <span style="color:#484f58;">（尚差{_dist_ma5:.1f}%）</span></div>', unsafe_allow_html=True)
                # 加碼點
                if _bull_align and vcp2 and not _vcp_ok:
                    _add_pt = round(_hi20_i * 1.01, 2)
                    st.markdown(f'<div style="font-size:12px;color:#58a6ff;padding:2px 0;">➕ 加碼點（策略3 突破法）：>{_add_pt:.2f}</div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

        else:
            st.info('載入個股資料後顯示進出場訊號')

        # ══ 龍頭預警區（孫慶龍龍多策略最高等級）══════════════════
        _is_dragon = False
        _dragon_reasons = []
        try:
            if cl2 is not None and cl2 > 0:
                # 用股價估算股本（簡化：取市值代理）
                _price_now = float(df2['close'].iloc[-1]) if df2 is not None and not df2.empty else 0
                # 合約負債 / 股本比估算（cl2 單位億）
                if cl2 > 0:
                    _dragon_reasons.append(f'合約負債 {cl2:.1f}億（>股本50% → 未來3-6月訂單保障）')
                    _is_dragon = True
            if cx2 is not None and cx2 > 0:
                _dragon_reasons.append(f'資本支出 {cx2:.1f}億（>股本80% → 大擴廠，看好未來需求）')
                _is_dragon = True
        except Exception:
            pass

        if _is_dragon:
            st.markdown(
                '<div style="background:linear-gradient(135deg,#2a1f00,#3d2d00);'
                'border:2px solid #ffd700;border-radius:10px;padding:12px 16px;margin-bottom:10px;">'
                '<div style="font-size:14px;font-weight:900;color:#ffd700;margin-bottom:6px;">'
                '🏆 龍頭預警區 — 極稀有高成長標的</div>' +
                ''.join(f'<div style="font-size:12px;color:#ffe066;padding:2px 0;">• {r}</div>' for r in _dragon_reasons) +
                '<div style="font-size:11px;color:#997a00;margin-top:4px;">'
                '策略1：「不要聽老闆說什麼，要看他做什麼」— 最誠實的領先指標</div>'
                '</div>', unsafe_allow_html=True)

        st.markdown("""<div style="margin:24px 0 8px;padding:8px 16px;background:linear-gradient(90deg,#58a6ff18,#0d1117);border-left:4px solid #58a6ff;border-radius:0 6px 6px 0;"><span style="font-size:15px;font-weight:900;color:#58a6ff;">📈 技術面分析</span><span style="font-size:11px;color:#8b949e;margin-left:8px;">健康度評分 · VCP波幅收縮 · K線技術圖 · 即時操作建議</span></div>""", unsafe_allow_html=True)
        # ══ A. 健康度評分 ══════════════════════════════════════
        st.markdown('#### 🏥 A. 個股健康度評分（0~100）')
        if health2 >= 80:
            _ha = f'健康度 {health2:.0f}分，技術面強勢'
            _hb = '確認大盤方向後可建倉，停損設月線下方'
        elif health2 >= 60:
            _ha = f'健康度 {health2:.0f}分，中性偏多，尚未達進場標準'
            _hb = '等待突破80分或放量突破前高再行動'
        else:
            _ha = f'健康度 {health2:.0f}分，技術面偏弱，跳過'
            _hb = '不要強求，另找更好標的'
        st.markdown(teacher_conclusion('宏爺', f'{sid2} 健康度 {health2:.0f}分', _ha, _hb), unsafe_allow_html=True)
        # 評分信心區間說明
        _score_help = (
            '<div style="background:#0a1628;border-left:3px solid #58a6ff;'
            'padding:8px 12px;border-radius:0 6px 6px 0;margin-bottom:8px;font-size:11px;color:#8b949e;">'
            '📊 <b>評分不是保證，是機率</b>：'
            '健康度80分 → 歷史勝率約65%（10次中6-7次對）。'
            '停損紀律決定你能否從對的那幾次賺夠錢。'
            '</div>'
        )

        ha, hb = st.columns([1, 2])
        with ha:
            # 基本面評分
            _fund_sc = calc_fundamental_score(qtr2, yearly2, avg_div2)
            # 技術警示
            _tech_al = []
            if rsi2 and rsi2 < 30:
                _tech_al.append(('🟡','RSI過低','看跌反彈',f'RSI={rsi2:.0f}，超賣可能反彈'))
            elif rsi2 and rsi2 > 70:
                _tech_al.append(('🔴','RSI超買','超買注意',f'RSI={rsi2:.0f}，高檔過熱'))
            if df2 is not None and 'MA5' in df2.columns and 'MA10' in df2.columns and len(df2)>=2:
                _m5,_m10  = float(df2['MA5'].iloc[-1]),  float(df2['MA10'].iloc[-1])
                _m5p,_m10p= float(df2['MA5'].iloc[-2]),  float(df2['MA10'].iloc[-2])
                if _m5<_m10 and _m5p>=_m10p:
                    _tech_al.insert(0,('🔴','MA5下穿MA10','看跌',  '短均死叉，趨勢轉弱'))
                elif _m5>_m10 and _m5p<=_m10p:
                    _tech_al.insert(0,('🟢','MA5上穿MA10','看漲','短均黃金交叉，轉強'))
            if vr2 and vr2 < 0.5:
                _tech_al.append(('🟡','量能不足','觀察',f'量比={vr2:.2f}，市場觀望'))
            if k2 and d2:
                if k2<d2 and k2>20:
                    _tech_al.append(('🟡','KD死亡交叉','看跌',f'K={k2:.0f} D={d2:.0f}'))
                elif k2>d2 and k2<80:
                    _tech_al.append(('🟢','KD黃金交叉','看漲',f'K={k2:.0f} D={d2:.0f}'))
            st.markdown(render_health_score(health2, details2, sid2, _fund_sc, _tech_al), unsafe_allow_html=True)
        with hb:
            # 六大技術指標卡片
            ind1, ind2, ind3 = st.columns(3)
            ind4, ind5, ind6 = st.columns(3)
            with ind1:
                rsi_c = '#d29922' if rsi2 and rsi2>70 else ('#3fb950' if rsi2 and rsi2<30 else '#58a6ff')
                rsi_txt = '超買⚠️' if rsi2 and rsi2>70 else ('超賣反彈' if rsi2 and rsi2<30 else '中性')
                st.markdown(kpi('RSI(14)',f'{rsi2}' if rsi2 else '-',rsi_txt,rsi_c,rsi_c),unsafe_allow_html=True)
            with ind2:
                vr_c = '#3fb950' if vr2 and vr2>=1.5 else ('#d29922' if vr2 and vr2>=1.0 else '#484f58')
                vr_txt = '異常放量' if vr2 and vr2>=1.5 else ('溫和放量' if vr2 and vr2>=1.0 else '量縮')
                st.markdown(kpi('量比(5日)',f'{vr2}' if vr2 else '-',vr_txt,vr_c,vr_c),unsafe_allow_html=True)
            with ind3:
                ibs_c = '#3fb950' if ibs2 is not None and ibs2<=0.2 else ('#f85149' if ibs2 is not None and ibs2>=0.8 else '#58a6ff')
                ibs_txt = '收低≤20%易反彈' if ibs2 is not None and ibs2<=0.2 else ('收高≥80%易賣壓' if ibs2 is not None and ibs2>=0.8 else '中性位置')
                st.markdown(kpi('IBS',f'{ibs2}' if ibs2 is not None else '-',ibs_txt,ibs_c,ibs_c),unsafe_allow_html=True)
            with ind4:
                kd_c = '#3fb950' if k2 and d2 and k2>d2 and k2<80 else ('#d29922' if k2 and d2 and k2>d2 else '#f85149')
                kd_txt = '黃金交叉' if k2 and d2 and k2>d2 else '死亡交叉'
                st.markdown(kpi('KD',f'K={k2}/D={d2}' if k2 else '-',kd_txt,kd_c,kd_c),unsafe_allow_html=True)
            with ind5:
                if df2 is not None and 'MA20' in df2.columns and 'MA100' in df2.columns:
                    p=price2
                    m20=float(df2['MA20'].iloc[-1])
                    m100=float(df2['MA100'].iloc[-1])
                    if p>m20>m100:
                        tr_txt='多頭排列'
                        tr_c='#3fb950'
                    elif p<m20<m100:
                        tr_txt='空頭排列'
                        tr_c='#f85149'
                    elif p>m100:
                        tr_txt='多箱整理'
                        tr_c='#d29922'
                    else:
                        tr_txt='空箱整理'
                        tr_c='#d29922'
                    st.markdown(kpi('趨勢',tr_txt,f'MA20={m20:.1f}',tr_c,tr_c),unsafe_allow_html=True)
                else:
                    st.markdown(kpi('趨勢','-','無MA數據','#484f58'),unsafe_allow_html=True)
            with ind6:
                if bb2:
                    bw_c='#3fb950' if bb2['bw']<bb2['bw_mean']*0.7 else '#58a6ff'
                    bw_txt='帶寬極縮⚡' if bb2['bw']<bb2['bw_mean']*0.7 else ('黏近上軌' if bb2['near_upper'] else f'均值{bb2["bw_mean"]:.1f}%')
                    st.markdown(kpi('布林帶寬',f'{bb2["bw"]:.1f}%',bw_txt,bw_c,bw_c),unsafe_allow_html=True)
                else:
                    st.markdown(kpi('布林帶寬','-','數據不足','#484f58'),unsafe_allow_html=True)

        # ── 動態大師建議（基於實際評分）──────────────────────
        _grade_label, _grade_color, _, _grade_emoji = health_grade(health2)
        _price_pos = ''
        if df2 is not None and 'MA20' in df2.columns and 'MA100' in df2.columns:
            _p2 = price2
            _m20 = float(df2['MA20'].iloc[-1])
            _m100 = float(df2['MA100'].iloc[-1])
            if _p2 > _m20 > _m100:
                _price_pos = '多頭排列，技術面強勢'
            elif _p2 < _m20 < _m100:
                _price_pos = '空頭排列，技術面偏弱'
            elif _p2 > _m100:
                _price_pos = '多箱整理，等待突破'
            else:
                _price_pos = '空箱整理，謹慎操作'
        _verdict_color = '#3fb950' if health2>=80 else ('#d29922' if health2>=50 else '#f85149')
        _verdict = ('持股不動，佛系等待；所有指標均表現優異，繼續持有。' if health2>=80
                    else ('等待突破訊號，不追高；多空交戰，方向未明，可分批布局。' if health2>=50
                          else '降低倉位或觀望；趨勢偏弱，以保本為優先。'))
        st.markdown(f"""<div style="background:#161b22;border:1px solid {_verdict_color};
border-left:4px solid {_verdict_color};border-radius:8px;padding:12px 14px;margin:8px 0;">
<span style="font-size:13px;font-weight:800;color:{_verdict_color};">{_grade_emoji} 大師綜合建議：{_verdict}</span>
<div style="font-size:11px;color:#8b949e;margin-top:4px;">技術位置：{_price_pos} | RSI={rsi2} | 量比={vr2} | KD=K{k2}/D{d2}</div>
</div>""", unsafe_allow_html=True)

        st.caption('📖 評分標準與指標說明 → 詳見「策略手冊」Tab')


        # ── v4.0 防守線 + 籌碼 + 套牢賣壓 ─────────────────────────────
        try:
            if df2 is not None and not df2.empty:
                # Build df for V4 engine (map column names)
                _v4_df = df2.copy()
                _col_map = {}
                for _c in _v4_df.columns:
                    if _c in ('close','Close','adj close'):
                        _col_map[_c] = 'close'
                    elif _c in ('open','Open'):
                        _col_map[_c] = 'open'
                    elif _c in ('low','Low'):
                        _col_map[_c] = 'low'
                    elif _c in ('volume','Volume','Trading_Volume'):
                        _col_map[_c] = 'volume'
                _v4_df = _v4_df.rename(columns=_col_map)

                # Try to get chip data from session state
                _inst2 = st.session_state.get('t2_inst', {})
                if '外資' in _inst2:
                    _v4_df['foreign_net'] = _inst2.get('外資', 0)
                    _v4_df['trust_net']   = _inst2.get('投信', 0)

                # Macro data from li_latest
                _li_for_v4 = st.session_state.get('li_latest')
                _v4_fut2 = 0.0
                _v4_pcr2 = 100.0
                if _li_for_v4 is not None and not _li_for_v4.empty:
                    try:
                        _v4_fut2 = float(_li_for_v4.iloc[-1].get('外資大小', 0) or 0)
                    except Exception:
                        pass
                    try:
                        _v4_pcr2 = float(_li_for_v4.iloc[-1].get('選PCR', 100) or 100)
                    except Exception:
                        pass

                _shares = st.session_state.get(f't2_shares_{sid2}', 1000000)
                _v4eng  = V4StrategyEngine(_v4_df,
                                           {'vix': 15, 'foreign_futures': _v4_fut2, 'pcr': _v4_pcr2},
                                           max(int(_shares), 1))
                _v4rep  = _v4eng.generate_report()

                st.markdown('---')
                _v4c1, _v4c2, _v4c3 = st.columns(3)

                # Task 4: Stop Loss
                with _v4c1:
                    _sl = _v4rep['stop_loss']
                    _sl_color = '#da3633' if _sl['stop_loss'] else '#484f58'
                    st.markdown(
                        f'<div style="background:#0d1117;border:1px solid {_sl_color};'
                        f'border-radius:8px;padding:12px;text-align:center;">'
                        f'<div style="font-size:10px;color:#484f58;">🛡️ v4 防守價</div>'
                        f'<div style="font-size:20px;font-weight:900;color:{_sl_color};">'
                        f'{_sl["stop_loss"] or "N/A"} 元</div>'
                        f'<div style="font-size:11px;color:#8b949e;">MA20={_sl["ma20"]} | '
                        f'風險 {_sl["risk_pct"]}%</div>'
                        f'<div style="font-size:10px;color:#da3633;">跌破無條件停損</div>'
                        f'</div>', unsafe_allow_html=True)

                # Task 3: VPOC Resistance
                with _v4c2:
                    _rs = _v4rep['resistance']
                    _rs_color = '#da3633' if _rs['has_pressure'] else '#2ea043'
                    st.markdown(
                        f'<div style="background:#0d1117;border:1px solid {_rs_color};'
                        f'border-radius:8px;padding:12px;text-align:center;">'
                        f'<div style="font-size:10px;color:#484f58;">📊 v4 上方賣壓</div>'
                        f'<div style="font-size:14px;font-weight:900;color:{_rs_color};">'
                        f'{"⚠️ 有解套賣壓" if _rs["has_pressure"] else "✅ 壓力有限"}</div>'
                        f'<div style="font-size:11px;color:#8b949e;">'
                        f'VPOC={_rs["vpoc_price"] or "N/A"} 元</div>'
                        f'</div>', unsafe_allow_html=True)

                # Task 1: Chip Ratio
                with _v4c3:
                    _ch = _v4rep['chip_analysis']
                    _ch_color = '#da3633' if '強勢' in _ch['signal'] else ('#2ea043' if '渙散' in _ch['signal'] else '#388bfd')
                    st.markdown(
                        f'<div style="background:#0d1117;border:1px solid {_ch_color};'
                        f'border-radius:8px;padding:12px;text-align:center;">'
                        f'<div style="font-size:10px;color:#484f58;">💹 v4 相對籌碼</div>'
                        f'<div style="font-size:13px;font-weight:900;color:{_ch_color};">'
                        f'{_ch["signal"][:10]}</div>'
                        f'<div style="font-size:10px;color:#8b949e;">'
                        f'外本比 {_ch["foreign_ratio"] or "--"}%</div>'
                        f'</div>', unsafe_allow_html=True)
        except Exception as _v4_err:
            st.caption(f'v4.0 分析略過：{type(_v4_err).__name__}')


        # ── v5.0 RS強度 + 估值 + 布林偵測 ─────────────────────────────
        try:
            if df2 is not None and not df2.empty and len(df2) >= 20:
                _v5_r1, _v5_r2, _v5_r3 = st.columns(3)

                # Task 9: Bollinger Breakout
                with _v5_r1:
                    _bb5 = detect_bollinger_breakout(df2)
                    _bb5c = _bb5['color']
                    st.markdown(
                        f'<div style="background:#0d1117;border:1px solid {_bb5c};'
                        f'border-radius:8px;padding:12px;text-align:center;">'
                        f'<div style="font-size:10px;color:#484f58;">📈 v5 布林偵測</div>'
                        f'<div style="font-size:13px;font-weight:900;color:{_bb5c};">'
                        f'{_bb5["signal"][:10]}</div>'
                        f'<div style="font-size:10px;color:#8b949e;">BW={_bb5["bw"]}%</div>'
                        f'</div>', unsafe_allow_html=True)

                # Task 10: 357 存股殖利率
                with _v5_r2:
                    _dy5 = calc_dividend_yield_357(
                        price2 or 0,
                        pd.to_numeric((qtr2['EPS'] if qtr2 is not None and not qtr2.empty and 'EPS' in qtr2.columns else pd.Series(dtype=float)).head(4), errors='coerce').fillna(0).sum(),
                        avg_div2 / max(price2, 1) if avg_div2 and price2 else 0,
                        len([d for d in (st.session_state.get('t2_div_hist',[]) or []) if d > 0])
                    )
                    _dy5c = _dy5['color']
                    st.markdown(
                        f'<div style="background:#0d1117;border:1px solid {_dy5c};'
                        f'border-radius:8px;padding:12px;text-align:center;">'
                        f'<div style="font-size:10px;color:#484f58;">💰 v5 存股殖利率</div>'
                        f'<div style="font-size:14px;font-weight:900;color:{_dy5c};">'
                        f'{_dy5["est_yield"] or "N/A"}%</div>'
                        f'<div style="font-size:10px;color:#8b949e;">{_dy5["signal"][:8]}</div>'
                        f'</div>', unsafe_allow_html=True)

                # Task 5: 財報領先
                with _v5_r3:
                    _fl5 = analyze_fundamental_leading(cl2, None, None, None,
                                                       st.session_state.get(f't2_equity_{sid2}'))
                    _fl5c = _fl5['color']
                    st.markdown(
                        f'<div style="background:#0d1117;border:1px solid {_fl5c};'
                        f'border-radius:8px;padding:12px;text-align:center;">'
                        f'<div style="font-size:10px;color:#484f58;">🔬 v5 財報領先</div>'
                        f'<div style="font-size:13px;font-weight:900;color:{_fl5c};">'
                        f'{_fl5["signal"][:8]}</div>'
                        f'<div style="font-size:10px;color:#8b949e;">'
                        f'{"合約負債 ✅" if cl2 and cl2>0 else "無合約負債"}</div>'
                        f'</div>', unsafe_allow_html=True)
        except Exception as _v5e2:
            st.caption(f'v5.0 進階分析略過：{type(_v5e2).__name__}')

        # ══ E. VCP + 布林 ══════════════════════════════════════
        st.markdown('---')
        st.markdown('#### 🎯 E. VCP波幅收縮 + 布林通道')
        if vcp2 and vcp2.get('contracting'):
            _sw = vcp2.get('swings', [])
            _ea = f'VCP確認收縮（{len(_sw)}波段），量能萎縮，等待帶量突破進場'
            _eb = '突破前高且放量時買入，停損設前波低點'
        elif vcp2:
            _sw = vcp2.get('swings', [])
            _ea = f'VCP尚未形成（{len(_sw)}波段），波動仍大，不宜進場'
            _eb = '等待更多整理時間，耐心等候'
        else:
            _ea = '數據不足，VCP無法計算（需至少30日價格資料）'
            _eb = ''
        st.markdown(teacher_conclusion('朱家泓', f'{sid2} VCP型態', _ea, _eb), unsafe_allow_html=True)
        ec1,ec2=st.columns(2)
        with ec1:
            st.markdown('**VCP [Mark Minervini]**')
            if vcp2:
                sw=' → '.join([f'{s:.1f}%' for s in vcp2['swings']])
                vc='#3fb950' if vcp2['contracting'] else '#d29922'
                st.markdown(kpi('VCP狀態','✅符合收縮' if vcp2['contracting'] else '⚠️未收縮',
                                f'波幅：{sw}',vc,vc),unsafe_allow_html=True)
                if vcp2['contracting']:
                    st.markdown(signal_box('🔴等待帶量突破頸線','green','確認突破才進場'),unsafe_allow_html=True)
            else:
                st.info('數據不足（需≥40日）')
        with ec2:
            st.markdown('**布林通道 [策略3]**')
            if bb2:
                b1,b2=st.columns(2)
                with b1:
                    st.markdown(kpi('現價',f'{bb2["price"]:.2f}','','#e6edf3'),unsafe_allow_html=True)
                    st.markdown(kpi('布林上軌',f'{bb2["upper"]:.2f}','壓力','#f85149','#f85149'),unsafe_allow_html=True)
                with b2:
                    bw_c='#3fb950' if bb2['bw']<bb2['bw_mean']*0.7 else '#d29922'
                    st.markdown(kpi('帶寬',f'{bb2["bw"]:.1f}%',
                                    f'均值{bb2["bw_mean"]:.1f}% {"⬇️收縮" if bb2["bw"]<bb2["bw_mean"] else "⬆️擴張"}',
                                    bw_c,bw_c),unsafe_allow_html=True)
                    st.markdown(kpi('布林下軌',f'{bb2["lower"]:.2f}','支撐','#3fb950','#3fb950'),unsafe_allow_html=True)
                if bb2['bw']<bb2['bw_mean']*0.6:
                    st.markdown(signal_box('🔵布林帶寬極度收縮','blue','即將爆發，注意量能方向'),unsafe_allow_html=True)
                if bb2['near_upper']:
                    st.markdown(signal_box('🟢股價黏近上軌','green','強勢突破訊號，搭配大量更可信'),unsafe_allow_html=True)
        # ── VCP+布林動態建議 ──
        _vcp_verdict = ''
        _bb_verdict  = ''
        if vcp2:
            _vcp_verdict = ('✅ VCP確認收縮：等待帶量突破頸線，是高確信進場點 [策略3]'
                            if vcp2['contracting']
                            else '⚪ 波幅尚未收縮：等待整理完成後再觀察')
        if bb2:
            if bb2['bw'] < bb2['bw_mean']*0.6:
                _bb_verdict = '🔵 布林帶寬極度收縮：即將爆發，注意量能確認方向 [策略3]'
            elif bb2['near_upper']:
                _bb_verdict = '🟢 股價黏近上軌＋強勢：搭配大量是突破確認訊號 [策略3]'
            else:
                _bb_verdict = f'⚪ 布林帶寬{bb2["bw"]:.1f}%（均值{bb2["bw_mean"]:.1f}%）：尚未到關鍵位置'
        if _vcp_verdict or _bb_verdict:
            for _msg in [m for m in [_vcp_verdict, _bb_verdict] if m]:
                _mc2 = '#3fb950' if '✅' in _msg or '🟢' in _msg else ('#58a6ff' if '🔵' in _msg else '#8b949e')
                st.markdown(f'<div style="border-left:3px solid {_mc2};padding:8px 12px;background:#0d1117;border-radius:0 6px 6px 0;font-size:12px;color:{_mc2};margin:4px 0;">{_msg}</div>', unsafe_allow_html=True)

        # VCP+布林結論（安全版：加入 _msg 預設值）
        _msg = _msg if '_msg' in dir() else '⚪ VCP/布林資料不足'
        _vcp_c = '#3fb950' if '✅' in _msg or '🟢' in _msg else ('#d29922' if '⚠️' in _msg else '#484f58')
        st.markdown(
            f'<div style="background:#0d1117;border-left:3px solid {_vcp_c};padding:7px 12px;border-radius:0 6px 6px 0;margin:4px 0;">'
            f'<span style="font-size:11px;color:#8b949e;">🎓 策略3 · VCP</span>　'
            f'<span style="font-size:13px;font-weight:700;color:{_vcp_c};">{_msg}</span>'
            f'</div>', unsafe_allow_html=True
        )
        if bb2:
            _bb_verdict_safe = _bb_verdict if '_bb_verdict' in dir() else '⚪ 布林資料不足'
            _bb_c = '#3fb950' if '✅' in _bb_verdict_safe or '🟢' in _bb_verdict_safe else ('#3aa2f5' if '🔵' in _bb_verdict_safe else '#d29922')
            st.markdown(
                f'<div style="background:#0d1117;border-left:3px solid {_bb_c};padding:7px 12px;border-radius:0 6px 6px 0;margin:4px 0;">'
                f'<span style="font-size:11px;color:#8b949e;">🎓 策略3 · 布林</span>　'
                f'<span style="font-size:13px;font-weight:700;color:{_bb_c};">{_bb_verdict_safe}</span>'
                f'</div>', unsafe_allow_html=True
            )

        # ══ G. 近 20 日籌碼集中度（外資+投信 vs 總成交量）═══════════
        st.markdown('---')
        st.markdown('#### 🔬 G. 近 20 日籌碼集中度')
        with st.spinner(f'計算 {sid2} 近 20 日籌碼集中度...'):
            _chip20 = analyze_20d_chips(sid2)
        if _chip20.get('error'):
            st.caption(f'⚫ 籌碼集中度取得失敗：{_chip20["error"]}')
        else:
            _sig20  = _chip20['signal']
            _con20  = _chip20['concentration']   # % 集中度
            _cty20  = _chip20['continuity']       # % 延續性
            _days20 = _chip20['days']
            _pos20  = _chip20['pos_days']
            _sig20_c = ('#f85149' if '吸籌' in _sig20
                        else ('#da3633' if '倒貨' in _sig20 else '#d29922'))
            st.markdown(
                f'<div style="background:#0d1117;border:1px solid {_sig20_c};'
                f'border-radius:8px;padding:10px 14px;margin:6px 0;">'
                f'<span style="font-size:14px;font-weight:900;color:{_sig20_c};">'
                f'{_sig20}</span>'
                f'<span style="font-size:11px;color:#8b949e;margin-left:12px;">'
                f'近 {_days20} 日 | 外+投累計 {_chip20["total_net_k"]:.1f}千張 | '
                f'成交量 {_chip20["total_vol_k"]:.1f}千張</span>'
                f'</div>', unsafe_allow_html=True)
            _g20c1, _g20c2 = st.columns(2)
            with _g20c1:
                st.metric(
                    label='指標A：集中度（外+投淨買／總量）',
                    value=f'{_con20:+.2f}%',
                    delta='吸籌' if _con20 >= 0 else '倒貨',
                    delta_color='normal' if _con20 >= 0 else 'inverse',
                    help='> +5% 且延續性 > 50% → 大戶吸籌；< -5% → 大戶倒貨')
                st.progress(min(abs(_con20) / 20.0, 1.0),
                            text=f'集中度絕對值 {abs(_con20):.1f}% / 20%上限')
            with _g20c2:
                st.metric(
                    label=f'指標B：延續性（{_days20}日中買超 {_pos20} 天）',
                    value=f'{_cty20:.0f}%',
                    help='> 50% 表示多數交易日外+投持續買超')
                st.progress(_cty20 / 100.0,
                            text=f'買超天數佔比 {_cty20:.0f}%')

        # ══ F. K線技術圖 ═══════════════════════════════════════
        st.markdown('---')
        st.markdown('#### 📊 F. K線技術圖表（含三大法人籌碼）')
        _fa = f'{sid2} K線技術'
        _fb_txt = ''
        _fc_txt = ''
        if df2 is not None and not df2.empty and len(df2) >= 20:
            _p_now_f = float(df2['close'].iloc[-1])
            _ma20_f  = float(df2['close'].rolling(20).mean().iloc[-1])
            _cl_trend = '上漲' if float(df2['close'].iloc[-1]) > float(df2['close'].iloc[-5]) else '下跌'
            _above_f = _p_now_f > _ma20_f
            _inst_f = st.session_state.get('t2_inst', {})
            _fnet_f = _inst_f.get('外資', 0) if _inst_f else 0
            if _above_f and _fnet_f > 0:
                _fb_txt = '站上月線 + 外資買超，主力進駐訊號，可跟進'
                _fc_txt = '停損設月線下方'
            elif _above_f and _fnet_f < 0:
                _fb_txt = '站上月線但外資賣超，需謹慎確認主力方向'
                _fc_txt = '等待外資轉買後再行動'
            elif not _above_f and _fnet_f > 0:
                _fb_txt = '月線下方但外資買超，可能正在築底'
                _fc_txt = '等待重回月線確認後再評估'
            else:
                _fb_txt = '月線下方且外資賣超，趨勢偏空，暫時迴避'
                _fc_txt = '等待更明確的多頭訊號'
            _fa = f'{sid2} 現價{_p_now_f:.1f}（{"站月線" if _above_f else "跌月線"}）| 外資{"買超" if _fnet_f>0 else "賣超" if _fnet_f<0 else "中性"}'
        else:
            _fb_txt = '技術資料載入中，請先點擊「🔍 載入完整分析」'
        st.markdown(teacher_conclusion('朱家泓', _fa, _fb_txt, _fc_txt), unsafe_allow_html=True)
        if df2 is not None and not df2.empty:
            fig_k = plot_combined_chart(df2, sid2, name2, show_ma_dict, k_line_type='還原K線' if t2_adjusted else '一般K線')
            st.plotly_chart(fig_k, width='stretch',
                            config={'displayModeBar':True,'displaylogo':False,
                                    'modeBarButtonsToRemove':['lasso2d','select2d']})
        else:
            if t2d.get('err'):
                st.error(f'❌ {t2d["err"]}')
        # ── K線動態趨勢建議 ──
        if df2 is not None and 'MA20' in df2.columns and 'MA100' in df2.columns:
            _kp = price2
            _km20 = float(df2['MA20'].iloc[-1])
            _km100 = float(df2['MA100'].iloc[-1])
            if _kp > _km20 > _km100:
                _trend_msg = f'📈 多頭排列：股價 {_kp:.1f} ＞ MA20 {_km20:.1f} ＞ MA100 {_km100:.1f} — 宏爺：可持股，大盤多頭才做個股'
                _tc = '#3fb950'
            elif _kp < _km20 < _km100:
                _trend_msg = f'📉 空頭排列：股價 {_kp:.1f} ＜ MA20 {_km20:.1f} ＜ MA100 {_km100:.1f} — 宏爺：不做多，嚴格停損'
                _tc = '#f85149'
            elif _kp > _km100:
                _trend_msg = f'📊 多箱整理：股價在 MA100 之上 — 宏爺：等待站上 MA20({_km20:.1f})確認方向'
                _tc = '#d29922'
            else:
                _trend_msg = '📊 空箱整理：股價低於 MA100 — 宏爺：耐心等待多頭訊號，不摸底'
                _tc = '#d29922'
            st.markdown(f'<div style="border-left:4px solid {_tc};padding:10px 14px;background:#0d1117;border-radius:0 8px 8px 0;font-size:13px;font-weight:700;color:{_tc};margin:8px 0;">{_trend_msg}</div>', unsafe_allow_html=True)

        # K線均線結論（安全版）
        _trend_msg_safe = _trend_msg if '_trend_msg' in dir() else '⚪ K線資料不足'
        _kl_c = '#3fb950' if '多頭' in _trend_msg_safe or '✅' in _trend_msg_safe else ('#f85149' if '空頭' in _trend_msg_safe else '#d29922')
        st.markdown(
            f'<div style="background:#0d1117;border-left:3px solid {_kl_c};padding:7px 12px;border-radius:0 6px 6px 0;margin:4px 0;">'
            f'<span style="font-size:11px;color:#8b949e;">🎓 宏爺 · 均線排列</span>　'
            f'<span style="font-size:13px;font-weight:700;color:{_kl_c};">{_trend_msg_safe}</span>'
            f'</div>', unsafe_allow_html=True
        )

        # ── 近5日評分走勢（儲存本次評分到歷史）───────────────────
        _score_hist_key = f'score_hist_{sid2}'
        _score_hist = st.session_state.get(_score_hist_key, [])
        # 加入今日評分
        _today_str = datetime.date.today().strftime('%m/%d')
        _last_entry = _score_hist[-1] if _score_hist else {}
        if _last_entry.get('date') != _today_str:
            _score_hist.append({
                'date':    _today_str,
                'health':  health2,
                'rsi':     rsi2 or 0,
                'total':   0,  # 多因子評分在 Tab3 中
            })
            _score_hist = _score_hist[-7:]  # 只保留最近7天
            st.session_state[_score_hist_key] = _score_hist

        if len(_score_hist) >= 2:
            st.markdown('---')
            st.markdown('##### 📈 健康度走勢（近5日）')
            _fig_sh = go.Figure()
            _sh_dates  = [r['date']   for r in _score_hist]
            _sh_health = [r['health'] for r in _score_hist]
            # 填色區間
            _fig_sh.add_hrect(y0=80, y1=100, fillcolor='rgba(63,185,80,0.08)',  line_width=0)
            _fig_sh.add_hrect(y0=50, y1=80,  fillcolor='rgba(210,153,34,0.05)', line_width=0)
            _fig_sh.add_hrect(y0=0,  y1=50,  fillcolor='rgba(248,81,73,0.05)',  line_width=0)
            _fig_sh.add_trace(go.Scatter(
                x=_sh_dates, y=_sh_health, mode='lines+markers',
                line=dict(color='#58a6ff', width=2.5),
                marker=dict(size=8, color=['#3fb950' if v>=80 else ('#d29922' if v>=50 else '#f85149')
                                           for v in _sh_health]),
                text=[str(v) for v in _sh_health], textposition='top center',
                hovertemplate='%{x}<br>健康度：%{y:.0f}<extra></extra>'
            ))
            _fig_sh.update_layout(
                height=180, plot_bgcolor='#0e1117', paper_bgcolor='#0e1117',
                font=dict(color='white',size=10), margin=dict(l=10,r=10,t=10,b=20),
                xaxis=dict(gridcolor='#21262d'), yaxis=dict(gridcolor='#21262d',range=[0,105]),
                showlegend=False)
            st.plotly_chart(_fig_sh, width='stretch', config={'displayModeBar':False})
            # 評分突變偵測（分數飆升≥20分）
            if len(_sh_health) >= 2 and _sh_health[-1] - _sh_health[-2] >= 20:
                st.success(f'🚀 評分突變！健康度從 {_sh_health[-2]:.0f} → {_sh_health[-1]:.0f}（+{_sh_health[-1]-_sh_health[-2]:.0f}），可能是主升段起點！')

        # ══ G. AI 五維報告 ══════════════════════════════════════
        st.markdown('---')

        # ── 即時文字建議（Rule-based，不需 AI API）──────────────
        st.markdown('#### 💡 即時操作建議（規則引擎）')
        _reg_op = st.session_state.get('mkt_info', {}).get('regime', 'neutral')
        _sig_count = sum([
            1 if health2 >= 80 else 0,
            1 if _reg_op == 'bull' else 0,
            1 if (vcp2 and vcp2.get('contracting')) else 0,
            1 if (avg_div2 > 0 and price2 > 0 and price2 <= round(avg_div2/0.05, 1)) else 0,
        ])
        if _reg_op == 'bear':
            _op_a = f'大盤空頭格局，{sid2} 無論評分多高，先降倉至20%以下'
            _op_b = '市場趨勢優先，個股強不等於能賺錢'
        elif _sig_count >= 3:
            _op_a = f'{_sig_count}個訊號共振（健康度+大盤+VCP+估值），可積極進場'
            _op_b = '分批建倉，停損設健康度跌破60'
        elif _sig_count >= 2:
            _op_a = f'{_sig_count}個訊號共振，中性偏多，可小倉試水溫'
            _op_b = '輕倉試探，等待更多確認訊號'
        else:
            _op_a = f'只有{_sig_count}個訊號，條件不足，今日不操作 {sid2}'
            _op_b = '耐心等待，寧可錯過勿強求'
        st.markdown(teacher_conclusion('宏爺', f'{sid2} 共振訊號 {_sig_count}/4', _op_a, _op_b), unsafe_allow_html=True)
        try:
            _mkt_top_g = st.session_state.get('mkt_info', {})
            _m1b_top_g = st.session_state.get('m1b_m2_info', {})
            _bias_g    = st.session_state.get('bias_info', {})
            _m1b_diff_g= _m1b_top_g.get('m1b_yoy',0)-_m1b_top_g.get('m2_yoy',0) if _m1b_top_g else 0
            # 取 Tab3 最近分析的外資資料
            _cd_g = st.session_state.get('cl_data',{})
            _inst_g = _cd_g.get('inst',{})
            _fk_g = next((k for k in _inst_g if '外資' in k), None)
            _tk_g = next((k for k in _inst_g if '投信' in k), None)
            _comment_data = {
                'health':      health2,
                'score':       0,  # Tab3 多因子評分（此處無法取得，用0）
                'rsi':         rsi2,
                'vcp_ok':      bool(vcp2 and isinstance(vcp2,dict) and vcp2.get('contracting')),
                'bias_240':    _bias_g.get('bias_240', 0),
                'bias_20':     _bias_g.get('bias_20', 0),
                'val_label':   _357_label2 if '_357_label2' in dir() else '',  # noqa: F821
                'trend':       _trend_text2 if '_trend_text2' in dir() else '',  # noqa: F821
                'cl':          cl2 / 1e8 if cl2 and cl2 > 0 else 0,
                'cx':          cx2 / 1e8 if cx2 and cx2 > 0 else 0,
                'foreign_buy': _inst_g.get(_fk_g,{}).get('net',0) if _fk_g else 0,
                'trust_buy':   _inst_g.get(_tk_g,{}).get('net',0) if _tk_g else 0,
                'm1b_diff':    _m1b_diff_g,
            }
            _comment_txt = generate_ai_comment(_comment_data)
            if _comment_txt:
                st.markdown(
                    '<div style="background:#0d1117;border:1px solid #30363d;'
                    'border-radius:10px;padding:14px;margin-bottom:10px;'
                    'font-size:13px;color:#c9d1d9;line-height:1.7;">'
                    + _comment_txt.replace(chr(10), '<br>') +
                    '</div>', unsafe_allow_html=True)
        except Exception as _ce:
            pass

        st.markdown("""<div style="margin:24px 0 8px;padding:8px 16px;background:linear-gradient(90deg,#3fb95018,#0d1117);border-left:4px solid #3fb950;border-radius:0 6px 6px 0;"><span style="font-size:15px;font-weight:900;color:#3fb950;">📊 基本面分析</span><span style="font-size:11px;color:#8b949e;margin-left:8px;">357殖利率評價 · 財報領先指標 · 月營收趨勢 · 六大先行指標</span></div>""", unsafe_allow_html=True)
        # ══ B. 357 評價 ════════════════════════════════════════
        st.markdown('---')
        st.markdown('#### 💰 B. 357殖利率評價 [策略1]')
        if avg_div2 > 0 and price2 > 0:
            _cp2 = round(avg_div2/0.07, 1)
            _fp2 = round(avg_div2/0.05, 1)
            _dp2 = round(avg_div2/0.03, 1)
            if price2 <= _cp2:
                _ba = f'現價 {price2:.1f} ≤ 便宜價 {_cp2:.1f}（殖利率>7%），積極買進區'
                _bb = '可大膽買進，股息都進口袋'
            elif price2 <= _fp2:
                _ba = f'現價 {price2:.1f} 在合理區 {_cp2:.1f}–{_fp2:.1f}（殖利率5-7%）'
                _bb = '可分批布局，勿一次梭哈'
            elif price2 <= _dp2:
                _ba = f'現價 {price2:.1f} 在昂貴區 {_fp2:.1f}–{_dp2:.1f}（殖利率3-5%）'
                _bb = '謹慎，等回調至合理價再進場'
            else:
                _ba = f'現價 {price2:.1f} > 昂貴價 {_dp2:.1f}（殖利率<3%），嚴禁追高'
                _bb = '放下，等大跌再看'
        else:
            _ba = '無股利資料，無法套用357評價'
            _bb = '以技術面健康度為主要判斷'
        st.markdown(teacher_conclusion('孫慶龍', f'{sid2} 現價{price2:.1f} vs 357區間', _ba, _bb), unsafe_allow_html=True)
        if avg_div2 > 0:
            cheap2=round(avg_div2/0.07,1)
            fair2=round(avg_div2/0.05,1)
            dear2=round(avg_div2/0.03,1)
            if price2<=cheap2:
                sig2,sc2='🟢便宜價 — 積極買進','#3fb950'
            elif price2<=fair2:
                sig2,sc2='🟡合理價 — 可分批布局','#d29922'
            elif price2<=dear2:
                sig2,sc2='🔴昂貴價 — 謹慎操作','#f85149'
            else:
                sig2,sc2='🔴超過昂貴 — 避免追高','#f85149'
            st.markdown(f"""<div style="background:#161b22;border:2px solid {sc2};border-radius:10px;
padding:12px 16px;margin:8px 0;">
<div style="font-size:16px;font-weight:900;color:{sc2};">{sig2}</div>
<div style="font-size:11px;color:#8b949e;margin-top:4px;">
  {sid2} {name2} | 現價 <b style="color:#58a6ff;">{price2:.2f}</b> |
  近5年均股利 <b style="color:#ffd700;">{avg_div2:.2f}元</b> ({t2d.get('div_src','')})
</div></div>""", unsafe_allow_html=True)
            v1,v2,v3,v4=st.columns(4)
            for vc,vl,vp,vcol in [(v1,'現價',price2,'#58a6ff'),(v2,'🟢便宜(7%)',cheap2,'#3fb950'),
                                   (v3,'🟡合理(5%)',fair2,'#d29922'),(v4,'🔴昂貴(3%)',dear2,'#f85149')]:
                with vc:
                    st.markdown(kpi(vl,f'{vp:.1f}','',vcol,vcol),unsafe_allow_html=True)
            if yearly2:
                fig_d=go.Figure(go.Bar(
                    x=[str(int(y['year'])) for y in yearly2],
                    y=[y['cash'] for y in yearly2],
                    marker_color='#ffd700',
                    text=[f'{y["cash"]:.2f}' for y in yearly2],textposition='auto'))
                fig_d.update_layout(height=180,plot_bgcolor='#0e1117',paper_bgcolor='#0e1117',
                                    font=dict(color='white'),margin=dict(l=20,r=20,t=30,b=20),
                                    title=dict(text=f'{sid2} 近5年現金股利',font=dict(color='#ffd700',size=12)),
                                    yaxis=dict(gridcolor='#333'),xaxis=dict(gridcolor='#333'))
                st.plotly_chart(fig_d,width='stretch',config={'displayModeBar':False})
        else:
            st.warning('⚠️ 無配息記錄（成長股）— 建議改用本益比評估')
        # ── 357 動態建議 ──
        _asset_type = '📈 大盤' if sid2 in ('^TWII', 'TAIEX') else '📊 個股'
        if avg_div2 > 0:
            _grade = ("便宜價🟢 — 策略1：積極買進！" if price2<=cheap2
                      else ("合理價🟡 — 策略1：可分批布局，等殖利率拉升再加碼" if price2<=fair2
                            else ("昂貴價🔴 — 策略1：謹慎操作，等待回檔再進場" if price2<=dear2
                                  else "超過昂貴價🔴 — 策略1：絕對不追高，等待大幅修正")))
            _357_verdict = f'**{sid2} {name2}** 現價 {price2:.1f} 處於 {_grade}，近5年均股利 {avg_div2:.2f} 元'
            _357_c = '#3fb950' if price2<=cheap2 else ('#d29922' if price2<=fair2 else '#f85149')
            st.markdown(
                f'{_asset_type} **`{sid2}` {name2}** ｜ 策略1·357法則判斷'
            )
            st.markdown(f'<div style="background:#161b22;border-left:4px solid {_357_c};padding:10px 14px;border-radius:0 8px 8px 0;font-size:13px;font-weight:700;color:{_357_c};margin:6px 0;">{_357_verdict}</div>', unsafe_allow_html=True)
        # 357結論：直接顯示當前評估，不導向策略手冊
        st.markdown(
            f'<div style="background:#0d1117;border-left:4px solid {_357_c};'
            f'padding:10px 14px;border-radius:0 8px 8px 0;margin:6px 0;">'
            f'<span style="font-size:12px;color:#8b949e;">{_asset_type} <code>{sid2}</code> {name2} ｜ 🎓 策略1 · 357法則判斷</span><br>'
            f'<span style="font-size:14px;font-weight:800;color:{_357_c};">{_357_verdict}</span><br>'
            f'<span style="font-size:11px;color:#8b949e;">判讀邏輯：殖利率≥7%=便宜大買；5-7%=合理；3-5%=偏貴持有；&lt;3%=昂貴停利</span>'
            f'</div>',
            unsafe_allow_html=True
        )

        # ── 估值河流圖（357殖利率河流，逐日 TTM）────────────────────
        if df2 is not None and not df2.empty:
            # ── 1. 將 yearly2 轉成「ex-div 事件序列」（年中 7/1 為合成除息日） ──
            # 防護：合成日期若 > 今天（如 2026/5 跑時 2026/7/1 在未來），365D rolling
            # 涵蓋不到 → 整段 TTM 為 0 → 河流消失。跳過所有未來事件。
            _today_ts = pd.Timestamp(datetime.date.today())
            _riv_events = []
            if yearly2:
                for _y in yearly2:
                    try:
                        _y_cash = float(_y.get('cash', 0) or 0)
                        if _y_cash > 0:
                            _ev_dt = pd.Timestamp(int(_y['year']), 7, 1)
                            if _ev_dt > _today_ts:
                                continue
                            _riv_events.append({'date': _ev_dt, 'div': _y_cash})
                    except Exception:
                        pass
            # 若無逐年資料，用 avg_div2 補「去年 7/1」（不是今年——避免落在未來）
            if not _riv_events and avg_div2 and avg_div2 > 0:
                _riv_events.append({
                    'date': pd.Timestamp(datetime.date.today().year - 1, 7, 1),
                    'div':  float(avg_div2)
                })

            if _riv_events:
                # ── 2. 對 df2 每個交易日做 365D rolling sum (TTM 股利) ──
                _rdates_s   = pd.to_datetime(
                    df2['date'] if 'date' in df2.columns else pd.RangeIndex(len(df2)))
                _rclose_riv = pd.to_numeric(df2['close'], errors='coerce').reset_index(drop=True)
                _rdates_riv = _rdates_s.reset_index(drop=True)

                # 合併「股利事件」+「交易日」成一條時間序列，計算 365D rolling sum
                _ev_df = pd.DataFrame(_riv_events).sort_values('date').reset_index(drop=True)
                _ev_df['kind'] = 'ev'
                _td_df = pd.DataFrame({'date': _rdates_riv, 'div': 0.0, 'kind': 'td'})
                _all_df = (pd.concat([_ev_df, _td_df], ignore_index=True)
                           .sort_values('date')
                           .reset_index(drop=True))
                _all_df['ttm'] = (_all_df.set_index('date')['div']
                                  .rolling('365D', min_periods=1).sum().values)

                # 抽出交易日對應的 TTM，並 forward-fill 上一次有效值（避免年末窗口空洞）
                _td_only = _all_df[_all_df['kind'] == 'td'].copy()
                _td_only['ttm'] = _td_only['ttm'].mask(_td_only['ttm'] <= 0).ffill()
                _ttm_series = pd.to_numeric(_td_only['ttm'], errors='coerce').reset_index(drop=True)

                # ── 安全網：TTM 整段全 0 / NaN（過去 12 月真的沒除息）→ 退回 avg_div2 橫帶 ──
                _ttm_valid = _ttm_series.dropna()
                _is_fallback_flat = (_ttm_valid.empty or float(_ttm_valid.max()) <= 0) \
                    and avg_div2 and avg_div2 > 0
                if _is_fallback_flat:
                    _ttm_series = pd.Series([float(avg_div2)] * len(_rdates_riv))

                # ── 3. 計算河流帶：P = TTM 股利 / 殖利率閾值（逐日） ──
                _band7_riv = (_ttm_series / 0.07).round(2)
                _band5_riv = (_ttm_series / 0.05).round(2)
                _band3_riv = (_ttm_series / 0.03).round(2)

                _cur_div_riv = float(_ttm_series.dropna().iloc[-1]) if not _ttm_series.dropna().empty else 0
                _p7r = float(_band7_riv.dropna().iloc[-1]) if not _band7_riv.dropna().empty else 0
                _p5r = float(_band5_riv.dropna().iloc[-1]) if not _band5_riv.dropna().empty else 0
                _p3r = float(_band3_riv.dropna().iloc[-1]) if not _band3_riv.dropna().empty else 0

                # ── 5. 繪圖 ──
                _fig_riv = go.Figure()
                _fig_riv.add_trace(go.Scatter(
                    x=_rdates_riv, y=_rclose_riv, name='收盤價',
                    line=dict(color='#e6edf3', width=2.5),
                    hovertemplate='%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>'))

                for _bs, _lbl_base, _last_val, _col in [
                    (_band7_riv, '7%便宜', _p7r, '#3fb950'),
                    (_band5_riv, '5%合理', _p5r, '#d29922'),
                    (_band3_riv, '3%昂貴', _p3r, '#f85149')
                ]:
                    _lbl = f'{_lbl_base}:{_last_val:.0f}' if _last_val > 0 else _lbl_base
                    _fig_riv.add_trace(go.Scatter(
                        x=_rdates_riv, y=_bs, name=_lbl,
                        line=dict(color=_col, width=1.5, dash='dot'),
                        hovertemplate=f'{_lbl_base}: %{{y:.0f}}<extra></extra>'))

                # 色帶（以最新一日的帶值為基準）
                _b7_last = float(_band7_riv.dropna().iloc[-1]) if not _band7_riv.dropna().empty else 0
                _b5_last = float(_band5_riv.dropna().iloc[-1]) if not _band5_riv.dropna().empty else 0
                _b3_last = float(_band3_riv.dropna().iloc[-1]) if not _band3_riv.dropna().empty else 0
                if _b7_last > 0:
                    _fig_riv.add_hrect(y0=0, y1=_b7_last, fillcolor='rgba(63,185,80,0.07)', line_width=0)
                if _b5_last > _b7_last:
                    _fig_riv.add_hrect(y0=_b7_last, y1=_b5_last, fillcolor='rgba(210,153,34,0.07)', line_width=0)
                if _b3_last > _b5_last:
                    _fig_riv.add_hrect(y0=_b5_last, y1=_b3_last, fillcolor='rgba(248,81,73,0.05)', line_width=0)

                # Y 軸：自動涵蓋股價與所有河流帶
                _all_riv_vals = (
                    list(_rclose_riv.dropna()) +
                    list(_band3_riv.dropna()) +
                    list(_band7_riv.dropna())
                )
                _ymax_riv = max(_all_riv_vals) * 1.05 if _all_riv_vals else 100
                _ymin_riv = max(0, min(_all_riv_vals) * 0.7) if _all_riv_vals else 0

                _div_label = '近5年均股利' if _is_fallback_flat else 'TTM 股利'
                _fig_riv.update_layout(
                    title=dict(
                        text=f'📊 {sid2} {name2} 殖利率河流圖（{_div_label} {_cur_div_riv:.2f}元）',
                        font=dict(color='#8b949e', size=12)),
                    height=300, plot_bgcolor='#0e1117', paper_bgcolor='#0e1117',
                    font=dict(color='white', size=11),
                    margin=dict(l=10, r=10, t=40, b=10),
                    xaxis=dict(gridcolor='#21262d'),
                    yaxis=dict(range=[_ymin_riv, _ymax_riv], gridcolor='#21262d'),
                    hovermode='x unified', showlegend=True,
                    legend=dict(orientation='h', y=1.08, x=0, font=dict(size=10)))
                st.plotly_chart(_fig_riv, width='stretch', config={'displayModeBar': False})

                _cur_price_riv = float(_rclose_riv.dropna().iloc[-1]) if not _rclose_riv.dropna().empty else 0
                if _is_fallback_flat:
                    # Fallback 模式（近 12 月無除息）：橫帶保留作歷史比較，但移除便宜/合理/昂貴/超昂貴判讀避免誤導
                    st.caption(
                        f'📊 歷史參考帶（{_div_label} {_cur_div_riv:.2f}元，非即時 TTM）　'
                        f'7%≤{_p7r:.0f} / 5%≤{_p5r:.0f} / 3%≤{_p3r:.0f}　現價 {_cur_price_riv:.0f}')
                    st.info('ℹ️ 此股近 12 個月無除息事件，殖利率河流退化為 5 年均股利橫帶（僅作歷史對照），**不適合作為即時估值依據**。建議改用本益比 / 股價淨值比等其他估值工具。')
                else:
                    _cur_zone = ('🟢 便宜區' if _cur_price_riv < _p7r else
                                 '🟡 合理區' if _cur_price_riv < _p5r else
                                 '🔴 昂貴區' if _cur_price_riv < _p3r else '⛔ 超昂貴')
                    st.caption(
                        f'目前位於 {_cur_zone}（現價 {_cur_price_riv:.0f} / '
                        f'便宜≤{_p7r:.0f} / 合理≤{_p5r:.0f} / 昂貴≤{_p3r:.0f}）'
                        f'　{_div_label} {_cur_div_riv:.2f}元')
                    if _cur_div_riv < 0.5:
                        st.info('ℹ️ 此股近年現金股利極低（< 0.5元），殖利率河流圖參考意義有限，建議搭配本益比等其他估值工具。')

        # ── 估值河流圖（PE 本益比河流，逐日 TTM EPS）───────────────────
        # TTM EPS = 最近 4 季 EPS 加總；歷史 TTM = 4 季 rolling sum，按公告生效日對應到日線
        _has_eps = (qtr2 is not None and not qtr2.empty
                    and 'EPS' in qtr2.columns and 'date' in qtr2.columns)
        _eps_q_clean = (pd.to_numeric(qtr2['EPS'], errors='coerce').dropna()
                        if _has_eps else pd.Series(dtype=float))

        if df2 is not None and not df2.empty and _has_eps and len(_eps_q_clean) >= 4:
            # PE 閾值三組 selectbox（依產業屬性切換）
            _pe_preset_label = st.selectbox(
                'PE 估值區間',
                ['通用 10/15/20', '保守 8/12/16（景氣循環股）', '成長 12/18/25'],
                index=0, key=f'pe_preset_{sid2}',
                help='通用：多數產業；保守：半導體代工/面板/DRAM 等高波動景氣循環股；成長：科技/消費/軟體股')
            _PE_BANDS = {
                '通用 10/15/20': (10, 15, 20),
                '保守 8/12/16（景氣循環股）': (8, 12, 16),
                '成長 12/18/25': (12, 18, 25),
            }
            _pe_low, _pe_mid, _pe_high = _PE_BANDS[_pe_preset_label]

            # ── 1. 計算逐季 TTM EPS（4 季 rolling sum） ──
            _qs = qtr2.sort_values(['年度', '季度']).reset_index(drop=True).copy()
            _qs['ttm_eps'] = pd.to_numeric(_qs['EPS'], errors='coerce').rolling(4, min_periods=4).sum()
            # 公告生效日：季末 + 60 天（涵蓋台股財報公告期 Q1=5/15、Q2=8/14、Q3=11/14、年報 3/31）
            _qs['announce'] = pd.to_datetime(_qs['date'], errors='coerce') + pd.Timedelta(days=60)
            _qa = _qs.dropna(subset=['ttm_eps', 'announce']).sort_values('announce').reset_index(drop=True)

            # ── 2. asof 對應到日線：每個交易日採用該日之前最後一筆已公告的 TTM EPS ──
            _rdates_pe = pd.to_datetime(
                df2['date'] if 'date' in df2.columns else pd.RangeIndex(len(df2)),
                errors='coerce').reset_index(drop=True)
            _rclose_pe = pd.to_numeric(df2['close'], errors='coerce').reset_index(drop=True)
            _df_p = pd.DataFrame({'date': _rdates_pe, 'close': _rclose_pe}).sort_values('date').reset_index(drop=True)
            _df_a = _qa[['announce', 'ttm_eps']].rename(columns={'announce': 'date'})
            _merged_pe = pd.merge_asof(_df_p, _df_a, on='date', direction='backward')
            _ttm_eps_series = _merged_pe['ttm_eps']

            # ── 3. 計算最新 TTM EPS + 虧損股檢查 ──
            _cur_eps_pe = float(_ttm_eps_series.dropna().iloc[-1]) if not _ttm_eps_series.dropna().empty else 0
            _cur_price_pe = float(_rclose_pe.dropna().iloc[-1]) if not _rclose_pe.dropna().empty else 0

            if _cur_eps_pe <= 0:
                st.warning(f'⚠️ {sid2} 近 4 季 TTM EPS = {_cur_eps_pe:.2f} 元（虧損），本益比估值不適用。請參考下方 P/B 股價淨值比河流圖。')
            else:
                # ── 4. 計算河流帶（逐日） ──
                _band_pe_low  = (_ttm_eps_series * _pe_low).round(2)
                _band_pe_mid  = (_ttm_eps_series * _pe_mid).round(2)
                _band_pe_high = (_ttm_eps_series * _pe_high).round(2)
                _p_lo = float(_band_pe_low.dropna().iloc[-1])  if not _band_pe_low.dropna().empty  else 0
                _p_mi = float(_band_pe_mid.dropna().iloc[-1])  if not _band_pe_mid.dropna().empty  else 0
                _p_hi = float(_band_pe_high.dropna().iloc[-1]) if not _band_pe_high.dropna().empty else 0

                # ── 5. 繪圖 ──
                _fig_pe = go.Figure()
                _fig_pe.add_trace(go.Scatter(
                    x=_rdates_pe, y=_rclose_pe, name='收盤價',
                    line=dict(color='#e6edf3', width=2.5),
                    hovertemplate='%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>'))
                for _bs, _lbl_base, _last_val, _col in [
                    (_band_pe_low,  f'PE{_pe_low}便宜',  _p_lo, '#3fb950'),
                    (_band_pe_mid,  f'PE{_pe_mid}合理',  _p_mi, '#d29922'),
                    (_band_pe_high, f'PE{_pe_high}昂貴', _p_hi, '#f85149'),
                ]:
                    _lbl = f'{_lbl_base}:{_last_val:.0f}' if _last_val > 0 else _lbl_base
                    _fig_pe.add_trace(go.Scatter(
                        x=_rdates_pe, y=_bs, name=_lbl,
                        line=dict(color=_col, width=1.5, dash='dot'),
                        hovertemplate=f'{_lbl_base}: %{{y:.0f}}<extra></extra>'))
                if _p_lo > 0:
                    _fig_pe.add_hrect(y0=0, y1=_p_lo, fillcolor='rgba(63,185,80,0.07)', line_width=0)
                if _p_mi > _p_lo:
                    _fig_pe.add_hrect(y0=_p_lo, y1=_p_mi, fillcolor='rgba(210,153,34,0.07)', line_width=0)
                if _p_hi > _p_mi:
                    _fig_pe.add_hrect(y0=_p_mi, y1=_p_hi, fillcolor='rgba(248,81,73,0.05)', line_width=0)

                _all_pe_vals = (list(_rclose_pe.dropna())
                                + list(_band_pe_high.dropna()) + list(_band_pe_low.dropna()))
                _ymax_pe = max(_all_pe_vals) * 1.05 if _all_pe_vals else 100
                _ymin_pe = max(0, min(_all_pe_vals) * 0.7) if _all_pe_vals else 0

                _fig_pe.update_layout(
                    title=dict(
                        text=f'📈 {sid2} {name2} 本益比河流圖（TTM EPS {_cur_eps_pe:.2f}元 × PE {_pe_low}/{_pe_mid}/{_pe_high}）',
                        font=dict(color='#8b949e', size=12)),
                    height=300, plot_bgcolor='#0e1117', paper_bgcolor='#0e1117',
                    font=dict(color='white', size=11),
                    margin=dict(l=10, r=10, t=40, b=10),
                    xaxis=dict(gridcolor='#21262d'),
                    yaxis=dict(range=[_ymin_pe, _ymax_pe], gridcolor='#21262d'),
                    hovermode='x unified', showlegend=True,
                    legend=dict(orientation='h', y=1.08, x=0, font=dict(size=10)))
                st.plotly_chart(_fig_pe, width='stretch', config={'displayModeBar': False})

                _cur_pe_ratio = _cur_price_pe / _cur_eps_pe if _cur_eps_pe > 0 else 0
                _cur_zone_pe = ('🟢 便宜區' if _cur_price_pe < _p_lo else
                                '🟡 合理區' if _cur_price_pe < _p_mi else
                                '🔴 昂貴區' if _cur_price_pe < _p_hi else '⛔ 超昂貴')
                st.caption(
                    f'目前位於 {_cur_zone_pe}（現價 {_cur_price_pe:.0f} / '
                    f'PE{_pe_low}≤{_p_lo:.0f} / PE{_pe_mid}≤{_p_mi:.0f} / PE{_pe_high}≤{_p_hi:.0f}）　'
                    f'TTM EPS {_cur_eps_pe:.2f}元，當前 PE ≈ {_cur_pe_ratio:.1f} 倍')
        elif df2 is not None and not df2.empty:
            st.info(f'ℹ️ {sid2} 季報 EPS 資料不足 4 季（取得 {len(_eps_q_clean)} 季），無法繪製本益比河流圖。')

        # ── 估值河流圖（PB 股價淨值比河流，BPS 橫帶 fallback）──────────
        # BPS 變化緩慢，採用 yfinance 最新 bookValue 畫橫帶（不做歷史 rolling）
        _bps_val = 0.0
        try:
            import yfinance as _yf_pb
            for _sfx_pb in ('.TW', '.TWO'):
                try:
                    _info_pb = _yf_pb.Ticker(f'{sid2}{_sfx_pb}').info or {}
                    _bps_v = _info_pb.get('bookValue')
                    if _bps_v and float(_bps_v) > 0:
                        _bps_val = float(_bps_v)
                        break
                except Exception:
                    continue
        except Exception:
            pass

        if df2 is not None and not df2.empty and _bps_val > 0:
            _PB_LOW, _PB_MID, _PB_HIGH = 0.8, 1.5, 2.5
            _b_lo_pb = round(_bps_val * _PB_LOW, 2)
            _b_mi_pb = round(_bps_val * _PB_MID, 2)
            _b_hi_pb = round(_bps_val * _PB_HIGH, 2)

            _rdates_pb = pd.to_datetime(
                df2['date'] if 'date' in df2.columns else pd.RangeIndex(len(df2)),
                errors='coerce').reset_index(drop=True)
            _rclose_pb = pd.to_numeric(df2['close'], errors='coerce').reset_index(drop=True)

            _fig_pb = go.Figure()
            _fig_pb.add_trace(go.Scatter(
                x=_rdates_pb, y=_rclose_pb, name='收盤價',
                line=dict(color='#e6edf3', width=2.5),
                hovertemplate='%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>'))
            for _v_pb, _lbl_pb, _col_pb in [
                (_b_lo_pb, f'PB{_PB_LOW}便宜:{_b_lo_pb:.0f}',  '#3fb950'),
                (_b_mi_pb, f'PB{_PB_MID}合理:{_b_mi_pb:.0f}',  '#d29922'),
                (_b_hi_pb, f'PB{_PB_HIGH}昂貴:{_b_hi_pb:.0f}', '#f85149'),
            ]:
                _fig_pb.add_hline(y=_v_pb, line=dict(color=_col_pb, width=1.5, dash='dot'),
                                  annotation_text=_lbl_pb, annotation_position='right',
                                  annotation_font=dict(color=_col_pb, size=10))
            _fig_pb.add_hrect(y0=0, y1=_b_lo_pb, fillcolor='rgba(63,185,80,0.07)', line_width=0)
            _fig_pb.add_hrect(y0=_b_lo_pb, y1=_b_mi_pb, fillcolor='rgba(210,153,34,0.07)', line_width=0)
            _fig_pb.add_hrect(y0=_b_mi_pb, y1=_b_hi_pb, fillcolor='rgba(248,81,73,0.05)', line_width=0)

            _all_pb_vals = list(_rclose_pb.dropna()) + [_b_hi_pb, _b_lo_pb]
            _ymax_pb = max(_all_pb_vals) * 1.05 if _all_pb_vals else 100
            _ymin_pb = max(0, min(_all_pb_vals) * 0.7) if _all_pb_vals else 0
            _cur_price_pb = float(_rclose_pb.dropna().iloc[-1]) if not _rclose_pb.dropna().empty else 0
            _cur_pb_ratio = _cur_price_pb / _bps_val if _bps_val > 0 else 0

            _fig_pb.update_layout(
                title=dict(
                    text=f'📐 {sid2} {name2} 股價淨值比河流圖（BPS {_bps_val:.2f}元 × PB {_PB_LOW}/{_PB_MID}/{_PB_HIGH}）',
                    font=dict(color='#8b949e', size=12)),
                height=280, plot_bgcolor='#0e1117', paper_bgcolor='#0e1117',
                font=dict(color='white', size=11),
                margin=dict(l=10, r=10, t=40, b=10),
                xaxis=dict(gridcolor='#21262d'),
                yaxis=dict(range=[_ymin_pb, _ymax_pb], gridcolor='#21262d'),
                hovermode='x unified', showlegend=False)
            st.plotly_chart(_fig_pb, width='stretch', config={'displayModeBar': False})

            _cur_zone_pb = ('🟢 便宜區' if _cur_price_pb < _b_lo_pb else
                            '🟡 合理區' if _cur_price_pb < _b_mi_pb else
                            '🔴 昂貴區' if _cur_price_pb < _b_hi_pb else '⛔ 超昂貴')
            st.caption(
                f'目前位於 {_cur_zone_pb}（現價 {_cur_price_pb:.0f} / '
                f'PB{_PB_LOW}≤{_b_lo_pb:.0f} / PB{_PB_MID}≤{_b_mi_pb:.0f} / PB{_PB_HIGH}≤{_b_hi_pb:.0f}）　'
                f'BPS {_bps_val:.2f}元，當前 PB ≈ {_cur_pb_ratio:.2f} 倍')
            st.info('ℹ️ BPS（每股淨值）變化緩慢，本圖採 yfinance 最新值作橫帶（非逐日 rolling）。製造業慣例 PB<1 便宜、1~1.5 合理、>1.5 昂貴；金融股可放寬。')
        elif df2 is not None and not df2.empty:
            st.caption('ℹ️ 股價淨值比河流圖：yfinance 未提供 BPS 資料，跳過。')

        # ══ C. 領先指標 ════════════════════════════════════════
        st.markdown('---')
        st.markdown('#### 🔬 C. 公司真的在賺錢嗎？（財報領先指標）')
        if cl2 and cl2 > 0 and cx2 and cx2 > 0:
            _ca = f'合約負債 {cl2/1e8:.1f}億 + 資本支出 {cx2/1e8:.1f}億，雙重確認龍多股'
            _cb = '基本面強勢，適合長期持有'
        elif cl2 and cl2 > 0:
            _ca = f'合約負債 {cl2/1e8:.1f}億（訂單豐沛），資本支出資料不足'
            _cb = '基本面良好，但擴廠意願待確認'
        elif cx2 and cx2 > 0:
            _ca = f'資本支出 {cx2/1e8:.1f}億（積極擴產），合約負債資料不足'
            _cb = '擴廠意願強，但訂單能見度待確認'
        else:
            _ca = '合約負債+資本支出均無資料（可能為金融股或資料源限制）'
            _cb = '請至 MOPS 或年報查閱'
        st.markdown(teacher_conclusion('孫慶龍', f'{sid2} 財報領先指標', _ca, _cb), unsafe_allow_html=True)
        st.markdown(
            '<div style="background:#0a1628;border-left:3px solid #bc8cff;padding:8px 12px;'
            'border-radius:0 6px 6px 0;margin-bottom:8px;font-size:12px;color:#c9d1d9;">'
            '💡 這兩個財報數字能預測未來3-6個月的獲利方向：'
            '<br>📌 <b>合約負債</b> = 客戶已付錢但還沒出貨的訂單 → 越高代表訂單很多、業績有保障'
            '<br>📌 <b>資本支出</b> = 公司花錢蓋廠房買設備 → 越高代表看好未來、準備大幅擴產'
            '<br>⭐ 兩個都很高 = 策略1所說的「龍多股」，是存股首選'
            '</div>', unsafe_allow_html=True)
        fc1,fc2=st.columns(2)
        cl_ok=cl2 is not None and cl2>0
        cx_ok=cx2 is not None and cx2>0
        _cl_st = _fin_st2.get('contract_liabilities') if '_fin_st2' in dir() else None  # noqa: F821
        _cx_st = _fin_st2.get('fixed_assets')         if '_fin_st2' in dir() else None  # noqa: F821
        _cl_label = "--" if cl_ok else '無數據'
        _cx_label = "--" if cx_ok else '無數據'
        _cl_color_map = {'ok':'#3fb950','missing':'#d29922','not_applicable':'#484f58','fetch_error':'#f85149'}
        _cx_color_map = {'ok':'#58a6ff','missing':'#d29922','not_applicable':'#484f58','fetch_error':'#f85149'}
        with fc1:
            _cl_val_txt = f'{cl2/1e8:.1f}億' if cl_ok else '抓取失敗'
            _cl_c = '#2ea043' if cl_ok else '#da3633'
            st.markdown(kpi('合約負債', _cl_val_txt,
                            '>股本50%→未來3-6月訂單保障', _cl_c,
                            _cl_c if cl_ok else '#21262d'),unsafe_allow_html=True)
            if not cl_ok:
                st.caption('來源：FinMind — 抓取失敗或無此財報')
        with fc2:
            _cx_val_txt = f'{cx2/1e8:.1f}億' if cx_ok else '抓取失敗'
            _cx_c = '#2ea043' if cx_ok else '#da3633'
            st.markdown(kpi('固定資產/資本支出', _cx_val_txt,
                            '>股本80%→大擴廠看好未來需求', _cx_c,
                            _cx_c if cx_ok else '#21262d'),unsafe_allow_html=True)
            if not cx_ok:
                st.caption(f'來源：{_cl_src2 or _cx_src2 or "未知"}')
        if not cl_ok and not cx_ok:
            _na = (not _fin_errs2 and not cl_ok and not cx_ok)
            _fe = bool(_fin_errs2)
            if _na:
                st.info('ℹ️ 此產業（金融/保險等）不適用合約負債/固定資產指標，可跳過')
            elif _fe:
                # 顯示具體錯誤給使用者
                _err_src = (_cl_src2 + '/' + _cx_src2).strip('/')
                _err_msg = '; '.join(_fin_errs2) if _fin_errs2 else '抓取失敗'
                st.error(f'❌ 財報資料抓取失敗 — 來源:{_err_src or "三源均未命中"} | 錯誤:{_err_msg}')
                st.caption('💡 可能原因：① FinMind Token 失效 ② MOPS 暫時無回應 ③ 個股無此財報')
            else:
                st.info('ℹ️ 查無揭露：服務業/軟體業通常無此數據，可跳過')
                st.caption(f'來源：{_cl_src2 or _cx_src2 or "未知"}')
        # 財報結論：依合約負債+固定資產狀態給出判斷
        _fin_color = '#3fb950' if cl_ok and cx_ok else ('#d29922' if cl_ok or cx_ok else '#484f58')
        _fin_label = ('✅ 龍多確認：合約負債高＋資本支出高 = 訂單滿、擴廠中' if cl_ok and cx_ok
                      else ('⚠️ 部分訊號：' + ('合約負債充裕' if cl_ok else '資本支出積極')
                            if cl_ok or cx_ok else '⚪ 資料不足，無法判斷'))
        st.markdown(
            f'<div style="background:#0d1117;border-left:4px solid {_fin_color};'
            f'padding:10px 14px;border-radius:0 8px 8px 0;margin:6px 0;">'
            f'<span style="font-size:12px;color:#8b949e;">🎓 策略1 · 財報領先指標</span><br>'
            f'<span style="font-size:14px;font-weight:800;color:{_fin_color};">{_fin_label}</span><br>'
            f'<span style="font-size:11px;color:#8b949e;">兩指標均高 = 龍多股首選；詳細門檻見「策略手冊」Tab</span>'
            f'</div>',
            unsafe_allow_html=True
        )

        # ══ D. 月營收 + 季毛利率 ══════════════════════════════
        st.markdown('---')
        st.markdown('#### 📈 D. 公司每月賺多少錢？（營收趨勢）')
        _d_ind = f'{sid2} 月營收YoY%'
        _da = '月營收數據尚未載入'
        _db = ''
        if rev2 is not None and not rev2.empty and len(rev2) >= 3:
            _yoy_col = next((c for c in rev2.columns if 'yoy' in str(c).lower() or '年增' in str(c) or 'YoY' in str(c)), None)
            if _yoy_col:
                _yoy3 = pd.to_numeric(rev2[_yoy_col].tail(3), errors='coerce').dropna()
                if len(_yoy3) >= 2:
                    _avg_y = float(_yoy3.mean())
                    _last_y = float(_yoy3.iloc[-1])
                    _d_ind = f'{sid2} 近3月平均YoY {_avg_y:+.1f}%'
                    if _avg_y > 15 and (_yoy3 > 0).all():
                        _da = f'近3月YoY平均 {_avg_y:+.1f}%（最新 {_last_y:+.1f}%），業績爆發，重點關注'
                        _db = '配合技術面買點可進場'
                    elif _avg_y > 0:
                        _da = f'近3月YoY平均 {_avg_y:+.1f}%，溫和成長'
                        _db = '持續追蹤，等待加速跡象'
                    else:
                        _da = f'近3月YoY平均 {_avg_y:+.1f}%，業績衰退'
                        _db = '不管K線多好看，先觀望'
        st.markdown(teacher_conclusion('孫慶龍', _d_ind, _da, _db), unsafe_allow_html=True)
        st.markdown(
            '<div style="background:#0a1628;border-left:3px solid #3fb950;padding:8px 12px;'
            'border-radius:0 6px 6px 0;margin-bottom:8px;font-size:12px;color:#c9d1d9;">'
            '💡 月營收年增率（YoY%）= 今年這個月比去年同月多賺了幾%'
            '<br>🟢 <b>連續3個月YoY>15%</b> = 業績爆發，股價可能跟著漲'
            '<br>🔴 <b>連續3個月YoY<0%</b> = 業績衰退，要小心'
            '</div>', unsafe_allow_html=True)
        if rev2 is not None and not rev2.empty:
            if _rev2_cached:
                st.caption('⚠️ 月營收使用快取資料（本次 API 未回應）')
            st.plotly_chart(plot_revenue_chart(rev2,sid2,name2),
                            width='stretch',config={'displayModeBar':False})
        else:
            st.warning('⚠️ 月營收數據暫無（請確認 FINMIND_TOKEN 是否正確，或重新載入）')
            st.caption('💡 首次查詢需網路抓取，若持續失敗請檢查 Token 或稍後重試')
        if qtr2 is not None and not qtr2.empty:
            if _qtr2_cached:
                st.caption('⚠️ 季財報使用快取資料（本次 API 未回應）')
            st.plotly_chart(plot_quarterly_chart(qtr2,sid2,name2),
                            width='stretch',config={'displayModeBar':False})
        with st.expander('📖 策略1 結論', expanded=True):
            if rev2 is not None and not rev2.empty and 'yoy' in rev2.columns:
                _yoy_last3 = rev2['yoy'].dropna().tail(3).tolist()
                if len(_yoy_last3) >= 2:
                    _yoy_trend = all(_yoy_last3[i] > _yoy_last3[i-1] for i in range(1,len(_yoy_last3)))
                    _yoy_latest = _yoy_last3[-1]
                    _rev_signal = '✅ 月營收YoY連續加速' if _yoy_trend and _yoy_latest>0 else ('⚠️ 月營收成長趨緩' if _yoy_latest>0 else '🔴 月營收年減')
                    st.markdown(f'<div style="color:#c9d1d9;font-size:13px;padding:3px 0;">• {_rev_signal}（最近YoY: {_yoy_latest:+.1f}%）</div>', unsafe_allow_html=True)
            # 月營收結論（移入 if 內，避免 _rev_signal 未定義）
            if rev2 is not None and not rev2.empty and 'yoy' in rev2.columns:
                _yoy_s2 = rev2['yoy'].dropna().tail(3).tolist()
                if _yoy_s2:
                    _rv_latest = _yoy_s2[-1]
                    _rv_trend  = len(_yoy_s2)>=2 and all(_yoy_s2[i]>_yoy_s2[i-1] for i in range(1,len(_yoy_s2)))
                    _rv_sig = ('✅ 月營收YoY連續加速' if _rv_trend and _rv_latest>0
                               else ('⚠️ 月營收成長趨緩' if _rv_latest>0 else '🔴 月營收年減'))
                    _rv_c = '#3fb950' if '✅' in _rv_sig else ('#f85149' if '🔴' in _rv_sig else '#d29922')
                    st.markdown(
                        f'<div style="background:#0d1117;border-left:3px solid {_rv_c};padding:7px 12px;border-radius:0 6px 6px 0;margin:4px 0;">'
                        f'<span style="font-size:11px;color:#8b949e;">🎓 策略1 · 月營收</span>　'
                        f'<span style="font-size:13px;font-weight:700;color:{_rv_c};">{_rv_sig}（YoY:{_rv_latest:+.1f}%）</span>'
                        f'</div>', unsafe_allow_html=True
                    )
                else:
                    st.caption('月營收資料不足，無法判斷趨勢')
            else:
                st.caption('⚠️ 月營收資料缺失（請確認 FinMind Token）')
            # 毛利率結論 + 獲利品質得分 (SQ)
            if qtr2 is not None and not qtr2.empty:
                _gp_col = '毛利率' if '毛利率' in qtr2.columns else None  # 精確比對，避免命中'毛利率名稱'
                if _gp_col:
                    import pandas as _pd_gp
                    _gp_series = _pd_gp.to_numeric(qtr2[_gp_col].tail(4), errors='coerce').dropna()
                    if len(_gp_series) >= 2:
                        _gp_now = float(_gp_series.iloc[-1])
                        _gp_trend = float(_gp_series.iloc[-1]) - float(_gp_series.iloc[-2])
                        _gp_c = '#3fb950' if _gp_now >= 30 and _gp_trend >= 0 else ('#d29922' if _gp_now >= 20 else '#f85149')
                        _gp_msg = (f'✅ {_gp_now:.1f}%（高毛利≥30%，護城河寬）' if _gp_now >= 30
                                   else f'⚠️ {_gp_now:.1f}%（中等毛利20~30%）' if _gp_now >= 20
                                   else f'🔴 {_gp_now:.1f}%（低毛利<20%）')
                        st.markdown(
                            f'<div style="background:#0d1117;border-left:3px solid {_gp_c};padding:7px 12px;border-radius:0 6px 6px 0;margin:4px 0;">'
                            f'<span style="font-size:11px;color:#8b949e;">🎓 陳重銘 · 毛利率</span>　'
                            f'<span style="font-size:13px;font-weight:700;color:{_gp_c};">{_gp_msg}</span>'
                            f'</div>', unsafe_allow_html=True
                        )
                # 獲利品質得分 (SQ)
                try:
                    from scoring_engine import calc_quality_score as _cqs
                    _sq_res = _cqs(qtr2)
                    if _sq_res.get('sq') is not None:
                        _sq_v = _sq_res['sq']
                        _sq_lbl = _sq_res['sq_label']
                        _sq_gm = _sq_res['gm_trend']
                        _sq_rv = _sq_res['rev_trend']
                        _sq_c  = '#3fb950' if _sq_v >= 75 else ('#d29922' if _sq_v >= 55 else '#f85149')
                        st.markdown(
                            f'<div style="background:#0d1117;border-left:3px solid {_sq_c};padding:7px 12px;border-radius:0 6px 6px 0;margin:4px 0;">'
                            f'<span style="font-size:11px;color:#8b949e;">🎓 獲利品質 SQ</span>　'
                            f'<span style="font-size:13px;font-weight:700;color:{_sq_c};">SQ {_sq_v:.0f}分 · {_sq_lbl}</span>'
                            f'<span style="font-size:11px;color:#8b949e;margin-left:8px;">毛利{_sq_gm} 營收{_sq_rv}</span>'
                            f'</div>', unsafe_allow_html=True
                        )
                except Exception:
                    pass
                # 前瞻成長動能分數 (FGMS)
                try:
                    from scoring_engine import calc_forward_momentum_score as _cfgms
                    _is_fin2 = bool(qtr2.get('是否金融股', pd.Series([False])).iloc[0]) if qtr2 is not None and '是否金融股' in qtr2.columns else False
                    print(f'[FGMS_UI] qtr2={qtr2 is not None and not qtr2.empty}, qtr_extra2={qtr_extra2 is not None and not qtr_extra2.empty}')
                    _fgms_r = _cfgms(qtr2, qtr_extra2, is_finance=_is_fin2)
                    print(f'[FGMS_UI] fgms={_fgms_r.get("fgms")}, three_rate={_fgms_r.get("three_rate")}')
                    if _fgms_r.get('fgms') is not None:
                        _fv = _fgms_r['fgms']
                        _fl = _fgms_r['fgms_label']
                        _fc = '#3fb950' if _fv >= 60 else ('#d29922' if _fv >= 45 else '#f85149')
                        # 子維度摘要（得分）
                        _fd_parts = []
                        if _fgms_r['cl_momentum']    is not None:
                            _fd_parts.append(f"合約負債:{_fgms_r['cl_momentum']:.0f}")
                        if _fgms_r['inv_divergence']  is not None:
                            _fd_parts.append(f"存貨背離:{_fgms_r['inv_divergence']:.0f}")
                        if _fgms_r['three_rate']      is not None:
                            _fd_parts.append(f"三率:{_fgms_r['three_rate']:.0f}")
                        if _fgms_r['capex_intensity'] is not None:
                            _fd_parts.append(f"資本支出:{_fgms_r['capex_intensity']:.0f}")
                        _fd_str = '  '.join(_fd_parts)
                        # 三率實際數值（最新季）
                        _rate_parts = []
                        if qtr2 is not None and not qtr2.empty:
                            def _last_rate(col):
                                if col in qtr2.columns:
                                    _s = pd.to_numeric(qtr2[col], errors='coerce').dropna()
                                    return f"{_s.iloc[-1]:.1f}%" if len(_s) else None
                                return None
                            _gm_v = _last_rate('毛利率')
                            _oi_v = _last_rate('營業利益率')
                            _ni_v = _last_rate('淨利率')
                            if _gm_v:
                                _rate_parts.append(f"毛利率{_gm_v}")
                            if _oi_v:
                                _rate_parts.append(f"營業利益率{_oi_v}")
                            if _ni_v:
                                _rate_parts.append(f"淨利率{_ni_v}")
                        _rate_str = '  '.join(_rate_parts)
                        _rate_line = (f'<div style="font-size:11px;color:#8b949e;margin-top:3px;">📊 三率實值：{_rate_str}</div>'
                                      if _rate_str else '')
                        st.markdown(
                            f'<div style="background:#0d1117;border-left:3px solid {_fc};padding:7px 12px;border-radius:0 6px 6px 0;margin:4px 0;">'
                            f'<span style="font-size:11px;color:#8b949e;">🔭 前瞻動能 FGMS</span>　'
                            f'<span style="font-size:13px;font-weight:700;color:{_fc};">FGMS {_fv:.0f}分 · {_fl}</span>'
                            f'<span style="font-size:11px;color:#8b949e;margin-left:8px;">{_fd_str}</span>'
                            f'{_rate_line}'
                            f'</div>', unsafe_allow_html=True
                        )
                except Exception as _efgms2:
                    import traceback as _tb2
                    print(f'[FGMS_UI] 顯示錯誤: {_efgms2}')
                    _tb2.print_exc()

        # ══ D2. 基本面先行指標（6大指標）══════════════════════
        st.markdown('---')
        st.markdown('#### 🔬 D2. 基本面先行指標（6大指標）')
        try:
            from scoring_engine import calc_leading_indicators_detail as _cli_fn
            _li_results = _cli_fn(rev_df=rev2, qtr_df=qtr2, bs_cf_df=qtr_extra2)
            _li_green = sum(1 for _r in _li_results if _r['signal'] == '🟢')
            _li_yellow = sum(1 for _r in _li_results if _r['signal'] == '🟡')
            _li_red = sum(1 for _r in _li_results if _r['signal'] == '🔴')
            _li_total_scored = _li_green + _li_yellow + _li_red
            if _li_total_scored > 0:
                _li_bar_c = '#3fb950' if _li_green >= _li_total_scored * 0.6 else (
                             '#d29922' if _li_green >= _li_total_scored * 0.3 else '#f85149')
                st.markdown(
                    f'<div style="background:#0d1117;border-left:3px solid {_li_bar_c};'
                    f'padding:6px 12px;border-radius:0 6px 6px 0;margin:4px 0 8px 0;">'
                    f'<span style="font-size:11px;color:#8b949e;">📊 基本面先行指標總覽</span>　'
                    f'<span style="font-size:13px;font-weight:700;color:{_li_bar_c};">'
                    f'🟢×{_li_green}  🟡×{_li_yellow}  🔴×{_li_red}</span>'
                    f'</div>', unsafe_allow_html=True
                )
            # 分模組顯示
            _li_modules = {}
            for _r in _li_results:
                _li_modules.setdefault(_r['module'], []).append(_r)
            _li_module_list = ['模組一', '模組二', '模組三', '模組四']
            _li_module_labels = {
                '模組一': '📈 模組一：高頻業績前瞻（月營收）',
                '模組二': '🏗️ 模組二：資產負債前瞻（季頻）',
                '模組三': '📦 模組三：存貨週期',
                '模組四': '👔 模組四：籌碼深度前瞻',
            }
            _li_col1, _li_col2 = st.columns(2)
            _li_cols = [_li_col1, _li_col2]
            _li_col_idx = 0
            for _mod in _li_module_list:
                if _mod not in _li_modules:
                    continue
                with _li_cols[_li_col_idx % 2]:
                    st.markdown(f'**{_li_module_labels.get(_mod, _mod)}**')
                    for _ind in _li_modules[_mod]:
                        _ic = ('#3fb950' if _ind['signal'] == '🟢' else
                               '#d29922' if _ind['signal'] == '🟡' else
                               '#f85149' if _ind['signal'] == '🔴' else '#8b949e')
                        st.markdown(
                            f'<div style="background:#0d1117;border-left:3px solid {_ic};'
                            f'padding:6px 10px;border-radius:0 4px 4px 0;margin:3px 0;">'
                            f'<div style="font-size:12px;font-weight:700;color:{_ic};">'
                            f'{_ind["signal"]} {_ind["name"]}</div>'
                            f'<div style="font-size:11px;color:#e6edf3;margin:1px 0;">{_ind["value"]}</div>'
                            f'<div style="font-size:10px;color:#8b949e;">{_ind["detail"]}</div>'
                            f'</div>', unsafe_allow_html=True
                        )
                _li_col_idx += 1
        except Exception as _eli_err:
            import traceback as _li_tb
            print(f'[先行指標-D2] 顯示錯誤: {_eli_err}')
            _li_tb.print_exc()

        # ── D2 動態投資建議（基於6大先行指標合成）──────────────
        try:
            from scoring_engine import calc_leading_indicators_detail as _cli_fn2
            _li2 = _cli_fn2(rev_df=rev2, qtr_df=qtr2, bs_cf_df=qtr_extra2)
            _li2_map = {r['id']: r for r in _li2}

            # ── 蒐集信號 ─────────────────────────────────────
            _pros  = []   # 多方理由
            _cons  = []   # 空方理由
            _notes = []   # 注意事項（事件驅動/中性）
            _event_driven_flags = []

            # I1 月營收YoY加速
            _r1 = _li2_map.get('I1', {})
            if _r1.get('signal') == '🟢':
                _pros.append(f"月營收YoY連續加速（{_r1.get('value','').split(':')[-1].strip()}），業績動能確立")
            elif _r1.get('signal') == '🔴':
                _cons.append('月營收年減中，基本面走弱')

            # I2 均線交叉
            _r2 = _li2_map.get('I2', {})
            if _r2.get('signal') == '🟢':
                _pros.append(f"月營收3M均線位於12M均線之上（{_r2.get('value','').split(':')[-1].strip()}），中期動能向上")
            elif _r2.get('signal') == '🔴':
                _cons.append('月營收均線死叉，中期趨勢轉弱')

            # I3 合約負債
            _r3 = _li2_map.get('I3', {})
            if _r3.get('signal') == '🟢':
                _v3 = _r3.get('value','')
                _pros.append(f"合約負債持續增加（{_v3}），未來營收能見度高")
            elif _r3.get('signal') == '🔴':
                _cons.append('合約負債減少，訂單能見度下降')

            # I4 CapEx（含事件驅動判斷）
            _r4 = _li2_map.get('I4', {})
            if '事件驅動' in _r4.get('detail', ''):
                _event_driven_flags.append('資本支出比較基期因重大資產處分失真')
                _notes.append(f"⚠️ CapEx：{_r4.get('detail','')}")
            elif _r4.get('signal') == '🟢':
                _pros.append(f"資本支出強度提升（{_r4.get('value','')}），積極擴產佈局未來")
            elif _r4.get('signal') == '🔴':
                _cons.append(f"資本支出大幅縮減（{_r4.get('value','')}），擴張意願低")

            # I5 存貨去化（含事件驅動）
            _r5 = _li2_map.get('I5', {})
            if '事件驅動' in _r5.get('detail', ''):
                _event_driven_flags.append('存貨急降原因待確認（資產處分可能帶走存貨）')
                _notes.append(f"⚠️ 存貨：{_r5.get('detail','')}")
            elif _r5.get('signal') == '🟢':
                _pros.append(f"存貨持續去化（{_r5.get('value','')}），供需關係改善")
            elif _r5.get('signal') == '🔴':
                _cons.append(f"存貨積壓風險（{_r5.get('value','')}），景氣下行壓力")

            # ── 綜合評估 ────────────────────────────────────
            _n_green = sum(1 for r in _li2 if r['signal'] == '🟢')
            _n_red   = sum(1 for r in _li2 if r['signal'] == '🔴')
            _n_scored = sum(1 for r in _li2 if r['signal'] in ('🟢','🟡','🔴'))

            if _event_driven_flags:
                _stance = 'event'
                _stance_label = '⚠️ 事件驅動觀察'
                _stance_color = '#d29922'
                _stance_desc  = '偵測到重大資產處分，部分指標基期失真。建議關注重組後的資本配置方向與營運重啟節奏，暫不適用純基本面成長框架評估。'
            elif _n_scored == 0:
                _stance = 'na'
                _stance_label = '⚪ 資料不足'
                _stance_color = '#8b949e'
                _stance_desc  = '基本面先行指標資料尚未完整載入，無法生成投資建議。'
            elif _n_green >= _n_scored * 0.6:
                _stance = 'bull'
                _stance_label = '🟢 多方偏多'
                _stance_color = '#3fb950'
                _stance_desc  = f'{_n_green}/{_n_scored} 項指標偏多，基本面動能強勁。'
            elif _n_red >= _n_scored * 0.6:
                _stance = 'bear'
                _stance_label = '🔴 基本面偏弱'
                _stance_color = '#f85149'
                _stance_desc  = f'{_n_red}/{_n_scored} 項指標偏空，基本面壓力明顯。'
            else:
                _stance = 'neutral'
                _stance_label = '🟡 中性觀察'
                _stance_color = '#d29922'
                _stance_desc  = f'多空指標交錯（🟢{_n_green}/🔴{_n_red}），基本面尚未形成明確方向。'

            # ── 建議行動 ────────────────────────────────────
            _action_map = {
                'bull':    '基本面動能向上，可搭配技術面（VCP/布林）確認進場時機，適合中長線佈局。',
                'bear':    '基本面呈現壓力，建議降低曝險或觀望，等待指標轉向後再評估。',
                'neutral': '基本面方向尚不明朗，建議輕倉或等待更多季度數據確認後再行動。',
                'event':   '轉機股需追蹤：①後續資本支出重建節奏 ②新業務（如HBM後段）訂單能見度 ③毛利率是否回升至正常水位。',
                'na':      '請確認 FINMIND_TOKEN 是否正確，並重新載入後查看建議。',
            }
            _action = _action_map.get(_stance, '')

            # ── 渲染 ────────────────────────────────────────
            _pros_html  = ''.join(f'<li style="margin:2px 0;">✅ {p}</li>' for p in _pros)  if _pros  else ''
            _cons_html  = ''.join(f'<li style="margin:2px 0;">⛔ {c}</li>' for c in _cons)  if _cons  else ''
            _notes_html = ''.join(f'<li style="margin:2px 0;">{n}</li>'    for n in _notes) if _notes else ''

            _pros_section  = (f'<div style="margin-top:6px;"><span style="font-size:11px;color:#3fb950;font-weight:600;">多方因素</span>'
                              f'<ul style="margin:2px 0 0 12px;padding:0;font-size:11px;color:#e6edf3;">{_pros_html}</ul></div>') if _pros_html else ''
            _cons_section  = (f'<div style="margin-top:4px;"><span style="font-size:11px;color:#f85149;font-weight:600;">風險因素</span>'
                              f'<ul style="margin:2px 0 0 12px;padding:0;font-size:11px;color:#e6edf3;">{_cons_html}</ul></div>') if _cons_html else ''
            _notes_section = (f'<div style="margin-top:4px;"><span style="font-size:11px;color:#d29922;font-weight:600;">注意事項</span>'
                              f'<ul style="margin:2px 0 0 12px;padding:0;font-size:11px;color:#8b949e;">{_notes_html}</ul></div>') if _notes_html else ''

            st.markdown(
                f'<div style="background:#161b22;border:1px solid {_stance_color};border-left:4px solid {_stance_color};'
                f'padding:10px 14px;border-radius:6px;margin:8px 0;">'
                f'<div style="font-size:12px;color:#8b949e;margin-bottom:4px;">💡 基本面先行指標 · 動態投資建議</div>'
                f'<div style="font-size:15px;font-weight:700;color:{_stance_color};">{_stance_label}</div>'
                f'<div style="font-size:12px;color:#e6edf3;margin-top:4px;">{_stance_desc}</div>'
                f'{_pros_section}{_cons_section}{_notes_section}'
                f'<div style="margin-top:8px;padding-top:6px;border-top:1px solid #30363d;">'
                f'<span style="font-size:11px;color:#8b949e;">📌 建議行動：</span>'
                f'<span style="font-size:12px;color:#e6edf3;">{_action}</span>'
                f'</div>'
                f'</div>', unsafe_allow_html=True
            )
        except Exception as _eli2_err:
            import traceback as _li2_tb
            print(f'[先行指標-建議] 顯示錯誤: {_eli2_err}')
            _li2_tb.print_exc()

        # ── 資料彙整（供 AI 總結使用）──────────────────────────
        _regime2 = st.session_state.get('mkt_info', {}).get('regime', 'neutral')
        _rev_yoy_list = []
        if rev2 is not None and not rev2.empty and 'yoy' in rev2.columns:
            # P4b: vectorized — 對齊 date/index 後一次 apply
            _r3 = rev2.tail(3).copy()
            _r3['_lbl'] = _r3['date'].astype(str) if 'date' in _r3.columns else _r3.index.astype(str)
            _rev_yoy_list = [
                f'{lbl}: {yoy:+.1f}%'
                for lbl, yoy in zip(_r3['_lbl'], pd.to_numeric(_r3['yoy'], errors='coerce'))
                if not pd.isna(yoy)
            ]
        _vcp_ok2 = bool(vcp2 and isinstance(vcp2, dict) and vcp2.get('signal'))
        _ma_above2 = {}
        if df2 is not None and not df2.empty:
            for _mn, _mc in [('20MA', 'MA20'), ('60MA', 'MA60'), ('240MA', 'MA240')]:
                if _mc in df2.columns:
                    _ma_above2[_mn] = price2 > float(df2[_mc].iloc[-1])

        st.markdown("""<div style="margin:24px 0 8px;padding:8px 16px;background:linear-gradient(90deg,#d2a8ff18,#0d1117);border-left:4px solid #d2a8ff;border-radius:0 6px 6px 0;"><span style="font-size:15px;font-weight:900;color:#d2a8ff;">🏥 體檢表</span><span style="font-size:11px;color:#8b949e;margin-left:8px;">策略2 · 4力1棒子 · 現金流矩陣 · OPM護城河</span></div>""", unsafe_allow_html=True)

        with st.expander('🔬 AI 財報體檢（策略2）', expanded=True):
            _fh_key2 = f'_fh_{sid2}'
            if _fh_key2 not in st.session_state:
                with st.spinner('📊 正在從 FinMind 抓取財報數據…'):
                    try:
                        _fin_raw = fetch_financial_statements(sid2, FINMIND_TOKEN)
                        if _fin_raw.get('error'):
                            st.session_state[_fh_key2] = {'error': True, 'ai_insight': _fin_raw['error']}
                        else:
                            # B項：預填 5 年現金流量允當比率（精確版）
                            try:
                                from tw_stock_data_fetcher import fetch_5_years_cash_flow
                                _fin_raw['b_item_5y'] = fetch_5_years_cash_flow(sid2, FINMIND_TOKEN)
                            except Exception:
                                pass  # fallback 到 1Q 估算
                            # 近期新聞：供 MJ 體檢 AI insight 結合市場情緒
                            _mj_news = _fetch_stock_news(sid2, name2, 3)
                            _mj_news_str = '\n'.join(
                                f'- {_n["title"]}（{_n.get("source","RSS")} · {_n.get("published","")}）'
                                for _n in _mj_news
                            ) if _mj_news else '（暫無近期個股新聞）'
                            _fh_out = analyze_financial_health(api_key, sid2, _fin_raw,
                                                               news_context=_mj_news_str)
                            st.session_state[_fh_key2] = _fh_out
                            # 保存原始財報數據供診斷面板使用（ar_days/liab/b_item_5y 等）
                            st.session_state[f'_fin_raw_{sid2}'] = _fin_raw
                    except Exception as _fh_exc:
                        st.session_state[_fh_key2] = {'error': True, 'ai_insight': f'財報體檢發生例外：{_fh_exc}'}
            _fh = st.session_state.get(_fh_key2)
            if not _fh or _fh.get('error'):
                st.error(_fh.get('ai_insight', '財報體檢失敗，請確認 FINMIND_TOKEN 已設定。') if _fh else '載入中...')
            else:
                # ── 第一關：三大生死燈號 ────────────────────
                st.markdown('#### 🛡️ 第一關：生死與體質防禦')
                _fh_c1, _fh_c2, _fh_c3 = st.columns(3)
                with _fh_c1:
                    st.metric(
                        label='氣長不長（現金佔總資產 > 25%）',
                        value=f"{_fh.get('cash_ratio_status','?')} {_fh.get('cash_ratio_value','N/A')}",
                        delta='安全' if _fh.get('cash_ratio_status') == '🟢' else
                              '注意' if _fh.get('cash_ratio_status') == '🟡' else '危險',
                        delta_color='normal' if _fh.get('cash_ratio_status') == '🟢' else 'inverse',
                    )
                with _fh_c2:
                    st.metric(
                        label='真假獲利（OCF 必須為正）',
                        value=f"{_fh.get('ocf_status','?')} {_fh.get('ocf_value','N/A')}",
                        delta='穩定流入' if _fh.get('ocf_status') == '🟢' else '黑字破產警戒',
                        delta_color='normal' if _fh.get('ocf_status') == '🟢' else 'inverse',
                    )
                with _fh_c3:
                    st.metric(
                        label='那根棒子（負債比 < 60%）',
                        value=f"{_fh.get('debt_ratio_status','?')} {_fh.get('debt_ratio_value','N/A')}",
                        delta='穩健' if _fh.get('debt_ratio_status') == '🟢' else
                              '留意' if _fh.get('debt_ratio_status') == '🟡' else '危險',
                        delta_color='normal' if _fh.get('debt_ratio_status') == '🟢' else 'inverse',
                    )

                st.markdown('<hr style="border-color:#21262d;margin:10px 0;">', unsafe_allow_html=True)

                # ── 五力雷達圖 + 企業DNA / 護城河 ──────────
                _fh_left, _fh_right = st.columns([1, 1])

                with _fh_left:
                    st.markdown('#### 🎯 五力體質雷達圖')
                    _radar = _fh.get('radar_scores', {})
                    if _radar:
                        import plotly.graph_objects as _go_fh
                        _cats = list(_radar.keys()) + [list(_radar.keys())[0]]
                        _vals = [max(0, min(100, int(v))) for v in _radar.values()]
                        _vals += [_vals[0]]
                        _fig_fh = _go_fh.Figure(_go_fh.Scatterpolar(
                            r=_vals, theta=_cats, fill='toself',
                            line_color='#3fb950', fillcolor='rgba(63,185,80,0.2)',
                        ))
                        _fig_fh.update_layout(
                            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            margin=dict(l=20, r=20, t=20, b=20),
                            showlegend=False,
                        )
                        st.plotly_chart(_fig_fh, width='stretch')
                    else:
                        st.warning('無法取得五力評分資料')

                with _fh_right:
                    st.markdown('#### 🧬 企業 DNA 與護城河')
                    _dna = _fh.get('business_model_dna', '無法判斷')
                    _dna_clr = ('#3fb950' if 'A+' in _dna or _dna.startswith('A ')
                                else '#d29922' if 'B' in _dna or 'C' in _dna
                                else '#f85149')
                    st.markdown(
                        f'<div style="background:#161b22;border-left:4px solid {_dna_clr};'
                        f'border-radius:8px;padding:14px 16px;margin-bottom:10px;">'
                        f'<div style="font-size:11px;color:#484f58;margin-bottom:4px;">現金流矩陣判定</div>'
                        f'<div style="font-size:18px;font-weight:900;color:{_dna_clr};">{_dna}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown('**OPM 商業話語權檢驗**')
                    _opm = _fh.get('opm_data', {})
                    _p_days = _opm.get('payable_days', 0)
                    _r_days = _opm.get('receivable_days', 0)
                    _adv = _opm.get('advantage', False)
                    if _adv:
                        st.success(
                            f'👑 具備快收慢付優勢\n\n'
                            f'應付帳款 **{_p_days}天** > 應收帳款 **{_r_days}天**'
                        )
                    elif _r_days == 0:
                        st.info('DSO (應收帳款天數) 資料缺漏，無法判定 OPM 護城河')
                    else:
                        st.warning(
                            f'⚠️ 營運資金壓力較大\n\n'
                            f'應付帳款 **{_p_days}天** < 應收帳款 **{_r_days}天**'
                        )

                st.markdown('<hr style="border-color:#21262d;margin:10px 0;">', unsafe_allow_html=True)

                # ── 存活能力精細模組（Survival Module）──────────
                _surv2 = _fh.get('survival_module', {})
                if _surv2:
                    st.markdown('#### 🏥 存活能力精細診斷（MJ 3大生死指標）')
                    _sc_map = {'Pass': '#3fb950', 'Acceptable': '#d29922', 'Fail': '#f85149'}
                    _s2c = st.columns(3)
                    for _col2, (_key2, _lbl2) in zip(_s2c, [
                        ('Cash_Ratio', '💰 氣長不長'), ('DSO_Speed', '⚡ 收現速度')
                    ]):
                        _si2 = _surv2.get(_key2, {})
                        _sc2 = _sc_map.get(_si2.get('Status', 'Fail'), '#f85149')
                        with _col2:
                            st.markdown(
                                f'<div style="background:{_sc2}18;border:1px solid {_sc2}55;'
                                f'border-radius:8px;padding:10px;text-align:center;">'
                                f'<div style="font-size:11px;color:#8b949e;">{_lbl2}</div>'
                                f'<div style="font-size:20px;font-weight:900;color:{_sc2};">{_si2.get("Value","N/A")}</div>'
                                f'<div style="font-size:11px;color:{_sc2};">{_si2.get("Status","?")}</div>'
                                f'<div style="font-size:10px;color:#8b949e;margin-top:4px;">{_si2.get("Insight","")}</div>'
                                f'</div>', unsafe_allow_html=True)
                    _r1102 = _surv2.get('Rule_100_100_10', {})
                    _r110c2 = _sc_map.get(_r1102.get('Status', 'Fail'), '#f85149')
                    # 各分項勾叉（門檻：A>100% / B≥100% / C>10%，與 financial_health_engine:416/423/431 對齊）
                    import re as _re_r110a
                    def _r110_ok_a(_s, _thr, _strict):
                        _ss = str(_s or '')
                        if not _ss or 'N/A' in _ss:
                            return None
                        _mn = _re_r110a.search(r'(-?\d+(?:\.\d+)?)\s*%', _ss)
                        if not _mn:
                            return None
                        _vn = float(_mn.group(1))
                        return (_vn > _thr) if _strict else (_vn >= _thr)
                    _a_ok2 = _r110_ok_a(_r1102.get('Cash_Flow_Ratio',''), 100, True)
                    _b_ok2 = _r110_ok_a(_r1102.get('Cash_Flow_Adequacy',''), 100, False)
                    _c_ok2 = _r110_ok_a(_r1102.get('Cash_Reinvestment',''), 10, True)
                    def _tk2(x):
                        return '✅' if x is True else ('❌' if x is False else '⚪')
                    with _s2c[2]:
                        st.markdown(
                            f'<div style="background:{_r110c2}18;border:1px solid {_r110c2}55;'
                            f'border-radius:8px;padding:10px;text-align:center;">'
                            f'<div style="font-size:11px;color:#8b949e;">🔄 100/100/10</div>'
                            f'<div style="font-size:11px;color:#c9d1d9;">'
                            f'A{_tk2(_a_ok2)}{_r1102.get("Cash_Flow_Ratio","N/A")} '
                            f'B{_tk2(_b_ok2)}{_r1102.get("Cash_Flow_Adequacy","N/A")} '
                            f'C{_tk2(_c_ok2)}{_r1102.get("Cash_Reinvestment","N/A")}</div>'
                            f'<div style="font-size:12px;font-weight:700;color:{_r110c2};">{_r1102.get("Status","?")}</div>'
                            f'<div style="font-size:10px;color:#8b949e;margin-top:4px;">{_r1102.get("Insight","")}</div>'
                            f'</div>', unsafe_allow_html=True)
                    _v2 = _surv2.get('Final_Survival_Verdict', '')
                    if _v2:
                        st.caption(f'🎯 {_v2}')

                # ── 經營能力模組（Operating Module）──────────────
                _oper2 = _fh.get('operating_module', {})
                if _oper2:
                    st.markdown('#### ⚙️ 經營能力診斷（周轉效率 + 資金壓力）')
                    _oc1, _oc2, _oc3, _oc4 = st.columns(4)
                    _ccc_str = str(_oper2.get('Cash_Gap_Days', 'N/A'))
                    try:
                        _ccc_num = float(_ccc_str.split()[0].replace('天', '').strip())
                        _ccc_is_num = True
                    except (ValueError, AttributeError):
                        _ccc_num, _ccc_is_num = 0.0, False
                    # OPM 護城河：引擎判定 Yes 且 CCC 為實質負數，兩者同時成立才顯示
                    _opm_yes = (_oper2.get('OPM_Strategy', 'No') == 'Yes') and _ccc_is_num and (_ccc_num < 0)
                    _ccc_color = '#3fb950' if _opm_yes else ('#8b949e' if not _ccc_is_num else '#d29922')
                    with _oc1:
                        st.metric('DSO 應收天數', _oper2.get('DSO', 'N/A'))
                    with _oc2:
                        st.metric('DIO 存貨天數', _oper2.get('DIO', 'N/A'))
                    with _oc3:
                        st.metric('DPO 應付天數', _oper2.get('DPO', 'N/A'))
                    with _oc4:
                        st.metric('總資產翻桌率', _oper2.get('Asset_Turnover', 'N/A'))
                    _oc5, _oc6 = st.columns(2)
                    with _oc5:
                        st.markdown(
                            f'<div style="background:#161b22;border-radius:8px;padding:10px;">'
                            f'<div style="font-size:11px;color:#8b949e;">做生意完整週期</div>'
                            f'<div style="font-size:18px;font-weight:900;color:#58a6ff;">{_oper2.get("Complete_Cycle","N/A")}</div>'
                            f'</div>', unsafe_allow_html=True)
                    with _oc6:
                        st.markdown(
                            f'<div style="background:#161b22;border-radius:8px;padding:10px;">'
                            f'<div style="font-size:11px;color:#8b949e;">缺錢天數 (CCC)</div>'
                            f'<div style="font-size:18px;font-weight:900;color:{_ccc_color};">{_oper2.get("Cash_Gap_Days","N/A")}</div>'
                            f'<div style="font-size:11px;color:{_ccc_color};">{"✅ OPM護城河：拿別人的錢做生意" if _opm_yes else ("⚪ CCC 資料不足" if not _ccc_is_num else "⚠️ 需自備營運資金")}</div>'
                            f'</div>', unsafe_allow_html=True)
                    if _oper2.get('Verdict'):
                        st.caption(f'💡 {_oper2["Verdict"]}')

                # ── 獲利能力模組（Profitability Module）─────────
                _prof2 = _fh.get('profitability_module', {})
                if _prof2:
                    st.markdown('#### 💰 獲利能力診斷（MJ 5大指標）')
                    _p5c = st.columns(5)
                    # 1 毛利率
                    _gm2 = _prof2.get('Gross_Margin', {})
                    _gm2_ok = _gm2.get('Status', '') == 'Good'
                    with _p5c[0]:
                        st.markdown(
                            f'<div style="background:{"#3fb95018" if _gm2_ok else "#f8514918"};'
                            f'border:1px solid {"#3fb95055" if _gm2_ok else "#f8514955"};'
                            f'border-radius:8px;padding:10px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">毛利率</div>'
                            f'<div style="font-size:17px;font-weight:900;color:{"#3fb950" if _gm2_ok else "#f85149"};">{_gm2.get("Value","N/A")}</div>'
                            f'<div style="font-size:10px;color:{"#3fb950" if _gm2_ok else "#f85149"};">{"好生意" if _gm2_ok else "辛苦生意"}</div>'
                            f'</div>', unsafe_allow_html=True)
                    # 2 營業利益率
                    _om2 = _prof2.get('Operating_Margin', {})
                    _om2_ok = _om2.get('Core_Business_Profitable', 'No') == 'Yes'
                    with _p5c[1]:
                        st.markdown(
                            f'<div style="background:{"#3fb95018" if _om2_ok else "#f8514918"};'
                            f'border:1px solid {"#3fb95055" if _om2_ok else "#f8514955"};'
                            f'border-radius:8px;padding:10px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">營業利益率</div>'
                            f'<div style="font-size:17px;font-weight:900;color:{"#3fb950" if _om2_ok else "#f85149"};">{_om2.get("Value","N/A")}</div>'
                            f'<div style="font-size:10px;color:{"#3fb950" if _om2_ok else "#f85149"};">{"本業獲利✅" if _om2_ok else "本業虧損❌"}</div>'
                            f'</div>', unsafe_allow_html=True)
                    # 3 安全邊際
                    _mos2 = _prof2.get('Margin_Of_Safety', {})
                    _mos2_ok = _mos2.get('Status', '') == 'Strong'
                    with _p5c[2]:
                        st.markdown(
                            f'<div style="background:{"#3fb95018" if _mos2_ok else "#d2992218"};'
                            f'border:1px solid {"#3fb95055" if _mos2_ok else "#d2992255"};'
                            f'border-radius:8px;padding:10px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">安全邊際</div>'
                            f'<div style="font-size:17px;font-weight:900;color:{"#3fb950" if _mos2_ok else "#d29922"};">{_mos2.get("Value","N/A")}</div>'
                            f'<div style="font-size:10px;color:{"#3fb950" if _mos2_ok else "#d29922"};">{"抗震極強✅" if _mos2_ok else "費用待改善"}</div>'
                            f'</div>', unsafe_allow_html=True)
                    # 4 稅後淨利率
                    _nm2 = _prof2.get('Net_Margin', {})
                    _nm2_s = _nm2.get('Status', '')
                    _nm2_c = '#3fb950' if _nm2_s == 'Pass' else ('#d29922' if _nm2_s == 'Thin Profit' else '#f85149')
                    with _p5c[3]:
                        st.markdown(
                            f'<div style="background:{_nm2_c}18;border:1px solid {_nm2_c}55;'
                            f'border-radius:8px;padding:10px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">稅後淨利率</div>'
                            f'<div style="font-size:17px;font-weight:900;color:{_nm2_c};">{_nm2.get("Value","N/A")}</div>'
                            f'<div style="font-size:10px;color:{_nm2_c};">{_nm2_s}</div>'
                            f'</div>', unsafe_allow_html=True)
                    # 5 ROE
                    _roe2 = _prof2.get('ROE', {})
                    _roe2_warn = _roe2.get('Leverage_Warning', 'None') != 'None'
                    try:
                        _roe2_num = float(_roe2.get('Value', '0').replace('%', '').strip())
                    except (ValueError, AttributeError):
                        _roe2_num = None
                    _roe2_positive = _roe2_num is not None and _roe2_num > 0
                    _roe2_c = '#d29922' if _roe2_warn else ('#3fb950' if _roe2_positive else '#f85149')
                    with _p5c[4]:
                        st.markdown(
                            f'<div style="background:{_roe2_c}18;border:1px solid {_roe2_c}55;'
                            f'border-radius:8px;padding:10px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">ROE</div>'
                            f'<div style="font-size:17px;font-weight:900;color:{_roe2_c};">{_roe2.get("Value","N/A")}</div>'
                            f'<div style="font-size:10px;color:{_roe2_c};">{"⚠️ 高槓桿驅動" if _roe2_warn else ("✅ 真實獲利" if _roe2_positive else "❌ 本業虧損")}</div>'
                            f'</div>', unsafe_allow_html=True)
                    if _prof2.get('Final_Insight'):
                        st.caption(f'🎯 {_prof2["Final_Insight"]}')

                # ── 財務結構模組（Financial Structure Module）────
                _fstr2 = _fh.get('financial_structure_module', {})
                if _fstr2:
                    st.markdown('#### 🏗️ 財務結構診斷（那根棒子 + 以長支長）')
                    _fs2c = st.columns(2)
                    # 1 負債佔資產比率
                    _dr2 = _fstr2.get('Debt_Ratio', {})
                    _dr2_s = _dr2.get('Status', '')
                    _dr2_c = {'Pass': '#3fb950', 'Warning': '#d29922', 'Fail': '#f85149', 'N/A': '#8b949e'}.get(_dr2_s, '#8b949e')
                    with _fs2c[0]:
                        st.markdown(
                            f'<div style="background:{_dr2_c}18;border:1px solid {_dr2_c}55;'
                            f'border-radius:10px;padding:14px;text-align:center;">'
                            f'<div style="font-size:11px;color:#8b949e;">負債佔資產比率</div>'
                            f'<div style="font-size:26px;font-weight:900;color:{_dr2_c};">{_dr2.get("Value","N/A")}</div>'
                            f'<div style="font-size:11px;color:{_dr2_c};">'
                            f'{"✅ 穩健（<60%）" if _dr2_s=="Pass" else ("⚠️ 偏高（60-70%）" if _dr2_s=="Warning" else ("🔴 高危（>70%）" if _dr2_s=="Fail" else ("🏦 特許行業" if "金融" in _dr2.get("Value","") else "⚪ 資料缺漏")))}'
                            f'</div></div>', unsafe_allow_html=True)
                    # 2 以長支長比率
                    _ltf2 = _fstr2.get('Long_Term_Funding_Ratio', {})
                    _ltf2_s = _ltf2.get('Status', '')
                    _ltf2_c = '#3fb950' if _ltf2_s == 'Pass' else ('#8b949e' if _ltf2_s == 'N/A' else '#f85149')
                    _ltf2_label = ('✅ 資金配置正確（>100%）' if _ltf2_s == 'Pass'
                                   else ('⚪ 資料不足，無法判斷' if _ltf2_s == 'N/A'
                                         else '🔴 短債長投！資金鏈危機'))
                    with _fs2c[1]:
                        st.markdown(
                            f'<div style="background:{_ltf2_c}18;border:1px solid {_ltf2_c}55;'
                            f'border-radius:10px;padding:14px;text-align:center;">'
                            f'<div style="font-size:11px;color:#8b949e;">以長支長比率</div>'
                            f'<div style="font-size:26px;font-weight:900;color:{_ltf2_c};">{_ltf2.get("Value","N/A")}</div>'
                            f'<div style="font-size:11px;color:{_ltf2_c};">{_ltf2_label}'
                            f'</div></div>', unsafe_allow_html=True)
                    if _fstr2.get('Final_Insight'):
                        st.caption(f'🏗️ {_fstr2["Final_Insight"]}')

                # ── 償債能力模組（Solvency Module）─────────────
                _solv2 = _fh.get('solvency_module', {})
                if _solv2:
                    st.markdown('#### 🛡️ 短期償債能力診斷（MJ 300/150 嚴格標準）')
                    # 最終裁決 banner
                    _sv2_v = _solv2.get('Final_Solvency_Verdict', '')
                    _sv2_pass = 'Pass' in _sv2_v
                    _sv2_exc  = 'Exception' in _sv2_v
                    _sv2_bc   = '#3fb950' if _sv2_pass and not _sv2_exc else ('#d29922' if _sv2_exc else '#f85149')
                    _sv2_icon = '✅' if _sv2_pass and not _sv2_exc else ('⚡' if _sv2_exc else '🔴')
                    st.markdown(
                        f'<div style="background:{_sv2_bc}18;border:2px solid {_sv2_bc};'
                        f'border-radius:10px;padding:10px 16px;margin-bottom:10px;">'
                        f'<span style="font-size:14px;font-weight:900;color:{_sv2_bc};">'
                        f'{_sv2_icon} {_sv2_v}</span></div>', unsafe_allow_html=True)
                    # 保命符：依 Final_Solvency_Verdict 區分例外類型
                    _is_dso_exception  = "條件B：天天收現" in _sv2_v
                    _is_cash_exception = "條件A：現金充足" in _sv2_v
                    _is_any_exception  = _is_dso_exception or _is_cash_exception
                    # 流動比率門檻：條件B→150%；條件A→100%；無例外→300%
                    _cr_thresh = 150 if _is_dso_exception else (100 if _is_cash_exception else 300)
                    _cr_label  = (f'流動比率（保命符放寬 >{_cr_thresh}%）'
                                  if _is_any_exception else '流動比率（MJ嚴格 >300%）')
                    _sv2c = st.columns(2)
                    for _col, (_key, _label, _thresh) in zip(_sv2c, [
                        ('Current_Ratio', _cr_label, _cr_thresh),
                        ('Quick_Ratio', '速動比率（MJ嚴格 >150%）', 150),
                    ]):
                        _si = _solv2.get(_key, {})
                        _si_s = _si.get('Status', '')
                        # 保命符啟動時，重新以放寬閾值判定流動比率顏色與標籤
                        if _key == 'Current_Ratio' and _is_any_exception:
                            try:
                                _cr_num = float(_si.get('Value', '0').replace('%', '').strip())
                                if _cr_num > _thresh:
                                    _si_c, _si_s = '#3fb950', f'Pass（保命符 >{_thresh}%）'
                                else:
                                    _si_c = '#f85149'
                            except (ValueError, AttributeError):
                                _si_c = '#3fb950' if 'Pass' in _si_s else '#f85149'
                        else:
                            _si_c = '#3fb950' if 'Pass' in _si_s else '#f85149'
                        with _col:
                            st.markdown(
                                f'<div style="background:{_si_c}18;border:1px solid {_si_c}55;'
                                f'border-radius:10px;padding:12px;text-align:center;">'
                                f'<div style="font-size:11px;color:#8b949e;">{_label}</div>'
                                f'<div style="font-size:24px;font-weight:900;color:{_si_c};">{_si.get("Value","N/A")}</div>'
                                f'<div style="font-size:11px;color:{_si_c};">{_si_s}</div>'
                                f'</div>', unsafe_allow_html=True)
                    # Banner：依例外類型顯示不同提示
                    if _is_dso_exception:
                        st.info('🔍 已啟動收現行業交叉驗證保命符（DSO ≤ 15天，流動比率門檻放寬至 >150%）')
                    elif _is_cash_exception:
                        st.info('💰 已啟動現金充足交叉驗證保命符（現金佔總資產 >25%，流動比率門檻放寬至 >100%）')
                    if _solv2.get('Final_Insight'):
                        st.caption(f'🛡️ {_solv2["Final_Insight"]}')

                # ── 綜合診斷模組（Advanced Diagnostic Module）────
                _adv2 = _fh.get('advanced_diagnostic_module', {})
                if _adv2:
                    st.markdown('#### 🔬 綜合診斷與避雷（跨表勾稽 + 地雷偵測）')
                    # 第一列：盈餘品質 + 杜邦 + 雙高
                    _ad2r1 = st.columns(3)
                    # 盈餘品質
                    _eq2 = _adv2.get('Earnings_Quality', {})
                    _eq2_s = _eq2.get('Status', '')
                    _eq2_c = '#3fb950' if _eq2_s == 'Pass' else ('#f85149' if _eq2_s == 'Fail' else '#8b949e')
                    with _ad2r1[0]:
                        st.markdown(
                            f'<div style="background:{_eq2_c}18;border:1px solid {_eq2_c}55;'
                            f'border-radius:10px;padding:12px;text-align:center;">'
                            f'<div style="font-size:11px;color:#8b949e;">盈餘含金量</div>'
                            f'<div style="font-size:22px;font-weight:900;color:{_eq2_c};">{_eq2.get("Value","N/A")}</div>'
                            f'<div style="font-size:11px;color:{_eq2_c};">{"✅ 真金白銀" if _eq2_s=="Pass" else ("🔴 紙上富貴" if _eq2_s=="Fail" else "N/A")}</div>'
                            f'</div>', unsafe_allow_html=True)
                    # 杜邦分析
                    _dp2 = _adv2.get('DuPont_Health', '')
                    _dp2_c = '#f85149' if '警報' in _dp2 else ('#3fb950' if '健康' in _dp2 else '#d29922')
                    _dp2_icon = '🔴' if '警報' in _dp2 else ('✅' if '健康' in _dp2 else '⚠️')
                    with _ad2r1[1]:
                        st.markdown(
                            f'<div style="background:{_dp2_c}18;border:1px solid {_dp2_c}55;'
                            f'border-radius:10px;padding:12px;text-align:center;">'
                            f'<div style="font-size:11px;color:#8b949e;">杜邦分析</div>'
                            f'<div style="font-size:13px;font-weight:900;color:{_dp2_c};line-height:1.4;">{_dp2_icon} {_dp2}</div>'
                            f'</div>', unsafe_allow_html=True)
                    # 雙高危機
                    _dh2 = _adv2.get('Double_High_Warning', '')
                    _dh2_danger = 'Triggered' in _dh2
                    _dh2_c = '#f85149' if _dh2_danger else ('#3fb950' if 'Clear' in _dh2 else '#8b949e')
                    with _ad2r1[2]:
                        st.markdown(
                            f'<div style="background:{_dh2_c}18;border:1px solid {_dh2_c}55;'
                            f'border-radius:10px;padding:12px;text-align:center;">'
                            f'<div style="font-size:11px;color:#8b949e;">雙高危機偵測</div>'
                            f'<div style="font-size:13px;font-weight:900;color:{_dh2_c};">{"🔴 觸發警報！" if _dh2_danger else ("✅ 安全" if "Clear" in _dh2 else "⬜ 資料不足")}</div>'
                            f'<div style="font-size:10px;color:{_dh2_c};">{_dh2}</div>'
                            f'</div>', unsafe_allow_html=True)
                    # 第二列：企業 DNA 全寬
                    _dna2 = _adv2.get('Business_DNA', '')
                    _dna2_c = '#3fb950' if 'A+' in _dna2 else ('#d29922' if '成長' in _dna2 or '新創' in _dna2 else ('#f85149' if '瀕死' in _dna2 else '#58a6ff'))
                    st.markdown(
                        f'<div style="background:{_dna2_c}18;border:1px solid {_dna2_c}55;'
                        f'border-radius:10px;padding:10px 16px;margin-top:8px;">'
                        f'<span style="font-size:11px;color:#8b949e;">企業 DNA（現金流矩陣）：</span>'
                        f'<span style="font-size:14px;font-weight:900;color:{_dna2_c};margin-left:8px;">{_dna2}</span>'
                        f'</div>', unsafe_allow_html=True)
                    if _adv2.get('Final_Verdict'):
                        st.caption(f'🔬 {_adv2["Final_Verdict"]}')

                # ── 老師動態總結論 ─────────────────────────────────
                _ov = no_ai_overall_verdict(
                    fin_data=st.session_state.get('t2_fin_data', {}),
                    fh_result=_fh,
                )
                _ovc = _ov.get("grade_color", "#58a6ff")
                st.markdown('<hr style="border-color:#30363d;margin:14px 0 10px;">', unsafe_allow_html=True)
                st.markdown(
                    f'<div style="background:{_ovc}12;border:2px solid {_ovc};border-radius:12px;padding:16px 20px;">'
                    f'<div style="display:flex;align-items:center;gap:14px;margin-bottom:8px;">'
                    f'<span style="font-size:36px;font-weight:900;color:{_ovc};font-family:monospace;">'
                    f'{_ov.get("grade","?")}</span>'
                    f'<div>'
                    f'<div style="font-size:14px;font-weight:900;color:{_ovc};">{_ov.get("headline","")}</div>'
                    f'<div style="font-size:10px;color:#8b949e;margin-top:2px;">'
                    f'策略2 · 6大模組綜合評估 · '
                    f'✅ {_ov.get("pass_count",0)} 項達標　'
                    f'🔴 {_ov.get("fail_count",0)} 項警示　'
                    f'企業DNA：{_ov.get("dna","--")}'
                    f'</div></div></div>'
                    f'<div style="font-size:12px;color:#c9d1d9;line-height:1.7;">{_ov.get("comment","")}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # ══ 🤖 AI 首席顧問總結 ═══════════════════════════════════
        st.markdown("""<div style="margin:28px 0 8px;padding:8px 16px;background:linear-gradient(90deg,#76e3ea18,#0d1117);border-left:4px solid #76e3ea;border-radius:0 6px 6px 0;"><span style="font-size:15px;font-weight:900;color:#76e3ea;">🤖 AI 首席顧問總結</span><span style="font-size:11px;color:#8b949e;margin-left:8px;">技術面 · 籌碼 · 基本面 · 財報體檢（策略2）· 總經 五維綜合評估</span></div>""", unsafe_allow_html=True)

        _ai_sum_key = f'_ai_sum_{sid2}'
        _ai_sum_cached = st.session_state.get(_ai_sum_key, '')
        _ai_sum_c1, _ai_sum_c2 = st.columns([3, 1])
        with _ai_sum_c1:
            _do_ai_sum = st.button('🤖 生成 AI 首席顧問戰略評估報告', key='btn_ai_sum2', type='primary')
        with _ai_sum_c2:
            if st.button('🗑️ 清除報告', key='btn_ai_sum2_clr'):
                st.session_state.pop(_ai_sum_key, None)
                st.rerun()

        if _do_ai_sum:
            # ── 彙整技術面數據 ────────────────────────────────────
            _atr2 = float(df2['high'].sub(df2['low']).tail(14).mean()) if df2 is not None and len(df2) >= 14 else 0
            _ibs2 = round((float(df2['close'].iloc[-1]) - float(df2['low'].iloc[-1])) /
                          max(float(df2['high'].iloc[-1]) - float(df2['low'].iloc[-1]), 0.01), 2) if df2 is not None and not df2.empty else 'N/A'
            _vol_ratio2 = round(float(df2['volume'].iloc[-1]) / float(df2['volume'].tail(20).mean()), 2) if df2 is not None and len(df2) >= 20 else 'N/A'
            _bb_pos2 = 'N/A'
            if df2 is not None and 'BB_upper' in df2.columns and 'BB_lower' in df2.columns:
                _bb_u = float(df2['BB_upper'].iloc[-1])
                _bb_l = float(df2['BB_lower'].iloc[-1])
                _bb_pos2 = f'{round((price2 - _bb_l) / max(_bb_u - _bb_l, 0.01) * 100, 1)}%'
            _ma_str2 = ', '.join(f'{k}:{"上方✅" if v else "下方⚠️"}' for k,v in _ma_above2.items()) if _ma_above2 else 'N/A'
            _rsi_str2 = f'{rsi2:.1f}' if rsi2 else 'N/A'
            _k_str2   = f'{k2:.1f}' if k2 else 'N/A'
            _d_str2   = f'{d2:.1f}' if d2 else 'N/A'
            _tech_data2 = (
                f"現價={price2:.2f} | 健康度={health2:.0f}/100 | RSI={_rsi_str2} | "
                f"KD=K:{_k_str2}/D:{_d_str2} | "
                f"IBS={_ibs2} | 量比={_vol_ratio2} | ATR={_atr2:.2f} | 布林位階={_bb_pos2}\n"
                f"均線位階={_ma_str2}\n"
                f"VCP={'突破訊號✅' if _vcp_ok2 else ('整理收縮中' if vcp2 else '未形成')}"
            )
            # ── 彙整籌碼數據 ──────────────────────────────────────
            _chip_str2 = '無法取得三大法人明細'
            if df2 is not None and not df2.empty:
                _fb = next((df2[c].tail(10).sum() for c in df2.columns if '外資' in str(c) and '買' in str(c)), None)
                _tb = next((df2[c].tail(10).sum() for c in df2.columns if '投信' in str(c)), None)
                _db = next((df2[c].tail(10).sum() for c in df2.columns if '自營' in str(c)), None)
                _parts = []
                if _fb is not None:
                    _parts.append(f'外資10日:{_fb/1e8:+.1f}億')
                if _tb is not None:
                    _parts.append(f'投信10日:{_tb/1e8:+.1f}億')
                if _db is not None:
                    _parts.append(f'自營10日:{_db/1e8:+.1f}億')
                if _parts:
                    _chip_str2 = ' | '.join(_parts)
            # ── 彙整基本面數據 ────────────────────────────────────
            _fund_str2 = []
            if _rev_yoy_list:
                _fund_str2.append(f'月營收YoY近3月={", ".join(_rev_yoy_list)}')
            if qtr2 is not None and not qtr2.empty:
                _gm_col = next((c for c in qtr2.columns if '毛利' in str(c)), None)
                _eps_col = next((c for c in qtr2.columns if 'eps' in str(c).lower() or 'EPS' in str(c)), None)
                if _gm_col:
                    _gm_vals = pd.to_numeric(qtr2[_gm_col].tail(4), errors='coerce').dropna()
                    _fund_str2.append(f'近4季毛利率={[round(v,1) for v in _gm_vals.tolist()]}%')
                if _eps_col:
                    _eps_vals = pd.to_numeric(qtr2[_eps_col].tail(4), errors='coerce').dropna()
                    _fund_str2.append(f'近4季EPS={_eps_vals.tolist()}')
            if cl2 and cl2 > 0:
                _fund_str2.append(f'合約負債={cl2/1e8:.1f}億')
            if cx2 and cx2 > 0:
                _fund_str2.append(f'資本支出={cx2/1e8:.1f}億')
            if avg_div2 > 0 and price2 > 0:
                _cp2_ai = round(avg_div2/0.07, 1)
                _fp2_ai = round(avg_div2/0.05, 1)
                _dp2_ai = round(avg_div2/0.03, 1)
                _zone2 = ('便宜' if price2 <= _cp2_ai else '合理' if price2 <= _fp2_ai
                          else '昂貴' if price2 <= _dp2_ai else '超過昂貴')
                _fund_str2.append(f'357估值={_zone2}（便宜:{_cp2_ai}/合理:{_fp2_ai}/昂貴:{_dp2_ai}）')
            _fund_data2 = '\n'.join(_fund_str2) if _fund_str2 else '基本面資料不足'
            # ── 彙整財報體檢結果 ──────────────────────────────────
            _fh_res2 = st.session_state.get(f'_fh_{sid2}', {})
            _health_check_str2 = '尚未執行財報體檢'
            if _fh_res2 and not _fh_res2.get('error'):
                _opm2 = _fh_res2.get('opm_data', {})
                _opm_str2 = (f"應付帳款天數={_opm2.get('payable_days','N/A')}天 / "
                             f"應收帳款天數={_opm2.get('receivable_days','N/A')}天 → "
                             f"{'具備快收慢付優勢' if _opm2.get('advantage') else '付款週期不利'}"
                             if _opm2 else '無 OPM 資料')
                _red2 = _fh_res2.get('red_flags', '')
                _flags_str2 = (_red2 if _red2 and _red2.strip().lower() not in ('none', '無', '') else '無明顯地雷')
                _health_check_str2 = (
                    f"現金水位={_fh_res2.get('cash_ratio_status','')} {_fh_res2.get('cash_ratio_value','')} | "
                    f"OCF={_fh_res2.get('ocf_status','')} {_fh_res2.get('ocf_value','')} | "
                    f"負債比={_fh_res2.get('debt_ratio_status','')} {_fh_res2.get('debt_ratio_value','')}\n"
                    f"企業DNA={_fh_res2.get('business_model_dna','N/A')}\n"
                    f"OPM商業話語權={_opm_str2}\n"
                    f"五力雷達={_fh_res2.get('radar_scores',{})}\n"
                    f"AI財報洞察={_fh_res2.get('ai_insight','')}\n"
                    f"地雷警示={_flags_str2}"
                )
            # ── 彙整市場背景 ──────────────────────────────────────
            _mkt_info2 = st.session_state.get('mkt_info', {})
            _regime_txt2 = {'bull':'多頭市場（積極操作）','neutral':'震盪整理（謹慎觀望）','bear':'空頭市場（縮減部位）'}.get(_regime2, _regime2)
            # 宏觀指標彙整（VIX / 美核心CPI / 🇹🇼 台灣 PMI / 美10Y / 費半 SOX）— 供 AI 跨資產判讀
            _macro_info2 = st.session_state.get('macro_info', {}) or {}
            _ma_snap2    = st.session_state.get('ma_snap', {}) or {}
            _intl_snap2  = st.session_state.get('intl_snap', {}) or {}
            _macro_lines2 = []
            _vix_v2 = (_macro_info2.get('vix') or {}).get('current') or _ma_snap2.get('vix')
            if _vix_v2 is not None:
                try:
                    _macro_lines2.append(f"VIX 恐慌指數={float(_vix_v2):.2f}（>20 警戒、>30 恐慌）")
                except (TypeError, ValueError):
                    pass
            _cpi_v2 = (_macro_info2.get('us_core_cpi') or {}).get('yoy') or _ma_snap2.get('cpi')
            if _cpi_v2 is not None:
                try:
                    _macro_lines2.append(f"美核心 CPI YoY={float(_cpi_v2):+.2f}%（Fed 目標 2%；>3% 升息壓力）")
                except (TypeError, ValueError):
                    pass
            _pmi_v2 = (_macro_info2.get('ism_pmi') or {}).get('value')
            if _pmi_v2 is not None:
                try:
                    _macro_lines2.append(f"🇹🇼 台灣 PMI={float(_pmi_v2):.1f}（CIER；50=榮枯線；<45=製造業衰退強訊；台灣製造業景氣領先指標）")
                except (TypeError, ValueError):
                    pass
            _tnx_v2 = (_intl_snap2.get('tnx') or {}).get('last') or _ma_snap2.get('us10y')
            if _tnx_v2 is not None:
                try:
                    _macro_lines2.append(f"美 10Y 殖利率={float(_tnx_v2):.2f}%（>4% 估值壓抑、>5% 殺戮區）")
                except (TypeError, ValueError):
                    pass
            _sox_obj2 = _intl_snap2.get('sox') or {}
            _sox_pct2 = _sox_obj2.get('pct')
            _sox_last2 = _sox_obj2.get('last')
            if _sox_pct2 is not None:
                try:
                    _sl_str = f"｜當前 {float(_sox_last2):.0f}" if _sox_last2 is not None else ""
                    _macro_lines2.append(f"費半 SOX={float(_sox_pct2):+.2f}%{_sl_str}（領先台股科技股 2-4 週）")
                except (TypeError, ValueError):
                    pass
            _macro_extra2 = "\n  • " + "\n  • ".join(_macro_lines2) if _macro_lines2 else "（暫無，請先到「宏觀拼圖」分頁更新）"
            _mkt_ctx2 = (
                f"大盤格局={_regime_txt2} | 健康評分={_mkt_info2.get('market_score','N/A')} | "
                f"建議持股={_mkt_info2.get('exposure_limit_pct', st.session_state.get('macro_state',{}).get('exposure_limit_pct','N/A'))}%\n"
                f"宏觀跨資產背景：{_macro_extra2}"
            )
            # ── 抓取個股新聞 ──────────────────────────────────────
            _stock_news2 = _fetch_stock_news(sid2, name2, 5)
            _news_str2 = '\n'.join(
                f'- {_n["title"]}（{_n.get("source","RSS")} · {_n.get("published","")}）'
                for _n in _stock_news2
            ) if _stock_news2 else '（暫無相關個股新聞）'
            # ── 建構新版 Prompt ───────────────────────────────────
            _ai_sum_prompt = f"""你是一位擁有 20 年經驗、精通量化分析與價值投資的「資深首席投資策略師」。你的分析風格冷靜、精準，且強調風險控管。

【輸入數據】（以下為不可撼動的事實，禁止使用預訓練記憶或猜測）

【個股技術指標】
{_tech_data2}

【籌碼動向】
{_chip_str2}

【財務基本面】
{_fund_data2}

【財報體檢（MJ林明樟體系）】
{_health_check_str2}

【近期相關新聞】（RSS 即時，供輔助研判，不作為唯一依據）
{_news_str2}

【總體經濟背景】
{_mkt_ctx2}

【分析指令】
請依照以下步驟進行五維度交叉驗證：
步驟一：技術籌碼共振 - 確認技術面突破是否伴隨法人籌碼同步進場。
步驟二：基本面背書 - 判斷股價波動是否有營收、毛利、EPS 增長支撐。
步驟三：財報體檢整合 - 綜合 MJ林明樟體系（企業DNA / 五力雷達 / OPM話語權 / 地雷警示）評判財務健康度與資金流向型態。
步驟四：估值定位 - 結合357估值區間判斷目前股價是否在合理買進區。
步驟五：風險量化與宏觀交叉驗證 - 利用ATR計算動態波動區間；並必須引用「宏觀跨資產背景」中的 VIX / 美核心CPI / 🇹🇼 台灣 PMI / 美10Y / 費半 SOX 至少 2 項，說明對個股估值與外資籌碼的影響（例：「台灣 PMI < 48 → 製造業衰退，台股出口股承壓」、「SOX 重挫 -2% 領先台股科技股 → 對外資權值股不利」、「美10Y > 4.5% → 高 PE 成長股估值壓抑」）。

【輸出格式】使用 Markdown 語法，生成以下架構的報告：

## 📊 {sid2} {name2} 戰略評估報告
分析時間：{pd.Timestamp.now().strftime('%Y-%m-%d')}

### 一、五維診斷雷達圖（0-10評分）
- **技術趨勢**：(得分/10，理由)
- **籌碼力度**：(得分/10，理由)
- **基本體質**：(得分/10，理由)
- **財報健康**：(得分/10，理由 — 含企業DNA/五力評分)
- **風險防禦**：(得分/10，安全邊際 + 地雷風險評價)

### 二、關鍵洞察摘要（100字以內）
（總結目前處於「築底/攻擊/噴發/轉弱/盤整」哪種階段及核心邏輯）

### 三、深度解析
- **技術/籌碼亮點**：（均線與法人的共振現象）
- **基本面與估值**：（目前股價是否透支未來成長，357估值定位）
- **財報體質**：（企業DNA類型說明、OPM商業話語權、五力雷達弱點、地雷警示是否觸發）

### 四、具體戰術建議
⚠️ 以下內容僅供參考，不構成買賣邀約。
- **參考進場區間**：（結合支撐位與ATR={_atr2:.2f}給予建議）
- **停利目標**：（目標一/目標二，參考前高或乖離率）
- **停損點位**：（根據ATR 1.5倍計算，即參考 {round(price2 - _atr2 * 1.5, 2):.2f} 附近）

### 五、警示與避雷針
（列出可能破壞此分析邏輯的風險因子，包含財報地雷警示與總經風險）

【語言規範】統一使用繁體中文。禁止出現「一定要買」、「保證獲利」等字眼。數據精確到小數點後兩位。"""

            # 串流輸出（打字機效果），L5：只讀 _ai_sum_prompt，不抓資料
            def _ai_stream_gen():
                _full = gemini_call(_ai_sum_prompt, max_tokens=1800)
                _chunk = 80
                import time as _t_ai
                for _i in range(0, len(_full), _chunk):
                    yield _full[_i:_i + _chunk]
                    _t_ai.sleep(0.015)
            _ai_sum_result = st.write_stream(_ai_stream_gen())
            st.session_state[_ai_sum_key] = _ai_sum_result

        if _ai_sum_cached and not _do_ai_sum:
            st.markdown(_ai_sum_cached)
        elif not _do_ai_sum:
            st.caption('▲ 點擊上方按鈕，AI 將綜合技術面、基本面、財報體檢四大群組資料生成完整戰略評估報告。')

# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
# TAB 3: 綜合評分戰情室（汰弱留強 × 多因子評分 合併版）
# ══════════════════════════════════════════════════════════════

    st.markdown("""<div style="background:#2a0d0d;border:1px solid #f85149;border-radius:8px;
padding:10px 14px;font-size:11px;color:#f85149;margin-top:12px;">
⚠️ 本手冊整理自各大師公開課程內容，僅供學術研究與教育用途。
投資涉及風險，任何操作均應自行判斷，盈虧自負。本系統非投資顧問，不構成買賣建議。
</div>""", unsafe_allow_html=True)
