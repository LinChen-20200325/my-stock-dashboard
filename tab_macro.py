"""TAB 總經紅綠燈 + 多指標儀表板 — 從 app.py 抽出（PR P2-B Phase 5-D，最終巨型 TAB）

依賴策略
========
- Top-level: streamlit（最穩定）
- 函式內 late import 44 個依賴，避免循環 import：
  * stdlib: datetime, json, os, pandas, plotly, concurrent.futures
  * 設定: config.FINMIND_TOKEN
  * 外部模組:
    - macro_state_locker: MacroStateLocker / calculate_system_state / load_macro_state
    - v4_strategy_engine: V4StrategyEngine
    - daily_checklist (17): _fetch_otc_via_finmind / calc_stats
      / evaluate_market_status_v4_final / fetch_adl / fetch_institutional
      / fetch_margin_balance / fetch_single / multi_chart / section_header
      / sparkline / stat_card / COLORS_7 / INTL_MAP / INTL_UNIT
      / TECH_MAP / TW_MAP / TW_UNIT
    - macro_alert (3): check_macro_alerts / fetch_macro_snapshot / render_macro_alerts
    - market_strategy: get_market_assessment
    - leading_indicators: build_leading_fast / render_leading_table
    - ui_widgets: beginner_kpi / kpi / teacher_conclusion
  * app.py 內部 (5): _bps / _fetch_macro_news / _get_fm_token / _tw_now_str / gemini_call

呼叫端
======
- app.py: `with tab_macro: render_tab_macro()`
"""
from __future__ import annotations

import streamlit as st

from macro_helpers import calc_traffic_light, rp_entry, rp_scalar, rp_ts
from tab_helpers import safe_get


def render_tab_macro():
    # ─ Late imports（避免循環 import）─
    import datetime
    import json
    import os
    import pandas as pd
    import plotly.graph_objects as go
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from config import FINMIND_TOKEN
    # 外部模組
    from macro_state_locker import (
        MacroStateLocker, calculate_system_state, load_macro_state,
    )
    from v4_strategy_engine import V4StrategyEngine
    from daily_checklist import (
        _fetch_otc_via_finmind, calc_stats, evaluate_market_status_v4_final,
        fetch_adl, fetch_institutional, fetch_margin_balance, fetch_single,
        multi_chart, section_header, sparkline, stat_card,
        COLORS_7, INTL_MAP, INTL_UNIT, TECH_MAP, TW_MAP, TW_UNIT,
    )
    from macro_alert import (
        check_macro_alerts, fetch_macro_snapshot, render_macro_alerts,
    )
    from market_strategy import get_market_assessment
    from leading_indicators import build_leading_fast, render_leading_table
    from ui_widgets import beginner_kpi, cond_badge, kpi, teacher_conclusion
    # app.py 內部 helper
    from app import (
        _bps, _fetch_macro_news, _get_fm_token, _tw_now_str, gemini_call,
    )

    # ════════════════════════════════════════════════════════
    # 【模組一】紅綠燈決策儀表板（st.empty 佔位符修復版）
    # 修復：先挖洞（placeholder）→ 資料到位後回填，杜絕未審先判
    # ════════════════════════════════════════════════════════

    # 紅綠燈計算邏輯已抽至 macro_helpers.calc_traffic_light（Phase 7A-Ext）

    def _render_traffic_light(placeholder, tl, mkt_info=None):
        """將計算結果回填到 placeholder（或顯示等待狀態）。
        mkt_info: 選填，來自 market_regime() 的原始 dict，用以合併顯示市場評分與信號。
        以較保守信號為主（traffic light 已含 defense/health 降級邏輯）。

        信心門檻：conf < 70% 時不顯示燈號，改列出缺失資料避免誤導決策。
        """
        if tl is None:
            placeholder.info(
                '⏳ **系統正在深度解析大盤與籌碼數據，請稍候...**\n\n'
                '首次使用請點擊「🚀 一鍵更新全部數據」載入資料。',
                icon='📡'
            )
            return

        # ── 信心門檻 gating：conf<70% 直接擋燈號，逐項列出缺失資料 ──
        if tl.get('conf', 0) < 70:
            _missing = tl.get('missing_sources', []) or []
            _missing_lines = ''.join(
                f'<li style="margin:4px 0;color:#f85149;">❌ {m}</li>' for m in _missing
            ) if _missing else '<li style="color:#8b949e;">（無法判斷）</li>'
            with placeholder.container():
                st.markdown(
                    f'<div style="background:linear-gradient(135deg,#2a1d00,#1a1208);'
                    f'border:2px solid #d29922;border-radius:14px;padding:18px 22px;margin-bottom:12px;">'
                    f'<div style="font-size:22px;font-weight:900;color:#d29922;">⏸️ 資料不足，無法判斷市場狀態</div>'
                    f'<div style="font-size:13px;color:#c9d1d9;margin-top:8px;">'
                    f'目前數據信心 <b style="color:#f85149;">{tl["conf"]}%</b>'
                    f'（門檻 70%，避免新舊資料混雜誤導決策）</div>'
                    f'<div style="font-size:12px;color:#8b949e;margin-top:10px;">缺少以下資料來源：</div>'
                    f'<ul style="font-size:13px;margin:6px 0 0 4px;padding-left:20px;">{_missing_lines}</ul>'
                    f'<div style="font-size:12px;color:#58a6ff;margin-top:12px;">'
                    f'👉 請點上方「🚀 一鍵更新全部數據」載入完整資料後，燈號才會顯示。'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            return

        # ── 整合 market_regime() 的輔助資訊 ──────────────────────
        _mi      = mkt_info or {}
        _mi_score  = _mi.get('score')
        _mi_mx     = _mi.get('max_score', 4)
        _mi_idx    = _mi.get('index_price', 0)
        _mi_exp    = _mi.get('exposure_pct', '--')
        _mi_sigs   = _mi.get('signals', [])
        _mi_upd    = st.session_state.get('cl_ts', '')

        _sigs_html = ''.join(
            f'<span style="background:#21262d;border-radius:5px;padding:2px 7px;'
            f'font-size:11px;color:#c9d1d9;margin-right:4px;">{s}</span>'
            for s in _mi_sigs
        )
        _meta_line = ''
        if _mi_score is not None:
            _meta_line = (
                f'<div style="display:flex;flex-wrap:wrap;gap:14px;margin-top:8px;">'
                f'<span style="font-size:12px;color:#8b949e;">評分 '
                f'<b style="color:{tl["color"]};">{_mi_score}/{_mi_mx}</b></span>'
                f'<span style="font-size:12px;color:#8b949e;">加權指數 '
                f'<b style="color:#e6edf3;">{_mi_idx:,.0f}</b></span>'
                f'<span style="font-size:12px;color:#8b949e;">建議持股 '
                f'<b style="color:{tl["color"]};">{_mi_exp}</b></span>'
                + (f'<span style="font-size:11px;color:#484f58;">更新 {_mi_upd}</span>'
                   if _mi_upd else '')
                + '</div>'
            )

        with placeholder.container():
            # ── 合併看板主體 ────────────────────────────────────
            st.markdown(f'''<div style="background:linear-gradient(135deg,#0a1628,#0d1f3c);
border:3px solid {tl["color"]};border-radius:16px;padding:20px 24px;margin-bottom:12px;">
<div style="display:flex;align-items:flex-start;gap:16px;">
  <div style="font-size:56px;line-height:1;flex-shrink:0;">{tl["icon"]}</div>
  <div style="flex:1;min-width:0;">
    <div style="font-size:24px;font-weight:900;color:{tl["color"]};">{tl["label"]}</div>
    <div style="font-size:15px;color:#c9d1d9;margin-top:4px;">{tl["action"]}</div>
    <div style="font-size:12px;color:#8b949e;margin-top:2px;">{tl["sub"]}</div>
    {f'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:8px;">{_sigs_html}</div>' if _sigs_html else ''}
    {_meta_line}
  </div>
  <div style="text-align:right;flex-shrink:0;">
    <div style="font-size:12px;color:#484f58;">綜合健康度</div>
    <div style="font-size:36px;font-weight:900;color:{tl["color"]};">{tl["health"]:.0f}</div>
    <div style="font-size:11px;color:#484f58;">/ 100分｜信心{tl["conf"]}%</div>
  </div>
</div></div>''', unsafe_allow_html=True)

            # ── 數據信心提示 ────────────────────────────────────
            if tl['conf'] < 80:
                st.warning(f'⚠️ 數據信心指數 {tl["conf"]}%，部分資料缺失，建議更新後再操作')

    # ── ① 最頂端先建立佔位符（關鍵：必須在任何計算前建立）───
    _tl_placeholder = st.empty()

    # ── ② 讀取快取（快取新鮮才顯示燈號，否則顯示等待，避免誤導）──
    # 設計原則：燈號必須反映「當前資料」而非「過期快取」
    # 30 分鐘內的快取視為有效；超過則要求重新更新
    import datetime as _dt_tl
    _cl_ts_str = st.session_state.get('cl_ts', '')
    _cache_fresh = False
    if _cl_ts_str:
        try:
            _cl_ts_dt = _dt_tl.datetime.strptime(_cl_ts_str[:16], '%Y-%m-%d %H:%M')
            _age_min  = (_dt_tl.datetime.now() - _cl_ts_dt).total_seconds() / 60
            _cache_fresh = _age_min < 30   # 30 分鐘內視為新鮮
        except Exception:
            _cache_fresh = False

    # 刷新進行中時隱藏舊資料（避免更新期間顯示過期結論）
    _is_refreshing = st.session_state.get('_is_refreshing', False)
    _show_market_data = _cache_fresh and not _is_refreshing

    if _cache_fresh and not _is_refreshing:
        # 快取新鮮 → 立即計算燈號（含資料新鮮度標記）
        _tm_mkt_init = st.session_state.get('mkt_info', {})
        _tm_jq_init  = st.session_state.get('jingqi_info', {})
        _tm_cd_init  = st.session_state.get('cl_data', {})
        _tm_li_init  = st.session_state.get('li_latest')
        _tl_init     = calc_traffic_light(_tm_mkt_init, _tm_jq_init, _tm_cd_init, _tm_li_init)
        _render_traffic_light(_tl_placeholder, _tl_init, _tm_mkt_init)
    else:
        # 無快取 or 快取過期 → 顯示等待狀態，不顯示誤導性燈號
        age_note = f'（上次更新 {_age_min:.0f} 分鐘前，已過期）' if _cl_ts_str and not _cache_fresh else '（尚無資料）'
        _tl_placeholder.warning(
            f'⏳ **燈號等待中 {age_note}**\n\n'
            '燈號將在「🚀 一鍵更新全部數據」完成後自動亮起。\n'
            '確保資料是今日最新，再做投資判斷。',
        )
        _tl_init = None

    # 統一有效市場 regime（確保交通燈與下方卡片結論一致）
    # 🔴 對應 bear，🟢 對應 bull，🟡 對應 neutral
    _tl_eff_reg = {'🔴': 'bear', '🟢': 'bull', '🟡': 'neutral'}.get(
        (_tl_init or {}).get('icon', ''), None
    )

    # ── 同步寫入 session_state（其他頁面需要的值）────────────
    if _tl_init:
        st.session_state['warroom_summary'] = {
            'traffic_light': _tl_init['label'],
            'health_score':  _tl_init['health'],
            'regime': _tm_mkt_init.get('regime', 'neutral'),
            'market_score':  _tl_init['score'],
            'jingqi_avg':    _tl_init['jqavg'],
            'leek_index':    _tl_init['leek'],
            'foreign_net_bn':_tl_init['fnet'],
            'futures_net':   _tl_init['fut_net'],
            'confidence_pct':_tl_init['conf'],
        }

    st.markdown('<div style="background:#0a1628;border:1px solid #1f6feb;border-radius:12px;padding:16px;margin-bottom:12px;">', unsafe_allow_html=True)
    st.markdown('<div style="font-size:18px;font-weight:900;color:#58a6ff;margin-bottom:8px;">🌍 今日市場總覽 — 現在適合買股票嗎？</div>', unsafe_allow_html=True)
    st.markdown('''<div style="font-size:13px;color:#c9d1d9;line-height:1.8;">
投資前先看大環境，就像出門前先看天氣預報。這個頁面告訴你：<br>
• <b style="color:#3fb950;">現在是多頭市場（晴天）</b> → 可以積極找好股票買進<br>
• <b style="color:#d29922;">現在是震盪整理（多雲）</b> → 謹慎操作，小量買進<br>
• <b style="color:#f85149;">現在是空頭市場（下雨）</b> → 先保留現金，等待機會<br>
</div>''', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ── 🔰 故事化白話解讀（純疊加；解碼上方燈號卡片的數字，不重複多空說明）──
    with st.expander('🔰 看不懂上面那張燈號卡片的數字？點我 30 秒讀懂'):
        st.markdown('''卡片上的每個數字，用一句話看懂：

| 卡片欄位 | 白話意思 |
|---|---|
| **綜合健康度 /100** | 把均線、籌碼、景氣等訊號綜合成一個「市場體檢分數」，越高越健康 |
| **信心 %** | 系統對「資料夠不夠新、夠不夠齊」的把握度；**低於 70% 會直接擋住燈號**，避免拿過期資料誤判 |
| **評分 x/4** | 大盤多空打分，分數越高越偏多頭 |
| **建議持股 %** | 對應目前環境，建議把多少比例的資金放在股票上（其餘留現金） |
| **灰色小標籤** | 當下觸發的關鍵訊號（如外資買超、融資增減、期貨淨部位等） |

> 💡 看燈前先按上方「🚀 一鍵更新全部數據」，燈號才會反映「今天」而不是過期資料。''')

    st.divider()

    st.markdown("""<div style="padding:6px 0 4px;">
<span style="font-size:20px;font-weight:900;color:#e6edf3;">🌍 今日市場總覽</span>
<span style="font-size:11px;color:#484f58;margin-left:10px;">決定：現在能買嗎？大盤水位？</span>
</div>""", unsafe_allow_html=True)
    # 五步流程說明已整合至主導覽列，此處不重複顯示

    # ══ 戰情概覽（一眼看清今日市場）══════════════════════════
    _ov_mkt  = st.session_state.get('mkt_info', {})
    _ov_jq   = st.session_state.get('jingqi_info', {})
    _ov_cd   = st.session_state.get('cl_data', {})
    # inst 優先從 cl_data，fallback 到獨立緩存的 _last_inst
    _ov_inst = _ov_cd.get('inst') or st.session_state.get('_last_inst', {})
    # 外資 key 匹配：TWSE 格式「外資及陸資(不含外資自營商)」或 FinMind 格式「外資」
    _ov_fk   = next((k for k in _ov_inst if '外資' in k), None)
    _ov_margin = _ov_cd.get('margin')
    _ov_bias = st.session_state.get('bias_info', {})

    if _show_market_data and any([_ov_mkt, _ov_jq, _ov_cd]):
        _ov_cols = st.columns(4)
        # 大盤
        with _ov_cols[0]:
            # 以交通燈有效 regime 為主，確保與頂部卡片結論一致
            _ov_reg = _tl_eff_reg or (_ov_mkt.get('regime','neutral') if _ov_mkt else 'neutral')
            _ov_lbl = {'bull':'🟢 多頭','neutral':'🟡 震盪','bear':'🔴 空頭防禦'}.get(_ov_reg,'⚪')
            _ov_exp = _ov_mkt.get('exposure_pct','--') if _ov_mkt else '--'
            st.markdown(beginner_kpi('今日市場狀態', _ov_lbl, f'建議持股比例 {_ov_exp}',
                            '#3fb950' if _ov_reg=='bull' else ('#f85149' if _ov_reg=='bear' else '#d29922'),
                            '#0d1117'), unsafe_allow_html=True)
        # 外資籌碼
        with _ov_cols[1]:
            _ov_fnet = _ov_inst.get(_ov_fk,{}).get('net',None) if _ov_fk else None
            if _ov_fnet is not None:
                _ov_fc = '#da3633' if _ov_fnet > 0 else '#2ea043'
                st.markdown(beginner_kpi('大戶今日', f'{_ov_fnet:+.1f}億', '外資淨買賣（+買 -賣）', _ov_fc, '正數=大戶在買，跟著買較安全'), unsafe_allow_html=True)
            else:
                st.markdown(kpi('外資現貨', '--', '更新後顯示', '#484f58', '#0d1117'), unsafe_allow_html=True)
        # 旌旗/廣度
        with _ov_cols[2]:
            _ov_jqp = _ov_jq.get('avg',None) if _ov_jq else None
            if _ov_jqp is not None:
                _ov_jc = '#3fb950' if _ov_jqp>=60 else ('#d29922' if _ov_jqp>=30 else '#f85149')
                st.markdown(beginner_kpi('全市場健康度', f'{_ov_jqp:.0f}%', '有幾%的股票站在均線之上', _ov_jc, '>60%才適合積極買進'), unsafe_allow_html=True)
            else:
                st.markdown(kpi('旌旗指數', '--', '掃描後顯示', '#484f58', '#0d1117'), unsafe_allow_html=True)
        # 乖離率
        with _ov_cols[3]:
            _ov_b240 = _ov_bias.get('bias_240', None) if _ov_bias else None
            if _ov_b240 is not None:
                _ov_bc = '#f85149' if abs(_ov_b240) > 20 else '#3fb950'
                st.markdown(beginner_kpi('大盤位置', f'{_ov_b240:+.1f}%', '偏離年均線多少（過高=貴）', _ov_bc, '>+20%過熱；<-20%便宜'), unsafe_allow_html=True)
            else:
                st.markdown(kpi('年線乖離', '--', '更新後顯示', '#484f58', '#0d1117'), unsafe_allow_html=True)
        st.markdown('')

    # ══ 今日作戰室（最重要：一眼看清今天該做什麼）══════════════
    st.markdown('''<div style="background:linear-gradient(135deg,#0a1628,#0d2040);
border:2px solid #1f6feb;border-radius:14px;padding:16px;margin-bottom:14px;">
<div style="font-size:18px;font-weight:900;color:#58a6ff;margin-bottom:4px;">
🎯 今日作戰室 — 現在該做什麼？</div>
<div style="font-size:11px;color:#484f58;">每次操作前先看這裡，5分鐘掌握今日全局</div>
</div>''', unsafe_allow_html=True)

    _wr_mkt  = st.session_state.get('mkt_info', {})
    _wr_cd   = st.session_state.get('cl_data', {})
    _wr_bias = st.session_state.get('bias_info', {})
    _wr_m1b  = st.session_state.get('m1b_m2_info', {})
    _wr_inst = _wr_cd.get('inst', {})
    _wr_fk   = next((k for k in _wr_inst if '外資' in k), None)
    if _wr_fk is None:
        _wr_fk = next((k for k in _wr_inst if '外資' in k), None)
    _wr_fnet = _wr_inst.get(_wr_fk,{}).get('net', None) if _wr_fk else None
    _wr_margin = _wr_cd.get('margin')
    _wr_adl  = _wr_cd.get('adl')
    _wr_ts   = st.session_state.get('cl_ts','')
    # 以交通燈有效 regime 為主，確保與頂部卡片結論一致
    _wr_reg  = _tl_eff_reg or (_wr_mkt.get('regime','neutral') if _wr_mkt else 'neutral')
    # v4 引擎：解耦趨勢與位階，取得精準操作建議
    _wr_fut_net = int(st.session_state.get('futures_net', 0) or 0)
    _v4 = evaluate_market_status_v4_final(
        _wr_bias.get('price', 0) or 0,
        _wr_bias.get('ma240', 0) or 0,
        _wr_fut_net,
    )
    # 持股建議統一用紅綠燈/market_regime 的 exposure_pct（與 ①②一致，不再用 v4 區間）
    _wr_exp = _wr_mkt.get('exposure_pct', '--') if _wr_mkt else '--'

    if _show_market_data and (_wr_mkt or _wr_cd):
        # ── 今日唯一結論（大字顯示）──────────────────────────
        _wr_action = '請先更新總經數據'
        _wr_action_color = '#484f58'
        _wr_warns = []

        # 主結論統一以頂部紅綠燈 regime 為準（與燈號/戰情概覽一致，杜絕打架）
        _wr_reg_map = {
            'bull':    ('🟢 趨勢偏多 — 可逢回布局核心部位',   '#3fb950'),
            'neutral': ('🟡 方向震盪 — 區間操作、控制部位',   '#d29922'),
            'bear':    ('🔴 趨勢偏空 — 優先保留現金、嚴設停損', '#f85149'),
        }
        _wr_base, _wr_action_color = _wr_reg_map.get(_wr_reg, ('請先更新總經數據', '#484f58'))
        _wr_action = (f'{_wr_base}（建議持股 {_wr_exp}）'
                      if _wr_exp not in ('--', None, '') else _wr_base)
        # v4 年線位階資訊 → 降為補充提示，不再覆蓋主結論
        _v4_bits = [f'年線乖離 {_v4["Bias_240"]:+.1f}%']
        if not _v4.get('Is_Bull'):
            _v4_bits.append('股價在年線下')
        if _v4.get('Is_Overheated'):
            _v4_bits.append('乖離過熱')
        if _v4.get('Is_Foreign_Hedging'):
            _v4_bits.append('外資期貨避險')
        _wr_v4_hint = '｜'.join(_v4_bits)

        # 風險警示收集（v5：純融資餘額判斷）
        if _wr_margin and _wr_margin > 3400:
            _wr_warns.append(('🔴', f'融資 {_wr_margin:.0f}億 極度危險，散戶過熱，不宜追高'))
        elif _wr_margin and _wr_margin > 2500:
            _wr_warns.append(('🟡', f'融資 {_wr_margin:.0f}億 警戒，注意風險'))

        if _wr_bias:
            _b240 = _wr_bias.get('bias_240', 0)
            if _b240 > 20:
                _wr_warns.append(('🟡', f'年線乖離 {_b240:+.1f}%，大盤偏高，勿追買'))
            elif _b240 < -20:
                _wr_warns.append(('✅', f'年線負乖離 {_b240:+.1f}%，長期布局機會'))

        if _wr_fnet is not None and _wr_fnet < -20:
            _wr_warns.append(('🔴', f'外資賣超 {abs(_wr_fnet):.1f}億，主力離場，謹慎'))

        if _wr_adl is not None and not _wr_adl.empty and 'ad_ratio' in _wr_adl.columns:
            _adl_r = float(_wr_adl['ad_ratio'].iloc[-1])
            if _adl_r < 35:
                _wr_warns.append(('🔴', f'上漲股票僅 {_adl_r:.0f}%，市場廣度不足，觀望'))

        # 顯示今日結論
        st.markdown(
            f'<div style="background:#0a2818;border-left:5px solid {_wr_action_color};'
            f'border-radius:0 10px 10px 0;padding:14px 18px;margin:8px 0;">'
            f'<div style="font-size:11px;color:#484f58;margin-bottom:4px;">📌 今日唯一行動建議</div>'
            f'<div style="font-size:17px;font-weight:900;color:{_wr_action_color};">{_wr_action}</div>'
            + (f'<div style="font-size:11px;color:#8b949e;margin-top:4px;">📐 年線位階參考：{_wr_v4_hint}</div>' if _wr_v4_hint else '')
            + (f'<div style="font-size:11px;color:#484f58;margin-top:4px;">更新時間：{_wr_ts}</div>' if _wr_ts else '') +
            '</div>', unsafe_allow_html=True)

        # 今日5分鐘清單
        st.markdown('##### ✅ 今日操作前 5 分鐘清單')
        _cl_items = [
            ('大盤燈號', '🟢 多頭' if _wr_reg=='bull' else ('🔴 空頭防禦' if _wr_reg=='bear' else '🟡 震盪'),
             _wr_reg=='bull', '多頭才積極操作'),
            ('外資方向', f'{"買超" if (_wr_fnet or 0)>0 else "賣超"} {abs(_wr_fnet or 0):.0f}億' if _wr_fnet is not None else '未知',
             (_wr_fnet or 0) > 0, '外資買超=跟著走'),
            ('融資餘額',
             f'{_wr_margin:.0f}億' if _wr_margin else '未取得 (N/A)',
             not _wr_margin or _wr_margin <= 2500,
             '>2500億警戒，>3400億極危'),
            ('年線位置', f'乖離{_wr_bias.get("bias_240",0):+.1f}%' if _wr_bias else '未知',
             not _wr_bias or abs(_wr_bias.get("bias_240",0)) < 20, '超過±20%要警惕'),
            ('持股比例', f'建議{_wr_exp}', _wr_reg!='bear', '按建議比例，不要滿倉'),
        ]
        for _name, _val, _ok, _tip in _cl_items:
            _ic = '✅' if _ok else '⚠️'
            _vc = '#3fb950' if _ok else '#f85149'
            st.markdown(
                f'<div style="display:flex;align-items:center;padding:5px 8px;margin:2px 0;'
                f'background:#0d1117;border-radius:6px;border:1px solid #21262d;">'
                f'<span style="font-size:16px;width:28px;">{_ic}</span>'
                f'<span style="font-size:13px;color:#c9d1d9;width:80px;">{_name}</span>'
                f'<span style="font-size:13px;color:{_vc};font-weight:700;flex:1;">{_val}</span>'
                f'<span style="font-size:11px;color:#484f58;">{_tip}</span>'
                f'</div>', unsafe_allow_html=True)

        # 風險警示
        if _wr_warns:
            st.markdown('##### ⚠️ 今日風險警示')
            for _wic, _wtxt in _wr_warns:
                _wbg = '#2a0d0d' if '🔴' in _wic else ('#2a1f00' if '🟡' in _wic else '#0a2818')
                st.markdown(
                    f'<div style="background:{_wbg};border-radius:6px;padding:7px 12px;margin:3px 0;'
                    f'font-size:13px;color:#c9d1d9;">{_wic} {_wtxt}</div>',
                    unsafe_allow_html=True)

        # 月虧損強制停機警示
        _monthly_loss = st.session_state.get('monthly_loss_pct', 0)
        if _monthly_loss < -10:
            st.markdown(
                f'<div style="background:#3a0000;border:2px solid #f85149;border-radius:10px;'
                f'padding:14px;margin:10px 0;text-align:center;">'
                f'<div style="font-size:16px;font-weight:900;color:#f85149;">⛔ 月虧損警示</div>'
                f'<div style="font-size:13px;color:#c9d1d9;margin-top:6px;">'
                f'本月虧損已達 {abs(_monthly_loss):.1f}%，建議暫停操作 7 天<br>'
                f'冷靜後重新評估選股邏輯</div></div>',
                unsafe_allow_html=True)

        st.markdown('<hr style="border-color:#21262d;margin:12px 0;">', unsafe_allow_html=True)
    else:
        st.info('📡 點擊「🚀 一鍵更新全部數據」載入今日作戰室')
        st.markdown('<hr style="border-color:#21262d;margin:12px 0;">', unsafe_allow_html=True)

    # ── FinMind Token 狀態提示（不發 API，只檢查 env 是否有值）───
    _fm_tok_now = _get_fm_token()
    if not _fm_tok_now:
        st.error(
            '🔑 **FINMIND_TOKEN 未設定** — 以下功能無法使用：月營收、合約負債/資本支出、'
            '先行指標（期貨/選擇權/法人留倉）\n\n'
            '**設定步驟（Streamlit Cloud）：**\n'
            '1. 前往 https://finmindtrade.com 免費註冊並取得 API Token\n'
            '2. Streamlit Cloud → 你的 App → **Settings → Secrets**\n'
            '3. 新增一行：`FINMIND_TOKEN = "your_token_here"`\n'
            '4. 按 Save → App 自動重啟後即生效'
        )
    else:
        st.success(f'✅ FinMind Token 已設定（{_fm_tok_now[:12]}...）', icon='🔑')

    def _on_refresh_click():
        """on_click callback：全清快取（pickle + st.cache_data + proxy URL cache
        + 總經相關 session_state），確保拿到真正最新資料，零殘留。
        """
        try:
            from daily_checklist import _pkl_clear_all
            _pkl_clear_all()
        except Exception as _e_clr:
            print(f'[Cache] pkl clear failed: {_e_clr}')
        try:
            st.cache_data.clear()
            print('[Cache] 🗑️ st.cache_data cleared')
        except Exception as _e_sc:
            print(f'[Cache] st.cache_data clear failed: {_e_sc}')
        try:
            import proxy_helper as _ph_clr
            _ph_clr._URL_CACHE.clear()
            _ph_clr.reset_proxy_cache()
            print('[Cache] 🗑️ proxy URL cache + config cache cleared')
        except Exception as _e_ph:
            print(f'[Cache] proxy clear failed: {_e_ph}')
        # 清除總經 tab session_state 殘留資料，避免新舊混雜
        for _k in ('cl_data', 'cl_ts', 'mkt_info', 'jingqi_info', 'li_latest',
                   'warroom_summary', '_last_inst', '_last_inst_date',
                   '_last_margin', 'futures_net', 'adl_debug_msg'):
            st.session_state.pop(_k, None)
        print('[Cache] 🗑️ session_state macro keys cleared')
        st.session_state['_is_refreshing'] = True

    cb1, cb2 = st.columns([5, 5])
    with cb1:
        # [v10.55.0] 合併雙按鈕為單一「一鍵更新」— 解決原「更新總經」+「載入籌碼面」雙按鈕造成的 UX 混淆
        do_refresh = st.button('🚀 一鍵更新全部數據（總經 + 籌碼 + 先行指標）',
                               key='cl_refresh',
                               on_click=_on_refresh_click, use_container_width=True,
                               type='primary',
                               help='點此一次抓取所有總經、籌碼、先行指標資料（約 30~50 秒）— 冷啟動為避免逾時，預設只載入輕量資料')
        # 點下時同步啟用 chips_loaded（讓 Phase 2 lazy-load 改成 full-load）
        if do_refresh:
            st.session_state['chips_loaded'] = True
            st.session_state.pop('cl_data', None)  # 強制重抓含籌碼版
    with cb2:
        _chips_loaded = st.session_state.get('chips_loaded', False)
        if _chips_loaded:
            st.markdown(
                '<div style="font-size:12px;color:#3fb950;text-align:center;'
                'padding:8px;border:1px solid #21262d;border-radius:6px;background:#0d1117;">'
                '✅ 籌碼面已載入<br>'
                '<span style="font-size:10px;color:#8b949e;">下次點按鈕即重新抓取</span></div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                '<div style="font-size:12px;color:#8b949e;text-align:center;'
                'padding:8px;border:1px dashed #30363d;border-radius:6px;background:#0d1117;">'
                '⏸️ 籌碼面尚未載入<br>'
                '<span style="font-size:10px;color:#484f58;">點左側按鈕即可載入</span></div>',
                unsafe_allow_html=True)

    # ── 時間戳列（合併按鈕後從 cb3 移到下方獨立一行） ──
    _now_ts = _tw_now_str()
    _last_ts = st.session_state.get('cl_ts', '尚未更新')
    _ts_color = '#3fb950' if _last_ts != '尚未更新' else '#484f58'
    st.markdown(
        f'<div style="font-size:11px;padding:4px 0;">'
        f'<span style="color:#484f58;">現在：{_now_ts}</span>　'
        f'<span style="color:{_ts_color};">上次更新：{_last_ts}</span>'
        f'</div>', unsafe_allow_html=True)

    # ── 使用者點了更新 → 立即清除舊燈號，避免誤導 ──
    if do_refresh:
        _tl_placeholder.info(
            '⏳ **正在重新載入市場數據...**\n\n'
            '燈號將在更新完成後顯示，請稍候。'
        )

    # ── 市場狀態卡 placeholder（等資料載入後才更新）──────────────
    _mkt_placeholder = st.empty()

    # [v10.56.0] 進頁完全不自動抓資料：必須使用者點按鈕才觸發
    # 移除舊的冷啟動條件 `'cl_data' not in st.session_state`，避免新舊資料混雜誤導
    # 副作用：冷啟動時所有資料區塊顯示 placeholder，由 _show_market_data gate 控制
    _load_heavy = bool(do_refresh) or bool(st.session_state.get('chips_loaded', False))

    if do_refresh:
        _fetch_ph = st.empty()
        _fetch_ph.info(
            '⏳ 載入指數行情中…' if not _load_heavy
            else '⏳ 並發抓取全部市場數據中，請稍候...'
        )
        if True:  # noqa
            import time as _t_spd
            _t_start = _t_spd.time()

            # ── 並發任務定義 ────────────────────────────────────
            def _job_intl():
                return {n: fetch_single(sym) for n, sym in INTL_MAP.items()}

            def _job_tw():
                # 9mo ≈ 195 交易日，確保 ^TWII 有足夠 bars 計算 MA120（需120筆）
                return {n: fetch_single(sym, period='9mo') for n, sym in TW_MAP.items()}

            def _job_tech():
                return {n: fetch_single(sym) for n, sym in TECH_MAP.items()}

            def _job_inst():
                return fetch_institutional()

            def _job_margin():
                try:
                    return fetch_margin_balance()
                except Exception as _em:
                    print(f'[融資] ❌ {_em}')
                    return None

            def _job_adl():
                _tok_adl = os.environ.get('FINMIND_TOKEN','') or FINMIND_TOKEN
                return fetch_adl(days=60, token=_tok_adl)

            def _job_li():
                # [v8] 直接呼叫，移除內層 Thread（純 FinMind 不需要額外執行緒）
                try:
                    tok = _get_fm_token() or FINMIND_TOKEN or os.environ.get('FINMIND_TOKEN','')
                    result = build_leading_fast(days=14, token=tok)
                    if result is not None and not result.empty:
                        print(f'[先行指標] ✅ {len(result)} 筆')
                    else:
                        print('[先行指標] ⚠️ 空資料')
                    return result
                except Exception as _eli:
                    import traceback
                    print(f'[先行指標] ❌ {_eli}')
                    print(traceback.format_exc())
                    return None

            # ── 並發執行（yfinance 最慢，先丟進去）─────────────
            # [v8] li 移出 TPE，在主流程直接呼叫（Colab worker thread 中 requests 可能受阻）
            # [Phase 2] 輕量任務（永遠跑，~30s 內完成）
            _jobs = {
                'intl':         _job_intl,
                'tw':           _job_tw,
                'tech':         _job_tech,
            }
            _job_timeouts = {
                'intl': 30, 'tw': 30, 'tech': 30,
            }
            # [Phase 2] 重量任務（按鈕觸發或手動 refresh 才跑）
            if _load_heavy:
                _jobs.update({
                    'inst':         _job_inst,
                    'margin':       _job_margin,
                    'adl':          _job_adl,
                })
                _job_timeouts.update({
                    'inst': 25,
                    'margin': 25,
                    'adl': 55,
                })
            _results = {}
            # [BUG FIX] as_completed global timeout 從 50s 改為 110s
            # 原因：li job 內部 thread join(timeout=80)，50 < 80 導致 TimeoutError 崩潰
            # 並用 try/except TimeoutError 包住迴圈，確保其他6個 job 結果不因 li 超時而丟失
            # [BUG FIX] shutdown(wait=False) — 消除 `with TPE` 阻塞 7-20 分鐘的問題
            # 原理：手動管理 executor，超時後立即 cancel 未開始任務
            _AS_COMPLETED_TIMEOUT = max(_job_timeouts.values()) + 20
            _exc = ThreadPoolExecutor(max_workers=len(_jobs))
            _futs = {_exc.submit(fn): name for name, fn in _jobs.items()}
            try:
                try:
                    for _fut in as_completed(_futs, timeout=_AS_COMPLETED_TIMEOUT):
                        name = _futs[_fut]
                        _t_limit = _job_timeouts.get(name, 20)
                        try:
                            _results[name] = _fut.result(timeout=_t_limit)
                            print(f'[並發] ✅ {name} ({_t_spd.time()-_t_start:.1f}s)')
                        except Exception as _fe:
                            _results[name] = None
                            print(f'[並發] ❌ {name}: {type(_fe).__name__}: {_fe}')
                except TimeoutError:
                    print(f'[並發] ⚠️ as_completed {_AS_COMPLETED_TIMEOUT}s 超時，補救已完成結果')
                    for _fut, _name in _futs.items():
                        if _name not in _results:
                            if _fut.done():
                                try:
                                    _results[_name] = _fut.result(timeout=1)
                                    print(f'[並發] ✅ {_name} 補救成功')
                                except Exception as _fe2:
                                    _results[_name] = None
                            else:
                                _results[_name] = None
                                print(f'[並發] ⏰ {_name} 確認超時')
            finally:
                # [BUG FIX] 關鍵：立即取消未開始任務，不等待執行中的 thread
                try:
                    _exc.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    _exc.shutdown(wait=False)  # Python < 3.9
            # 補齊所有未收到結果的 job
            for _name in _jobs:
                if _name not in _results:
                    _results[_name] = None
                    print(f'[並發] ⏰ {_name} 超時')
            
            # ── 解包結果 ────────────────────────────────────────
            intl_raw  = _results.get('intl') or {}
            tw_raw    = _results.get('tw') or {}
            tech_raw  = _results.get('tech') or {}

            # [Phase 2] 重量區塊：cl_data 已存在則沿用舊值，否則 None
            _prev_cl  = st.session_state.get('cl_data') or {}
            if _load_heavy:
                inst_res  = _results.get('inst') or (None, None)
                inst, inst_date = inst_res if isinstance(inst_res, tuple) else (inst_res, None)
                # 如果 inst 是空的，用 FinMind TaiwanStockTotalInstitutionalInvestors 補救
                if not inst:
                    print('[並發] inst 為空，用 FinMind 補救...')
                    try:
                        _fm_t = _get_fm_token()
                        _start_i = (datetime.date.today()-datetime.timedelta(days=5)).strftime('%Y-%m-%d')
                        _ri = _bps().get('https://api.finmindtrade.com/api/v4/data',
                            params={'dataset':'TaiwanStockTotalInstitutionalInvestors',
                                    'start_date':_start_i,'token':_fm_t},
                            headers={'Authorization':f'Bearer {_fm_t}'}, timeout=15)
                        _ji = _ri.json()
                        print(f'[FinMind-Inst] status={_ji.get("status")} rows={len(_ji.get("data",[]))}')
                        if _ji.get('status')==200 and _ji.get('data'):
                            _df_i = pd.DataFrame(_ji['data'])
                            _ld_i = _df_i['date'].max()
                            _df_i = _df_i[_df_i['date']==_ld_i]
                            _df_i['buy']  = pd.to_numeric(_df_i.get('buy',  0), errors='coerce').fillna(0)
                            _df_i['sell'] = pd.to_numeric(_df_i.get('sell', 0), errors='coerce').fillna(0)
                            _df_i['_net'] = ((_df_i['buy'] - _df_i['sell']) / 1e8).round(2)
                            inst = {}
                            for _nm, _net in zip(_df_i['name'].astype(str), _df_i['_net']):
                                if '外資' in _nm:
                                    inst['外資及陸資'] = {'net': _net}
                                elif '投信' in _nm:
                                    inst['投信'] = {'net': _net}
                                elif '自營' in _nm:
                                    inst.setdefault('_d', 0)
                                    inst['_d'] = round(inst['_d'] + _net, 2)
                            if '_d' in inst:
                                inst['自營商'] = {'net': inst.pop('_d')}
                            inst_date = _ld_i
                            print(f'[FinMind-Inst] ✅ {inst}')
                    except Exception as _ei:
                        print(f'[FinMind-Inst] ❌ {_ei}')
                margin       = _results.get('margin')
                df_adl_raw   = _results.get('adl')
                if df_adl_raw is None:
                    st.session_state['adl_debug_msg'] = '來源均無回應（yfinance + TWSE MI_INDEX），詳見 Colab [ADL] 輸出'
                else:
                    st.session_state.pop('adl_debug_msg', None)
                # 先行指標：強制 reload + UI 進度顯示
                df_li_a   = None
                _li_tok   = _get_fm_token() or FINMIND_TOKEN or os.environ.get('FINMIND_TOKEN','')
                _li_ph    = st.empty()
                _li_lines = []
                def _li_log(msg):
                    print(f'[先行指標] {msg}', flush=True)
                    _li_lines.append(msg)
                    _li_ph.info('📡 先行指標載入中…\n' + '\n'.join(_li_lines[-5:]))
                try:
                    import importlib
                    import leading_indicators as _li_mod
                    importlib.reload(_li_mod)
                    _li_log(f'v={getattr(_li_mod,"LI_VERSION","?")} token={bool(_li_tok)}')
                    df_li_a = _li_mod.build_leading_fast(days=14, token=_li_tok)
                    if df_li_a is not None and not df_li_a.empty:
                        _li_log(f'✅ 成功 {len(df_li_a)} 筆')
                    else:
                        _li_log('⚠️ 回傳空資料，請查 Colab 輸出')
                except Exception as _li_err:
                    import traceback as _tb
                    _li_log(f'❌ {type(_li_err).__name__}: {_li_err}')
                    print(_tb.format_exc())
                finally:
                    _li_ph.empty()
            else:
                # 冷啟動跳過重資料：沿用舊 cl_data 或 None
                inst       = _prev_cl.get('inst') or {}
                inst_date  = _prev_cl.get('inst_date')
                margin     = _prev_cl.get('margin')
                df_adl_raw = _prev_cl.get('adl')
                df_li_a    = st.session_state.get('li_latest')
                print('[Phase 2] 冷啟動跳過 inst/margin/adl/li（按鈕載入）')

            # ── 儲存主要數據 ─────────────────────────────────────
            st.session_state['cl_data'] = dict(
                intl=intl_raw, tw=tw_raw, tech=tech_raw,
                inst=inst, inst_date=inst_date, margin=margin,
                adl=df_adl_raw)
            st.session_state['cl_ts'] = _tw_now_str()
            st.session_state['_is_refreshing'] = False  # 資料就位，解除刷新鎖
            # 快取最後一次有效的法人/融資資料，供 API 失敗時 fallback 使用
            if inst:
                st.session_state['_last_inst'] = inst
                st.session_state['_last_inst_date'] = inst_date
            if margin:
                st.session_state['_last_margin'] = margin

            # [BUG FIX] 寬鬆條件：有任何 DataFrame（即使全 '-'）都存入 session_state
            # 原本 not df_li_a.empty 在 rows 有骨架但全 None 時仍為 True，但若某個版本回 None 或空 DF 則捨棄
            if df_li_a is not None and not df_li_a.empty:
                st.session_state['li_latest'] = df_li_a
                print(f'[先行指標] ✅ {len(df_li_a)} 筆 (有效欄={df_li_a.notna().any().sum()})')
            else:
                # 保留舊資料（若有），避免畫面空白
                if 'li_latest' not in st.session_state:
                    st.session_state.pop('li_latest', None)
                print(f'[先行指標] ⚠️ 回傳{"空" if df_li_a is not None else "None"} — 保留舊快取')

            print(f'[並發] 🎉 全部完成 共 {_t_spd.time()-_t_start:.1f}s')
            try:
                _fetch_ph.empty()
            except Exception:
                pass
            try:
                with open('/tmp/_adl_log.txt','r',encoding='utf-8') as _af:
                    print('[ADL詳細]\n' + _af.read())
                import os as _rmf
                _rmf.remove('/tmp/_adl_log.txt')
            except Exception:
                pass

            # ── do_refresh 完成後自動估算旌旗指數（不等掃描）──────
            _jq_ratio_src = None
            if df_adl_raw is not None and not df_adl_raw.empty and 'ad_ratio' in df_adl_raw.columns:
                _jq_ratio_src = 'ADL'
                _jq_ratio = float(df_adl_raw['ad_ratio'].tail(5).mean())
            else:
                # 備援：用大盤漲跌估算（正日=60%上漲，負日=40%）
                _tw_d = st.session_state.get('cl_data',{}).get('tw',{})
                _twii_d = _tw_d.get('台股加權指數')
                if _twii_d is not None and not _twii_d.empty:
                    _cc_d = 'close' if 'close' in _twii_d.columns else 'Close'
                    if _cc_d in _twii_d.columns:
                        _ret5 = _twii_d[_cc_d].pct_change().tail(5)
                        _up_days = (_ret5 > 0).sum()
                        _jq_ratio = 40 + _up_days * 5  # 全漲=65%, 全跌=40%
                        _jq_ratio_src = '大盤估算'
                else:
                    _jq_ratio_src = None  # 無資料時不設定，不顯示錯誤數值
            if _jq_ratio_src and _jq_ratio_src != '預設值':
                _jq_ratio = float(_jq_ratio)
                _jq_pos  = '80~100%' if _jq_ratio>=60 else ('50~70%' if _jq_ratio>=40 else ('20~40%' if _jq_ratio>=20 else '0~20%'))
                _jq_reg  = 'bull' if _jq_ratio>=60 else ('neutral' if _jq_ratio>=40 else 'bear')
                _jq_col  = '#3fb950' if _jq_ratio>=60 else ('#d29922' if _jq_ratio>=40 else '#f85149')
                _jq_lbl  = '🟢 多頭積極' if _jq_ratio>=60 else ('🟡 中性均衡' if _jq_ratio>=40 else '🔴 保守防禦')
                _jq_src_note = f'（來源：{_jq_ratio_src}）'
                st.session_state['jingqi_info'] = {
                    'avg':_jq_ratio,'pos':_jq_pos,'regime':_jq_reg,
                    'color':_jq_col,'label':_jq_lbl,'total':0,
                    'source':_jq_ratio_src,
                    'pct20':_jq_ratio,'pct60':_jq_ratio*0.9,
                    'pct120':_jq_ratio*0.8,'pct240':_jq_ratio*0.7
                }

            # ── M1B-M2 + 乖離率 並發計算 ──────────────────────
            def _job_m1b():
                import requests as _rq_m1
                import pandas as _pd_m1
                _fm_tok_m1 = _get_fm_token()
                _start_m1 = (datetime.date.today()-datetime.timedelta(days=420)).strftime('%Y-%m-%d')

                # ── [Step 4] 路徑 0：tw_macro.fetch_cbc_m1b_m2 統一委派 ──
                # 內含 Tier 1 (CBC ms1.json) + Tier 2 (CPX EF15M01) + Tier 3 (^TWII proxy)
                # 全部走 NAS proxy,取代原本散落的 CPX EF01M01/EF17M01 + ms1.json 直連
                try:
                    from tw_macro import fetch_cbc_m1b_m2 as _tw_cbc
                    _cbc_snap = _tw_cbc()
                    if _cbc_snap.get('m1b_yoy') is not None:
                        _src_label = ('TWII-proxy' if _cbc_snap.get('is_proxy_tier')
                                      else f'CBC-tier{_cbc_snap.get("tier_used")}')
                        print(f'[M1B/tw_macro] ✅ {_src_label} '
                              f'M1B={_cbc_snap["m1b_yoy"]:.2f}% M2={_cbc_snap["m2_yoy"]:.2f}%')
                        return {'m1b_yoy': _cbc_snap['m1b_yoy'],
                                'm2_yoy':  _cbc_snap['m2_yoy'],
                                'source':  _src_label}
                except Exception as _tw_e:
                    print(f'[M1B/tw_macro] ❌ {_tw_e}')

                # ── 路徑 2：FRED（台灣 M1B/M2，fetch_url + FRED_API_KEY）──
                try:
                    import os as _os_m1f
                    from proxy_helper import fetch_url as _fu_m1
                    _fred_key_m1 = (_os_m1f.environ.get('FRED_API_KEY') or
                                    (st.secrets.get('FRED_API_KEY') if hasattr(st, 'secrets') else None) or '')
                    _fp_m1 = {'api_key': _fred_key_m1} if _fred_key_m1 else {}
                    _fred_base_p = {'file_type': 'json', 'sort_order': 'asc', 'limit': 36, **_fp_m1}
                    _fred_m1b_r = _fu_m1('https://api.stlouisfed.org/fred/series/observations',
                                         params={'series_id': 'MYAGM1TWA189S', **_fred_base_p}, timeout=12, attempts=1)
                    _fred_m2_r  = _fu_m1('https://api.stlouisfed.org/fred/series/observations',
                                         params={'series_id': 'MYAGM2TWA189S', **_fred_base_p}, timeout=12, attempts=1)
                    if _fred_m1b_r is None or _fred_m2_r is None:
                        raise ValueError('FRED fetch_url 回傳 None')
                    print('[M1B/FRED] M1 OK M2 OK')
                    if True:  # 保留縮排結構
                        _obs_m1 = [o for o in _fred_m1b_r.json().get('observations', [])
                                   if o.get('value', '.') != '.']
                        _obs_m2 = [o for o in _fred_m2_r.json().get('observations', [])
                                   if o.get('value', '.') != '.']
                        _df_fred_m1 = _pd_m1.DataFrame(_obs_m1)
                        _df_fred_m2 = _pd_m1.DataFrame(_obs_m2)
                        for _dfm in [_df_fred_m1, _df_fred_m2]:
                            _dfm['value'] = _pd_m1.to_numeric(_dfm['value'], errors='coerce')
                        _df_fred_m1 = _df_fred_m1.dropna(subset=['value'])
                        _df_fred_m2 = _df_fred_m2.dropna(subset=['value'])
                        print(f'[M1B/FRED] M1 rows={len(_df_fred_m1)} M2 rows={len(_df_fred_m2)} last={_df_fred_m1["date"].iloc[-1] if len(_df_fred_m1) else "?"}')
                        if len(_df_fred_m1) >= 13 and len(_df_fred_m2) >= 13:
                            _m1b_yoy_f = round((_df_fred_m1['value'].iloc[-1]/_df_fred_m1['value'].iloc[-13]-1)*100, 2)
                            _m2_yoy_f  = round((_df_fred_m2['value'].iloc[-1]/_df_fred_m2['value'].iloc[-13]-1)*100, 2)
                            print(f'[M1B/FRED] ✅ M1B={_m1b_yoy_f:.2f}% M2={_m2_yoy_f:.2f}%')
                            return {'m1b_yoy': _m1b_yoy_f, 'm2_yoy': _m2_yoy_f, 'source': 'FRED'}
                except Exception as _fred_e:
                    print(f'[M1B/FRED] ❌ {_fred_e}')

                # ── 路徑 2b：IMF DataMapper API（FRED 備援，全球可達）──
                try:
                    # MABMM301 = M2 年增率%, MANMM101 = M1 年增率% (IMF IFS)
                    _imf_m1_r = _rq_m1.get(
                        'https://www.imf.org/external/datamapper/api/v1/MANMM101/TW',
                        headers={'User-Agent': 'Mozilla/5.0'}, timeout=15, verify=False)
                    _imf_m2_r = _rq_m1.get(
                        'https://www.imf.org/external/datamapper/api/v1/MABMM301/TW',
                        headers={'User-Agent': 'Mozilla/5.0'}, timeout=15, verify=False)
                    print(f'[M1B/IMF] M1={_imf_m1_r.status_code} M2={_imf_m2_r.status_code}')
                    if _imf_m1_r.status_code == 200 and _imf_m2_r.status_code == 200:
                        _imf_m1_j = _imf_m1_r.json()
                        _imf_m2_j = _imf_m2_r.json()
                        _imf_m1_vals = _imf_m1_j.get('values', {}).get('MANMM101', {}).get('TW', {})
                        _imf_m2_vals = _imf_m2_j.get('values', {}).get('MABMM301', {}).get('TW', {})
                        print(f'[M1B/IMF] M1 years={len(_imf_m1_vals)} M2 years={len(_imf_m2_vals)}')
                        if _imf_m1_vals and _imf_m2_vals:
                            # IMF 返回的已是 YoY 年增率%，取最新一年
                            _imf_m1_sorted = sorted([(k, float(v)) for k, v in _imf_m1_vals.items() if v is not None], key=lambda x: x[0])
                            _imf_m2_sorted = sorted([(k, float(v)) for k, v in _imf_m2_vals.items() if v is not None], key=lambda x: x[0])
                            if _imf_m1_sorted and _imf_m2_sorted:
                                _m1b_yoy_imf = round(_imf_m1_sorted[-1][1], 2)
                                _m2_yoy_imf  = round(_imf_m2_sorted[-1][1], 2)
                                print(f'[M1B/IMF] ✅ year={_imf_m1_sorted[-1][0]} M1B={_m1b_yoy_imf:.2f}% M2={_m2_yoy_imf:.2f}%')
                                return {'m1b_yoy': _m1b_yoy_imf, 'm2_yoy': _m2_yoy_imf, 'source': f'IMF({_imf_m1_sorted[-1][0]})'}
                except Exception as _imf_e:
                    print(f'[M1B/IMF] ❌ {_imf_e}')

                # [Step 4] 舊路徑 3 (CBC ms1.json 直連) 已由 tw_macro Tier 1 取代

                # 若所有真實來源都失敗，回傳 None（顯示「待更新」比顯示錯誤數字好）
                print('[M1B] 所有路徑失敗，回傳 None')
                return None

            def _job_bias():
                try:
                    # tw_raw 只有 90 天，MA240 需要另外抓 2 年資料
                    _twii = tw_raw.get('台股加權指數')
                    _cc_b = 'Close' if (_twii is not None and 'Close' in getattr(_twii,'columns',[])) else 'close'
                    _n_existing = len(_twii) if _twii is not None and not _twii.empty else 0
                    if _n_existing < 240:
                        # 重新抓 2 年完整資料，確保 MA240 正確
                        try:
                            import yfinance as _yf_bias
                            import pandas as _pd_bias
                            _twii_2y = _yf_bias.download('^TWII', period='2y',
                                                          progress=False, auto_adjust=True)
                            # yfinance 1.x 可能返回 MultiIndex columns，需展平
                            if _twii_2y is not None and isinstance(_twii_2y.columns, _pd_bias.MultiIndex):
                                try:
                                    _twii_2y.columns = _twii_2y.columns.get_level_values(0)
                                    print(f'[Bias] MultiIndex → 展平欄位: {list(_twii_2y.columns)}')
                                except Exception as _mi_e:
                                    print(f'[Bias] MultiIndex 展平失敗: {_mi_e}')
                            if _twii_2y is not None and len(_twii_2y) >= 240:
                                _twii = _twii_2y
                                _cc_b = 'Close'
                                print(f'[Bias] yfinance ^TWII 2y 抓到 {len(_twii_2y)} 天，欄位={list(_twii_2y.columns)[:4]}')
                            else:
                                print(f'[Bias] yfinance 2y 資料不足 ({len(_twii_2y) if _twii_2y is not None else 0} 天)，使用現有 {_n_existing} 天')
                        except Exception as _yf_b_e:
                            print(f'[Bias] yfinance 2y 失敗: {_yf_b_e}')
                    if _twii is None or _twii.empty:
                        return None
                    # 寬鬆欄位查找：Close / close / Adj Close
                    if _cc_b not in _twii.columns:
                        _cc_b = next((c for c in _twii.columns if str(c).lower() in ('close','adj close','adjclose')), None)
                        if _cc_b is None:
                            print(f'[Bias] 找不到 Close 欄，現有欄位={list(_twii.columns)[:6]}')
                            return None
                    _cs = _twii[_cc_b].dropna()
                    _n  = len(_cs)
                    _lp = float(_cs.iloc[-1])
                    _ma20  = float(_cs.tail(min(20,_n)).mean())
                    _ma60  = float(_cs.tail(min(60,_n)).mean())
                    _ma120 = float(_cs.tail(min(120,_n)).mean())
                    _ma240 = float(_cs.tail(min(240,_n)).mean())
                    print(f'[Bias] price={_lp:.0f} MA240={_ma240:.0f} bias240={((_lp-_ma240)/_ma240*100):.1f}% (n={_n})')
                    return {
                        'bias_20':  round((_lp-_ma20) /_ma20 *100, 1) if _ma20  else 0,
                        'bias_60':  round((_lp-_ma60) /_ma60 *100, 1) if _ma60  else 0,
                        'bias_240': round((_lp-_ma240)/_ma240*100, 1) if _ma240 else 0,
                        'price':_lp,'ma20':_ma20,'ma60':_ma60,'ma120':_ma120,'ma240':_ma240,
                        'data_days':_n,'is_estimated':_n<240
                    }
                except Exception:
                    return None

            def _job_macro():
                """總經拼圖 v5.2：VIX/CPI/PMI/NDC/Export 並行抓取（NDC 改抓 StockFeel+MacroMicro 雙源）"""
                import requests as _rq_mc
                # L2: 使用頂層已匯入的 ThreadPoolExecutor / as_completed
                _TPE, _asc_mc = ThreadPoolExecutor, as_completed
                # 兼容 Python 3.8-3.10：concurrent.futures.TimeoutError 與 builtins.TimeoutError 不同類別
                from concurrent.futures import TimeoutError as _ConcFutTimeout

                def _mk_s():
                    """NAS proxy Session — 直接套用 proxy_helper.get_proxies()"""
                    from requests.adapters import HTTPAdapter as _HA
                    from urllib3.util.retry import Retry as _Rt
                    try:
                        from proxy_helper import get_proxies as _gp
                        _px = _gp()
                    except Exception:
                        _px = None
                    _s2 = _rq_mc.Session()
                    _adp = _HA(max_retries=_Rt(total=2, backoff_factor=1.0,
                               status_forcelist=[429, 503, 504], raise_on_status=False))
                    _s2.mount('https://', _adp)
                    _s2.mount('http://', _adp)
                    if _px:
                        _s2.proxies.update(_px)
                    _s2.verify = False
                    return _s2

                def _mk_s_tw():
                    """台灣 IP proxy Session（同 _mk_s，保留名稱供既有呼叫相容）"""
                    return _mk_s()

                # ── 1. VIX ──────────────────────────────────────────────────────────
                def _fetch_vix():
                    try:
                        import yfinance as _yf_vix
                        _df_v = _yf_vix.download('^VIX', period='3mo', interval='1d',
                                                  progress=False, auto_adjust=True)
                        if _df_v is None or _df_v.empty:
                            return {'_err_vix': 'yfinance empty'}
                        if hasattr(_df_v.columns, 'nlevels') and _df_v.columns.nlevels > 1:
                            _df_v.columns = _df_v.columns.get_level_values(0)
                        _df_v = _df_v.dropna(subset=['Close'])
                        _vv = [round(float(v), 1) for v in _df_v['Close']]
                        _vd = [str(d)[:10] for d in _df_v.index]
                        if len(_vv) < 3:
                            return {'_err_vix': 'not enough data'}
                        _s20 = _vv[-20:] if len(_vv) >= 20 else _vv
                        print(f'[Macro/VIX] ✅ current={_vv[-1]} date={_vd[-1]}')
                        return {'vix': {'current': _vv[-1], 'ma20': round(sum(_s20)/len(_s20), 1),
                                        'dates': _vd[-60:], 'values': _vv[-60:], 'date': _vd[-1]}}
                    except Exception as _e_vix:
                        print(f'[Macro/VIX] ❌ {_e_vix}')
                        return {'_err_vix': str(_e_vix)[:80]}

                # ── 2. CPI ──────────────────────────────────────────────────────────
                def _fetch_cpi():
                    import datetime as _dt_cpi
                    _s = _mk_s()
                    _cpi_errs = []
                    # ── 方案1: FRED CSV（fetch_url + FRED_API_KEY）──────────────
                    try:
                        import os as _os_cpi_f
                        from proxy_helper import fetch_url as _fu_cpi
                        _fred_key_cpi = (_os_cpi_f.environ.get('FRED_API_KEY') or
                                         (st.secrets.get('FRED_API_KEY') if hasattr(st, 'secrets') else None) or '')
                        _cpi_start = (_dt_cpi.datetime.now() - _dt_cpi.timedelta(days=365*3)).strftime('%Y-%m-%d')
                        _cpi_end   = _dt_cpi.datetime.now().strftime('%Y-%m-%d')
                        _cpi_p = {'series_id': 'CPIAUCSL', 'file_type': 'json',
                                  'sort_order': 'asc', 'limit': 36,
                                  'observation_start': _cpi_start,
                                  'observation_end': _cpi_end}
                        if _fred_key_cpi:
                            _cpi_p['api_key'] = _fred_key_cpi
                        _rc1 = _fu_cpi('https://api.stlouisfed.org/fred/series/observations',
                                       params=_cpi_p, timeout=12, attempts=1)
                        print(f'[Macro/CPI/FRED] response={"OK" if _rc1 else "None"}')
                        if _rc1 is not None:
                            _obs_c = [o for o in _rc1.json().get('observations', [])
                                      if o.get('value', '.') != '.']
                            if len(_obs_c) >= 13:
                                _vals_c = [float(o['value']) for o in _obs_c]
                                _yoy = round((_vals_c[-1] / _vals_c[-13] - 1) * 100, 2)
                                _date = _obs_c[-1]['date']
                                print(f'[Macro/CPI/FRED] ✅ YoY={_yoy:.2f}% date={_date}')
                                return {'us_core_cpi': {'yoy': _yoy, 'date': _date, 'source': 'FRED'}}
                    except Exception as _e:
                        _cpi_errs.append(f'FRED:{type(_e).__name__}')
                        print(f'[Macro/CPI/FRED] ❌ {_e}')
                    # ── 方案2: BLS API（CUSR0000SA0L1E 核心CPI）──────────────────────
                    try:
                        _rc = _s.post('https://api.bls.gov/publicAPI/v2/timeseries/data/',
                                      json={'seriesid': ['CPIAUCSL'],
                                            'startyear': str(_dt_cpi.date.today().year - 2),
                                            'endyear':   str(_dt_cpi.date.today().year)},
                                      headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'},
                                      timeout=15, verify=False)
                        print(f'[Macro/CPI/BLS] status={_rc.status_code}')
                        if _rc.status_code == 200:
                            _j = _rc.json()
                            _obs = (_j.get('Results') or {}).get('series', [{}])[0].get('data', [])
                            if len(_obs) >= 13:
                                _s2 = sorted([o for o in _obs if o.get('period', 'M13') != 'M13'],
                                             key=lambda x: (x['year'], x['period']))
                                _valid = []
                                for _o in _s2:
                                    try:
                                        _v = float(str(_o.get('value', '')).replace(',', ''))
                                        if _v > 0:
                                            _valid.append((_o, _v))
                                    except Exception:
                                        pass
                                if len(_valid) >= 13:
                                    _ents = [o for o, _ in _valid]
                                    _vals = [v for _, v in _valid]
                                    _yoy = round((_vals[-1] / _vals[-13] - 1) * 100, 2)
                                    _last = _ents[-1]
                                    _date = f"{_last['year']}-{int(_last['period'][1:]):02d}-01"
                                    print(f'[Macro/CPI/BLS] ✅ YoY={_yoy:.2f}% date={_date}')
                                    return {'us_core_cpi': {'yoy': _yoy, 'date': _date, 'source': 'BLS'}}
                    except Exception as _e:
                        _cpi_errs.append(f'BLS:{type(_e).__name__}')
                        print(f'[Macro/CPI/BLS] ❌ {_e}')
                    return {'_err_cpi': ' | '.join(_cpi_errs) or 'all failed'}

                # ── 3. 台灣 PMI（CIER 中華經濟研究院）────────────────────────────
                #   v3：Stock 端定位是台股視角，應抓「台灣製造業 PMI」（CIER 中華
                #   經濟研究院每月第一個工作日公布），而非美國 ISM PMI。
                #   舊版誤抓美國 ISM 導致與在地景氣脫節，且 ISM 自 2016-08 後 FRED
                #   斷供，三段爬蟲備援也常掛。改呼叫 macro_core.fetch_tw_pmi()
                #   共用函式（4 段備援：MacroMicro → CIER → StockFeel → 鉅亨）。
                #   注意：session_state key 仍為 'ism_pmi' 以維持向後相容（14 處讀取
                #   點不必動），但內容是台灣 PMI；UI 顯示為「🇹🇼 台灣製造業 PMI」。
                def _fetch_pmi():
                    """v3 薄殼：呼叫 macro_core.fetch_tw_pmi()，回傳台灣 CIER PMI。"""
                    from macro_core import fetch_tw_pmi as _ftp
                    _result = _ftp()
                    if _result.get('value') is not None:
                        return {'ism_pmi': _result}
                    # 失敗：只回傳 _err_pmi（不再帶 value:None junk 進 macro_info）
                    return {'_err_pmi': _result.get('_err_pmi', '4 段備援全失敗')}

                # ── 4. NDC 景氣對策信號 v2 — StockFeel + MacroMicro 雙源（v10.57.0 復活）
                #    舊源全廢（FinMind/NDC JSON/CKAN/行動版 HTML 都失效），改抓第三方。
                def _fetch_ndc():
                    import re as _re_ndc
                    from proxy_helper import fetch_url as _fu_ndc
                    from bs4 import BeautifulSoup as _BS_ndc

                    # 方案 A: StockFeel 股感（每月更新文章，HTML 含「綜合分數 39」）
                    try:
                        _sf_url = ('https://www.stockfeel.com.tw/'
                                   '%E6%99%AF%E6%B0%A3%E5%B0%8D%E7%AD%96%E4%BF%A1%E8%99%9F-'
                                   '%E6%99%AF%E6%B0%A3%E6%8C%87%E6%A8%99-%E7%B7%A8%E5%88%B6-'
                                   '%E5%9C%8B%E7%99%BC%E6%9C%83/')
                        _sf_r = _fu_ndc(_sf_url, timeout=12, attempts=1)
                        if _sf_r is not None:
                            _sf_r.encoding = 'utf-8'
                            _txt_sf = _BS_ndc(_sf_r.text, 'html.parser').get_text(' ', strip=True)
                            # 找最近一筆「YYYY年M月.*?綜合(?:判斷)?分數.*?N分」
                            _m_sf = _re_ndc.search(
                                r'(20\d{2})\s*年\s*(\d{1,2})\s*月[^。]{0,80}?綜合(?:判斷)?分數[^\d]{0,15}(\d{1,2})\s*分',
                                _txt_sf)
                            if _m_sf:
                                _yr_sf, _mo_sf, _sc_sf = _m_sf.group(1), _m_sf.group(2), int(_m_sf.group(3))
                                if 9 <= _sc_sf <= 45:
                                    _date_sf = f'{_yr_sf}-{int(_mo_sf):02d}-01'
                                    print(f'[NDC/StockFeel] ✅ score={_sc_sf} date={_date_sf}')
                                    return {'ndc_signal': {'score': _sc_sf, 'signal': None,
                                                           'date': _date_sf, 'source': 'StockFeel'}}
                            print('[NDC/StockFeel] ⚠️ 未匹配「YYYY年M月...綜合分數N分」')
                    except Exception as _e_sf:
                        print(f'[NDC/StockFeel] ❌ {type(_e_sf).__name__}: {_e_sf}')

                    # 方案 B: MacroMicro 財經 M 平方（UGC Charts 公開頁面）
                    try:
                        _mm_url = 'https://www.macromicro.me/collections/10/tw-monitoring-indicators-relative'
                        _mm_r = _fu_ndc(_mm_url, timeout=12, attempts=1)
                        if _mm_r is not None:
                            _mm_r.encoding = 'utf-8'
                            _txt_mm = _BS_ndc(_mm_r.text, 'html.parser').get_text(' ', strip=True)
                            _m_mm = _re_ndc.search(
                                r'景氣對策信號[^。]{0,200}?(\d{1,2})\s*分',
                                _txt_mm)
                            if _m_mm:
                                _sc_mm = int(_m_mm.group(1))
                                if 9 <= _sc_mm <= 45:
                                    print(f'[NDC/MacroMicro] ✅ score={_sc_mm}')
                                    return {'ndc_signal': {'score': _sc_mm, 'signal': None,
                                                           'date': '', 'source': 'MacroMicro'}}
                            print('[NDC/MacroMicro] ⚠️ 未匹配「景氣對策信號...N分」')
                    except Exception as _e_mm:
                        print(f'[NDC/MacroMicro] ❌ {type(_e_mm).__name__}: {_e_mm}')

                    print('[NDC] ⚠️ 雙源皆失敗，回 None')
                    return None

                # ── 5. 台灣出口 YoY ─────────────────────────────────────────
                def _fetch_export():
                    import pandas as _pd7
                    import io as _io_ex
                    import os as _os_ex
                    import datetime as _dt_ex
                    _s_ex = _mk_s()
                    _s_ex.verify = False
                    _s_ex.headers.update({'User-Agent': 'Mozilla/5.0',
                                          'Accept': 'application/json'})

                    # 方案FM: FinMind TaiwanEconomicIndicator 出口相關指標
                    try:
                        _fm_tok_ex = (_os_ex.environ.get('FINMIND_TOKEN') or
                                      (st.secrets.get('FINMIND_TOKEN') if hasattr(st, 'secrets') else None))
                        if _fm_tok_ex:
                            _ex_start_fm = (_dt_ex.date.today() - _dt_ex.timedelta(days=365*2)).strftime('%Y-%m-%d')
                            _fm_ex_r = _s_ex.get(
                                'https://api.finmindtrade.com/api/v4/data',
                                params={'dataset': 'TaiwanEconomicIndicator',
                                        'start_date': _ex_start_fm, 'token': _fm_tok_ex},
                                timeout=10)
                            if _fm_ex_r.status_code == 200:
                                _fm_ex_data = _fm_ex_r.json().get('data', [])
                                # 尋找出口相關指標（外銷訂單 or 出口）
                                for _kw_ex in ('出口', '外銷', 'export', 'Export'):
                                    _ex_rows = [r for r in _fm_ex_data
                                                if _kw_ex in str(r.get('indicator', ''))]
                                    if _ex_rows:
                                        _ex_rows.sort(key=lambda r: r.get('date', ''))
                                        # 找同類指標最新 13 筆算 YoY
                                        _ind_name = _ex_rows[-1].get('indicator')
                                        _same = [r for r in _ex_rows if r.get('indicator') == _ind_name]
                                        if len(_same) >= 13:
                                            _cur_ex = float(_same[-1].get('value', 0) or 0)
                                            _prev_ex = float(_same[-13].get('value', 1) or 1)
                                            if _prev_ex != 0:
                                                _yoy_ex = round((_cur_ex - _prev_ex) / abs(_prev_ex) * 100, 2)
                                                _date_ex = str(_same[-1].get('date', ''))[:7]
                                                print(f'[Export/FinMind] ✅ YoY={_yoy_ex:.2f}% date={_date_ex} ind={_ind_name}')
                                                return {'tw_export': {'yoy': _yoy_ex, 'date': _date_ex,
                                                                      'source': f'FinMind/{_ind_name}'}}
                                        break
                    except Exception as _e_fm_ex:
                        print(f'[Export/FinMind] ❌ {type(_e_fm_ex).__name__}: {_e_fm_ex}')

                    # 方案MOF: 財政部統計處 CSV — 透過 NAS proxy（台灣 IP 可直接存取）
                    try:
                        from proxy_helper import fetch_url as _fu_ex
                        _now_ex = _dt_ex.date.today()
                        _mof_found = False
                        # v10.61.0: 月份迴圈從 4 砍到 2（當月+上月），避免最壞 8 URL × ~12s = 100s
                        # 拖爆 as_completed 70s timeout；MOF 通常上月就有，找不到再讓使用者手動重抓
                        for _m_off in range(0, 2):
                            if _mof_found:
                                break
                            _chk = (_now_ex.replace(day=1) - _dt_ex.timedelta(days=_m_off * 30))
                            for _mof_url in [
                                f'https://service.mof.gov.tw/public/Data/statistic/trade/excel/{_chk.year}{_chk.month:02d}.csv',
                                f'https://service.mof.gov.tw/public/Data/statistic/trade/html/{_chk.year}{_chk.month:02d}.csv',
                            ]:
                                try:
                                    _r_mof = _fu_ex(_mof_url, timeout=10, attempts=1)
                                    if _r_mof is not None and len(_r_mof.content) > 500:
                                        _df_mof = _pd7.read_csv(
                                            _io_ex.StringIO(_r_mof.content.decode('utf-8-sig', errors='ignore')),
                                            header=None)
                                        _vals_mof = _pd7.to_numeric(_df_mof.iloc[:, 1], errors='coerce').dropna()
                                        if len(_vals_mof) >= 13:
                                            _yoy_mof = round((_vals_mof.iloc[-1] - _vals_mof.iloc[-13]) /
                                                             abs(_vals_mof.iloc[-13]) * 100, 2)
                                            print(f'[Export/MOF] ✅ YoY={_yoy_mof:.2f}% url={_mof_url[-25:]}')
                                            _mof_found = True
                                            return {'tw_export': {'yoy': _yoy_mof,
                                                                  'date': f'{_chk.year}-{_chk.month:02d}',
                                                                  'source': 'MOF-proxy'}}
                                except Exception:
                                    continue
                    except Exception as _e_mof:
                        print(f'[Export/MOF] ❌ {type(_e_mof).__name__}: {_e_mof}')

                    # 方案FRED: FRED CSV（fetch_url + FRED_API_KEY，timeout 8s）
                    try:
                        _ex_start = (_dt_ex.datetime.now() - _dt_ex.timedelta(days=365*5)).strftime('%Y-%m-%d')
                        _ex_end   = _dt_ex.datetime.now().strftime('%Y-%m-%d')
                        _fred_key_ex = (_os_ex.environ.get('FRED_API_KEY') or
                                        (st.secrets.get('FRED_API_KEY') if hasattr(st, 'secrets') else None) or '')
                        _fred_ex_p = {'id': 'VALEXPTWM052N', 'observation_start': _ex_start,
                                      'observation_end': _ex_end}
                        if _fred_key_ex:
                            _fred_ex_p['api_key'] = _fred_key_ex
                        _r_fred = _fu_ex('https://fred.stlouisfed.org/graph/fredgraph.csv',
                                         params=_fred_ex_p, timeout=8, attempts=1)
                        print(f'[Export/FRED] response={"OK" if _r_fred else "None"}')
                        if _r_fred is not None and _r_fred.text.strip():
                            _df_fred = _pd7.read_csv(
                                _io_ex.StringIO(_r_fred.text),
                                names=['date', 'value'], skiprows=1)
                            _df_fred['value'] = _pd7.to_numeric(_df_fred['value'], errors='coerce')
                            _df_fred = _df_fred.dropna(subset=['value'])
                            if len(_df_fred) >= 13:
                                _cur_f = float(_df_fred['value'].iloc[-1])
                                _prev_f = float(_df_fred['value'].iloc[-13])
                                if _prev_f and _prev_f != 0:
                                    _yoy_f = round((_cur_f - _prev_f) / abs(_prev_f) * 100, 2)
                                    _date_f = str(_df_fred['date'].iloc[-1])[:7]
                                    print(f'[Export/FRED] ✅ YoY={_yoy_f:.2f}% date={_date_f}')
                                    return {'tw_export': {'yoy': _yoy_f, 'date': _date_f, 'source': 'FRED'}}
                    except Exception as _e_fred:
                        print(f'[Export/FRED] ❌ {type(_e_fred).__name__}: {_e_fred}')

                    # 方案2: data.gov.tw CKAN — 財政部進出口統計（加 Accept header 防空 body）
                    try:
                        _pkg2 = _s_ex.get(
                            'https://data.gov.tw/api/3/action/package_search',
                            params={'q': '進出口貿易統計', 'fq': 'organization:mof', 'rows': 5},
                            headers={'Accept': 'application/json'},
                            timeout=5)
                        _pkg2_j = _pkg2.json()
                        _res_id2 = None
                        for _pk2 in ((_pkg2_j.get('result') or {}).get('results') or []):
                            for _rs2 in (_pk2.get('resources') or []):
                                if _rs2.get('format', '').upper() in ('CSV', 'TEXT'):
                                    _res_id2 = _rs2.get('url') or _rs2.get('download_url')
                                    break
                            if _res_id2:
                                break
                        if _res_id2:
                            _csv_ex = _s_ex.get(_res_id2, timeout=10)
                            _df_ex = _pd7.read_csv(
                                _io_ex.StringIO(_csv_ex.content.decode('utf-8-sig', errors='ignore')))
                            _val_k = next((c for c in _df_ex.columns
                                           if '出口' in c and '值' in c and '增' not in c), None)
                            _dt_k = next((c for c in _df_ex.columns
                                          if '年月' in c or '月份' in c or 'DATE' in c.upper()), None)
                            if _val_k and _dt_k and len(_df_ex) >= 13:
                                _df_ex = _df_ex.dropna(subset=[_val_k])
                                _cur = float(str(_df_ex[_val_k].iloc[-1]).replace(',', ''))
                                _prev = float(str(_df_ex[_val_k].iloc[-13]).replace(',', ''))
                                if _prev != 0:
                                    _yoy = round((_cur - _prev) / abs(_prev) * 100, 2)
                                    _dv = str(_df_ex[_dt_k].iloc[-1])[:7]
                                    print(f'[Export/gov-mof] ✅ YoY={_yoy:.2f}% date={_dv}')
                                    return {'tw_export': {'yoy': _yoy, 'date': _dv, 'source': 'MOF-CSV'}}
                        print(f'[Export/gov-mof] ❌ res_id={_res_id2}')
                    except Exception as _e_gov2:
                        print(f'[Export/gov-mof] ❌ {type(_e_gov2).__name__}: {_e_gov2}')

                    # 靜態備援：所有方案失敗時回傳最後已知穩定歷史數據
                    print('[Export/fallback] ⚠️ 所有方案失敗，使用靜態備援 2026-03')
                    return {'tw_export': {'yoy': 18.9, 'date': '2026-03-01', 'source': '靜態備援'}}

                # ── 並行執行（5 個獨立資料源同時跑，總時間 = max 而非 sum）──────
                # v10.61.0: 改手動 executor 管理，as_completed timeout 後 shutdown(wait=False)
                # 立刻逃離；避免 with-block 退出時 shutdown(wait=True) 卡在 stuck thread 上等
                # ~240s（fetch_url 三層重試 × 8 個 MOF URL）拖爆外層 _fut_macro.result(80s)。
                _r = {}
                _pool_mc = _TPE(max_workers=5)
                try:
                    _futs_mc = {
                        _pool_mc.submit(_fetch_vix):    'vix',
                        _pool_mc.submit(_fetch_cpi):    'cpi',
                        _pool_mc.submit(_fetch_pmi):    'pmi',
                        _pool_mc.submit(_fetch_ndc):    'ndc',
                        _pool_mc.submit(_fetch_export): 'export',
                    }
                    try:
                        for _fut_mc in _asc_mc(_futs_mc, timeout=70):
                            try:
                                _part = _fut_mc.result()
                                if _part:
                                    _r.update(_part)
                            except Exception as _e:
                                print(f'[Macro] ❌ {_futs_mc.get(_fut_mc, "?")}: {_e}')
                    except (TimeoutError, _ConcFutTimeout):
                        # 70s 到仍有 future 未完成：取消未完成者，保留已收到的 partial _r
                        _stuck = [_futs_mc[_f] for _f in _futs_mc if not _f.done()]
                        for _f_pending in _futs_mc:
                            if not _f_pending.done():
                                _f_pending.cancel()
                        print(f'[Macro] ⏰ as_completed 70s timeout，未完成={_stuck}，保留已收到 keys={list(_r.keys())}')
                finally:
                    # wait=False：不等 stuck thread 自然結束（thread 會 zombie 在背景跑完後自滅）
                    # 避免 with-block 預設 wait=True 把 _job_macro 卡到 240s
                    _pool_mc.shutdown(wait=False)

                # Failsafe：即使全失敗也回傳 partial 標記（不回 None），讓診斷頁能區分
                # 「沒抓」vs「抓過全失敗」；macro_info 至少有時間戳供 UX 判斷
                _r.setdefault('_loaded_at', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                if not any(k for k in _r if not k.startswith('_')):
                    _r['_all_failed'] = True
                print(f'[Macro] 完成 keys={[k for k in _r.keys() if not k.startswith("_")]}')
                return _r

            # v10.61.0: 改手動 executor 管理；原本 `with ThreadPoolExecutor as _exc2:`
            # 在 with 結束時呼叫 shutdown(wait=True)，會等所有 job 自然結束才放行，
            # 後面 `result(timeout=N)` 形同虛設。改 try/finally + shutdown(wait=False)，
            # 讓 result(timeout=N) 真的能在 N 秒後 cut over，stuck thread 變 zombie 自滅。
            _exc2 = ThreadPoolExecutor(max_workers=3)
            try:
                _fut_m1b   = _exc2.submit(_job_m1b)
                _fut_bias  = _exc2.submit(_job_bias)
                _fut_macro = _exc2.submit(_job_macro)
                try:
                    _m1b_res   = _fut_m1b.result(timeout=30)
                except Exception:
                    _m1b_res = None
                    print('[並發] ⏰ M1B 超時')
                try:
                    _bias_res  = _fut_bias.result(timeout=30)
                except Exception:
                    _bias_res = None
                    print('[並發] ⏰ bias 超時')
                try:
                    _macro_res = _fut_macro.result(timeout=80)
                except Exception:
                    _macro_res = None
                    print('[並發] ⏰ Macro 超時')
            finally:
                _exc2.shutdown(wait=False)
            if _m1b_res:
                st.session_state['m1b_m2_info'] = _m1b_res
            if _bias_res:
                st.session_state['bias_info']   = _bias_res
            if _macro_res:
                st.session_state['macro_info']  = _macro_res

            # ── 計算市場狀態（用已載入資料，不另外發請求）
            try:
                _foreign_net_loaded = 0  # 0 = 尚無資料（market_regime 會顯示「待更新」）
                for _k, _v in inst.items():
                    if '外資' in _k:
                        _net_v = _v.get('net')
                        if _net_v is not None:
                            _foreign_net_loaded = float(_net_v) * 1e8
                        break
                _twii_df_loaded = tw_raw.get('台股加權指數')
                print(f'[市場評估] 大盤DF shape={getattr(_twii_df_loaded,"shape",None)}, '
                      f'columns={list(getattr(_twii_df_loaded,"columns",[]))}, '
                      f'外資淨={_foreign_net_loaded/1e8:.1f}億')
                # 取得 M1B-M2 資金活水資料（宏爺評分維度）
                _m1b2  = st.session_state.get('m1b_m2_info') or {}
                _m1b2_gap  = (round(float(_m1b2['m1b_yoy']) - float(_m1b2['m2_yoy']), 2)
                               if _m1b2.get('m1b_yoy') is not None and _m1b2.get('m2_yoy') is not None
                               else None)
                _m1b2_prev = _m1b2.get('m1b_m2_gap_prev')  # 上月 gap（若有）
                _mkt_loaded = get_market_assessment(
                    df_index=_twii_df_loaded,
                    foreign_net=_foreign_net_loaded,
                    m1b_m2_gap=_m1b2_gap,
                    m1b_m2_prev=_m1b2_prev,
                )
                if _mkt_loaded:
                    if margin:
                        if margin > 3400:
                            _mkt_loaded['signals'].append('🔴 融資極度危險（>3400億）')
                        elif margin > 2500:
                            _mkt_loaded['signals'].append('⚠️ 融資警戒（>2500億）')
                        else:
                            _mkt_loaded['signals'].append(f'✅ 融資安全（{margin:.0f}億）')
                    st.session_state['mkt_info'] = _mkt_loaded
                    print(f'[市場評估] 成功：{_mkt_loaded.get("label")} 評分{_mkt_loaded.get("score")}')
                else:
                    # 備援：直接用 yfinance 重抓
                    print('[市場評估] df_index 失敗，用 yfinance 備援')
                    _mkt_fb = get_market_assessment(df_index=None, foreign_net=_foreign_net_loaded)
                    if _mkt_fb:
                        if margin:
                            if margin > 3400:
                                _mkt_fb['signals'].append('🔴 融資極度危險（>3400億）')
                            elif margin > 2500:
                                _mkt_fb['signals'].append('⚠️ 融資警戒（>2500億）')
                            else:
                                _mkt_fb['signals'].append(f'✅ 融資安全（{margin:.0f}億）')
                        st.session_state['mkt_info'] = _mkt_fb
                        print(f'[市場評估] 備援成功：{_mkt_fb.get("label")}')
            except Exception as _me:
                print(f'[市場評估 ERROR] {_me}')
                import traceback
                traceback.print_exc()
        # ── 全域資料登錄中心：掃描所有已載入 DF，寫入 data_registry ────
        try:
            import pandas as _pd_reg
            _reg_new: dict = {}

            def _reg_add(_rname: str, _rdf, category: str = '大盤', frequency: str = 'daily'):
                """提取最新時間戳後寫入 registry（不儲存 df 本體，僅保留元資料）。"""
                if not isinstance(_rdf, _pd_reg.DataFrame) or _rdf.empty:
                    return
                _d = _rdf
                if isinstance(_d.index, _pd_reg.DatetimeIndex):
                    _latest = _d.index.max()
                else:
                    _dcol = None
                    _date_fmt = None
                    for _c in _d.columns:
                        _cl = str(_c).lower()
                        if _cl == '_date':
                            _dcol = _c
                            _date_fmt = '%Y%m%d'
                            break
                        if _cl in ('date', 'datetime', 'timestamp', '日期', 'quarter', 'period'):
                            _dcol = _c
                            break
                    if _dcol:
                        try:
                            _s = _d[_dcol]
                            if _date_fmt:
                                _s = _pd_reg.to_datetime(_s, format=_date_fmt, errors='coerce')
                            else:
                                _s = _pd_reg.to_datetime(_s, errors='coerce')
                            _latest = _s.max()
                        except Exception:
                            _latest = None
                    else:
                        _latest = None
                try:
                    _ls = (_pd_reg.Timestamp(_latest).strftime('%Y-%m-%d')
                           if _latest is not None and not _pd_reg.isna(_latest) else 'N/A')
                except Exception:
                    _ls = 'N/A'
                _reg_new[_rname] = {
                    'last_updated': _ls, 'rows': len(_d),
                    'category': category, 'frequency': frequency,
                }

            def _reg_missing(_rname: str, category: str = '大盤', frequency: str = 'daily'):
                _reg_new[_rname] = {
                    'last_updated': 'N/A', 'rows': 0,
                    'category': category, 'frequency': frequency, 'missing': True,
                }

            # ── 大盤/總經：國際、台股、科技指數（日更新，固定清單確保永遠顯示 20 筆）──
            _cl_reg = st.session_state.get('cl_data', {})
            _intl_d = _cl_reg.get('intl') or {}
            for _rn in INTL_MAP:
                _rdf = _intl_d.get(_rn)
                if isinstance(_rdf, _pd_reg.DataFrame) and not _rdf.empty:
                    _reg_add(_rn, _rdf, category='大盤', frequency='daily')
                else:
                    _reg_missing(_rn, category='大盤', frequency='daily')
            _tw_d = _cl_reg.get('tw') or {}
            for _rn in TW_MAP:
                _rdf = _tw_d.get(_rn)
                if isinstance(_rdf, _pd_reg.DataFrame) and not _rdf.empty:
                    _reg_add(_rn, _rdf, category='大盤', frequency='daily')
                else:
                    _reg_missing(_rn, category='大盤', frequency='daily')
            _tech_d = _cl_reg.get('tech') or {}
            for _rn in TECH_MAP:
                _rdf = _tech_d.get(_rn)
                if isinstance(_rdf, _pd_reg.DataFrame) and not _rdf.empty:
                    _reg_add(_rn, _rdf, category='大盤', frequency='daily')
                else:
                    _reg_missing(_rn, category='大盤', frequency='daily')
            _adl_reg = _cl_reg.get('adl')
            if isinstance(_adl_reg, _pd_reg.DataFrame) and not _adl_reg.empty:
                _reg_add('ADL 市場廣度', _adl_reg, category='大盤', frequency='daily')
                # 拆分個別欄位：上漲家數 / 下跌家數 / AD累計值
                _adl_date_col = '_date' if '_date' in _adl_reg.columns else (
                    'date' if 'date' in _adl_reg.columns else None)
                for _acname, _acol in [('上漲股票家數', 'up'), ('下跌股票家數', 'down'),
                                        ('ADL 累計廣度值', 'adl')]:
                    if _acol in _adl_reg.columns:
                        _acsub = _adl_reg[[c for c in [_adl_date_col, _acol] if c]].copy()
                        _reg_add(_acname, _acsub, category='大盤', frequency='daily')
                    else:
                        _reg_missing(_acname, category='大盤', frequency='daily')
            else:
                _reg_missing('ADL 市場廣度', category='大盤', frequency='daily')
                for _acname0 in ('上漲股票家數', '下跌股票家數', 'ADL 累計廣度值'):
                    _reg_missing(_acname0, category='大盤', frequency='daily')

            # ── 三大法人 + 融資餘額（籌碼面，日更新）────────────────────
            _cl_inst_reg = _cl_reg.get('inst') or st.session_state.get('_last_inst') or {}
            _inst_date_reg = (_cl_reg.get('inst_date') or st.session_state.get('_last_inst_date'))
            try:
                _inst_ds = str(_inst_date_reg)[:10] if _inst_date_reg else 'N/A'
            except Exception:
                _inst_ds = 'N/A'
            for _ik, _iname in [('外資及陸資', '三大法人 外資買賣超'),
                                 ('投信',       '三大法人 投信買賣超'),
                                 ('自營商',     '三大法人 自營商買賣超')]:
                if _cl_inst_reg.get(_ik) is not None:
                    _reg_new[_iname] = {'last_updated': _inst_ds, 'rows': 1, 'category': '大盤', 'frequency': 'daily'}
                else:
                    _reg_missing(_iname, category='大盤', frequency='daily')
            _margin_reg2 = _cl_reg.get('margin') or st.session_state.get('_last_margin')
            if _margin_reg2:
                _reg_new['融資餘額（台股）'] = {'last_updated': _inst_ds, 'rows': 1, 'category': '大盤', 'frequency': 'daily'}
            else:
                _reg_missing('融資餘額（台股）', category='大盤', frequency='daily')

            # ── 旌旗指數 + 乖離率（日更新）──────────────────────────────
            # 用 cl_ts 作為代理日期（這些指標沒有獨立時間戳）
            _cl_ts_proxy = st.session_state.get('cl_ts', '')
            try:
                import re as _re_ts_reg
                _m_ts = _re_ts_reg.search(r'(\d{4}-\d{2}-\d{2})', _cl_ts_proxy)
                _proxy_date = _m_ts.group(1) if _m_ts else 'N/A'
            except Exception:
                _proxy_date = 'N/A'
            _jq_reg3 = st.session_state.get('jingqi_info') or {}
            if _jq_reg3.get('avg') is not None:
                _reg_new['旌旗指數（上漲佔比）'] = {'last_updated': _proxy_date, 'rows': 1, 'category': '大盤', 'frequency': 'daily'}
            else:
                _reg_missing('旌旗指數（上漲佔比）', category='大盤', frequency='daily')
            _bias_reg3 = st.session_state.get('bias_info') or {}
            for _bk, _bn in [('bias_240', 'TWII 年線乖離率'), ('bias_20', 'TWII 月線乖離率')]:
                if _bias_reg3.get(_bk) is not None:
                    _reg_new[_bn] = {'last_updated': _proxy_date, 'rows': 1, 'category': '大盤', 'frequency': 'daily'}
                else:
                    _reg_missing(_bn, category='大盤', frequency='daily')

            # ── M1B / M2 貨幣資金（月更新）──────────────────────────────
            _m1b_reg3 = st.session_state.get('m1b_m2_info') or {}
            for _mk, _mn in [('m1b_yoy', 'M1B 資金活水年增率'), ('m2_yoy', 'M2 廣義貨幣年增率')]:
                if _m1b_reg3.get(_mk) is not None:
                    _reg_new[_mn] = {'last_updated': _proxy_date, 'rows': 1, 'category': '大盤', 'frequency': 'monthly'}
                else:
                    _reg_missing(_mn, category='大盤', frequency='monthly')
            # M1B-M2 資金缺口（衍生指標）
            if _m1b_reg3.get('m1b_yoy') is not None and _m1b_reg3.get('m2_yoy') is not None:
                _reg_new['M1B-M2 資金缺口'] = {'last_updated': _proxy_date, 'rows': 1, 'category': '大盤', 'frequency': 'monthly'}
            else:
                _reg_missing('M1B-M2 資金缺口', category='大盤', frequency='monthly')

            # ── 宏觀指標（月/日更新）────────────────────────────────────
            _macro_reg3 = st.session_state.get('macro_info') or {}
            for _mkey, _mname, _mfreq in [
                ('vix',         'VIX 波動率指數',      'daily'),
                ('us_core_cpi', '美國核心CPI年增率',   'monthly'),
                ('ism_pmi',     '🇹🇼 台灣 PMI 製造業指數',  'monthly'),
                ('tw_export',   '台灣出口年增率',       'monthly'),
                ('ndc_signal',  '景氣先行指標（NDC）', 'monthly'),
            ]:
                _msub = _macro_reg3.get(_mkey)
                if _msub:
                    if isinstance(_msub, dict):
                        # vix 的日期在 'dates' list 最後一筆
                        _raw_d = (_msub.get('date') or _msub.get('period')
                                  or (_msub.get('dates') or [''])[-1] or _proxy_date)
                        _mdate = str(_raw_d)[:10]
                    else:
                        _mdate = _proxy_date
                    _reg_new[_mname] = {'last_updated': _mdate, 'rows': 1, 'category': '大盤', 'frequency': _mfreq}
                else:
                    _reg_missing(_mname, category='大盤', frequency=_mfreq)

            # ── 先行指標：按來源拆 5 細項（大盤，日更新）────────────────
            _li_reg = st.session_state.get('li_latest')
            _li_groups = {
                '[先行指標] 三大法人現貨':    ['外資', '投信', '自營'],
                '[先行指標] 外資期貨留倉':    ['外資大小'],
                '[先行指標] 選擇權PCR':       ['選PCR', '外(選)'],
                '[先行指標] 成交量（TWSE）':  ['成交量'],
                '[先行指標] 未平倉/韭菜指數': ['前五大留倉', '前十大留倉', '未平倉口數', '韭菜指數'],
            }
            if isinstance(_li_reg, _pd_reg.DataFrame) and not _li_reg.empty:
                _li_date_cols = [c for c in ['_date'] if c in _li_reg.columns]
                for _grp, _cols in _li_groups.items():
                    _vcols = [c for c in _cols if c in _li_reg.columns]
                    if not _vcols:
                        _reg_missing(_grp, category='大盤', frequency='daily')
                        continue
                    _sub = _li_reg[_li_date_cols + _vcols].copy()
                    _mask = _sub[_vcols].apply(
                        lambda s: s.notna() & (s.astype(str).str.strip() != '-')
                    ).any(axis=1)
                    _sub = _sub[_mask]
                    if not _sub.empty:
                        _reg_add(_grp, _sub, category='大盤', frequency='daily')
                    else:
                        _reg_missing(_grp, category='大盤', frequency='daily')
            else:
                for _grp in _li_groups:
                    _reg_missing(_grp, category='大盤', frequency='daily')

            # ── 個股細項（5項全部強制顯示，含缺失）──────────────────────
            _t2d_reg = st.session_state.get('t2_data')
            if _t2d_reg:
                _s2r = _t2d_reg.get('sid', '')
                _n2r = (_t2d_reg.get('name') or _s2r) or _s2r
                _pfx = f'[個股] {_s2r} {_n2r}'
                _lbl_freq = {
                    '價格走勢': 'daily', '月營收': 'monthly',
                    '季財報': 'quarterly', '現金流量': 'quarterly', '資產負債': 'quarterly'
                }
                for _lbl, _key in [('價格走勢','df'),('月營收','rev'),
                                    ('季財報','qtr'),('現金流量','cl'),('資產負債','cx')]:
                    _sub = _t2d_reg.get(_key)
                    _rname = f'{_pfx} | {_lbl}'
                    _f = _lbl_freq[_lbl]
                    if isinstance(_sub, _pd_reg.DataFrame) and not _sub.empty:
                        _reg_add(_rname, _sub, category='個股', frequency=_f)
                    else:
                        _reg_missing(_rname, category='個股', frequency=_f)
            else:
                _pfx0 = '[個股] — 尚未搜尋'
                for _lbl0, _f0 in [('價格走勢','daily'),('月營收','monthly'),
                                    ('季財報','quarterly'),('現金流量','quarterly'),('資產負債','quarterly')]:
                    _reg_missing(f'{_pfx0} | {_lbl0}', category='個股', frequency=_f0)

            # ── 比較排行（個股類別）──────────────────────────────────────
            _t3d_reg = st.session_state.get('t3_data')
            if _t3d_reg and _t3d_reg.get('results'):
                _reg_new['[比較] 多股比較排行'] = {
                    'last_updated': 'N/A', 'rows': len(_t3d_reg['results']),
                    'category': '個股', 'frequency': 'daily',
                }
            else:
                _reg_missing('[比較] 多股比較排行', category='個股', frequency='daily')

            # ── ETF 細項（全部強制顯示）─────────────────────────────────
            _etf1_reg = st.session_state.get('etf_single_data') or {}
            _etf_pdf  = _etf1_reg.get('price_df')
            _etf_tk   = _etf1_reg.get('ticker', '')
            _etf_nm   = _etf1_reg.get('name', '')
            _etf_pfx  = f'[ETF] {_etf_tk} {_etf_nm}'.strip() if _etf_tk else '[ETF] — 尚未搜尋'
            if isinstance(_etf_pdf, _pd_reg.DataFrame) and not _etf_pdf.empty:
                _reg_add(f'{_etf_pfx} | 價格走勢', _etf_pdf, category='ETF', frequency='daily')
            else:
                _reg_missing(f'{_etf_pfx} | 價格走勢', category='ETF', frequency='daily')
            if _etf1_reg.get('cur_yield') is not None:
                _reg_new[f'{_etf_pfx} | 殖利率與技術分析'] = {
                    'last_updated': 'N/A', 'rows': 1, 'category': 'ETF', 'frequency': 'daily',
                }
            else:
                _reg_missing(f'{_etf_pfx} | 殖利率與技術分析', category='ETF', frequency='daily')
            _etf2_reg = st.session_state.get('etf_portfolio_data') or {}
            if _etf2_reg.get('rows'):
                _etf2n = len(_etf2_reg['rows'])
                _reg_new[f'[ETF組合] 再平衡分析（{_etf2n}檔）'] = {
                    'last_updated': 'N/A', 'rows': _etf2n, 'category': 'ETF', 'frequency': 'daily',
                }
            else:
                _reg_missing('[ETF組合] 再平衡分析', category='ETF', frequency='daily')
            _etf3_reg = st.session_state.get('etf_backtest_data') or {}
            if _etf3_reg.get('cagr') is not None:
                _etf3n = len(_etf3_reg.get('weights', {}))
                _reg_new[f'[ETF回測] 回測績效（{_etf3n}檔）'] = {
                    'last_updated': 'N/A', 'rows': _etf3n, 'category': 'ETF', 'frequency': 'daily',
                }
            else:
                _reg_missing('[ETF回測] 回測績效', category='ETF', frequency='daily')


            st.session_state['data_registry'] = _reg_new
            print(f'[DataRegistry] 已登錄 {len(_reg_new)} 個資料源，類別標籤已寫入')
        except Exception as _re:
            print(f'[DataRegistry] 建立失敗: {_re}')

        st.rerun()  # 資料更新完成，重跑腳本讓頂部看板讀取最新 session_state

    cd     = st.session_state.get('cl_data', {})

    # ── Registry 常態 Patch：每次頁面渲染都更新個股/ETF 部分（不重發請求）──
    # 個股(t2_data)、ETF、比較排行 是用戶互動後才載入，需在每次 rerun 補入 registry
    # 注意：不限制 if _rp:，即使總經尚未更新也要讓 ETF/個股 資料進入診斷 Tab
    try:
        import pandas as _pd_rp
        _rp = dict(st.session_state.get('data_registry') or {})
        # proxy 日期：優先用總經更新時間；未更新過則用今天
        import datetime as _dt_prp
        _cl_ts_rp = st.session_state.get('cl_ts', '')
        try:
            import re as _re_rp
            _m_rp = _re_rp.search(r'(\d{4}-\d{2}-\d{2})', _cl_ts_rp)
            _proxy_rp = _m_rp.group(1) if _m_rp else _dt_prp.date.today().strftime('%Y-%m-%d')
        except Exception:
            _proxy_rp = _dt_prp.date.today().strftime('%Y-%m-%d')

        # 移除所有舊的個股 / ETF 單一 / ETF組合 / ETF回測 / 比較 key
        for _ok in list(_rp.keys()):
            if (_ok.startswith('[個股]') or _ok.startswith('[比較]')
                    or (_ok.startswith('[ETF]') and '|' in _ok)
                    or '[ETF組合]' in _ok or '[ETF回測]' in _ok):
                del _rp[_ok]

        # ── 個股 ──────────────────────────────────────────────────────
        _t2rp = st.session_state.get('t2_data')
        if _t2rp:
            _spfx = f'[個股] {_t2rp.get("sid","")} {(_t2rp.get("name") or _t2rp.get("sid",""))}'
            # DataFrame 型資料
            for _lbl, _key, _f in [('價格走勢','df','daily'),('月營收','rev','monthly'),
                                    ('季財報','qtr','quarterly')]:
                _rp[f'{_spfx} | {_lbl}'] = rp_entry(_t2rp.get(_key), '個股', _f)
            # cl/cx 為 fetch_financials 回傳的純量金額（非 DataFrame），須用 rp_scalar
            _rp[f'{_spfx} | 現金流量'] = rp_scalar(_t2rp.get('cl'), '個股', 'quarterly', _proxy_rp)
            _rp[f'{_spfx} | 資產負債'] = rp_scalar(_t2rp.get('cx'), '個股', 'quarterly', _proxy_rp)
            # 年度股利（list of dicts）
            import datetime as _dt_yr_rp
            _yr_rp = _t2rp.get('yearly') or []
            if _yr_rp:
                _yr_raw = str(_yr_rp[-1].get('year', ''))[:4]
                if _yr_raw.isdigit():
                    _yr_date = f'{_yr_raw}-12-31'
                    # 若為未來日期（如年度=當年但12月尚未到），截斷至今天
                    _today_cap = _dt_yr_rp.date.today().strftime('%Y-%m-%d')
                    _yr_date = min(_yr_date, _today_cap)
                else:
                    _yr_date = _proxy_rp
                _rp[f'{_spfx} | 年度股利'] = {'last_updated': _yr_date,
                                               'rows': len(_yr_rp), 'category': '個股', 'frequency': 'yearly'}
            else:
                _rp[f'{_spfx} | 年度股利'] = {'last_updated': 'N/A', 'rows': 0,
                                               'category': '個股', 'frequency': 'yearly', 'missing': True}
            # 健康度評分（純量）
            _rp[f'{_spfx} | 健康度評分'] = rp_scalar(_t2rp.get('health'), '個股', 'daily', _proxy_rp)
            # 技術指標：各自獨立
            _rp[f'{_spfx} | RSI'] = rp_scalar(_t2rp.get('rsi'), '個股', 'daily', _proxy_rp)
            _rp[f'{_spfx} | KD (K值)'] = rp_scalar(_t2rp.get('k'), '個股', 'daily', _proxy_rp)
            _rp[f'{_spfx} | IBS 內部強弱'] = rp_scalar(_t2rp.get('ibs'), '個股', 'daily', _proxy_rp)
            _rp[f'{_spfx} | 量比 VR'] = rp_scalar(_t2rp.get('vr'), '個股', 'daily', _proxy_rp)
            _rp[f'{_spfx} | 布林帶'] = rp_scalar(_t2rp.get('bb'), '個股', 'daily', _proxy_rp)
            _rp[f'{_spfx} | VCP 波幅收縮'] = rp_scalar(_t2rp.get('vcp'), '個股', 'daily', _proxy_rp)
            # 財報延伸（合約負債/存貨/資本支出時序）
            _rp[f'{_spfx} | 合約負債/資本支出'] = rp_entry(_t2rp.get('qtr_extra'), '個股', 'quarterly')
        else:
            _spfx0 = '[個股] — 尚未搜尋'
            for _lbl0, _f0 in [
                ('價格走勢','daily'),('月營收','monthly'),('季財報','quarterly'),
                ('現金流量','quarterly'),('資產負債','quarterly'),('年度股利','yearly'),
                ('健康度評分','daily'),('RSI','daily'),('KD (K值)','daily'),
                ('IBS 內部強弱','daily'),('量比 VR','daily'),('布林帶','daily'),
                ('VCP 波幅收縮','daily'),('合約負債/資本支出','quarterly'),
            ]:
                _rp[f'{_spfx0} | {_lbl0}'] = {'last_updated':'N/A','rows':0,'category':'個股','frequency':_f0,'missing':True}

        # ── 比較排行 ──────────────────────────────────────────────────
        _t3rp = st.session_state.get('t3_data')
        if _t3rp and _t3rp.get('results'):
            _rp['[比較] 多股比較排行'] = {'last_updated': _proxy_rp, 'rows': len(_t3rp['results']), 'category': '個股', 'frequency': 'daily'}
        else:
            _rp['[比較] 多股比較排行'] = {'last_updated': 'N/A', 'rows': 0, 'category': '個股', 'frequency': 'daily', 'missing': True}

        # ── ETF 單一 ──────────────────────────────────────────────────
        _e1rp = st.session_state.get('etf_single_data') or {}
        _etkrp = _e1rp.get('ticker', '')
        _epfxrp = f'[ETF] {_etkrp} {_e1rp.get("name","")}'.strip() if _etkrp else '[ETF] — 尚未搜尋'
        _rp[f'{_epfxrp} | 價格走勢'] = rp_entry(_e1rp.get('price_df'), 'ETF', 'daily')
        _rp[f'{_epfxrp} | 現金殖利率'] = rp_scalar(_e1rp.get('cur_yield'), 'ETF', 'daily', _proxy_rp)
        _rp[f'{_epfxrp} | 近5年平均殖利率'] = rp_scalar(_e1rp.get('avg_yield'), 'ETF', 'yearly', _proxy_rp)
        _rp[f'{_epfxrp} | 近1年含息總報酬'] = rp_scalar(_e1rp.get('total_ret'), 'ETF', 'daily', _proxy_rp)
        _e1_prem = (_e1rp.get('premium') or {})
        _rp[f'{_epfxrp} | 折溢價率'] = rp_scalar(_e1_prem.get('premium_pct'), 'ETF', 'daily', _proxy_rp)
        _rp[f'{_epfxrp} | 淨值 (NAV)'] = rp_scalar(_e1_prem.get('nav'), 'ETF', 'daily', _proxy_rp)
        _rp[f'{_epfxrp} | 追蹤誤差'] = rp_scalar(_e1rp.get('te'), 'ETF', 'daily', _proxy_rp)
        _rp[f'{_epfxrp} | VCP 波幅收縮'] = rp_scalar(_e1rp.get('vcp'), 'ETF', 'daily', _proxy_rp)
        _rp[f'{_epfxrp} | 內控費用率'] = rp_scalar(_e1rp.get('expense'), 'ETF', 'yearly', _proxy_rp)
        _rp[f'{_epfxrp} | Beta'] = rp_scalar(_e1rp.get('beta'), 'ETF', 'daily', _proxy_rp)
        _rp[f'{_epfxrp} | AuM 規模'] = rp_scalar(_e1rp.get('aum'), 'ETF', 'daily', _proxy_rp)
        _rp[f'{_epfxrp} | KD 技術指標'] = rp_scalar(_e1rp.get('k_val'), 'ETF', 'daily', _proxy_rp)
        _rp[f'{_epfxrp} | 年線乖離率 BIAS240'] = rp_scalar(_e1rp.get('bias240'), 'ETF', 'daily', _proxy_rp)

        # ── ETF 組合 ──────────────────────────────────────────────────
        _e2rp = st.session_state.get('etf_portfolio_data') or {}
        if _e2rp.get('rows'):
            _e2n = len(_e2rp['rows'])
            _rp[f'[ETF組合] 再平衡分析（{_e2n}檔）'] = {'last_updated': _proxy_rp, 'rows': _e2n, 'category': 'ETF', 'frequency': 'daily'}
        else:
            _rp['[ETF組合] 再平衡分析'] = {'last_updated': 'N/A', 'rows': 0, 'category': 'ETF', 'frequency': 'daily', 'missing': True}

        # ── ETF 回測 ──────────────────────────────────────────────────
        _e3rp = st.session_state.get('etf_backtest_data') or {}
        if _e3rp.get('cagr') is not None:
            _e3n = len(_e3rp.get('weights', {}))
            _rp[f'[ETF回測] 回測績效（{_e3n}檔）'] = {'last_updated': _proxy_rp, 'rows': _e3n, 'category': 'ETF', 'frequency': 'daily'}
        else:
            _rp['[ETF回測] 回測績效'] = {'last_updated': 'N/A', 'rows': 0, 'category': 'ETF', 'frequency': 'daily', 'missing': True}

        # 若大盤項目完全缺失（DataRegistry 建立時拋出 exception），從 cl_data 補建
        if not any(v.get('category') == '大盤' for v in _rp.values()):
            _cd_rb = st.session_state.get('cl_data', {})
            if _cd_rb:
                def _rb_add(_n, _df, _cat='大盤', _freq='daily'):
                    if isinstance(_df, _pd_rp.DataFrame) and not _df.empty:
                        _rp[_n] = {'last_updated': rp_ts(_df), 'rows': len(_df), 'category': _cat, 'frequency': _freq}
                    else:
                        _rp[_n] = {'last_updated': 'N/A', 'rows': 0, 'category': _cat, 'frequency': _freq, 'missing': True}
                for _n in INTL_MAP:
                    _rb_add(_n, (_cd_rb.get('intl') or {}).get(_n))
                for _n in TW_MAP:
                    _rb_add(_n, (_cd_rb.get('tw') or {}).get(_n))
                for _n in TECH_MAP:
                    _rb_add(_n, (_cd_rb.get('tech') or {}).get(_n))
                _rb_add('ADL 市場廣度', _cd_rb.get('adl'))
                _inst_rb = _cd_rb.get('inst') or {}
                for _ik, _iname in [('外資及陸資','三大法人 外資買賣超'),
                                     ('投信','三大法人 投信買賣超'),
                                     ('自營商','三大法人 自營商買賣超')]:
                    _rp[_iname] = {'last_updated': 'N/A', 'rows': 1 if _inst_rb.get(_ik) else 0,
                                   'category': '大盤', 'frequency': 'daily',
                                   **({} if _inst_rb.get(_ik) else {'missing': True})}
                _rp['融資餘額（台股）'] = {'last_updated': 'N/A', 'rows': 1 if _cd_rb.get('margin') else 0,
                                          'category': '大盤', 'frequency': 'daily',
                                          **({} if _cd_rb.get('margin') else {'missing': True})}
                _macro_rb = st.session_state.get('macro_info') or {}
                for _mk, _mn, _mf in [('vix','VIX 波動率指數','daily'),
                                       ('us_core_cpi','美國核心CPI年增率','monthly'),
                                       ('ism_pmi','🇹🇼 台灣 PMI 製造業指數','monthly'),
                                       ('tw_export','台灣出口年增率','monthly'),
                                       ('ndc_signal','景氣先行指標（NDC）','monthly')]:
                    _msub_rb = _macro_rb.get(_mk)
                    if _msub_rb:
                        _raw_rb = ((_msub_rb.get('date') or _msub_rb.get('period')
                                    or (_msub_rb.get('dates') or [''])[-1])
                                   if isinstance(_msub_rb, dict) else None) or _proxy_rp
                        _rp[_mn] = {'last_updated': str(_raw_rb)[:10], 'rows': 1,
                                    'category': '大盤', 'frequency': _mf}
                    else:
                        _rp[_mn] = {'last_updated': 'N/A', 'rows': 0,
                                    'category': '大盤', 'frequency': _mf, 'missing': True}
                print('[RegistryPatch] 大盤項目補建完成')

        st.session_state['data_registry'] = _rp
    except Exception as _rpe:
        print(f'[RegistryPatch] {_rpe}')

    intl   = {n:s for n,s in cd.get('intl',{}).items() if s is not None and not s.empty}
    tw     = {n:s for n,s in cd.get('tw',{}).items()   if s is not None and not s.empty}
    tech   = {n:s for n,s in cd.get('tech',{}).items() if s is not None and not s.empty}
    inst   = cd.get('inst', {})
    margin = cd.get('margin')
    _inst_is_cached = False
    _margin_is_cached = False
    if not inst and st.session_state.get('_last_inst'):
        inst = st.session_state['_last_inst']
        _inst_is_cached = True
    if not margin and st.session_state.get('_last_margin'):
        margin = st.session_state['_last_margin']
        _margin_is_cached = True
    df_adl = cd.get('adl')  # 騰落指標 DataFrame

    # ── 市場狀態卡：用已載入的真實資料渲染 ────────────────
    _mkt_info = st.session_state.get('mkt_info')
    if _mkt_info:
        _mkt_placeholder.empty()
        _mkt_placeholder.empty()  # 市場評分已整合至頂部紅綠燈看板，不重複顯示


    # ══════════════════════════════════════════════════════════════
    # 拐點偵測系統（整合五大面向）
    # ══════════════════════════════════════════════════════════════
    if _mkt_info:
        _mi2    = _mkt_info
        _ma60   = _mi2.get('ma60', 0)
        _ma120  = _mi2.get('ma120', 0)
        _ma200  = _mi2.get('ma200', 0)
        _idx2   = _mi2.get('index_price', 0)
        _sigs2  = _mi2.get('signals', [])
        _regime2= _mi2.get('regime','neutral')
        _m1b2   = st.session_state.get('m1b_m2_info', {})
        _bias2  = st.session_state.get('bias_info', {})
        _li2    = st.session_state.get('li_latest')
        _cd2    = st.session_state.get('cl_data', {})
        _tw2    = _cd2.get('tw', {})
        _twd_df = _tw2.get('新台幣匯率')

        # ── 計算各項拐點訊號 ─────────────────────────────────────
        pivot_signals = []  # (label, icon, color, detail)

        # 1. 技術面：均線方向（MA60/MA120 彎折）
        if _ma60 and _ma120 and _idx2:
            _turn_up   = any('向上彎折' in s for s in _sigs2)
            _turn_down = any('向下' in s and 'MA' in s for s in _sigs2)
            _above60   = _idx2 > _ma60
            _above120  = _idx2 > _ma120
            _above200  = _idx2 > _ma200 if _ma200 else None
            _d60  = (_idx2-_ma60)/_ma60*100
            _d120 = (_idx2-_ma120)/_ma120*100

            if _turn_up and _above60 and _above120:
                pivot_signals.append(('均線多頭確認','🟢','#3fb950',
                    f'站上MA60(+{_d60:.1f}%) & MA120(+{_d120:.1f}%) + 均線向上彎折 → 中長線起漲點'))
            elif _turn_up and _above60:
                pivot_signals.append(('均線初步翻多','🟡','#d29922',
                    f'站上MA60(+{_d60:.1f}%) + 向上彎折，待突破MA120({_ma120:,.0f})確認'))
            elif not _above60 and _turn_down:
                pivot_signals.append(('均線空頭確認','🔴','#f85149',
                    f'跌破MA60({_d60:.1f}%) + 均線向下 → 中期起跌訊號'))
            elif _above60 and not _above120:
                pivot_signals.append(('整理區間','⚪','#8b949e',
                    '站上MA60但未過MA120 → 等待方向確認'))

        # 2. 乖離率（與台股體質 ±7~10% 門檻）
        if _bias2:
            _b240 = _bias2.get('bias_240', 0)
            _b60  = _bias2.get('bias_60', _bias2.get('bias_20', 0))
            _b20  = _bias2.get('bias_20', 0)
            if _b240 > 10:
                pivot_signals.append(('年線乖離過大','⚠️','#f85149',
                    f'年線乖離 +{_b240:.1f}% > 10% → 頂部拐點區間，考慮減碼'))
            elif _b240 < -10:
                pivot_signals.append(('年線深度低估','💡','#3fb950',
                    f'年線乖離 {_b240:.1f}% < -10% → 底部拐點區間，考慮布局'))
            if abs(_b20) > 8:
                _bl20 = '過熱' if _b20 > 0 else '超賣'
                pivot_signals.append((f'月線{_bl20}',
                    '⚠️' if _b20 > 0 else '💡',
                    '#da3633' if _b20>0 else '#2ea043',
                    f'月線乖離 {_b20:+.1f}% → 短線{_bl20}修正機率高'))

        # 3. M1B-M2（資金面黃金/死亡交叉）
        if _m1b2 and not _m1b2.get('is_proxy'):
            _m1b_y = _m1b2.get('m1b_yoy', 0)
            _m2_y  = _m1b2.get('m2_yoy', 0)
            _diff  = _m1b_y - _m2_y
            if _diff > 0:
                pivot_signals.append(('M1B>M2 黃金交叉','✅','#3fb950',
                    f'M1B({_m1b_y:.1f}%) > M2({_m2_y:.1f}%) → 資金由定存轉入股市，長線起漲徵兆'))
            elif _diff < -1:
                pivot_signals.append(('M1B<M2 死亡交叉','❌','#f85149',
                    f'M1B({_m1b_y:.1f}%) < M2({_m2_y:.1f}%) → 資金撤離股市，長線起跌警示'))

        # 4. 台幣匯率（貶轉升=外資流入，升轉貶=外資撤退）
        if _twd_df is not None and not _twd_df.empty:
            _twd_col = 'close' if 'close' in _twd_df.columns else 'Close'
            if _twd_col in _twd_df.columns and len(_twd_df) >= 10:
                _twd_now   = float(_twd_df[_twd_col].iloc[-1])
                _twd_prev5 = float(_twd_df[_twd_col].iloc[-5])
                _twd_chg   = (_twd_now - _twd_prev5) / _twd_prev5 * 100
                # 注意：TWD=X 是 USD/TWD，數字越小=台幣越升值
                if _twd_chg < -0.5:  # 台幣升值 (匯率數字下降)
                    pivot_signals.append(('台幣升值','✅','#3fb950',
                        f'台幣近5日升值 {abs(_twd_chg):.1f}% → 外資熱錢流入，指數底部反彈訊號'))
                elif _twd_chg > 0.5:  # 台幣貶值 (匯率數字上升)
                    pivot_signals.append(('台幣貶值','⚠️','#d29922',
                        f'台幣近5日貶值 {_twd_chg:.1f}% → 外資撤退觀察，留意資金流出風險'))

        # 5. 外資期貨 + 散戶比（先行指標）
        if _li2 is not None and not _li2.empty:
            _last_li = _li2.iloc[-1]
            _fut_net = _last_li.get('外資大小')
            _leek    = _last_li.get('韭菜指數')
            _pcr     = _last_li.get('選PCR')
            if _fut_net is not None:
                _fut_net_v = float(_fut_net)
                if _fut_net_v < -30000:
                    pivot_signals.append(('外資期貨大量空單','🔴','#f85149',
                        f'外資期貨淨空 {abs(_fut_net_v):,.0f}口 > 3萬口 → 頂部起跌訊號'))
                elif _fut_net_v < 0 and abs(_fut_net_v) < 10000:
                    pivot_signals.append(('外資空單縮減','🟡','#d29922',
                        f'外資期貨淨空 {abs(_fut_net_v):,.0f}口（補回中）→ 底部拐點觀察'))
                elif _fut_net_v > 10000:
                    pivot_signals.append(('外資期貨多方','✅','#3fb950',
                        f'外資期貨淨多 {_fut_net_v:,.0f}口 → 多頭強勢確認'))
            if _leek is not None:
                _leek_v = float(_leek)
                if _leek_v > 20:
                    pivot_signals.append(('散戶極度看多（危險）','⚠️','#f85149',
                        f'韭菜指數 +{_leek_v:.1f}% > 20% → 散戶過熱，頂部拐點警示（反向指標）'))
                elif _leek_v < -20:
                    pivot_signals.append(('散戶極度悲觀（機會）','💡','#3fb950',
                        f'韭菜指數 {_leek_v:.1f}% < -20% → 散戶極度看空，底部拐點機會（反向指標）'))

        # ── 綜合評分 & 顯示 ──────────────────────────────────────
        _bull_pts = sum(1 for _,_,c,_ in pivot_signals if c == '#3fb950')
        _bear_pts = sum(1 for _,_,c,_ in pivot_signals if c == '#f85149')
        _warn_pts = sum(1 for _,_,c,_ in pivot_signals if c in ('#d29922',''))

        if _bull_pts > _bear_pts and _bull_pts >= 2:
            _pivot_overall = f'🟢 綜合拐點：{_bull_pts} 個多頭訊號 → 偏向底部起漲'
            _pivot_color   = '#3fb950'
        elif _bear_pts > _bull_pts and _bear_pts >= 2:
            _pivot_overall = f'🔴 綜合拐點：{_bear_pts} 個空頭訊號 → 偏向頂部起跌'
            _pivot_color   = '#f85149'
        else:
            _pivot_overall = f'⚪ 訊號分歧：多頭{_bull_pts} vs 空頭{_bear_pts}，方向待確認'
            _pivot_color   = '#d29922'

        st.markdown(f'<div style="background:#161b22;border-left:4px solid {_pivot_color};'
                    f'border-radius:0 8px 8px 0;padding:8px 12px;margin:6px 0;'
                    f'font-size:13px;font-weight:600;color:{_pivot_color};">'
                    f'{_pivot_overall}</div>', unsafe_allow_html=True)

        with st.expander('📊 拐點詳細分析 — 五大面向綜合判斷', expanded=True):
            if pivot_signals:
                for _label, _icon, _color, _detail in pivot_signals:
                    st.markdown(
                        f'<div style="background:#0d1117;border-left:3px solid {_color};'
                        f'border-radius:0 6px 6px 0;padding:6px 10px;margin:4px 0;">'
                        f'<span style="color:{_color};font-weight:600;">{_icon} {_label}</span>'
                        f'<br><span style="color:#8b949e;font-size:12px;">{_detail}</span>'
                        f'</div>', unsafe_allow_html=True)
            else:
                st.info('尚無足夠資料計算拐點，請點擊「🚀 一鍵更新全部數據」')

            # 拐點參考表 → 已移至 Tab5 策略手冊
            st.caption('📖 拐點判斷參考表 → 詳見「策略手冊」Tab')

    elif not cd:
        with _mkt_placeholder.container():
            st.info('📡 請點擊「🚀 一鍵更新全部數據」載入大盤數據')
    # ── ③ 資料到位後，回填紅綠燈佔位符（修復「未審先判」Bug）────
    _tl_final = calc_traffic_light(
        st.session_state.get('mkt_info', {}),
        st.session_state.get('jingqi_info', {}),
        st.session_state.get('cl_data', {}),
        st.session_state.get('li_latest'),
    )
    _render_traffic_light(_tl_placeholder, _tl_final, st.session_state.get('mkt_info', {}))
    if _tl_final:
        st.session_state['warroom_summary'] = {
            'traffic_light': _tl_final['label'],
            'health_score':  _tl_final['health'],
            'regime': st.session_state.get('mkt_info', {}).get('regime', 'neutral'),
            'market_score':  _tl_final['score'],
            'jingqi_avg':    _tl_final['jqavg'],
            'leek_index':    _tl_final['leek'],
            'foreign_net_bn':_tl_final['fnet'],
            'futures_net':   _tl_final['fut_net'],
            'confidence_pct':_tl_final['conf'],
        }

    intl_s = {n:calc_stats(s) for n,s in intl.items()}
    tw_s   = {n:calc_stats(s) for n,s in tw.items()}
    tech_s = {n:calc_stats(s) for n,s in tech.items()}

    # 持久化跨 tab 共用的國際指標 snapshot（供 tab_stock AI Prompt 引用）
    st.session_state['intl_snap'] = {
        'sox': intl_s.get('費城半導體 SOX'),
        'dxy': intl_s.get('美元指數 DXY'),
        'tnx': intl_s.get('10Y公債殖利率'),
        'dji': intl_s.get('道瓊工業 DJI'),
    }

    st.markdown(section_header('一','🌍 國際市場動態（影響台股的全球指標）','🌐'), unsafe_allow_html=True)
    _sox1 = intl_s.get('費城半導體 SOX')
    _dji1 = intl_s.get('道瓊工業 DJI')
    _dxy1 = intl_s.get('美元指數 DXY')
    _tyx1 = intl_s.get('10Y公債殖利率')

    # ── 宏爺：SOX × DXY 動態結論 ─────────────────────────────
    _sox_pct = _sox1.get('pct', None) if _sox1 else None
    _dxy_val = _dxy1.get('last', None) if _dxy1 else None
    _tyx_val = _tyx1.get('last', None) if _tyx1 else None

    if _sox_pct is not None and _dxy_val is not None:
        if _sox_pct >= 1.5 and _dxy_val < 100:
            _i1c = f'SOX {_sox_pct:+.1f}% / DXY {_dxy_val:.1f} → 熱錢狂潮，重壓電子強勢股'
            _i1a = '台積電/矽力/聯發科可積極持有'
        elif _sox_pct <= -1.5 and _dxy_val >= 103:
            _i1c = f'SOX {_sox_pct:+.1f}% / DXY {_dxy_val:.1f} → 外資提款，電子股嚴格減碼'
            _i1a = '降倉至 3 成以下，等待 DXY 回落'
        elif _sox_pct >= 1.0 and _dxy_val >= 100:
            _i1c = f'SOX {_sox_pct:+.1f}% / DXY {_dxy_val:.1f} → 內資控盤，精選中小型題材股'
            _i1a = '避開外資重倉大型權值，找內資題材'
        elif _sox_pct <= -1.5:
            _i1c = f'SOX {_sox_pct:+.1f}% / DXY {_dxy_val:.1f} → 費半重挫，台股科技開低機率高'
            _i1a = '設好停損，避免隔日追殺'
        else:
            _i1c = f'SOX {_sox_pct:+.1f}% / DXY {_dxy_val:.1f} → 走勢分化，方向未明'
            _i1a = '降部位等待費半方向確認'
        _i1_ind = f'SOX {_sox_pct:+.1f}% / DXY {_dxy_val:.1f}'
    elif _sox1 and _dji1:
        _sp = _sox1.get('pct', 0)
        _dp = _dji1.get('pct', 0)
        _i1c = f'費半 {_sp:+.1f}% / 道瓊 {_dp:+.1f}%（DXY 資料未載入）'
        _i1a = '等待完整數據確認'
        _i1_ind = f'SOX {_sp:+.1f}%'
    else:
        _i1c = '數據尚未載入，請點擊「🚀 一鍵更新全部數據」'
        _i1a = ''
        _i1_ind = '費半+美元'
    st.markdown(teacher_conclusion('宏爺', _i1_ind, _i1c, _i1a), unsafe_allow_html=True)

    # ── 策略1：10Y Yield 動態結論 ─────────────────────────────
    if _tyx_val is not None:
        if _tyx_val >= 4.8:
            _sql_c = f'10Y殖利率 {_tyx_val:.2f}% → 系統風險！無風險利率飆升，本益比大幅下修'
            _sql_a = '保留現金，嚴格控制槓桿'
        elif _tyx_val >= 4.5:
            _sql_c = f'10Y殖利率 {_tyx_val:.2f}% → 估值承壓，資金成本上升'
            _sql_a = '避開高本夢比個股，轉向低本益比價值股'
        else:
            _sql_c = f'10Y殖利率 {_tyx_val:.2f}% → 總經安全，利率溫和股市友善'
            _sql_a = '精選低基期價值股，可適度持有'
        st.markdown(teacher_conclusion('孫慶龍', f'10Y {_tyx_val:.2f}%', _sql_c, _sql_a), unsafe_allow_html=True)
    ci = st.columns(len(INTL_UNIT))
    for col,(name,unit) in zip(ci,INTL_UNIT.items()):
        with col:
            st.markdown(stat_card(name,intl_s.get(name),unit,name in intl_s),unsafe_allow_html=True)
    idx_d = {k:v for k,v in intl.items() if k in ['道瓊工業 DJI','納斯達克 IXIC','費城半導體 SOX']}
    if idx_d:
        st.plotly_chart(multi_chart(idx_d,'美股三大指數標準化比較',norm=True,height=220),
                        width='stretch', config={'displayModeBar':False})
    bc,dc = st.columns(2)
    with bc:
        if '10Y公債殖利率' in intl:
            st.plotly_chart(sparkline(intl['10Y公債殖利率'],'10Y公債殖利率','#f85149'),
                            width='stretch',config={'displayModeBar':False})
    with dc:
        if '美元指數 DXY' in intl:
            st.plotly_chart(sparkline(intl['美元指數 DXY'],'美元指數 DXY','#ffd700'),
                            width='stretch',config={'displayModeBar':False})
    st.markdown('<hr style="border-color:#21262d;margin:14px 0;">',unsafe_allow_html=True)
    st.markdown(section_header('二','🇹🇼 台股大盤（今日漲跌 + 台幣匯率）','🇹🇼'),unsafe_allow_html=True)
    _twii2 = tw_s.get('台股加權指數')
    _twd2 = tw_s.get('新台幣匯率')
    if _twii2 and _twd2:
        _tp = _twii2.get('pct')
        _fp = _twd2.get('pct')
        # 邊界防呆：API 回傳 None 時不崩潰
        _tp = float(_tp) if _tp is not None else None
        _fp = float(_fp) if _fp is not None else None
        if _tp is not None and _fp is not None:
            # 四象限資金流向判斷（fx>0=台幣貶值，fx<0=台幣升值）
            if _tp > 0 and _fp < 0:
                # 股匯雙漲：外資真實匯入
                _t2c = f'台股 {_tp:+.1f}% ／ 台幣升值 {_fp:+.2f}% → 股匯雙漲，外資真金白銀匯入，權值股領軍'
                _t2a = '順勢大膽作多，持股建議 80~100%'
            elif _tp > 0 and _fp > 0:
                # 股漲匯貶：疑似拉高出貨
                _t2c = f'台股 {_tp:+.1f}% ／ 台幣貶值 {_fp:+.2f}% → 股漲匯貶，指數虛漲，疑似外資拉高出貨'
                _t2a = '不追高，謹慎觀察，持股建議 50%'
            elif _tp < 0 and _fp > 0:
                # 股匯雙殺：外資大舉提款
                _t2c = f'台股 {_tp:+.1f}% ／ 台幣貶值 {_fp:+.2f}% → 股匯雙殺，外資無情提款撤出'
                _t2a = '嚴格減碼防守，持股建議 0~30%（現金為王）'
            elif _tp < 0 and _fp < 0:
                # 股跌匯升：技術性洗盤
                _t2c = f'台股 {_tp:+.1f}% ／ 台幣升值 {_fp:+.2f}% → 股跌匯升，外資資金停泊未撤，技術性洗盤'
                _t2a = '尋找錯殺優質股逢低布局，持股建議 50~70%'
            else:
                _t2c = f'台股 {_tp:+.1f}% ／ 台幣 {_fp:+.2f}%，無明顯方向性波動'
                _t2a = '維持現有部位，靜待表態'
        else:
            _t2c = '台股資料載入中'
            _t2a = '等待完整數據'
            _tp = _twii2.get('pct', 0) or 0
            _fp = _twd2.get('pct', 0) or 0
        _t2_ind = f'加權 {_twii2.get("last",0):,.0f}pt {(_tp or 0):+.1f}% | 台幣 {_twd2.get("last",0):.2f}'
    elif _twii2:
        _tp = _twii2.get('pct', 0) or 0
        _t2c = f'台股 {_tp:+.1f}%，{"偏多" if _tp > 0 else "偏空"}（台幣資料未載入）'
        _t2a = '參考其他指標確認方向'
        _t2_ind = f'加權 {_twii2.get("last",0):,.0f}pt {_tp:+.1f}%'
    else:
        _t2c = '數據尚未載入，請點擊「🚀 一鍵更新全部數據」'
        _t2a = ''
        _t2_ind = '台股加權 + 台幣'
    st.markdown(teacher_conclusion('宏爺', _t2_ind, _t2c, _t2a), unsafe_allow_html=True)
    tc = st.columns(len(TW_UNIT))
    for col,(name,unit) in zip(tc,TW_UNIT.items()):
        with col:
            st.markdown(stat_card(name,tw_s.get(name),unit,name in tw_s),unsafe_allow_html=True)
    tw1,tw2 = st.columns(2)
    with tw1:
        if '台股加權指數' in tw:
            _twii_ohlc = tw['台股加權指數']
            if all(c in _twii_ohlc.columns for c in ['open', 'high', 'low', 'close']):
                import plotly.graph_objects as _go_kl
                _ohlc_tail = _twii_ohlc.tail(60)
                _fig_kl = _go_kl.Figure(data=[_go_kl.Candlestick(
                    x=_ohlc_tail.index,
                    open=_ohlc_tail['open'], high=_ohlc_tail['high'],
                    low=_ohlc_tail['low'],   close=_ohlc_tail['close'],
                    increasing_line_color='#f85149', increasing_fillcolor='rgba(248,81,73,0.75)',
                    decreasing_line_color='#3fb950', decreasing_fillcolor='rgba(63,185,80,0.75)',
                    name='加權指數',
                )])
                _fig_kl.update_layout(
                    title=dict(text='台股加權指數（日K）', font=dict(size=11, color='#8b949e'), x=0),
                    height=220, margin=dict(l=40, r=15, t=30, b=20),
                    paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
                    font=dict(color='#8b949e', size=10), showlegend=False,
                    xaxis=dict(showgrid=False, color='#484f58', rangeslider=dict(visible=False)),
                    yaxis=dict(showgrid=True, gridcolor='#21262d', color='#484f58'),
                )
                st.plotly_chart(_fig_kl, width='stretch', config={'displayModeBar': False})
            else:
                st.plotly_chart(sparkline(_twii_ohlc, '台股加權指數', '#58a6ff'),
                                width='stretch', config={'displayModeBar': False})
    with tw2:
        try:
            otc = _fetch_otc_via_finmind(FINMIND_TOKEN)
            if otc is not None and not otc.empty:
                st.plotly_chart(sparkline(otc,'櫃買指數 OTC','#3fb950'),
                                width='stretch',config={'displayModeBar':False})
        except Exception:
            pass
    st.markdown('<hr style="border-color:#21262d;margin:14px 0;">',unsafe_allow_html=True)
    st.markdown('<hr style="border-color:#21262d;margin:8px 0;">', unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════════════════
    # 三、大戶籌碼全貌：法人聰明錢 × 融資融券 × 先行指標
    # ════════════════════════════════════════════════════════════════════
    st.markdown(section_header('三','🧮 大戶籌碼全貌：法人聰明錢 × 融資融券 × 先行指標','🧮'),unsafe_allow_html=True)

    if inst:
        _fk3 = next((k for k in inst if '外資' in k and '陸資' in k), None) or next((k for k in inst if '外資' in k), None)
        _tk3 = next((k for k in inst if '投信' in k), None)
        _fn3 = inst[_fk3]['net'] if _fk3 else 0
        _tn3 = inst[_tk3]['net'] if _tk3 else 0
        if _fn3 >= 100:
            _hye_c = '#3fb950'
            _hye_ind = f'外資大買超 {_fn3:.1f}億'
            _hye_concl = '大戶點火，跟著大戶走 → 積極加碼'
            _hye_act = '趁拉回布局，持股 80~100%'
        elif _fn3 <= -100:
            _hye_c = '#f85149'
            _hye_ind = f'外資大賣超 {abs(_fn3):.1f}億'
            _hye_concl = '大戶倒貨，嚴格減碼 → 離場為上'
            _hye_act = '持股降至 0~30%，停損優先'
        else:
            _hye_c = '#8b949e'
            _hye_ind = f'外資 {_fn3:+.1f}億（觀望區間）'
            _hye_concl = '資金觀望，區間操作'
            _hye_act = '持股 50%，高出低進等方向'
        st.markdown(teacher_conclusion('宏爺', _hye_ind, _hye_concl, color=_hye_c), unsafe_allow_html=True)
        st.markdown(f'<div style="color:#8b949e;font-size:11px;padding:1px 8px 6px 8px;">→ 建議行動：{_hye_act}</div>', unsafe_allow_html=True)
        if _tn3 > 5:
            st.markdown(f'<div style="color:#58a6ff;font-size:12px;padding:2px 6px;">• 投信買超 {_tn3:.1f}億 → 連續買超是加碼訊號</div>', unsafe_allow_html=True)
        # 三大法人買賣超柱狀圖（直接用 plotly，繞過 st.bar_chart→altair 相容性問題）
        _zk3 = next((k for k in inst if '自營' in k), None)
        _bc_vals = [float(_fn3 or 0),
                    float(_tn3 or 0),
                    float((inst.get(_zk3) or {}).get('net', 0) or 0)]
        _bc_colors = ['#58a6ff' if v >= 0 else '#f85149' for v in _bc_vals] + \
                     ['#3fb950' if _bc_vals[1] >= 0 else '#f85149',
                      '#ffd700' if _bc_vals[2] >= 0 else '#f85149']
        _bc_colors = ['#58a6ff' if _bc_vals[0] >= 0 else '#f85149',
                      '#3fb950' if _bc_vals[1] >= 0 else '#f85149',
                      '#ffd700' if _bc_vals[2] >= 0 else '#f85149']
        try:
            import plotly.graph_objects as _go_bc
            _fig_bc = _go_bc.Figure(_go_bc.Bar(
                x=['外資', '投信', '自營商'], y=_bc_vals,
                marker_color=_bc_colors, text=[f'{v:+.1f}億' for v in _bc_vals],
                textposition='outside'))
            _fig_bc.update_layout(
                height=200, margin=dict(t=30, b=10, l=10, r=10),
                paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
                font=dict(color='#e6edf3', size=12),
                yaxis=dict(showgrid=False, zeroline=True,
                           zerolinecolor='#484f58', showticklabels=False))
            st.plotly_chart(_fig_bc, use_container_width=True,
                            config={'displayModeBar': False})
        except Exception as _bc_err:
            st.caption(f'外資 {_bc_vals[0]:+.1f}億 ｜ 投信 {_bc_vals[1]:+.1f}億 ｜ 自營商 {_bc_vals[2]:+.1f}億')
    if margin:
        if margin >= 3400:
            _sql_mc = '#f85149'
            _sql_mind = f'融資餘額 {margin:.0f}億'
            _sql_mconcl = '極度危險，嚴防多殺多 → 行情尾端'
            _sql_mact = '全面減碼，勿追高，準備逃命'
        elif margin >= 2800:
            _sql_mc = '#d29922'
            _sql_mind = f'融資餘額 {margin:.0f}億'
            _sql_mconcl = '水位偏高，籌碼凌亂 → 警戒操作'
            _sql_mact = '持股降至 50% 以下，避免重倉'
        else:
            _sql_mc = '#3fb950'
            _sql_mind = f'融資餘額 {margin:.0f}億'
            _sql_mconcl = '籌碼乾淨，安全水位 → 可積極布局'
            _sql_mact = '健康多頭格局，持股 70~100%'
        st.markdown(teacher_conclusion('孫慶龍', _sql_mind, _sql_mconcl, color=_sql_mc), unsafe_allow_html=True)
        st.markdown(f'<div style="color:#8b949e;font-size:11px;padding:1px 8px 6px 8px;">→ 建議行動：{_sql_mact}</div>', unsafe_allow_html=True)
    st.markdown('<hr style="border-color:#21262d;margin:10px 0;">', unsafe_allow_html=True)

    # ── 宏爺外資期貨（先行指標快速結論）─────────────────────────────────
    _li4 = st.session_state.get('li_latest')
    if _li4 is not None and not _li4.empty:
        _fut4 = (float(_li4.iloc[-1].get('外資大小', 0)) if '外資大小' in _li4.columns else None)
        _pcr4 = (float(_li4.iloc[-1].get('選PCR', 0)) if '選PCR' in _li4.columns else None)
        if _fut4 is not None:
            _pcr_txt = f' | PCR {_pcr4:.1f}' if _pcr4 else ''
            _l4_ind = f'外資期貨 {_fut4:,.0f}口{_pcr_txt}'
            # 宏爺絕對口數門檻（容錯率最高）
            if _fut4 <= -30000:
                _l4c = f'外資期貨空單 {abs(_fut4):,.0f}口 > 3萬口，啟動強制防禦，強制減倉至20%以下，等待空單回補'
                _l4a = '強制減倉至 20% 以下，嚴禁追高攤平，保護本金'
            elif _fut4 <= -15000:
                _l4c = f'外資期貨空單 {abs(_fut4):,.0f}口，空單累積中，大戶動向保守，逢高調節'
                _l4a = '收回資金，持股降至 50%，等待明確表態'
            elif _fut4 > 0:
                _l4c = f'外資期貨多單 {_fut4:,.0f}口，外資期貨翻多，燃料充足，積極作多'
                _l4a = '順勢重壓強勢股，持股 80~100%'
            else:
                _l4c = f'外資期貨微空 {abs(_fut4):,.0f}口，水位正常，依個股技術面操作'
                _l4a = '持股 70%，現金 30% 備用'
        else:
            _l4c = '先行指標欄位異常，請確認 FinMind Token'
            _l4a = ''
            _l4_ind = '外資期貨留倉'
    else:
        _l4c = '先行指標尚未載入，請點擊「🚀 一鍵更新全部數據」'
        _l4a = ''
        _l4_ind = '外資期貨留倉'
    st.markdown(teacher_conclusion('宏爺', _l4_ind, _l4c, _l4a), unsafe_allow_html=True)

    # ── 副標籤：欄位確認列（v12 風格）─────────────────────────────────
    st.markdown("""<div style="font-size:11px;color:#484f58;margin:-6px 0 10px 0;">
✅ 外資期貨留倉口數 &nbsp;｜&nbsp; ✅ 前五大/前十大交易人 &nbsp;｜&nbsp; ✅ 外資選擇權金額 &nbsp;｜&nbsp; ✅ 韭菜指數 &nbsp;｜&nbsp; ✅ PCR
</div>""", unsafe_allow_html=True)

    # 先行指標隨更新大盤自動載入（執行緒快取版，build_leading_fast）
    df_li_show = st.session_state.get('li_latest')

    if df_li_show is not None and not df_li_show.empty:
        # 向前填補 NaN（各欄位用最後一次有效數值補齊，避免 API 部分失敗造成空格）
        _li_num_cols = [c for c in df_li_show.columns if c != '日期']
        df_li_show = df_li_show.copy()
        df_li_show[_li_num_cols] = df_li_show[_li_num_cols].ffill()

        # ── ① 資料期間 caption ─────────────────────────────────────────
        _li_dates = df_li_show['日期'].tolist() if '日期' in df_li_show.columns else []
        if _li_dates:
            _d0 = _li_dates[0]
            _d1 = _li_dates[-1]
            st.caption(
                f'📅 資料期間：{_d0} ~ {_d1}  共 {len(df_li_show)} 筆  '
                f'｜外資空單>3萬⚠️  前五大>1萬⚠️  PCR<100偏空'
            )

        # ── ② 主表格（render_leading_table，已內含深色主題CSS）──────────
        st.markdown(render_leading_table(df_li_show), unsafe_allow_html=True)

        # 欄位說明 → 已移至 Tab 5 策略手冊



        # ── ③ 進階警示訊號（依建議加入5個條件）──────────────────────────
        _last_row = df_li_show.iloc[-1] if not df_li_show.empty else {}
        _fut_net  = _last_row.get('外資大小')
        _pcr      = _last_row.get('選PCR')
        _opt_net  = _last_row.get('外(選)')
        _leek     = _last_row.get('韭菜指數')
        _foreign  = _last_row.get('外資')  # 現貨外資買賣
        _trust    = _last_row.get('投信')  # 投信買賣
        _warnings = []

        # 訊號 1：期權同向崩盤訊號（最強烈）
        # 期貨大空 + 選擇權外資淨空 → 不惜成本避險
        try:
            if _fut_net is not None and float(_fut_net) < -20000:
                if _opt_net is not None and float(_opt_net) < 0:
                    _warnings.append(('🔴', '期權同向崩盤警戒',
                        f'期貨空{abs(float(_fut_net)):,.0f}口 + 選擇權外資淨空{float(_opt_net):,.0f}千元',
                        '外資「不惜成本」雙向避險，高機率隨即殺盤，建議降倉至30%以下'))
                elif _fut_net is not None and float(_fut_net) < -30000:
                    _warnings.append(('🟡', '期貨大空警戒',
                        f'外資期貨空單 {abs(float(_fut_net)):,.0f} 口（>3萬口門檻）',
                        '注意流向：若每日持續增加空單才是真訊號；若空單縮減則危機解除'))
        except Exception:
            pass

        # 訊號 2：韭菜指數極端值
        try:
            if _leek is not None:
                _leek_f = float(_leek)
                if _leek_f > 30:
                    _warnings.append(('🔴', '散戶過度樂觀（韭菜極端多）',
                        f'法人空多比 +{_leek_f:.1f}%（超過+30%警戒線）',
                        '散戶一面倒看多，短線見頂訊號，主力容易在此出貨'))
                elif _leek_f < -30:
                    _warnings.append(('🟢', '軋空動能極強（韭菜極端空）',
                        f'法人空多比 {_leek_f:.1f}%（超過-30%機會線）',
                        '散戶爭相放空，軋空動能強，千萬不要在此放空，逆勢做多機會'))
        except Exception:
            pass

        # 訊號 3：外資投信同買（最強籌碼訊號）
        try:
            if _foreign is not None and _trust is not None:
                _f2 = float(_foreign)
                _t2 = float(_trust)
                if _f2 > 50 and _t2 > 5:
                    _warnings.append(('🟢', '外資投信同買（籌碼共鳴）',
                        f'外資+{_f2:.0f}億 + 投信+{_t2:.1f}億 同步買超',
                        '外投同買的股票漲幅連續性最強，現貨籌碼最乾淨'))
                elif _f2 < -100 and _t2 < -5:
                    _warnings.append(('🔴', '外資投信同賣（籌碼潰散）',
                        f'外資{_f2:.0f}億 + 投信{_t2:.1f}億 同步賣超',
                        '雙主力同步出場，下跌壓力沉重'))
        except Exception:
            pass

        # 訊號 4：PCR 極端值判斷
        try:
            if _pcr is not None:
                _pcr_f = float(_pcr)
                if _pcr_f < 80:
                    _warnings.append(('🔴', '選擇權Put/Call偏低（市場過樂觀）',
                        f'PCR={_pcr_f:.1f}（<80偏危險，市場保護不足）',
                        '選擇權市場無人買保護，通常出現在短線頂部'))
                elif _pcr_f > 150:
                    _warnings.append(('🟢', '選擇權Put/Call偏高（恐慌區）',
                        f'PCR={_pcr_f:.1f}（>150偏多，市場過度悲觀）',
                        '大量買保護代表市場恐慌，通常是逆向布局訊號'))
        except Exception:
            pass

        # 訊號 5：成交量萎縮（市場觀望）
        try:
            # P4: vectorized str → numeric，避免逐列 Python 呼叫
            _vols = (pd.to_numeric(
                df_li_show['成交量'].tail(5).astype(str).str.replace('億','', regex=False),
                errors='coerce').dropna().tolist()
                if '成交量' in df_li_show.columns else [])
            if len(_vols) >= 3:
                _avg_vol = sum(_vols[:-1]) / len(_vols[:-1])
                _last_vol = _vols[-1]
                if _last_vol < _avg_vol * 0.7:
                    _warnings.append(('🟡', '成交量急萎縮（市場觀望）',
                        f'今日成交量{_last_vol:.0f}億（前{len(_vols)-1}日均量{_avg_vol:.0f}億的{_last_vol/_avg_vol*100:.0f}%）',
                        '量縮超過30%代表市場觀望，方向選擇前勿輕易追高'))
                elif _last_vol > _avg_vol * 1.5:
                    _warnings.append(('🔵', '成交量急放（趨勢加速）',
                        f'今日成交量{_last_vol:.0f}億（前均量{_avg_vol:.0f}億的{_last_vol/_avg_vol*100:.0f}%）',
                        '成交量暴增50%以上，趨勢加速，注意是否配合方向'))
        except Exception:
            pass

        if _warnings:
            for _wc, _wt, _wd, _wa in _warnings:
                _wcolor = ('#2ea043' if _wc == '🟢' else
                           '#da3633' if _wc == '🔴' else
                           '#d29922' if _wc == '🟡' else '#388bfd')
                st.markdown(
                    f'<div style="border-left:5px solid {_wcolor};background:#0d1117;'
                    f'padding:9px 14px;border-radius:0 8px 8px 0;margin:4px 0;">'
                    f'<span style="font-size:11px;color:#6e7681;">⚡ 進階警示</span><br>'
                    f'<span style="font-size:14px;font-weight:900;color:{_wcolor};">{_wc} {_wt}</span><br>'
                    f'<span style="font-size:12px;color:#c9d1d9;">{_wd}</span><br>'
                    f'<span style="font-size:11px;color:#8b949e;">→ {_wa}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )

        
        # ── ⑤ v4.0 總經一票否決 (Task 2) ─────────────────────────────
        try:
            _v4_pcr = float(_last_row.get('選PCR') or 100)
            _v4_fut = float(_last_row.get('外資大小') or 0)
            _v4_mac = V4StrategyEngine.__new__(V4StrategyEngine)
            _v4_mac.macro = {'vix': 15, 'foreign_futures': _v4_fut, 'pcr': _v4_pcr}
            _v4_veto = _v4_mac.check_macro_veto()
            _v4_c = _v4_veto['color']
            st.markdown(
                f'<div style="border-left:5px solid {_v4_c};background:#0d1117;'
                f'padding:9px 14px;border-radius:0 8px 8px 0;margin:6px 0;">'
                f'<span style="font-size:11px;color:#6e7681;">🏛️ v4.0 總經否決權</span><br>'
                f'<span style="font-size:14px;font-weight:900;color:{_v4_c};">'
                f'{_v4_veto["status"]} — 最大建議持股 {_v4_veto["max_position"]}%</span><br>'
                f'<span style="font-size:12px;color:#c9d1d9;">{_v4_veto["msg"]}</span>'
                f'</div>',
                unsafe_allow_html=True
            )
        except Exception as _v4e:
            pass


        # ── v5.0 動態資產配置建議（純現金策略，無 ETF）────────────────
        try:
            _v5_fut = float(_last_row.get('外資大小') or 0)
            if _v5_fut <= -30000:
                _v5_stock, _v5_cash = 20, 80
                _v5_strategy = '嚴禁追高攤平，保護本金優先；可留意低基期高殖利率個股'
                _v5_color = '#f85149'
            elif _v5_fut <= -15000:
                _v5_stock, _v5_cash = 50, 50
                _v5_strategy = '收回資金，逢高減碼漲多個股，等待期空回補訊號'
                _v5_color = '#d29922'
            elif _v5_fut > 0:
                _v5_stock, _v5_cash = 90, 10
                _v5_strategy = '期貨翻多，順勢重壓強勢股，外投同買個股優先布局'
                _v5_color = '#3fb950'
            else:
                _v5_stock, _v5_cash = 70, 30
                _v5_strategy = '水位中性，依個股技術面操作，保留現金彈藥'
                _v5_color = '#58a6ff'
            st.markdown(
                f'<div style="border-left:5px solid {_v5_color};background:#0d1117;'
                f'padding:9px 14px;border-radius:0 8px 8px 0;margin:6px 0;">'
                f'<span style="font-size:11px;color:#6e7681;">💰 v5 動態配置</span><br>'
                f'<span style="font-size:14px;font-weight:900;color:{_v5_color};">'
                f'建議股票 {_v5_stock}% ／現金 {_v5_cash}%</span><br>'
                f'<span style="font-size:12px;color:#c9d1d9;">📌 {_v5_strategy}</span>'
                f'</div>',
                unsafe_allow_html=True
            )
        except Exception:
            pass

# ── ④ 資料來源診斷（收合，供進階使用者確認）─────────────────────
        with st.expander('🔍 資料來源診斷（點此確認各欄數據正確性）', expanded=False):
            _diag_cols = {
                '外資大小':       ('FinMind TX+MTX 期貨留倉 / TAIFEX futContractsDate備援', '外資大台淨口 + 外資小台淨口×0.25'),
                '前五大留倉':     ('TAIFEX largeTraderFutQry POST',                         '前五大買方所有契約 − 賣方所有契約'),
                '前十大留倉':     ('TAIFEX largeTraderFutQry POST',                         '前十大買方所有契約 − 賣方所有契約'),
                '選PCR':          ('TAIFEX pcRatio POST',                                   'Put未平倉量 / Call未平倉量 × 100'),
                '外(選)':         ('TAIFEX callsAndPutsDate POST',                          'BC金額 − SC金額 − BP金額 + SP金額'),
                '韭菜指數':       ('TAIFEX futContractsDate+futDailyMarketReport',          '(法人空方MTX OI − 法人多方MTX OI) / 全體MTX OI × 100'),
                '外資/投信/自營': ('TWSE BFI82U',                                           '三大法人現貨買賣差額（億元）'),
                '成交量':         ('TWSE FMTQIK 月報',                                      '每日全市場成交金額（億元）'),
            }
            for _col, (_src, _formula) in _diag_cols.items():
                st.markdown(
                    f'<div style="font-size:12px;color:#8b949e;padding:2px 0;">'
                    f'<b style="color:#c9d1d9;">{_col}</b> → 來源：{_src}<br>'
                    f'&nbsp;&nbsp;&nbsp;公式：{_formula}</div>',
                    unsafe_allow_html=True
                )
            # [BUG FIX] 最新一筆原始值 - 用 pd.isna 確保 NaN 不造成 format error
            if len(df_li_show) > 0:
                _raw = df_li_show.iloc[-1]
                st.markdown('<br><b style="color:#c9d1d9;font-size:12px;">最新一筆原始值：</b>', unsafe_allow_html=True)
                _raw_items = []
                for _c in ['外資大小','前五大留倉','前十大留倉','選PCR','外(選)','韭菜指數','外資','投信','自營']:
                    _v = _raw.get(_c)
                    if _v is not None:
                        try:
                            import pandas as _pd_raw
                            if not _pd_raw.isna(_v):  # [BUG FIX] 過濾 NaN 避免 format 崩潰
                                _raw_items.append(f'{_c}={float(_v):+,.0f}')
                        except Exception:
                            _raw_items.append(f'{_c}={_v}')
                st.code(' | '.join(_raw_items), language=None)

        # ── ⑤ 下載按鈕（Base64 data URL，不依賴 WebSocket）──────
        try:
            import base64 as _b64_li
            _csv_li = df_li_show.to_csv(index=False, encoding='utf-8-sig')
            _b64_li_data = _b64_li.b64encode(_csv_li.encode('utf-8-sig')).decode()
            st.markdown(
                f'<a href="data:text/csv;charset=utf-8-sig;base64,{_b64_li_data}" '
                f'download="先行指標.csv" '
                f'style="display:inline-block;padding:5px 14px;background:#21262d;'
                f'color:#e6edf3;border:1px solid #30363d;border-radius:6px;'
                f'font-size:13px;text-decoration:none;">⬇️ 下載先行指標 CSV</a>',
                unsafe_allow_html=True
            )
        except Exception:
            pass

    elif cd:
        # 已有其他總經數據但先行指標失敗 → 顯示診斷
        with st.expander('⚠️ 先行指標載入失敗 — 診斷說明', expanded=True):
            st.warning('先行指標尚未載入，請重新點擊「🚀 一鍵更新全部數據」')
            st.markdown('''<div style="font-size:12px;color:#8b949e;line-height:1.8;">
<b>可能原因：</b><br>
① TAIFEX 在 Colab 常被封鎖 → 外資大小/PCR/韭菜仍可從 FinMind 取得<br>
② FinMind API 速率限制 → 等待 10 分鐘後重試<br>
③ 非交易日（週末/假日）→ 資料期間無新增屬正常<br><br>
<b>✅ 免費可用（不需 Token）：</b><br>
• 外資大小 TX+MTX | 選PCR(FinMind) | 外(選) | 三大法人買賣 | 成交量 | ADL<br>
• TAIFEX 可達時自動補充：前五大/前十大/精確PCR/未平倉/韭菜精確值<br>
</div>''', unsafe_allow_html=True)
    else:
        st.info('📡 請點擊「🚀 一鍵更新全部數據」自動載入先行指標')

    # 宏爺判斷方式 → 已移至 Tab 5 策略手冊

    # ── 宏爺智能綜合結論 ─────────────────────────────────────────────────────
    _df_li_c = st.session_state.get('li_latest')
    if _df_li_c is not None and not _df_li_c.empty:
        _last_li = _df_li_c.iloc[-1]
        _fnet = safe_get(_last_li.get('外資大小'))
        _pcr  = safe_get(_last_li.get('選PCR'))
        _leek = safe_get(_last_li.get('韭菜指數'))
        _top5 = safe_get(_last_li.get('前五大留倉'))
        _opt  = safe_get(_last_li.get('外(選)'))
        _date = _last_li.get('日期','最新')

        _score = 0
        _sigs = []
        if _fnet is not None:
            if   _fnet < -30000:
                _score -= 2
                _sigs.append(f'🔴 期貨空單 {_fnet:,.0f}口（超越3萬危險線）')
            elif _fnet <      0:
                _score -= 1
                _sigs.append(f'⚠️ 期貨淨空 {_fnet:,.0f}口')
            else:
                _score += 1
                _sigs.append(f'✅ 期貨淨多 {_fnet:+,.0f}口')
        if _pcr is not None:
            if   _pcr > 130:
                _score += 1
                _sigs.append(f'🟢 PCR={_pcr:.0f}（>130強支撐）')
            elif _pcr > 100:
                _sigs.append(f'🔵 PCR={_pcr:.0f}（偏多）')
            else:
                _score -= 1
                _sigs.append(f'🔴 PCR={_pcr:.0f}（<100偏空）')
        if _opt is not None:
            if   _opt >  10000:
                _score += 1
                _sigs.append(f'🟢 外選 +{_opt:,.0f}千元（多方佈局）')
            elif _opt < -10000:
                _score -= 1
                _sigs.append(f'🔴 外選 {_opt:,.0f}千元（空方佈局）')
            else:
                _sigs.append(f'⚪ 外選 {_opt:+,.0f}千元（中性）')
        if _top5 is not None:
            if   _top5 < -10000:
                _score -= 1
                _sigs.append(f'🔴 前五大淨空 {_top5:,.0f}口（警戒）')
            elif _top5 >       0:
                _score += 1
                _sigs.append(f'✅ 前五大淨多 {_top5:+,.0f}口')
        if _leek is not None:
            if   _leek > 10:
                _score -= 1
                _sigs.append(f'🔴 韭菜指數{_leek:.1f}%（散戶過熱）')
            elif _leek < -5:
                _score += 1
                _sigs.append(f'✅ 韭菜指數{_leek:.1f}%（散戶悲觀）')
            else:
                _sigs.append(f'⚪ 韭菜指數{_leek:.1f}%（中性）')

        if   _score <= -3:
            _vd='🚨 強烈偏空'
            _vc='#f85149'
            _va='建議大幅降倉，等待空單回補訊號'
        elif _score <= -1:
            _vd='🔴 偏空'
            _vc='#da6d3e'
            _va='籌碼不穩，建議觀望為主'
        elif _score ==  0:
            _vd='⚪ 多空分歧'
            _vc='#d29922'
            _va='訊號分歧，小倉觀察，詳見策略手冊'
        elif _score <=  2:
            _vd='🟢 偏多'
            _vc='#3fb950'
            _va='籌碼偏健康，可正常持倉'
        else:
            _vd='💚 強烈偏多'
            _vc='#2ea043'
            _va='聰明錢明顯佈多，積極持倉'

        st.markdown(
            f'<div style="background:#0d1117;border:2px solid {_vc}44;border-radius:10px;padding:14px 18px;margin:8px 0;">'
            f'<div style="font-size:11px;color:#8b949e;margin-bottom:4px;">🎯 {_date} 籌碼綜合判斷</div>'
            f'<div style="font-size:24px;font-weight:900;color:{_vc};">{_vd}</div>'
            f'<div style="font-size:13px;color:#c9d1d9;margin:6px 0 10px 0;">{_va}</div>'
            f'<div style="font-size:12px;color:#484f58;">{" ； ".join(_sigs)}</div>'
            f'</div>',
            unsafe_allow_html=True
        )


    st.markdown('<hr style="border-color:#21262d;margin:14px 0;">',unsafe_allow_html=True)
    st.markdown('<hr style="border-color:#21262d;margin:8px 0;">', unsafe_allow_html=True)
    st.markdown('<div style="font-size:10px;color:#484f58;text-transform:uppercase;letter-spacing:1px;margin:4px 0;">📊 市場廣度</div>', unsafe_allow_html=True)
    st.markdown(section_header('五','📊 全市場健康度 × 騰落指標（ADL）','📉'),unsafe_allow_html=True)
    _adl5 = st.session_state.get('cl_data', {}).get('adl')
    _mkt5 = st.session_state.get('mkt_info', {})
    if _adl5 is not None and not _adl5.empty:
        _ac5 = next((c for c in _adl5.columns if 'adl' in c.lower()), _adl5.columns[0])
        _adl_vals5 = _adl5[_ac5].dropna().tail(5)
        _adl_up5 = (len(_adl_vals5) >= 2 and float(_adl_vals5.iloc[-1]) > float(_adl_vals5.iloc[0]))
        # 優先從 tw_s 取當日漲跌 %（比 mkt_info 更可靠），fallback 到 mkt5
        _twii_s5 = tw_s.get('台股加權指數') or {}
        _twii_p5 = _twii_s5.get('pct') if isinstance(_twii_s5, dict) and _twii_s5.get('pct') is not None \
                   else (_mkt5.get('台股加權指數', {}).get('pct', None) if isinstance(_mkt5.get('台股加權指數'), dict) else None)
        # Bug fix：_twii_p5=0 或 None 時，依 ADL 方向判斷（不能落入空頭 else）
        _idx_up = (_twii_p5 is not None and _twii_p5 > 0)
        _idx_dn = (_twii_p5 is not None and _twii_p5 < 0)
        if _adl_up5 and _idx_up:
            _a5c = '廣泛多頭：ADL↑+指數↑，市場健康，全面性上漲'
            _a5a = '可積極持股'
        elif _adl_up5 and _idx_dn:
            _a5c = 'ADL↑但指數跌，廣度健康，或為技術回調非崩盤'
            _a5a = '可留意回調後逢低布局'
        elif _adl_up5:
            # ADL上升但指數資料不足/持平 → 廣度健康，中性偏多
            _a5c = 'ADL↑廣度健康，指數方向待確認（持平或資料更新中）'
            _a5a = '維持現有部位，等待指數方向確認'
        elif not _adl_up5 and _idx_up:
            _a5c = '⚠️ 背離警訊：指數漲但ADL↓，行情由少數權值股撐，不可追'
            _a5a = '謹慎，不追高，等待廣度改善'
        else:
            _a5c = '廣泛賣壓：ADL↓+指數↓，空頭格局，降低部位'
            _a5a = '降低持倉，保護本金'
        _a5_ind = f'ADL近5日{"↑上升" if _adl_up5 else "↓下降"}'
    else:
        _a5c = 'ADL數據尚未載入，請點擊「🚀 一鍵更新全部數據」'
        _a5a = ''
        _a5_ind = 'ADL騰落線'
    st.markdown(teacher_conclusion('宏爺', _a5_ind, _a5c, _a5a), unsafe_allow_html=True)
    st.caption('💡 衡量「多少股票真的在漲」—— 分數越高 = 廣度越健康；ADL 趨勢 vs 指數是否背離是最重要的觀察點')
    # 如果是代理資料，顯示提示
    _adl_chk = st.session_state.get('cl_data',{}).get('adl')
    if _adl_chk is not None and not _adl_chk.empty:
        if 'is_proxy' in _adl_chk.columns and _adl_chk['is_proxy'].any():
            st.caption('⚠️ 目前顯示 yfinance 代理數據（TWSE 上漲/下跌家數暫時無法取得），上漲佔比為估算值')

    # ── 宏爺策略 + 上漲佔比動態結論（移至 Section 標題下方）──────────
    if df_adl is not None and not df_adl.empty:
        st.caption('💡 宏爺策略：ADL 趨勢比今日漲跌更重要，要看「方向」是否與指數一致。')
        _ar2 = df_adl.iloc[-1]
        _ad2 = _ar2.get('ad', 0)
        _ratio2 = _ar2.get('ad_ratio', 50)
        _adl2 = _ar2.get('adl', 0)
        _ma2  = df_adl['adl_ma20'].dropna().iloc[-1] if df_adl['adl_ma20'].notna().any() else _adl2
        _twii_pct2 = tw_s.get('台股加權指數', {}).get('pct', 0) if tw_s.get('台股加權指數') else 0
        _ad_ratio_int  = int(round(_ratio2)) if _ratio2 else 0
        _adl_above_ma  = (_adl2 is not None and _ma2 is not None and _adl2 > _ma2)
        _adl_below_ma  = (_adl2 is not None and _ma2 is not None and _adl2 < _ma2)
        _adl_concl = []
        if _twii_pct2 > 0.5 and _ad2 < -50:
            _adl_concl.append(
                f'🔴 指數漲({_twii_pct2:+.1f}%) 但 AD值({_ad2:+,}) < -50 → '
                f'背離！僅少數大型股撐盤，廣度萎縮，建議準備降倉')
        elif _twii_pct2 < -0.5 and _ad2 > 50:
            _adl_concl.append(
                f'🟢 指數跌({_twii_pct2:+.1f}%) 但 AD值({_ad2:+,}) > 50 → '
                f'底部擴散！多數股票止跌，可留意逢低布局機會')
        elif _ratio2 >= 70 and _adl_above_ma:
            _adl_concl.append(
                f'✅ 上漲佔比 {_ad_ratio_int}%（>70%）+ ADL在MA上 → '
                f'全面多頭，市場廣度充足，可積極持股')
        elif _ratio2 >= 60 and _adl_above_ma:
            _adl_concl.append(
                f'✅ 上漲佔比 {_ad_ratio_int}%（60~70%）+ ADL在MA上 → '
                f'多頭健康，可持股偏多，注意量能配合')
        elif _ratio2 < 40 and _adl_below_ma:
            _adl_concl.append(
                f'🔴 上漲佔比 {_ad_ratio_int}%（<40%）+ ADL破MA → '
                f'廣泛賣壓，空頭格局，建議降倉保守')
        elif _ratio2 < 40:
            _adl_concl.append(
                f'⚠️ 上漲佔比 {_ad_ratio_int}%（<40%）→ '
                f'廣度不足，多數股票弱勢，不宜追高')
        elif _adl_below_ma:
            _adl_concl.append(
                f'⚠️ 上漲佔比 {_ad_ratio_int}% 但 ADL跌破MA → '
                f'趨勢轉弱訊號，觀望等方向確認')
        else:
            _adl_concl.append(
                f'⚪ 上漲佔比 {_ad_ratio_int}%（40~60%）→ '
                f'廣度中性，盤整格局，等待方向選擇')
        for _ac in _adl_concl:
            _ac_c = ('#2ea043' if '✅' in _ac or '可進攻' in _ac
                     else '#da3633' if '🔴' in _ac or '警告' in _ac
                     else '#d29922' if '⚠️' in _ac else '#388bfd')
            _ac_dot = '🟢' if '✅' in _ac else ('🔴' if '🔴' in _ac else ('🟡' if '⚠️' in _ac else '⚪'))
            _ac_clean = _ac.lstrip('✅⚠️🔴⚪').strip()
            st.markdown(
                f'<div style="border-left:5px solid {_ac_c};background:#0d1117;'
                f'padding:9px 14px;border-radius:0 8px 8px 0;margin:5px 0;">'
                f'<span style="font-size:14px;font-weight:900;color:{_ac_c};">{_ac_dot} {_ac_clean}</span><br>'
                f'<span style="font-size:10px;color:#484f58;">詳細判讀 → 「策略手冊」Tab</span>'
                f'</div>',
                unsafe_allow_html=True
            )

    # ── ADL 即時補救（TWSE 封鎖時自動觸發 FinMind）─────────────────
    if (df_adl is None or df_adl.empty):
        _adl_ph = st.empty()
        _adl_ph.info('⏳ ADL 資料載入中...')
        try:
            from daily_checklist import fetch_adl as _fa
            _tok_rt = os.environ.get('FINMIND_TOKEN','') or FINMIND_TOKEN
            _df_rt  = _fa(days=60, token=_tok_rt)
            if _df_rt is not None and not _df_rt.empty:
                df_adl = _df_rt
                _cd_u  = st.session_state.get('cl_data', {})
                _cd_u['adl'] = df_adl
                st.session_state['cl_data'] = _cd_u
        except Exception as _adl_e:
            print(f'[ADL補救] {_adl_e}')
        finally:
            _adl_ph.empty()

    if df_adl is not None and not df_adl.empty:
        _adl_last   = df_adl.iloc[-1]
        _adl_up     = int(_adl_last.get('up', 0))
        _adl_down   = int(_adl_last.get('down', 0))
        _adl_ad     = int(_adl_last.get('ad', 0))
        _adl_ratio  = float(_adl_last.get('ad_ratio', 50))
        _adl_val    = float(_adl_last.get('adl', 0))
        _adl_ma20   = df_adl['adl_ma20'].dropna().iloc[-1] if df_adl['adl_ma20'].notna().any() else _adl_val
        _adl_trend  = '↑' if _adl_val > _adl_ma20 else '↓'
        _adl_color  = '#da3633' if _adl_ad > 0 else '#2ea043'
        _adl_signal = ('🟢 廣度擴張，多頭健康' if _adl_ad > 200
                       else ('🟡 廣度收窄，市場整理' if _adl_ad >= -100
                       else '🔴 廣度萎縮，主力集中在少數股'))
        # 背離偵測（指數上漲但 ADL 下跌 = 警告）
        _twii_pct = tw_s.get('台股加權指數', {}).get('pct', 0) if tw_s.get('台股加權指數') else 0
        _divergence = _twii_pct > 0.5 and _adl_ad < -50

        # KPI 卡片
        _adl_cols = st.columns(4)
        with _adl_cols[0]:
            st.markdown(kpi('今日上漲家數', f'{_adl_up:,}', '上漲股票總數', '#3fb950', '#0d2818'), unsafe_allow_html=True)
        with _adl_cols[1]:
            st.markdown(kpi('今日下跌家數', f'{_adl_down:,}', '下跌股票總數', '#f85149', '#2a0d0d'), unsafe_allow_html=True)
        with _adl_cols[2]:
            st.markdown(kpi('AD值（今日）', f'{_adl_ad:+,}', '漲家－跌家', _adl_color, '#0d1117'), unsafe_allow_html=True)
        with _adl_cols[3]:
            # 廣度健康評分：0-100（對應全市場健康度）
            _breadth_score = round(_adl_ratio)  # 直接用上漲佔比%當分數
            _bs_color = '#3fb950' if _breadth_score>=60 else ('#d29922' if _breadth_score>=40 else '#f85149')
            _bs_label = '🟢 廣度健康' if _breadth_score>=60 else ('🟡 中性' if _breadth_score>=40 else '🔴 廣度不足')
            st.markdown(kpi('全市場健康度', f'{_breadth_score}分', _bs_label, _bs_color, '#0d1117'), unsafe_allow_html=True)
            # 同步更新旌旗指數（如果尚未由 ADL 計算）
            if not st.session_state.get('jingqi_info'):
                st.session_state['jingqi_info'] = {
                    'avg': _adl_ratio, 'pos': ('80~100%' if _adl_ratio>=60 else ('50~70%' if _adl_ratio>=40 else '20~40%')),
                    'regime': ('bull' if _adl_ratio>=60 else ('neutral' if _adl_ratio>=40 else 'bear')),
                    'color': _bs_color, 'label': _bs_label, 'source': 'ADL廣度',
                    'pct20':_adl_ratio,'pct60':_adl_ratio*0.9,'pct120':_adl_ratio*0.8,'pct240':_adl_ratio*0.7,
                }

        # 信號提示
        _sig_color = '#3fb950' if _adl_ad > 200 else ('#d29922' if _adl_ad >= -100 else '#f85149')
        st.markdown(
            f'<div style="background:#0d1117;border-left:4px solid {_sig_color};border-radius:0 8px 8px 0;'
            f'padding:10px 14px;margin:8px 0;">'
            f'<span style="color:{_sig_color};font-weight:700;">{_adl_signal}</span>'
            f'　｜　騰落線 {_adl_val:,.0f} {_adl_trend} MA20({_adl_ma20:,.0f})'
            + ('　⚠️ <span style="color:#f85149;font-weight:700;">背離警告：指數漲但廣度萎縮！</span>' if _divergence else '') +
            '</div>', unsafe_allow_html=True)

        # 騰落線圖（ADL + MA20 + 上漲佔比）
        _fig_adl = go.Figure()
        # 上漲佔比柱狀圖（背景）
        _ratio_colors = ['rgba(63,185,80,0.4)' if v >= 50 else 'rgba(248,81,73,0.4)' for v in df_adl['ad_ratio'].fillna(50)]
        _fig_adl.add_trace(go.Bar(
            x=df_adl['date'], y=df_adl['ad_ratio'],
            name='上漲佔比%', marker_color=_ratio_colors,
            yaxis='y2', opacity=0.5,
            hovertemplate='%{x|%Y-%m-%d}<br>上漲佔比: %{y:.1f}%<extra></extra>'
        ))
        # ADL 線
        _fig_adl.add_trace(go.Scatter(
            x=df_adl['date'], y=df_adl['adl'],
            name='騰落線 ADL', line=dict(color='#58a6ff', width=2.5),
            hovertemplate='%{x|%Y-%m-%d}<br>ADL: %{y:,.0f}<extra></extra>'
        ))
        # ADL MA20
        _fig_adl.add_trace(go.Scatter(
            x=df_adl['date'], y=df_adl['adl_ma20'],
            name='ADL MA20', line=dict(color='#ffd700', width=1.5, dash='dot'),
            hovertemplate='%{x|%Y-%m-%d}<br>MA20: %{y:,.0f}<extra></extra>'
        ))
        # 零軸
        _fig_adl.add_hline(y=0, line_dash='dash', line_color='#484f58', opacity=0.5)
        _fig_adl.update_layout(
            title=dict(text='台股騰落線（ADL）— 衡量多數股票是否真的在漲', font=dict(color='#8b949e', size=13)),
            height=320, plot_bgcolor='#0e1117', paper_bgcolor='#0e1117',
            font=dict(color='white', size=11),
            legend=dict(orientation='h', y=-0.15, bgcolor='rgba(0,0,0,0)'),
            margin=dict(l=10, r=10, t=40, b=10),
            hovermode='x unified',
            yaxis=dict(title='ADL 累積值', gridcolor='#21262d', zeroline=True),
            yaxis2=dict(title='上漲佔比%', gridcolor='rgba(0,0,0,0)',
                        overlaying='y', side='right', range=[0, 100], showgrid=False),
            xaxis=dict(gridcolor='#21262d', tickformat='%m/%d'),
        )
        st.plotly_chart(_fig_adl, width='stretch', config={'displayModeBar': False})

        # ── ADL vs 加權指數 雙軸背離圖 ──────────────────────────
        _twii_data = tw.get('台股加權指數')
        if _twii_data is not None and not _twii_data.empty:
            _cc_t = 'close' if 'close' in _twii_data.columns else 'Close'
            if _cc_t in _twii_data.columns:
                # 對齊日期
                _adl_dates = df_adl['date'].dt.date.tolist()
                _twii_sub = _twii_data.copy()
                _twii_sub.index = _twii_sub.index.date if hasattr(_twii_sub.index, 'date') else _twii_sub.index
                _twii_aligned = [float(_twii_sub.loc[d, _cc_t]) if d in _twii_sub.index else None
                                 for d in _adl_dates]
                _fig_div = go.Figure()
                _fig_div.add_trace(go.Scatter(
                    x=df_adl['date'], y=df_adl['adl'],
                    name='騰落線 ADL', line=dict(color='#58a6ff', width=2),
                    hovertemplate='%{x|%m/%d}<br>ADL: %{y:,.0f}<extra></extra>'
                ))
                _fig_div.add_trace(go.Scatter(
                    x=df_adl['date'], y=_twii_aligned,
                    name='加權指數', line=dict(color='#ffd700', width=2, dash='dot'),
                    yaxis='y2',
                    hovertemplate='%{x|%m/%d}<br>指數: %{y:,.0f}<extra></extra>'
                ))
                # 背離區域標示
                if _divergence:
                    _fig_div.add_annotation(
                        x=df_adl['date'].iloc[-1], y=_adl_val,
                        text='⚠️ 背離警告', showarrow=True, arrowhead=2,
                        font=dict(color='#f85149', size=12), bgcolor='#2a0d0d'
                    )
                _fig_div.update_layout(
                    title=dict(text='🔍 ADL vs 加權指數（看背離是否存在）', font=dict(color='#8b949e', size=12)),
                    height=280, plot_bgcolor='#0e1117', paper_bgcolor='#0e1117',
                    font=dict(color='white', size=10),
                    legend=dict(orientation='h', y=-0.2, bgcolor='rgba(0,0,0,0)'),
                    margin=dict(l=10,r=60,t=40,b=10),
                    hovermode='x unified',
                    yaxis=dict(title='ADL', gridcolor='#21262d'),
                    yaxis2=dict(title='加權指數', overlaying='y', side='right',
                               gridcolor='rgba(0,0,0,0)', showgrid=False),
                    xaxis=dict(gridcolor='#21262d', tickformat='%m/%d'),
                )
                st.plotly_chart(_fig_div, width='stretch', config={'displayModeBar': False})
                if _divergence:
                    st.error('⚠️ 背離警告：大盤指數上漲，但騰落線下跌！代表只有少數權值股在撐盤，市場廣度惡化，要注意風險！')

        # 近5日 AD 明細表
        _adl_tbl = df_adl.tail(5)[['date','up','down','ad','ad_ratio','adl']].copy()
        _adl_tbl['date'] = _adl_tbl['date'].dt.strftime('%m/%d')
        _adl_tbl = _adl_tbl.rename(columns={
            'date':'日期','up':'上漲','down':'下跌','ad':'AD值','ad_ratio':'上漲佔比%','adl':'ADL累積'
        }).sort_values('日期', ascending=False)
        st.dataframe(_adl_tbl, use_container_width=True, hide_index=True,
            column_config={
                '上漲佔比%': st.column_config.NumberColumn('上漲佔比%', format='%.1f%%'),
                'ADL累積': st.column_config.NumberColumn('ADL累積', format='%,.0f'),
                'AD值': st.column_config.NumberColumn('AD值', format='%+d'),
            })


    else:
        _adl_debug = st.session_state.get('adl_debug_msg', '')
        if _adl_debug:
            st.error(f'❌ 騰落指標抓取失敗：{_adl_debug}')
            st.caption('💡 請到 Colab 查看 [ADL] 開頭的輸出訊息')
        else:
            st.info('📡 點擊「🚀 一鍵更新全部數據」載入騰落指標')
        # [Step 4] 備援：即時抓取漲跌家數 — 委派 tw_macro.fetch_twse_breadth()（走 NAS proxy）
        _adl_today_cols = st.columns(3)
        try:
            from tw_macro import fetch_twse_breadth
            _bd = fetch_twse_breadth()
            _up_v, _dn_v = _bd.get('adv'), _bd.get('dec')
            if _up_v is not None and _dn_v is not None and (_up_v + _dn_v) > 50:
                _ratio_v = round(_up_v / (_up_v + _dn_v) * 100, 1)
                _col_v = '#3fb950' if _ratio_v >= 60 else ('#d29922' if _ratio_v >= 40 else '#f85149')
                with _adl_today_cols[0]:
                    st.markdown(kpi('今日上漲家數', f'{_up_v:,}', '即時TWSE', '#3fb950', '#0d2818'), unsafe_allow_html=True)
                with _adl_today_cols[1]:
                    st.markdown(kpi('今日下跌家數', f'{_dn_v:,}', '即時TWSE', '#f85149', '#2a0d0d'), unsafe_allow_html=True)
                with _adl_today_cols[2]:
                    st.markdown(kpi('全市場健康度', f'{_ratio_v:.1f}%',
                                    ('廣度健康' if _ratio_v >= 60 else ('中性' if _ratio_v >= 40 else '廣度不足')),
                                    _col_v, '#0d1117'), unsafe_allow_html=True)
                # 同步旌旗指數（schema 完全保留）
                if not st.session_state.get('jingqi_info'):
                    st.session_state['jingqi_info'] = {
                        'avg': _ratio_v,
                        'pos': ('80~100%' if _ratio_v >= 60 else ('50~70%' if _ratio_v >= 40 else '20~40%')),
                        'regime': ('bull' if _ratio_v >= 60 else ('neutral' if _ratio_v >= 40 else 'bear')),
                        'color': _col_v,
                        'label': ('🟢 多頭積極' if _ratio_v >= 60 else ('🟡 中性均衡' if _ratio_v >= 40 else '🔴 保守防禦')),
                        'source': 'TWSE即時',
                        'pct20': _ratio_v, 'pct60': _ratio_v * 0.9,
                        'pct120': _ratio_v * 0.8, 'pct240': _ratio_v * 0.7,
                    }
        except Exception as _adl_e:
            pass

    st.markdown('<hr style="border-color:#21262d;margin:8px 0;">', unsafe_allow_html=True)
    st.markdown('<div style="font-size:10px;color:#484f58;text-transform:uppercase;letter-spacing:1px;margin:4px 0;">🌐 國際市場</div>', unsafe_allow_html=True)
    st.markdown(section_header('六','🖥️ 美股科技巨頭（台股明天的風向球）','🖥️'),unsafe_allow_html=True)
    _sox6 = intl_s.get('費城半導體 SOX') or tech_s.get('費城半導體 SOX')
    _nvda6 = next((tech_s[k] for k in tech_s if 'NVDA' in k or '輝達' in k), None)
    if _sox6:
        _sp6 = _sox6.get('pct', 0)
        if _sp6 > 2:
            _t6c = f'費半強漲 {_sp6:+.1f}%，明日台積電/聯發科可望跟漲'
            _t6a = '科技類股可持有或加碼'
        elif _sp6 > 0:
            _t6c = f'費半小漲 {_sp6:+.1f}%，台股科技偏多但力道有限'
            _t6a = '持有觀察，不急著追高'
        elif _sp6 < -2:
            _t6c = f'費半重挫 {_sp6:+.1f}%，明日台股科技開低機率高'
            _t6a = '設好停損，避免隔日追殺'
        else:
            _t6c = f'費半小跌 {_sp6:+.1f}%，短線偏空但未破關鍵支撐'
            _t6a = '觀望等待方向確認'
        _nvda_txt = f' | NVDA {_nvda6.get("pct",0):+.1f}%' if _nvda6 else ''
        _t6_ind = f'費半 SOX {_sp6:+.1f}%{_nvda_txt}'
    else:
        _t6c = '技術股數據尚未載入，請點擊「🚀 一鍵更新全部數據」'
        _t6a = ''
        _t6_ind = '費半+美股科技'
    st.markdown(teacher_conclusion('蔡森', _t6_ind, _t6c, _t6a), unsafe_allow_html=True)
    tc_list = list(TECH_MAP.keys())
    tr1=st.columns(4)
    tr2=st.columns(len(tc_list[4:]) if len(tc_list)>4 else 1)
    for i,(col,name) in enumerate(zip(tr1,tc_list[:4])):
        with col:
            st.markdown(stat_card(name,tech_s.get(name),'USD',name in tech_s),unsafe_allow_html=True)
    for i,(col,name) in enumerate(zip(tr2,tc_list[4:])):
        with col:
            st.markdown(stat_card(name,tech_s.get(name),'USD',name in tech_s),unsafe_allow_html=True)
    if tech:
        st.plotly_chart(multi_chart(tech,'科技巨頭標準化比較',norm=True,height=250),
                        width='stretch',config={'displayModeBar':False})
        clrs=COLORS_7 if isinstance(COLORS_7,list) else list(COLORS_7.values())
        sp1=st.columns(4)
        sp2=st.columns(len(tc_list[4:]) if len(tc_list)>4 else 1)
        for i,(col,name) in enumerate(zip(sp1,tc_list[:4])):
            with col:
                if name in tech:
                    st.plotly_chart(sparkline(tech[name],name,clrs[i] if i<len(clrs) else '#58a6ff'),
                                    width='stretch',config={'displayModeBar':False})
        for i,(col,name) in enumerate(zip(sp2,tc_list[4:])):
            with col:
                if name in tech:
                    st.plotly_chart(sparkline(tech[name],name,clrs[i+4] if i+4<len(clrs) else '#ffd700'),
                                    width='stretch',config={'displayModeBar':False})
    _tsm = tech_s.get('台積電 ADR')
    _nvda = tech_s.get('輝達 NVDA')
    _concl_tech = []
    if _tsm:
        _concl_tech.append(f'TSM ADR {_tsm["last"]:.2f} ({_tsm["pct"]:+.1f}%) → {"✅ 台積電強→明日2330有望跟漲" if _tsm["pct"]>1 else ("⚠️ 台積電弱→注意2330壓力" if _tsm["pct"]<-1 else "⚪ 台積電持平")}')
    if _nvda:
        _concl_tech.append(f'NVDA {_nvda["last"]:.2f} ({_nvda["pct"]:+.1f}%) → {"✅ AI族群情緒熱" if _nvda["pct"]>2 else ("🔴 AI族群降溫" if _nvda["pct"]<-2 else "⚪ AI族群穩定")}')
    for _tc2 in _concl_tech:
        st.markdown(f'<div style="color:#c9d1d9;font-size:13px;padding:3px 0;">• {_tc2}</div>', unsafe_allow_html=True)

    st.markdown('<hr style="border-color:#21262d;margin:14px 0;">',unsafe_allow_html=True)
    st.markdown(section_header('七','💰 資金環境 × 估值（M1B-M2 + 年線乖離）','💰'),unsafe_allow_html=True)

    # ── M1B-M2 年增率（FinMind）──────────────────────────────
    _m1b_info = st.session_state.get('m1b_m2_info')
    _bias_info = st.session_state.get('bias_info')

    # ── 弘爺 × 孫慶龍 結論（標題下方直接顯示）──────────────────
    _macro_concl = []
    if _m1b_info:
        _diff2 = _m1b_info.get('m1b_yoy', 0) - _m1b_info.get('m2_yoy', 0)
        if _diff2 > 0:
            _macro_concl.append(f'✅ M1B-M2={_diff2:+.2f}% 正值 → 策略3：資金行情啟動，大膽做多！（領先大盤3~6月）')
        elif _diff2 > -2:
            _macro_concl.append(f'⚠️ M1B-M2={_diff2:+.2f}% 接近0 → 策略3：資金動能趨緩，減碼等待訊號確認')
        else:
            _macro_concl.append(f'🔴 M1B-M2={_diff2:+.2f}% 負值 → 策略3：資金撤離，空手觀望！')
    if _bias_info:
        _bv2 = _bias_info.get('bias_240', 0)
        if _bv2 > 20:
            _macro_concl.append(f'⚠️ 年線乖離 {_bv2:+.1f}% 過大 → 策略1：開始分批減碼（乖離>20%啟動停利）')
        elif _bv2 < -20:
            _macro_concl.append(f'✅ 年線乖離 {_bv2:+.1f}% 嚴重低估 → 策略1：左側交易最佳布局區，大膽加碼！')
        else:
            _macro_concl.append(f'✅ 年線乖離 {_bv2:+.1f}% 正常 → 策略1：可持股，按計畫操作')
    for _mc2 in _macro_concl:
        _mc3 = _mc2.replace('✅','').replace('⚠️','').replace('🔴','').strip()
        if '→' in _mc3:
            _ind7, _res7 = _mc3.split('→', 1)
            _col7 = '#f85149' if any(k in _mc2 for k in ['🔴','⚠️']) else '#3fb950'
            _tchr7 = '弘爺' if 'M1B' in _mc2 else '孫慶龍'
            st.markdown(teacher_conclusion(_tchr7, _ind7.strip(), _res7.strip(), color=_col7), unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="color:#c9d1d9;font-size:12px;padding:2px 6px;">• {_mc2}</div>', unsafe_allow_html=True)

    _m_cols = st.columns(3)
    with _m_cols[0]:
        if _m1b_info:
            _m1b_v  = _m1b_info.get('m1b_yoy', 0)
            _m2_v   = _m1b_info.get('m2_yoy', 0)
            _diff   = round(_m1b_v - _m2_v, 2)
            _mc     = '#da3633' if _diff > 0 else '#2ea043'
            _ml     = '✅ 資金流入股市' if _diff > 0 else '🔴 資金撤離股市'
            _proxy_note = '（大盤動能代理估算）' if _m1b_info.get('is_proxy') else ''
            st.markdown(kpi('M1B-M2 差距', f'{_diff:+.2f}%{_proxy_note}',
                            f'M1B:{_m1b_info.get("m1b_yoy",0):.1f}%  M2:{_m1b_info.get("m2_yoy",0):.1f}%  {_ml}', _mc, '#0d1117'), unsafe_allow_html=True)
        else:
            st.markdown(kpi('M1B-M2 差距', '抓取中', '更新總經數據後自動計算', '#484f58', '#0d1117'), unsafe_allow_html=True)

    with _m_cols[1]:
        if _bias_info:
            _bias_v = _bias_info.get('bias_240', 0)
            _bc     = '#f85149' if _bias_v > 20 else ('#3fb950' if _bias_v < -20 else '#d29922')
            _bl     = ('⚠️ 乖離過大，考慮減碼' if _bias_v > 20
                       else ('✅ 嚴重低估，可積極布局' if _bias_v < -20
                       else '⚪ 乖離正常區間'))
            _est_note = '（估算）' if _bias_info.get('is_estimated') else ''
            _days_note = f" {_bias_info.get('data_days',0)}天資料" if _bias_info.get('is_estimated') else ''
            st.markdown(kpi(f'年線乖離率(240MA){_est_note}', f'{_bias_v:+.1f}%',
                            f'{_bl}{_days_note}', _bc, '#0d1117'), unsafe_allow_html=True)
        else:
            st.markdown(kpi('年線乖離率(240MA)', '計算中', '大盤收盤/年線', '#484f58', '#0d1117'), unsafe_allow_html=True)

    with _m_cols[2]:
        if _bias_info:
            _bias_20 = _bias_info.get('bias_20', 0)
            _bc20    = '#f85149' if _bias_20 > 10 else ('#3fb950' if _bias_20 < -10 else '#d29922')
            _bl20    = ('⚠️ 月線乖離過大，短線過熱' if _bias_20 > 10
                        else ('✅ 月線負乖離，考慮進場' if _bias_20 < -10
                        else '⚪ 月線乖離正常'))
            st.markdown(kpi('月線乖離率(20MA)', f'{_bias_20:+.1f}%',
                            _bl20, _bc20, '#0d1117'), unsafe_allow_html=True)
        else:
            st.markdown(kpi('月線乖離率(20MA)', '計算中', '', '#484f58', '#0d1117'), unsafe_allow_html=True)

    st.markdown('<hr style="border-color:#21262d;margin:14px 0;">',unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════
    # SECTION 八: 總經拼圖 v4.0 (景氣位階 × 前瞻需求 × 全球風險)
    # ══════════════════════════════════════════════════════════════
    st.markdown(section_header('八','🌐 總經拼圖 v4.0（景氣位階 × 前瞻需求 × 全球風險）','🌐'),unsafe_allow_html=True)

    # ── 🔰 故事化白話解讀（純疊加；解釋三塊拼圖如何「合在一起看」，非重複各 KPI 副標）──
    with st.expander('🔰 這張「總經拼圖」在拼什麼？三塊怎麼一起看？'):
        st.markdown('''這一區把三種「大環境訊號」拼起來，判斷台股的外部是順風還是逆風：

1. **景氣位階（現在冷熱）** — NDC 景氣燈號：藍燈=景氣冷（衰退）、綠燈=穩定、紅燈=過熱，分數越高景氣越熱。
2. **前瞻需求（未來動能）** — 外銷訂單 YoY、台灣 PMI，領先實際營收約 1~2 個月；PMI 以 **50 為榮枯線**（>50 擴張、<50 收縮）。
3. **全球風險（外部壓力）** — 美國核心 CPI、VIX、美債殖利率、美元指數；通膨高或恐慌高 → 外資容易從台股提款。

**怎麼合著看？**
- 三塊都偏多（景氣穩+訂單成長+風險低）→ 基本面順風，可較積極。
- 互相打架（如景氣熱但 PMI 轉弱、外銷成長但 CPI 飆高）→ 留意背離，降低部位。
- 多塊轉空 → 基本面逆風，優先保留現金。

> 💡 這區看的是「中長期基本面」，和最上方的紅綠燈（偏即時多空）互相搭配，不是互相取代。''')

    st.divider()

    # ── 總經自動警示看板（VIX / CPI / 10Y / DXY / PCR）────────
    _ma_snap   = fetch_macro_snapshot(
        session_macro=st.session_state.get('macro_info'),
        session_li=st.session_state.get('li_latest'),
        session_m1b2=st.session_state.get('m1b_m2_info'),
    )
    _ma_alerts = check_macro_alerts(_ma_snap)
    st.session_state['macro_alerts'] = _ma_alerts   # 供 Section 九/十共用
    st.session_state['ma_snap']      = _ma_snap     # 供 tab_stock AI Prompt 引用 VIX/CPI/US10Y/DXY
    render_macro_alerts(_ma_alerts)

    _macro_info = st.session_state.get('macro_info') or {}
    _m8_ndc   = _macro_info.get('ndc_signal')
    _m8_exp   = _macro_info.get('tw_export')
    _m8_pmi   = _macro_info.get('ism_pmi')
    _m8_cpi   = _macro_info.get('us_core_cpi')
    _m8_vix   = _macro_info.get('vix')

    # ── Row 1: NDC燈號 | 外銷訂單YoY | 🇹🇼 台灣 PMI ──────────
    _s8c1 = st.columns(3)

    with _s8c1[0]:
        if _m8_ndc:
            _sc8   = float(_m8_ndc.get('score', 0))
            _nc8   = ('#f85149' if _sc8 >= 38 else '#d29922' if _sc8 >= 32 else
                      '#3fb950' if _sc8 >= 23 else '#58a6ff')
            _nl8   = ('🔴 紅燈 過熱' if _sc8 >= 38 else '🟡 黃紅燈 繁榮' if _sc8 >= 32 else
                      '🟢 綠燈 穩定' if _sc8 >= 23 else '🔵 黃藍燈 趨緩' if _sc8 >= 17 else '🔵 藍燈 衰退')
            _nd8   = f" ({_m8_ndc.get('date','')})" if _m8_ndc.get('date') else ''
            _ndc_title8 = 'NDC 景氣燈號'
            st.markdown(kpi(_ndc_title8, f'{_sc8:.0f} 分', f'{_nl8}{_nd8}', _nc8, '#0d1117'), unsafe_allow_html=True)
        else:
            st.markdown(kpi('NDC 景氣燈號', '待取得', '9分藍燈→45分紅燈（StockFeel+MacroMicro）', '#484f58', '#0d1117'), unsafe_allow_html=True)

    with _s8c1[1]:
        if _m8_exp:
            _ey8 = _m8_exp.get('yoy', 0)
            _ec8 = '#3fb950' if _ey8 > 0 else '#f85149'
            _el8 = ('✅ 出口動能正成長，基本面有撐' if _ey8 > 0 else
                    ('🔴 外銷連兩月衰退，基本面警示！' if _ey8 < -5 else '⚠️ 外銷轉弱，留意基本面背離'))
            st.markdown(kpi('外銷訂單 YoY', f'{_ey8:+.1f}%', _el8, _ec8, '#0d1117'), unsafe_allow_html=True)
        else:
            st.markdown(kpi('外銷訂單 YoY', '待取得', '領先實際營收 1~2 月', '#484f58', '#0d1117'), unsafe_allow_html=True)

    with _s8c1[2]:
        if _m8_pmi:
            _pv8 = _m8_pmi.get('value', 50)
            _pmi_title = '🇹🇼 台灣 PMI'
            _pmi_榮枯 = 50
            _pc8 = '#3fb950' if _pv8 >= _pmi_榮枯 else ('#d29922' if _pv8 >= (_pmi_榮枯-3) else '#f85149')
            _pl8 = ('✅ 製造業擴張' if _pv8 >= _pmi_榮枯 else
                    ('⚠️ 輕微收縮，留意內需與外銷動能' if _pv8 >= (_pmi_榮枯-3) else '🔴 嚴重收縮，台股出口/電子股承壓'))
            _pd8 = f" ({_m8_pmi.get('date','')})" if _m8_pmi.get('date') else ''
            st.markdown(kpi(_pmi_title, f'{_pv8:.1f}', f'{_pl8}{_pd8}', _pc8, '#0d1117'), unsafe_allow_html=True)
        else:
            st.markdown(kpi('🇹🇼 台灣 PMI', '待取得', '50為榮枯線（CIER 中華經濟研究院）', '#484f58', '#0d1117'), unsafe_allow_html=True)

    # ── Row 2: 美國核心CPI | VIX 時間序列圖 ────────────────
    _s8c2 = st.columns([1, 2])

    with _s8c2[0]:
        if _m8_cpi:
            _cy8 = _m8_cpi.get('yoy', 0)
            _cc8 = '#f85149' if _cy8 > 3.5 else ('#d29922' if _cy8 > 2.5 else '#3fb950')
            _cl8 = ('🔴 通膨偏高，Fed升息壓力大' if _cy8 > 3.5 else
                    ('⚠️ 通膨黏性，降息路徑放緩' if _cy8 > 2.5 else '✅ 通膨受控，降息可期'))
            _cdate8 = f" ({_m8_cpi.get('date','')})" if _m8_cpi.get('date') else ''
            st.markdown(kpi('美國核心CPI YoY', f'{_cy8:+.2f}%', f'{_cl8}{_cdate8}', _cc8, '#0d1117'), unsafe_allow_html=True)
            st.caption('💡 Fed 目標值 = 2%。CPI > 3.5% 時升息預期升高，外資易從台股提款。')
        else:
            st.markdown(kpi('美國核心CPI YoY', '待取得', 'Fed 目標值 = 2%', '#484f58', '#0d1117'), unsafe_allow_html=True)

    with _s8c2[1]:
        if _m8_vix and _m8_vix.get('dates'):
            _vcur8 = _m8_vix.get('current', 0)
            _vma8  = _m8_vix.get('ma20', 0)
            _vc8   = '#f85149' if _vcur8 >= 30 else ('#d29922' if _vcur8 >= 20 else '#3fb950')
            _vl8   = ('🚨 恐慌衝頂，強制空手' if _vcur8 >= 30 else
                      ('⚠️ 市場緊張，降低持倉' if _vcur8 >= 20 else '✅ 市場平靜'))
            import plotly.graph_objects as _go8
            _vfig8 = _go8.Figure()
            _vfig8.add_trace(_go8.Scatter(
                x=_m8_vix['dates'], y=_m8_vix['values'],
                mode='lines', line=dict(color='#58a6ff', width=1.5),
                fill='tozeroy', fillcolor='rgba(88,166,255,0.08)', name='VIX'))
            _vfig8.add_hline(y=25, line_dash='dash', line_color='#d29922', opacity=0.6,
                             annotation_text='25 警戒', annotation_font_color='#d29922')
            _vfig8.add_hline(y=30, line_dash='dash', line_color='#f85149', opacity=0.6,
                             annotation_text='30 危機', annotation_font_color='#f85149')
            _vfig8.add_annotation(x=_m8_vix['dates'][-1], y=_vcur8,
                                  text=f'<b>{_vcur8}</b>', showarrow=True, arrowhead=2,
                                  font=dict(color=_vc8, size=12),
                                  bgcolor='#0d1117', bordercolor=_vc8)
            _vfig8.update_layout(
                height=170, margin=dict(l=35, r=60, t=30, b=20),
                paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
                font=dict(color='#8b949e', size=10), showlegend=False,
                xaxis=dict(showgrid=False, color='#484f58'),
                yaxis=dict(showgrid=True, gridcolor='#21262d', color='#484f58'),
                title=dict(text=f'VIX 恐慌指數 {_vcur8}（MA20={_vma8}）— {_vl8}',
                           font=dict(size=11, color=_vc8), x=0))
            st.plotly_chart(_vfig8, width='stretch')
        else:
            st.markdown(kpi('VIX 恐慌指數', '待取得', '≥25警戒 / ≥30危機→強制空手', '#484f58', '#0d1117'), unsafe_allow_html=True)

    # ── v4.0 總經否決權 ─────────────────────────────────────
    _veto8 = []
    if _m8_vix and _m8_vix.get('current', 0) >= 30:
        _veto8.append(('🚨', f'VIX={_m8_vix["current"]} ≥ 30：全球流動性危機，無視所有技術面買訊，強制空手！', '#f85149'))
    if _m8_pmi and _m8_pmi.get('value', 55) < 48:
        _veto8.append(('⚠️', f'🇹🇼 台灣 PMI={_m8_pmi["value"]} < 48：在地製造業需求急凍，若 SOX 仍漲為「無基之彈」，降低持股水位', '#d29922'))
    if _m8_cpi and _m8_cpi.get('yoy', 0) > 4.0:
        _veto8.append(('⚠️', f'核心CPI={_m8_cpi["yoy"]:.1f}% > 4%：通膨嚴峻，外資提款風險升高，注意匯率變動', '#d29922'))
    if _m8_exp and _m8_exp.get('yoy', 0) < -5:
        _veto8.append(('⚠️', f'外銷訂單 YoY={_m8_exp["yoy"]:.1f}%：連續衰退，股價與基本面嚴重背離，謹慎追高', '#d29922'))
    _crisis_buy = _m8_ndc and _m8_ndc.get('score', 25) <= 16
    if _crisis_buy:
        _veto8.append(('💡', f'NDC燈號={_m8_ndc["score"]:.0f}分（藍燈）：實體景氣衰退但為左側交易黃金布局時機！低基期好股勇敢建倉', '#3fb950'))

    if _veto8:
        _has_veto = any(e[0] != '💡' for e in _veto8)
        _exp_title = ('🚨 v4.0 總經否決權已觸發（展開看詳情）' if _has_veto else
                      '💡 v4.0 危機入市訊號（展開看詳情）')
        with st.expander(_exp_title, expanded=_has_veto):
            for _icon8, _msg8, _col8 in _veto8:
                st.markdown(
                    f'<div style="border-left:3px solid {_col8};padding:6px 12px;'
                    f'margin:4px 0;color:{_col8};font-size:13px;">{_icon8} {_msg8}</div>',
                    unsafe_allow_html=True)
    elif any([_m8_vix, _m8_pmi, _m8_cpi, _m8_ndc]):
        st.success('✅ v4.0 總經否決權：無觸發 — 當前宏觀環境無系統性風險訊號')

    # ── Section 八 v4.0 動態結論（宏爺VIX否決權 × 孫慶龍估值/CLI矩陣）────
    _bias_info8 = st.session_state.get('bias_info') or {}
    _b240_8     = float(_bias_info8.get('bias_240', 0))
    _vix_now8   = float(_m8_vix.get('current', 0)) if _m8_vix else None
    # CLI：OECD CLI 榮枯線 = 100，取自 _m8_pmi（is_oecd_cli=True 時）
    _cli_8 = None
    if _m8_pmi and _m8_pmi.get('is_oecd_cli'):
        _cli_8 = float(_m8_pmi.get('value', 100))

    # VIX 防呆：若值 > 100 代表 API 錯置
    if _vix_now8 is not None and _vix_now8 > 100:
        st.error(f'❌ VIX 數值異常（{_vix_now8:.0f}），疑似 API 變數映射錯誤，結論暫不顯示。請重新整理。')
    else:
        # ── 宏爺：VIX 總經否決權 ──────────────────────────────
        if _vix_now8 is not None:
            if _vix_now8 >= 30:
                _hyc8 = '#f85149'
                _hyi8 = f'VIX {_vix_now8:.1f} ≥ 30'
                _hyc8t = '🔴 系統性風險爆發，觸發否決權！無視所有技術面多頭訊號，強制清倉，建議持股 0~10%，現金為王。'
            elif _vix_now8 >= 20:
                _hyc8 = '#d29922'
                _hyi8 = f'VIX {_vix_now8:.1f}（20~30 警戒）'
                _hyc8t = '🟡 波動率飆升，市場情緒轉恐慌。停止加槓桿，汰弱留強，持股上限壓縮在 30% 以下。'
            else:
                _hyc8 = '#3fb950'
                _hyi8 = f'VIX {_vix_now8:.1f} < 20（平靜期）'
                _hyc8t = '🟢 全球風險情緒穩定，未觸發否決權。回歸個股籌碼面與基本面操作。'
            st.markdown(teacher_conclusion('弘爺', _hyi8, _hyc8t, color=_hyc8), unsafe_allow_html=True)
        else:
            st.info('VIX 數據載入中，宏爺否決權暫無法判斷')

        # ── 宏爺：M1B-M2 資金動能（三段公式）────────────────────
        _m1b8_info = st.session_state.get('m1b_m2_info', {})
        if _m1b8_info and _m1b8_info.get('m1b_yoy') is not None and _m1b8_info.get('m2_yoy') is not None:
            _m1b8 = float(_m1b8_info.get('m1b_yoy', 0))
            _m2b8 = float(_m1b8_info.get('m2_yoy', 0))
            _gap8 = round(_m1b8 - _m2b8, 2)
            if _gap8 >= 1.0:
                _m1bc8 = '#3fb950'
                _m1bi8 = f'M1B-M2 Gap = +{_gap8:.2f}%（黃金交叉·熱錢狂潮）'
                _m1bt8 = (f'🔥 資金動能強勁（M1B={_m1b8:.1f}% > M2={_m2b8:.1f}%），'
                          '熱錢湧入股市，積極作多強勢股。')
            elif _gap8 >= 0:
                _m1bc8 = '#3fb950'
                _m1bi8 = f'M1B-M2 Gap = +{_gap8:.2f}%（資金溫和·中性擴張）'
                _m1bt8 = (f'💧 資金動能溫和（M1B={_m1b8:.1f}% ≥ M2={_m2b8:.1f}%），'
                          '無失血風險，回歸個股基本面與籌碼面操作。')
            else:
                _m1bc8 = '#d29922'
                _m1bi8 = f'M1B-M2 Gap = {_gap8:.2f}%（死亡交叉·資金退潮）'
                _m1bt8 = (f'📉 資金動能趨緩（M1B={_m1b8:.1f}% < M2={_m2b8:.1f}%），'
                          '資金轉向定存或匯出，減碼等待訊號確認。')
            st.markdown(teacher_conclusion('宏爺', _m1bi8, _m1bt8, color=_m1bc8), unsafe_allow_html=True)
        else:
            st.info('M1B/M2 數據載入後自動顯示宏爺資金動能判斷')

        # ── 策略1：BIAS240 × 外銷訂單 二維矩陣（v5.0）──────────────
        if _bias_info8:
            _sql_b    = _b240_8
            _exp_yoy8 = float(_m8_exp.get('yoy', 0)) if _m8_exp else None
            _exp_dt8  = _m8_exp.get('date', '') if _m8_exp else ''
            if _exp_yoy8 is not None:
                _exp_txt8 = f'外銷訂單 YoY={_exp_yoy8:+.1f}%（{_exp_dt8}）'
                if _sql_b >= 15 and _exp_yoy8 >= 10:
                    _sqc8  = '#f85149'
                    _sqi8  = f'年線乖離 +{_sql_b:.1f}% × {_exp_txt8} → 🚀 有基之彈'
                    _sqc8t = ('🚀 有基之彈（主升段狂熱）：高估值由強勁出口基本面支撐，'
                              '資金面與基本面完美共振。順勢作多，但需以月線作為嚴格停損，'
                              '跌破月線即走，切勿因多頭情緒追漲加碼。')
                elif _sql_b >= 15 and _exp_yoy8 < 0:
                    _sqc8  = '#f85149'
                    _sqi8  = f'年線乖離 +{_sql_b:.1f}% × {_exp_txt8} → ⚠️ 無基之彈'
                    _sqc8t = ('⚠️ 無基之彈（史詩級泡沫）：股價嚴重高估且出口動能衰退，'
                              '純粹資金炒作泡沫，均值回歸壓力極大。'
                              '全面出清高本夢比個股，啟動長線倉位停利，切勿追高。')
                elif _sql_b >= 15:  # Export 0~10%
                    _sqc8  = '#d29922'
                    _sqi8  = f'年線乖離 +{_sql_b:.1f}% × {_exp_txt8} → ⚡ 高估技術整理'
                    _sqc8t = ('⚡ 技術嚴重過熱，出口尚可但未爆發：高位持多需謹慎，'
                              '嚴設 ATR 動態停損，逢高獲利了結部分倉位，'
                              '等待出口數據確認是否升為「有基之彈」格局。')
                elif _sql_b > 0 and _exp_yoy8 > 0:
                    _sqc8  = '#3fb950'
                    _sqi8  = f'年線乖離 +{_sql_b:.1f}% × {_exp_txt8} → 🟢 趨勢多頭'
                    _sqc8t = ('🟢 趨勢多頭（基本面支撐）：均線多頭發散且出口擴張，'
                              '可持股按原計畫操作，回歸個股財報與籌碼面選股，'
                              '等待更明確的突破訊號加碼。')
                elif _sql_b <= 0 and _exp_yoy8 > 0:
                    _sqc8  = '#58a6ff'
                    _sqi8  = f'年線乖離 {_sql_b:.1f}% × {_exp_txt8} → 💎 長線黃金坑'
                    _sqc8t = ('💎 長線黃金坑（超跌買點）：大盤超跌至年線之下，'
                              '但出口正在成長，實體基本面有撐。'
                              '大膽重壓具備 EPS 支撐的低基期錯殺股，左側分批建倉。')
                elif _sql_b <= 0 and _exp_yoy8 <= 0:
                    _sqc8  = '#8b949e'
                    _sqi8  = f'年線乖離 {_sql_b:.1f}% × {_exp_txt8} → 📉 景氣寒冬'
                    _sqc8t = ('📉 景氣寒冬（空頭格局）：技術面與基本面雙殺，'
                              '出口衰退且指數跌破年線，景氣收縮中。'
                              '多看少做，保留高比例現金，等待出口數據翻正再佈局。')
                else:
                    _sqc8  = '#8b949e'
                    _sqi8  = f'年線乖離 {_sql_b:.1f}% × {_exp_txt8} → 🟡 整理觀望'
                    _sqc8t = '🟡 指數在年線附近整理，等待方向確認後再布局，持股偏保守。'
            else:
                # Export 無資料 → 降級用 CLI
                _cli_txt8 = (f'CLI={_cli_8:.1f}（{"擴張" if _cli_8 >= 100 else "收縮"}）'
                             if _cli_8 is not None else 'CLI未知')
                if _sql_b >= 15 and _cli_8 is not None and _cli_8 >= 100:
                    _sqc8  = '#f85149'
                    _sqi8  = f'年線乖離 +{_sql_b:.1f}% × {_cli_txt8}（CLI備援·有基之彈）'
                    _sqc8t = '🔥 技術嚴重過熱且 CLI 擴張，可順勢持多，嚴設月線停損。'
                elif _sql_b >= 15:
                    _sqc8  = '#f85149'
                    _sqi8  = f'年線乖離 +{_sql_b:.1f}% × {_cli_txt8}（CLI備援·無基之彈）'
                    _sqc8t = '⚠️ 史詩級過熱，外銷訂單無資料，謹慎追高，嚴防崩盤。'
                elif _sql_b >= 0:
                    _sqc8  = '#3fb950'
                    _sqi8  = f'年線乖離 +{_sql_b:.1f}%（趨勢多頭） {_cli_txt8}'
                    _sqc8t = '🟢 均線多頭，可持股操作，等待外銷訂單資料補充判斷。'
                elif _cli_8 is not None and _cli_8 > 100:
                    _sqc8  = '#58a6ff'
                    _sqi8  = f'年線乖離 {_sql_b:.1f}% × {_cli_txt8}（CLI備援·黃金坑）'
                    _sqc8t = '💎 CLI 擴張中大盤超跌，分批建倉低基期優質股。'
                else:
                    _sqc8  = '#8b949e'
                    _sqi8  = f'年線乖離 {_sql_b:.1f}%（整理·觀望） {_cli_txt8}'
                    _sqc8t = '🟡 外銷訂單待取得，景氣尚未明確擴張，持股保守等待訊號。'
            st.markdown(teacher_conclusion('孫慶龍', _sqi8, _sqc8t, color=_sqc8), unsafe_allow_html=True)

        # ── ⚔️ 攻擊火力分級（三環公式 SSS/A/B）────────────────────
        with st.expander('⚔️ 攻擊發動判定 — 三環公式 + 火力分級', expanded=True):
            # 取得需要的變數
            _li8      = st.session_state.get('li_latest')
            _fut8     = None
            if _li8 is not None and hasattr(_li8, 'empty') and not _li8.empty and '外資大小' in _li8.columns:
                try:
                    _fut8 = float(_li8.iloc[-1].get('外資大小', 0))
                except Exception:
                    pass
            _cl8d     = st.session_state.get('cl_data', {})
            _inst8    = _cl8d.get('inst', {})
            _fk8      = next((k for k in _inst8 if '外資' in k), None)
            _fnet8    = _inst8.get(_fk8, {}).get('net', None) if _fk8 else None
            _twii8    = tw_s.get('台股加權指數', {})
            _twd8     = tw_s.get('新台幣匯率', {})
            _sox8     = intl_s.get('費城半導體 SOX', {})
            _nvda8    = tech_s.get('輝達 NVDA', {})
            _exp_c    = float(_m8_exp.get('yoy', 0)) if _m8_exp else None
            _gap8c    = None
            if (_m1b8_info and _m1b8_info.get('m1b_yoy') is not None and
                    _m1b8_info.get('m2_yoy') is not None):
                try:
                    _gap8c = round(float(_m1b8_info['m1b_yoy']) -
                                   float(_m1b8_info['m2_yoy']), 2)
                except Exception:
                    pass

            # 三環條件評估
            _cA = _vix_now8 is not None and _vix_now8 < 20
            _cB = _fut8 is not None and _fut8 > -15000
            _cC = _exp_c is not None and _exp_c >= 10
            _cD = _gap8c is not None and _gap8c >= 1.0
            _cE = _fnet8 is not None and _fnet8 >= 100
            _cF = (float(_twii8.get('pct') or 0) > 0 and
                   float(_twd8.get('pct') or 0) < 0)
            _cG = (float(_sox8.get('pct') or 0) >= 1.5 or
                   float(_nvda8.get('pct') or 0) >= 2.0)

            _ring1_pass = _cA and _cB
            _ring2_cnt  = int(_cC) + int(_cD)
            _ring3_cnt  = int(_cE) + int(_cF) + int(_cG)

            _r1_html = (cond_badge(_cA, f'A VIX={_vix_now8:.1f}<20' if _vix_now8 else 'A VIX未知') + ' ' +
                        cond_badge(_cB, f'B 期貨={_fut8:,.0f}口' if _fut8 is not None else 'B 期貨未知'))
            _r2_html = (cond_badge(_cC, f'C 出口={_exp_c:+.1f}%' if _exp_c is not None else 'C 出口未知') + ' ' +
                        cond_badge(_cD, f'D M1B-M2={_gap8c:+.2f}%' if _gap8c is not None else 'D M1B-M2未知'))
            _r3_html = (cond_badge(_cE, f'E 外資={_fnet8:+.0f}億' if _fnet8 is not None else 'E 外資未知') + ' ' +
                        cond_badge(_cF, 'F 股匯雙漲' if _cF else 'F 股匯雙漲') + ' ' +
                        cond_badge(_cG, 'G SOX/NVDA點火'))

            if not _ring1_pass:
                _atk_color = '#f85149'
                _atk_grade = '🚫 禁止攻擊'
                _atk_pct = '持股 0~20%'
                _atk_txt = ('第一環未通過（VIX過高 或 外資重兵空單）：'
                            '大環境有鬼，任何技術面突破均為誘多，嚴格停損保留現金。')
            elif _ring2_cnt >= 2 and _ring3_cnt >= 2:
                _atk_color = '#f0e040'
                _atk_grade = '🚀 SSS 級全面總攻'
                _atk_pct = '持股 80~100%'
                _atk_txt = ('三環齊備、資金面與基本面完美共振：天時地利人和。'
                            '勇敢追擊強勢突破股，重壓半導體主流。')
            elif _ring2_cnt >= 1 and _ring3_cnt >= 1:
                _atk_color = '#f85149'
                _atk_grade = '🔥 A 級強勢進攻'
                _atk_pct = '持股 60~80%'
                _atk_txt = ('標準順風局：第二環（燃料）、第三環（點火）各至少一條通過。'
                            '順勢佈局，汰弱留強，跌破 10MA 停損。')
            elif _ring3_cnt >= 1:
                _atk_color = '#d29922'
                _atk_grade = '🛡️ B 級試探性建倉'
                _atk_pct = '持股 30~50%'
                _atk_txt = ('大環境無足夠燃料，但短線有點火訊號。'
                            '屬於「跌深反彈」或「區間震盪」，打帶跑策略，見好就收。')
            else:
                _atk_color = '#8b949e'
                _atk_grade = '⏸️ 暫不進攻'
                _atk_pct = '持股 30% 以下'
                _atk_txt = '三環條件均不足，等待更明確訊號，保守觀望。'

            st.markdown(
                f'<div style="background:#0d1117;border:2px solid {_atk_color};border-radius:12px;padding:16px;margin:8px 0;">'
                f'<div style="font-size:18px;font-weight:900;color:{_atk_color};">{_atk_grade}</div>'
                f'<div style="font-size:14px;color:#c9d1d9;margin:4px 0;">{_atk_pct} — {_atk_txt}</div>'
                f'<div style="margin-top:10px;font-size:12px;color:#8b949e;">第一環（解除保險）：{_r1_html}<br>'
                f'第二環（確認燃料）：{_r2_html}<br>'
                f'第三環（點火訊號）：{_r3_html}</div>'
                f'</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════
    # SECTION 九: 總經 AI 投資決策分析（五維度綜合研判）
    # ══════════════════════════════════════════════════════════════
    st.markdown(section_header('九', '🧠 總經 AI 投資決策分析', '🧠'), unsafe_allow_html=True)

    # ── 安全取數 ────────────────────────────────────────────────
    _ai_vix  = float(_m8_vix.get('current', 0))  if _m8_vix else None
    _ai_vma  = float(_m8_vix.get('ma20', 0))     if _m8_vix else None
    _ai_is_cli = bool(_m8_pmi.get('is_oecd_cli', False)) if _m8_pmi else False
    _ai_cli  = float(_m8_pmi.get('value', 100))  if (_m8_pmi and _ai_is_cli) else None
    _ai_pmi  = float(_m8_pmi.get('value', 50))   if (_m8_pmi and not _ai_is_cli) else None
    _ai_exp  = float(_m8_exp.get('yoy', 0))      if _m8_exp else None
    _ai_cpi  = float(_m8_cpi.get('yoy', 0))      if _m8_cpi else None
    _ai_mi8  = st.session_state.get('m1b_m2_info') or {}
    _ai_m1b  = float(_ai_mi8['m1b_yoy']) if _ai_mi8.get('m1b_yoy') is not None else None
    _ai_m2   = float(_ai_mi8['m2_yoy'])  if _ai_mi8.get('m2_yoy') is not None else None
    _ai_gap  = round(_ai_m1b - _ai_m2, 2) if (_ai_m1b is not None and _ai_m2 is not None) else None
    _ai_bias = float(st.session_state.get('bias_info', {}).get('bias_240', 0))
    _ai_sox  = float((tech_s.get('費城半導體 SOX') or {}).get('pct') or 0)
    _ai_nvda = float((tech_s.get('輝達 NVDA') or {}).get('pct') or 0)
    _ai_twii_pct = float((tech_s.get('大盤 TWII') or tw_s.get('台股加權指數') or {}).get('pct') or 0)

    # ── ① 目前總經位階 ──────────────────────────────────────────
    _ai1_lbl, _ai1_clr, _ai1_desc, _ai1_cyc = '資料載入中', '#484f58', '請點擊更新總經拼圖', None
    _cycle_ref = _ai_cli if _ai_cli is not None else (_ai_pmi if _ai_pmi is not None else None)
    _cycle_exp = (_cycle_ref >= 100.0) if (_ai_cli is not None) else (_cycle_ref >= 50.0 if _cycle_ref is not None else None)
    if _ai_exp is not None:
        _exp_str = f'外銷訂單YoY={_ai_exp:+.1f}%'
        _cli_str = (f'OECD CLI={_ai_cli:.2f}' if _ai_cli is not None else
                    f'台灣 PMI={_ai_pmi:.1f}' if _ai_pmi is not None else '')
        if _cycle_exp and _ai_exp >= 10:
            _ai1_lbl, _ai1_clr, _ai1_cyc = '景氣擴張強勢期 📈', '#f85149', 'bull'
            _ai1_desc = f'{_cli_str}（擴張）× {_exp_str}（強勁需求）— 主升段格局，基本面充分支撐'
        elif _cycle_exp and _ai_exp > 0:
            _ai1_lbl, _ai1_clr, _ai1_cyc = '景氣溫和擴張 🟢', '#3fb950', 'bull'
            _ai1_desc = f'{_cli_str}（擴張）× {_exp_str}— 穩步復甦，基本面有撐，持股安全'
        elif _cycle_exp and _ai_exp <= 0:
            _ai1_lbl, _ai1_clr, _ai1_cyc = '景氣高峰震盪 ⚡', '#d29922', 'peak'
            _ai1_desc = f'{_cli_str}（微擴張）× {_exp_str}— 高位整理，需求疲軟，留意反轉訊號'
        elif not _cycle_exp and _ai_exp >= 5:
            _ai1_lbl, _ai1_clr, _ai1_cyc = '景氣觸底回升 💎', '#58a6ff', 'recovery'
            _ai1_desc = f'{_cli_str}（收縮但出口反彈）× {_exp_str}— 左側佈局黃金窗口'
        elif not _cycle_exp and _ai_exp < 0:
            _ai1_lbl, _ai1_clr, _ai1_cyc = '景氣收縮期 📉', '#8b949e', 'bear'
            _ai1_desc = f'{_cli_str}（收縮）× {_exp_str}— 多看少做，等待出口數據翻正'
        else:
            _ai1_lbl, _ai1_clr, _ai1_cyc = '景氣整理期 🟡', '#d29922', 'neutral'
            _ai1_desc = f'{_cli_str} × {_exp_str}— 方向待確認，保守持股'
    elif _cycle_ref is not None:
        _cli_str = f'OECD CLI={_ai_cli:.2f}' if _ai_cli is not None else f'台灣 PMI={_ai_pmi:.1f}'
        _ai1_lbl = '景氣擴張（出口待確認）' if _cycle_exp else '景氣趨緩（出口待確認）'
        _ai1_clr = '#3fb950' if _cycle_exp else '#d29922'
        _ai1_cyc = 'bull' if _cycle_exp else 'neutral'
        _ai1_desc = f'{_cli_str} — 外銷訂單數據載入中'

    # ── ② 建議配置 ──────────────────────────────────────────────
    _ai2_lbl, _ai2_clr, _ai2_desc = '計算中', '#484f58', '等待 VIX 及資金數據'
    if _ai_vix is not None:
        _r1_ok  = _ai_vix < 20
        _r2_exp = _ai_exp is not None and _ai_exp >= 10
        _r2_gap = _ai_gap is not None and _ai_gap >= 1.0
        _r2_cnt = int(_r2_exp) + int(_r2_gap)
        _r3_sox = _ai_sox >= 1.5 or _ai_nvda >= 2.0
        _r3_tw  = _ai_twii_pct > 0
        _r3_cnt = int(_r3_sox) + int(_r3_tw)
        _fuel_str = ((' 出口+' if _r2_exp else '') + (' M1B-M2+' if _r2_gap else '')).strip(' +') or '—'
        if not _r1_ok:
            _ai2_lbl, _ai2_clr = '⛔ 防禦模式 持股0~20%', '#f85149'
            _ai2_desc = f'VIX={_ai_vix:.1f}≥20，大環境風險偏高，現金為王，等待 VIX<20 才考慮進場'
        elif _r2_cnt >= 2 and _r3_cnt >= 1:
            _ai2_lbl, _ai2_clr = '🚀 積極進攻 持股80~100%', '#f0e040'
            _ai2_desc = f'VIX={_ai_vix:.1f}安全 × 燃料充足（{_fuel_str}）× 點火訊號啟動 — 三環齊備，重壓主流'
        elif _r2_cnt >= 1 and _r3_cnt >= 1:
            _ai2_lbl, _ai2_clr = '🔥 標準多頭 持股60~80%', '#f85149'
            _ai2_desc = f'VIX={_ai_vix:.1f}安全，燃料（{_fuel_str}）有效，順勢佈局強勢個股，跌破10MA停損'
        elif _r3_cnt >= 1:
            _ai2_lbl, _ai2_clr = '🛡️ 試探建倉 持股30~50%', '#d29922'
            _ai2_desc = '短線點火訊號存在但燃料不足，打帶跑策略，見好就收，嚴設停損'
        else:
            _ai2_lbl, _ai2_clr = '⏸️ 保守觀望 持股30%以下', '#8b949e'
            _ai2_desc = '三環條件均不足，保留現金等待更明確訊號，避免追高'

    # ── ③ 目前貨幣流向 ──────────────────────────────────────────
    _ai3_lbl, _ai3_clr, _ai3_desc = '待取得 M1B/M2', '#484f58', '央行貨幣數據載入中'
    if _ai_gap is not None:
        _gap_str = f'M1B={_ai_m1b:.1f}% M2={_ai_m2:.1f}% Gap={_ai_gap:+.2f}%'
        if _ai_gap >= 2.0:
            _ai3_lbl, _ai3_clr = '🔥 熱錢大量流入股市', '#f85149'
            _ai3_desc = f'{_gap_str} — 黃金交叉大幅擴散，投機資金湧入，活絡貨幣遠超廣義貨幣'
        elif _ai_gap >= 1.0:
            _ai3_lbl, _ai3_clr = '✅ 資金動能轉強', '#3fb950'
            _ai3_desc = f'{_gap_str} — 活絡資金超越廣義貨幣，熱錢進場訊號確立，行情可期'
        elif _ai_gap >= 0:
            _ai3_lbl, _ai3_clr = '🟡 資金溫和偏多', '#d29922'
            _ai3_desc = f'{_gap_str} — M1B微幅領先，資金偏多但動能尚未爆發，需等待 Gap≥1% 確認'
        elif _ai_gap > -1.0:
            _ai3_lbl, _ai3_clr = '⚠️ 資金略偏保守', '#d29922'
            _ai3_desc = f'{_gap_str} — M2相對偏高，部分資金仍停留在定存，股市吸引力不足'
        else:
            _ai3_lbl, _ai3_clr = '📉 資金明顯外逃', '#8b949e'
            _ai3_desc = f'{_gap_str} — 死亡交叉，資金轉向固定收益，股市失血，謹慎操作'
    elif _ai_m1b is not None:
        _ai3_lbl, _ai3_clr = f'M1B={_ai_m1b:.1f}% M2待取得', '#484f58'
        _ai3_desc = 'M2 數據未就緒，暫無法判斷 Gap'

    # ── ④ 美股動態 ──────────────────────────────────────────────
    _ai4_lbl, _ai4_clr, _ai4_desc = '待取得', '#484f58', 'VIX / CPI 數據載入中'
    if _ai_vix is not None:
        _cpi_ok  = _ai_cpi is None or _ai_cpi < 3.0
        _cpi_wrm = _ai_cpi is not None and 3.0 <= _ai_cpi < 4.0
        _cpi_hot = _ai_cpi is not None and _ai_cpi >= 4.0
        _cpi_s   = f' CPI={_ai_cpi:.1f}%' if _ai_cpi is not None else ''
        _sox_s   = f' SOX={_ai_sox:+.1f}%' if _ai_sox else ''
        _vma_s   = f' MA20={_ai_vma:.1f}' if _ai_vma else ''
        if _ai_vix < 20 and _cpi_ok and (_ai_sox >= 1.5 or _ai_nvda >= 2.0):
            _ai4_lbl, _ai4_clr = '🚀 美股強勢，科技領漲', '#f85149'
            _ai4_desc = f'VIX={_ai_vix:.1f}（恐慌低）{_sox_s}（半導體點火）{_cpi_s} — 台股跟漲機率高，可積極佈局科技'
        elif _ai_vix < 20 and _cpi_ok:
            _ai4_lbl, _ai4_clr = '🟢 美股平穩，降息預期支撐', '#3fb950'
            _ai4_desc = f'VIX={_ai_vix:.1f}{_vma_s}（安全）{_cpi_s} — 無系統性風險，有利個股選股表現'
        elif _ai_vix < 20 and _cpi_wrm:
            _ai4_lbl, _ai4_clr = '🟡 美股震盪，通膨黏性制約', '#d29922'
            _ai4_desc = f'VIX={_ai_vix:.1f}尚可但{_cpi_s}偏高 — Fed降息預期受壓，資金轉向謹慎，避免過度加槓桿'
        elif _ai_vix < 20 and _cpi_hot:
            _ai4_lbl, _ai4_clr = '⚠️ 美股承壓，Fed鷹派升溫', '#d29922'
            _ai4_desc = f'VIX={_ai_vix:.1f}{_cpi_s}超標 — 高利率環境延續，外資提款風險升高，注意匯率走勢'
        elif _ai_vix < 30:
            _ai4_lbl, _ai4_clr = '🟡 美股波動加劇，謹慎操作', '#d29922'
            _ai4_desc = f'VIX={_ai_vix:.1f}（警戒區間 20~30）{_vma_s} — 市場情緒不確定，控制倉位，勿追高'
        else:
            _ai4_lbl, _ai4_clr = '🔴 美股恐慌模式，流動性危機', '#f85149'
            _ai4_desc = f'VIX={_ai_vix:.1f}≥30 — 全球流動性急凍，強制防禦，任何技術面買訊均視為誘多'

    # ── ⑤ 結論 ──────────────────────────────────────────────────
    _ai5_pts = []
    if _ai1_cyc == 'bull':
        _ai5_pts.append('景氣擴張有基本面支撐')
    elif _ai1_cyc == 'recovery':
        _ai5_pts.append('景氣觸底，左側佈局機會')
    elif _ai1_cyc == 'peak':
        _ai5_pts.append('高位整理，防範反轉')
    elif _ai1_cyc == 'bear':
        _ai5_pts.append('景氣收縮，防禦優先')
    if _ai_gap is not None:
        if _ai_gap >= 1.0:
            _ai5_pts.append(f'M1B-M2 Gap=+{_ai_gap:.1f}% 資金動能正向共振')
        elif _ai_gap < 0:
            _ai5_pts.append('M1B-M2死亡交叉，貨幣資金外逃')
    if _ai_vix is not None:
        if _ai_vix < 15:
            _ai5_pts.append(f'VIX={_ai_vix:.1f} 極度平靜')
        elif _ai_vix < 20:
            _ai5_pts.append(f'VIX={_ai_vix:.1f} 安全窗口')
        elif _ai_vix >= 30:
            _ai5_pts.append(f'VIX={_ai_vix:.1f} 觸發危機，暫停攻擊')
    if _ai_bias >= 15:
        _ai5_pts.append(f'年線乖離+{_ai_bias:.1f}% 高估值需嚴設停損')
    elif _ai_bias <= -5:
        _ai5_pts.append(f'年線乖離{_ai_bias:.1f}% 超跌逢低佈局')
    if _ai_exp is not None:
        if _ai_exp >= 10:
            _ai5_pts.append(f'外銷訂單YoY={_ai_exp:+.1f}% 出口強勁')
        elif _ai_exp < -5:
            _ai5_pts.append(f'外銷訂單YoY={_ai_exp:+.1f}% 出口衰退警訊')

    if _ai5_pts:
        _ai5_txt = '；'.join(_ai5_pts) + '。'
        _bull_score = (int(_ai1_cyc in ('bull', 'recovery')) +
                       int(_ai_gap is not None and _ai_gap >= 1.0) +
                       int(_ai_vix is not None and _ai_vix < 20) +
                       int(_ai_exp is not None and _ai_exp >= 0))
        _bear_score = (int(_ai1_cyc == 'bear') +
                       int(_ai_gap is not None and _ai_gap < 0) +
                       int(_ai_vix is not None and _ai_vix >= 30))
        if _bull_score >= 3 and _bear_score == 0:
            _ai5_clr, _ai5_icon = '#3fb950', '✅ 整體偏多，積極操作'
        elif _bear_score >= 2 or (_ai_vix is not None and _ai_vix >= 30):
            _ai5_clr, _ai5_icon = '#f85149', '🚨 整體偏空，防禦為主'
        elif _bull_score >= 2:
            _ai5_clr, _ai5_icon = '#d29922', '🟡 溫和偏多，精選個股'
        else:
            _ai5_clr, _ai5_icon = '#8b949e', '⏸️ 中性觀望，等待訊號'
    else:
        _ai5_txt  = '請點擊「更新總經拼圖」載入資料後自動生成結論。'
        _ai5_clr, _ai5_icon = '#484f58', '⏳ 等待資料'

    # ── 渲染五維度卡片 ────────────────────────────────────────────
    _aic1, _aic2, _aic3 = st.columns(3)
    def _ai_card(title, label, desc, color):
        return (f'<div style="background:#0d1117;border:1px solid {color}44;border-radius:8px;'
                f'padding:12px;min-height:110px;">'
                f'<div style="font-size:10px;color:#484f58;margin-bottom:4px;">{title}</div>'
                f'<div style="font-size:13px;font-weight:700;color:{color};line-height:1.3;">{label}</div>'
                f'<div style="font-size:11px;color:#8b949e;margin-top:6px;line-height:1.5;">{desc}</div>'
                f'</div>')
    with _aic1:
        st.markdown(_ai_card('① 目前總經位階', _ai1_lbl, _ai1_desc, _ai1_clr), unsafe_allow_html=True)
    with _aic2:
        st.markdown(_ai_card('② 建議配置', _ai2_lbl, _ai2_desc, _ai2_clr), unsafe_allow_html=True)
    with _aic3:
        st.markdown(_ai_card('③ 目前貨幣流向', _ai3_lbl, _ai3_desc, _ai3_clr), unsafe_allow_html=True)

    _aic4, _aic5 = st.columns(2)
    with _aic4:
        st.markdown(_ai_card('④ 美股動態', _ai4_lbl, _ai4_desc, _ai4_clr), unsafe_allow_html=True)
    with _aic5:
        st.markdown(
            f'<div style="background:#0d1117;border:2px solid {_ai5_clr};border-radius:8px;'
            f'padding:12px;min-height:110px;">'
            f'<div style="font-size:10px;color:#484f58;margin-bottom:4px;">⑤ 結論</div>'
            f'<div style="font-size:14px;font-weight:900;color:{_ai5_clr};">{_ai5_icon}</div>'
            f'<div style="font-size:12px;color:#c9d1d9;margin-top:6px;line-height:1.6;">{_ai5_txt}</div>'
            f'</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════
    # SECTION 十: 🤖 AI 總裁決（實體狀態鎖架構）
    # 前端唯讀 macro_state.json；LLM 運算由觸發按鈕在背景執行並寫檔
    # ══════════════════════════════════════════════════════════════
    st.markdown(section_header('十', '🤖 AI 總裁決', '🤖'), unsafe_allow_html=True)

    with st.expander('🤖 AI 總裁決 — 實體狀態鎖架構（唯讀）', expanded=True):
        _verdict_hdr_c1, _verdict_hdr_c2, _verdict_hdr_c3 = st.columns([4, 1, 1])
        with _verdict_hdr_c1:
            st.markdown(
                '<div style="font-size:12px;color:#8b949e;padding:4px 0;">'
                '整合即時國際財經新聞（RSS）與當前量化總經數據，'
                '由 Gemini AI 生成 Markdown 戰情報告。'
                '曝險上限由 Python 規則引擎計算，AI 負責解讀。'
                '<br><span style="color:#484f58;">需設定 Streamlit Secrets：'
                '<code>GEMINI_API_KEY = "AIza..."</code></span></div>',
                unsafe_allow_html=True)
        with _verdict_hdr_c2:
            _do_verdict = st.button('🔒 執行 AI 裁決', key='btn_run_verdict',
                                    use_container_width=True, type='primary')
        with _verdict_hdr_c3:
            if st.button('🗑️ 清除報告', key='btn_clear_verdict', use_container_width=True):
                st.session_state.pop('_macro_ai_report', None)
                st.session_state.pop('_macro_ai_ts', None)
                st.rerun()

        # ── 觸發：呼叫 MacroStateLocker 寫入 macro_state.json ──
        if _do_verdict:
            with st.spinner('📡 正在抓取財經新聞 + 呼叫 Gemini AI（約 15~30 秒）…'):
                _v_news = _fetch_macro_news(5)
                _v_news_titles = [_n['title'] for _n in _v_news]
                # 組裝量化數據快照供 AI 判讀
                _vix_d  = _macro_info.get('vix') or {}
                _exp_d  = _macro_info.get('tw_export') or {}
                _pmi_d  = _macro_info.get('ism_pmi') or {}
                _cpi_d  = _macro_info.get('us_core_cpi') or {}
                _mi_d   = st.session_state.get('m1b_m2_info') or {}
                _bi_d   = st.session_state.get('bias_info') or {}
                _li_d   = st.session_state.get('li_latest')
                _pcr_v  = None
                if _li_d is not None and not _li_d.empty and '選PCR' in _li_d.columns:
                    _pcr_raw = str(_li_d.iloc[-1].get('選PCR', ''))
                    if _pcr_raw not in ('', '-', 'nan', 'None'):
                        try:
                            _pcr_v = float(_pcr_raw)
                        except ValueError:
                            pass
                # 外資期貨淨口數（負值=淨空單）
                _fut_net_v = None
                if _li_d is not None and not _li_d.empty and '外資大小' in _li_d.columns:
                    try:
                        _fut_net_v = float(_li_d.iloc[-1].get('外資大小', 0))
                    except (ValueError, TypeError):
                        pass
                # 指數是否跌破 MA5（從 mkt_info 取得）
                _mkt_d = st.session_state.get('mkt_info') or {}
                _below_ma5 = bool(_mkt_d.get('index_below_ma5', False))
                # PMI 連兩月追蹤：本次觸發時記錄當前值，下次觸發時作為「前月」
                _pmi_cur = _pmi_d.get('value')
                _pmi_prev_v = st.session_state.get('_s10_prev_pmi_value')
                if _pmi_cur is not None:
                    st.session_state['_s10_prev_pmi_value'] = _pmi_cur
                _macro_numbers = {
                    'VIX_Index':           _vix_d.get('current'),
                    'M1B_YoY_pct':         _mi_d.get('m1b_yoy'),
                    'M2_YoY_pct':          _mi_d.get('m2_yoy'),
                    'TW_Export_YoY_pct':   _exp_d.get('yoy'),
                    'ISM_PMI_or_OECD_CLI': _pmi_cur,
                    'PMI_Prev_Month':       _pmi_prev_v,
                    'US_Core_CPI_YoY_pct': _cpi_d.get('yoy'),
                    'BIAS240_pct':         _bi_d.get('bias_240'),
                    'PCR':                 _pcr_v,
                    'Futures_Net_Short':   _fut_net_v,
                    'Index_Below_MA5':     _below_ma5,
                    'Sahm_Rule_Triggered': False,  # 尚無薩姆規則資料來源，預設 False
                }
                _system_state = calculate_system_state(_macro_numbers)
                # ── 組裝量化原始數據字串供新版 AI 提示語使用 ──────
                _cl_d_v = st.session_state.get('cl_data', {})
                _inst_v = _cl_d_v.get('inst', {})
                _fk_v   = next((k for k in _inst_v if '外資' in k), None)
                _tk_v   = next((k for k in _inst_v if '投信' in k), None)
                _dk_v   = next((k for k in _inst_v if '自營' in k), None)
                _fnet_v = _inst_v.get(_fk_v, {}).get('net') if _fk_v else None
                _tnet_v = _inst_v.get(_tk_v, {}).get('net') if _tk_v else None
                _dnet_v = _inst_v.get(_dk_v, {}).get('net') if _dk_v else None
                _margin_v = _cl_d_v.get('margin')
                _adl_v   = _cl_d_v.get('adl')
                _adl_ratio_v = None
                if _adl_v is not None and not _adl_v.empty and 'ad_ratio' in _adl_v.columns:
                    try:
                        _adl_ratio_v = float(_adl_v['ad_ratio'].iloc[-1])
                    except (ValueError, TypeError):
                        pass
                _leek_v2 = None
                if _li_d is not None and not _li_d.empty and '韭菜指數' in _li_d.columns:
                    try:
                        _leek_v2 = float(_li_d.iloc[-1].get('韭菜指數', None))
                    except (ValueError, TypeError):
                        pass
                _ctx = []
                if _bi_d.get('bias_240') is not None:
                    _ctx.append(f'• 大盤年線乖離率 BIAS240：{_bi_d["bias_240"]:+.1f}%（>15%偏貴、<-10%低估）')
                if _mi_d.get('m1b_yoy') is not None:
                    _gap_v = round(float(_mi_d['m1b_yoy']) - float(_mi_d.get('m2_yoy') or 0), 2)
                    _ctx.append(f'• M1B={_mi_d["m1b_yoy"]:.1f}%  M2={_mi_d.get("m2_yoy",0):.1f}%  差額={_gap_v:+.2f}%（正=資金行情啟動）')
                if _fnet_v is not None:
                    _ctx.append(f'• 外資現貨買賣超：{_fnet_v:+.1f}億')
                if _tnet_v is not None:
                    _ctx.append(f'• 投信買賣超：{_tnet_v:+.1f}億')
                if _dnet_v is not None:
                    _ctx.append(f'• 自營商買賣超：{_dnet_v:+.1f}億')
                if _margin_v is not None:
                    _ctx.append(f'• 融資餘額：{_margin_v:.0f}億（>3400億危險、>2500億警戒）')
                if _leek_v2 is not None:
                    _ctx.append(f'• 韭菜指數（小台散戶多空比）：{_leek_v2:.0f}（>80散戶過熱、<20散戶恐慌）')
                if _pcr_v is not None:
                    _ctx.append(f'• 選擇權 PCR：{_pcr_v:.2f}（>1.3市場恐慌偏多訊號、<0.7過度樂觀偏空）')
                if _adl_ratio_v is not None:
                    _ctx.append(f'• ADR 廣度指標：{_adl_ratio_v:.0f}%（>70市場健康、<30廣度不足）')
                if _fut_net_v is not None:
                    _ctx.append(f'• 外資期貨淨口數：{_fut_net_v:+.0f}口（負=淨空單、<-35000強烈空頭信號）')
                if _vix_d.get('current'):
                    _ctx.append(f'• VIX 恐慌指數：{_vix_d["current"]}（>28警戒、>35極度恐慌）')
                _ndc_v = locals().get('_m8_ndc')
                if _ndc_v and _ndc_v.get('score') is not None:
                    _ctx.append(f'• NDC 景氣對策信號：{float(_ndc_v["score"]):.0f}分（9-16藍燈衰退 / 23-31綠燈穩定 / 38-45紅燈過熱）')
                if _pmi_cur is not None:
                    _ctx.append(f'• 台灣 PMI / 景氣領先：{_pmi_cur}（>50擴張、<50收縮、<48製造業衰退）')
                if _exp_d.get('yoy') is not None:
                    _ctx.append(f'• 台灣外銷訂單 YoY：{_exp_d["yoy"]:+.1f}%（科技出口景氣領先）')
                if _cpi_d.get('yoy') is not None:
                    _ctx.append(f'• 美國核心 CPI YoY：{_cpi_d["yoy"]:+.1f}%（>3% 升息壓力、壓抑高 PE 成長股估值）')
                _sox_v = locals().get('_ai_sox') or 0
                _nvda_v = locals().get('_ai_nvda') or 0
                if _sox_v or _nvda_v:
                    _ctx.append(f'• 美股科技動能：費半 SOX={_sox_v:+.1f}% / NVDA={_nvda_v:+.1f}%（領先台股科技權值股 2-4 週）')
                _v_macro_ctx = '\n'.join(_ctx) if _ctx else '（數據尚未載入，請先更新總經拼圖）'
                _locker = MacroStateLocker()
                _locker.lock_system_state_only(_system_state)
                # 組裝 Markdown 提示語（不依賴 JSON 解析，與 Tab 2 AI 首席顧問同風格）
                _v_state_json = json.dumps(_system_state, ensure_ascii=False, indent=2)
                # 將新聞標題與摘要一併傳給 AI（提升黑天鵝偵測準確度）
                _v_news_lines = []
                for _n_item in _v_news:
                    _t_n = _n_item.get('title', '').strip()
                    _s_n = _n_item.get('summary', '').strip()
                    _src_n = _n_item.get('source', '')
                    if _t_n:
                        _line = f'- [{_src_n}] {_t_n}'
                        if _s_n:
                            _line += f'｜{_s_n[:120]}'
                        _v_news_lines.append(_line)
                _v_news_str = '\n'.join(_v_news_lines) if _v_news_lines else '（無法取得新聞）'
                _macro_ai_prompt = (
                    '你是一位擁有 20 年台股與全球宏觀研究經驗的「台股AI戰情室」首席總經分析師。'
                    '你的分析風格冷靜、精準，且強調風險控管。\n\n'
                    '## 資訊隔離約束（絕對遵守）\n'
                    '- 禁止使用預訓練知識中的具體數字，解讀必須 100% 基於下方 Input Data 的內容\n'
                    '- 禁止建議任何個股、ETF 或特定標的\n'
                    '- 不得出現任何具體持股百分比數字\n\n'
                    '## 🚨 系統性風險前置檢核（最高優先級，先做再寫報告）\n'
                    '在進入正式分析前，**強制掃描【即時財經新聞】**，逐則比對下列黑天鵝關鍵字：\n'
                    '  • 戰爭 / 軍事衝突 / 飛彈 / 入侵 / war / military / invasion\n'
                    '  • 疫情 / 大規模封城 / pandemic / lockdown / outbreak\n'
                    '  • 央行突發政策 / 緊急升降息 / emergency rate / unscheduled meeting\n'
                    '  • 金融機構倒閉 / 擠兌 / bank run / collapse / bailout\n'
                    '  • 重大地緣政治 / 制裁 / 斷交 / sanctions / embargo\n'
                    '  • 主權違約 / 信評降等 / sovereign default / downgrade\n'
                    '若**任一則新聞**命中以上關鍵字，視為【系統性風險觸發】：\n'
                    '  ① 在報告最開頭以紅色橫幅標註 `🚨 系統性風險警報觸發`，列出觸發新聞 1-3 則\n'
                    '  ② 「大盤戰略建議」中「操作方向」**強制下調一級**（多頭→震盪、震盪→空頭、空頭→極度防禦）\n'
                    '  ③ 「警示旗語」中**首位**列出觸發新聞與其潛在傳導路徑（對台股的衝擊鏈）\n'
                    '若沒有命中關鍵字，仍須在「警示旗語」末段註明「✅ 已掃描 N 則新聞，未發現系統性風險訊號」。\n\n'
                    '## Input Data\n\n'
                    f'【系統狀態（Python 規則引擎計算結果）】\n{_v_state_json}\n\n'
                    f'【量化數據快照】\n{_v_macro_ctx if _v_macro_ctx else "（數據尚未載入，請先更新總經拼圖）"}\n\n'
                    f'【即時財經新聞】\n{_v_news_str}\n\n'
                    '## 輸出格式\n'
                    '使用 Markdown 語法，生成以下架構的台股大盤戰情研判報告：\n\n'
                    '## 📊 台股大盤戰情研判報告\n\n'
                    '### 一、市場五維診斷（0-10 評分）\n'
                    '- **景氣循環**：（得分/10，依據 PMI/OECD CLI）\n'
                    '- **資金動能**：（得分/10，依據 M1B-M2 Gap）\n'
                    '- **市場情緒**：（得分/10，依據 VIX/PCR）\n'
                    '- **籌碼趨勢**：（得分/10，依據外資/融資/期貨淨部位）\n'
                    '- **美股連動**：（得分/10，依據 SOX/VIX）\n\n'
                    '### 二、核心洞察（50 字以內）\n'
                    '（當前大盤處於哪個操作階段及核心邏輯）\n\n'
                    '### 三、深度解析\n'
                    '- **資金流向**：\n'
                    '- **籌碼博弈**：\n'
                    '- **潛在隱患**：\n\n'
                    '### 四、大盤戰略建議\n'
                    '⚠️ 僅供學術研究，不構成投資建議，盈虧自負。\n'
                    '- **操作方向**：\n'
                    '- **防禦策略**：\n'
                    '- **追蹤指標**：\n\n'
                    '### 五、警示旗語\n'
                    '（列出可能破壞此分析邏輯的關鍵風險因子）\n\n'
                    '【語言規範】統一使用繁體中文。禁止出現任何持股百分比數字。'
                )
                _ai_rpt = gemini_call(_macro_ai_prompt, max_tokens=1800)
                _tz8 = datetime.timezone(datetime.timedelta(hours=8))
                st.session_state['_macro_ai_report'] = _ai_rpt
                st.session_state['_macro_ai_ts'] = datetime.datetime.now(_tz8).strftime('%Y-%m-%d %H:%M:%S')
            st.rerun()

        # ── 唯讀渲染：從 macro_state.json 讀取曝險數據 ────────────
        _ms = load_macro_state()
        _srl = _ms.get('systemic_risk_level', '危險')
        _regime = _ms.get('market_regime', '系統異常')
        _exp_pct = int(_ms.get('exposure_limit_pct', 0))
        _cash_pct = 100 - _exp_pct
        _ms_ts = _ms.get('timestamp', '')

        _srl_clr = {'安全': '#3fb950', '警告': '#d29922', '危險': '#f85149'}.get(_srl, '#8b949e')
        _reg_clr = {'多頭': '#3fb950', '震盪': '#d29922', '空頭': '#f85149'}.get(_regime, '#8b949e')

        st.markdown(
            f'<div style="background:#0d1117;border:2px solid {_srl_clr};'
            f'border-radius:12px;padding:18px 20px;margin:10px 0;">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f'flex-wrap:wrap;gap:8px;margin-bottom:10px;">'
            f'<div>'
            f'<span style="font-size:11px;color:#484f58;">市場體制</span><br>'
            f'<span style="font-size:22px;font-weight:900;color:{_reg_clr};">{_regime}</span>'
            f'</div>'
            f'<div style="text-align:right;">'
            f'<span style="background:{_srl_clr}22;border:1px solid {_srl_clr};'
            f'border-radius:20px;padding:4px 14px;font-size:12px;'
            f'font-weight:700;color:{_srl_clr};">系統風險：{_srl}</span>'
            f'<div style="font-size:10px;color:#484f58;margin-top:4px;">'
            f'裁決時間：{_ms_ts if _ms_ts else "尚未執行"}</div>'
            f'</div>'
            f'</div>'
            f'<div style="text-align:center;padding:8px 0;">'
            f'<div style="font-size:10px;color:#484f58;">建議股票型基金曝險</div>'
            f'<div style="font-size:48px;font-weight:900;color:{_srl_clr};">'
            f'{_exp_pct}<span style="font-size:18px;">%</span></div>'
            f'<div style="font-size:11px;color:#8b949e;">現金/防禦型資產 {_cash_pct}%</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True)

        # 快照時效檢查：與即時紅綠燈比對，不一致則提醒重新裁決（避免依過期判斷操作）
        _live_reg_zh = {'bull': '多頭', 'neutral': '震盪', 'bear': '空頭'}.get(_tl_eff_reg, '')
        if _ms_ts and _live_reg_zh and _regime in ('多頭', '震盪', '空頭') and _regime != _live_reg_zh:
            st.warning(
                f'⚠️ 此為 {_ms_ts} 的鎖定快照（市場體制：{_regime}），'
                f'與目前即時紅綠燈（{_live_reg_zh}）不一致 —— '
                f'請重按上方「執行 AI 裁決」更新，以免依過期判斷操作。')

        # ── Markdown AI 戰情報告（與 Tab 2 AI 首席顧問同風格）────
        _macro_ai_rpt = st.session_state.get('_macro_ai_report', '')
        _macro_ai_ts  = st.session_state.get('_macro_ai_ts', '')
        if _macro_ai_rpt:
            st.markdown(
                f'<div style="margin:14px 0 8px;padding:8px 16px;'
                f'background:linear-gradient(90deg,#76e3ea18,#0d1117);'
                f'border-left:4px solid #76e3ea;border-radius:0 6px 6px 0;">'
                f'<span style="font-size:15px;font-weight:900;color:#76e3ea;">🤖 AI 首席總經分析師報告</span>'
                f'<span style="font-size:11px;color:#8b949e;margin-left:8px;">'
                f'分析時間：{_macro_ai_ts}</span></div>',
                unsafe_allow_html=True)
            st.markdown(_macro_ai_rpt)
        elif not _ms_ts:
            st.info('尚未執行 AI 裁決。點擊上方「執行 AI 裁決」按鈕以生成首次分析。')
        else:
            st.caption('▲ 點擊上方「執行 AI 裁決」，AI 將綜合量化數據與即時新聞生成完整戰情報告。')

    st.markdown('<hr style="border-color:#21262d;margin:14px 0;">',unsafe_allow_html=True)
