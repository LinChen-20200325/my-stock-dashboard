"""TAB 比較 × 排行（多股比較 / 多因子排行 / 汰弱留強）— 從 app.py 抽出（PR P2-B Phase 5-B）

依賴策略
========
- Top-level: streamlit
- 函式內 late import: 27 個依賴（含 app.py 內部 helper 與外部模組函式），
  避免循環 import（tab_stock_grp.py ← app.py ← tab_stock_grp.py）。

呼叫端
======
- app.py: `with tab_stock_grp: render_stock_grp()`
"""
from __future__ import annotations

import streamlit as st


def render_stock_grp():
    # ─ Late imports（避免循環 import）─
    import time
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from config import FINMIND_TOKEN  # noqa: F401  (some sub-features may use)
    # 外部模組
    from tech_indicators import (
        calc_rsi, calc_ibs, calc_volume_ratio,
        calc_kd, calc_bollinger, calc_vcp,
    )
    from scoring_helpers import calc_health_score, health_grade
    from ui_widgets import teacher_conclusion
    from financial_health_engine import analyze_financial_health
    # app.py 內部 helper
    from app import (
        _fetch_stock_news, _get_loader, _load_cache, _save_cache,
        fetch_dividend_data, fetch_financials,
        fetch_quarterly, fetch_quarterly_extra,
        gemini_call, parse_stocks,
    )
    # data_loader 可能也提供 fetch_financial_statements
    try:
        from data_loader import fetch_financial_statements
    except ImportError:
        from app import fetch_financial_statements

    st.markdown("""<div style="padding:6px 0 4px;">
<span style="font-size:20px;font-weight:900;color:#e6edf3;">📊 比較 × 排行</span>
<span style="font-size:11px;color:#484f58;margin-left:10px;">市場狀態 · 多股比較 · 多因子排行 · 汰弱留強 · 最終建議</span>
</div>""", unsafe_allow_html=True)

    # ══ ① 市場狀態快覽 ══════════════════════════════════════════
    _t3_mkt = st.session_state.get('mkt_info', {})
    _t3_li  = st.session_state.get('li_latest')
    _t3_tl  = st.session_state.get('warroom_summary', {})
    if _t3_tl or _t3_mkt:
        _t3c1, _t3c2, _t3c3 = st.columns(3)
        with _t3c1:
            _tl_label = _t3_tl.get('traffic_light', '未更新')
            _tl_color = ('#3fb950' if '綠' in _tl_label else
                         '#d29922' if '黃' in _tl_label else
                         '#f85149' if '紅' in _tl_label else '#484f58')
            st.markdown(
                f'<div style="background:#0d1117;border:1px solid {_tl_color}33;border-radius:8px;'
                f'padding:10px 14px;text-align:center;">'
                f'<div style="font-size:11px;color:#8b949e;">🚦 大盤燈號</div>'
                f'<div style="font-size:16px;font-weight:900;color:{_tl_color};">{_tl_label}</div>'
                f'</div>', unsafe_allow_html=True)
        with _t3c2:
            _twii = _t3_mkt.get('台股加權指數', {})
            _twii_pct = _twii.get('pct', 0) if _twii else 0
            _twii_c = '#da3633' if _twii_pct > 0 else '#2ea043'
            st.markdown(
                f'<div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;'
                f'padding:10px 14px;text-align:center;">'
                f'<div style="font-size:11px;color:#8b949e;">📈 台股大盤</div>'
                f'<div style="font-size:16px;font-weight:900;color:{_twii_c};">{_twii_pct:+.2f}%</div>'
                f'</div>', unsafe_allow_html=True)
        with _t3c3:
            _t3_hold = _t3_tl.get('hold_pct', '--')
            st.markdown(
                f'<div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;'
                f'padding:10px 14px;text-align:center;">'
                f'<div style="font-size:11px;color:#8b949e;">💼 建議持股</div>'
                f'<div style="font-size:16px;font-weight:900;color:#58a6ff;">{_t3_hold}%</div>'
                f'</div>', unsafe_allow_html=True)
        st.markdown('')
    else:
        st.info('⏳ 請先到「🌍 總經」Tab 點擊「🚀 一鍵更新全部數據」取得最新大盤狀態')

    # ══ ② 輸入多檔代碼 ══════════════════════════════════════════
    with st.container(border=True):
        t3c1, t3c2 = st.columns([4, 1])
        with t3c1:
            multi_input = st.text_area(
                '輸入多檔代碼（逗號/空格/換行，最多10檔）',
                value='2330 2454 2317 2382 3017 2308 2303 2376 6669 3661',
                height=68, key='multi_input',
                placeholder='例：2330 2454 2317 2382 3017')
        with t3c2:
            st.markdown('<br>', unsafe_allow_html=True)
            t3_run_btn = st.button('🚀 批次分析', type='primary',
                                   use_container_width=True, key='t3_run_btn')

    stock_list_t3 = parse_stocks(multi_input)[:10]
    if stock_list_t3:
        st.caption(f'待分析：{", ".join(stock_list_t3)}（共{len(stock_list_t3)}檔）')

    # ══ 批次分析邏輯 ════════════════════════════════════════════
    if t3_run_btn and stock_list_t3:
        loader_t3  = _get_loader()
        results_t3 = []          # 汰弱留強（健康度）結果
        score_t3   = []          # 多因子評分結果

        prog_t3 = st.progress(0, text='批次分析中...')
        from scoring_engine import score_single_stock as _sss
        from stock_names    import get_stock_name as _gsn
        import threading as _threading
        _t3_loader_lock = _threading.Lock()  # FinMind dl 非線程安全，需串行保護

        # ── 並發抓取（ThreadPoolExecutor，最多3個同時）────────
        def _fetch_single_t3(sid4):
            # 先檢查本地緩存（v2 prefix 強制清除舊錯誤 cache）
            _cached = _load_cache('t3v2', sid4, ttl_hours=4)
            if _cached:
                return _cached
            try:
                # get_combined_data 共享 FinMind dl 實例，需加鎖確保線程安全
                with _t3_loader_lock:
                    _df4_raw, _err4, _name4 = loader_t3.get_combined_data(sid4, 360, True)
                df4   = _df4_raw.tail(300).reset_index(drop=True) if _df4_raw is not None and not _df4_raw.empty else None
                # _name4 可能就是 sid4（get_stock_name fallback），需確認是真正的名稱
                name4 = (_name4 if _name4 and _name4 != sid4 else None) or _gsn(sid4) or sid4
                avg_div4, _, _ = fetch_dividend_data(sid4)
                cl4, cx4, _capex4, _cl_src4, _cx_src4, _, _fin_errs4 = fetch_financials(sid4, industry='')
                result4 = {'sid': sid4, 'df': df4, 'name': name4,
                           'avg_div': avg_div4, 'cl': cl4, 'cx': cx4}
                _save_cache('t3v2', sid4, result4)
                return result4
            except Exception as _e4:
                return {'sid': sid4, 'error': str(_e4)}

        _t3_futures = {}
        with ThreadPoolExecutor(max_workers=3) as _t3_exec:
            for sid4 in stock_list_t3:
                _t3_futures[_t3_exec.submit(_fetch_single_t3, sid4)] = sid4
        _t3_fetched = {}
        for _fut, _sid in _t3_futures.items():
            try:
                _t3_fetched[_sid] = _fut.result()
            except Exception:
                _t3_fetched[_sid] = {'sid': _sid, 'error': 'timeout'}

        for i4, sid4 in enumerate(stock_list_t3):
            prog_t3.progress((i4 + 1) / len(stock_list_t3),
                             text=f'分析 {sid4} ({i4+1}/{len(stock_list_t3)})...')
            try:
                _d4     = _t3_fetched.get(sid4, {})
                df4     = _d4.get('df')
                # 名稱優先: loader返回值 > stock_names靜態字典 > 代碼本身
                _raw_name4 = _d4.get('name', '')
                name4   = (_raw_name4 if _raw_name4 and _raw_name4 != sid4
                           else _gsn(sid4))
                avg_div4= _d4.get('avg_div', 0)
                cl4     = _d4.get('cl')
                _fin_st4= {}

                price4  = float(df4['close'].iloc[-1]) if df4 is not None and not df4.empty else 0
                ma20_4  = float(df4['MA20'].iloc[-1])  if df4 is not None and 'MA20'  in df4.columns else None
                ma100_4 = float(df4['MA100'].iloc[-1]) if df4 is not None and 'MA100' in df4.columns else None
                rsi4    = calc_rsi(df4)
                ibs4 = calc_ibs(df4)
                vr4     = calc_volume_ratio(df4)
                k4, d4  = calc_kd(df4)
                bb4  = calc_bollinger(df4)
                vcp4    = calc_vcp(df4) if df4 is not None and len(df4) >= 30 else None
                health4, _ = calc_health_score(df4, rsi4, ibs4, vr4, k4, d4, bb4)
                grade4, grade_color4, _, emoji4 = health_grade(health4)

                if ma20_4 and ma100_4 and price4 > ma20_4 > ma100_4:
                    trend4 = '📈多頭'
                elif ma20_4 and ma100_4 and price4 < ma20_4 < ma100_4:
                    trend4 = '📉空頭'
                elif ma100_4 and price4 > ma100_4:
                    trend4 = '📊多箱'
                elif price4 > 0:
                    trend4 = '📊空箱'
                else:
                    trend4 = '⚪無資料'

                val4 = '⚪無股利'
                if avg_div4 > 0 and price4 > 0:
                    ch4, fa4, de4 = avg_div4/0.07, avg_div4/0.05, avg_div4/0.03
                    if price4 <= ch4:
                        val4 = '🟢便宜'
                    elif price4 <= fa4:
                        val4 = '🟡合理'
                    elif price4 <= de4:
                        val4 = '🔴昂貴'
                    else:
                        val4 = '🔴超貴'

                vcp_ok4 = vcp4 and vcp4['contracting']

                # ── 汰弱留強舊評分 ─────────────────────────────
                old_score4 = 0
                if '多頭' in trend4:
                    old_score4 += 2
                if '便宜' in val4:
                    old_score4 += 3
                elif '合理' in val4:
                    old_score4 += 1
                if vcp_ok4:
                    old_score4 += 2
                if cl4 and cl4 > 0:
                    old_score4 += 1
                old_score4 += round(health4 / 50, 0)

                results_t3.append({
                    'stock_id': sid4,
                    '代碼': sid4, '名稱': name4 or sid4, '現價': f'{price4:.2f}',
                    '健康度': health4, '評級': f'{emoji4}{grade4}',
                    'RSI':  f'{rsi4}' if rsi4 else '-',
                    '量比': f'{vr4}' if vr4 else '-',
                    'IBS':  f'{ibs4}' if ibs4 is not None else '-',
                    'KD':   f'K{k4}/D{d4}' if k4 else '-',
                    '趨勢': trend4, '357評價': val4,
                    'VCP':  '✅收縮' if vcp_ok4 else '⚪',
                     '合約負債': f'{cl4/1e8:.1f}億' if cl4 and cl4 > 0 else '-',



                    '舊評分': int(old_score4),
                    '_health': health4, '_val': val4, '_trend': trend4,
                })

                # ── 操作狀態燈 🔵🟠🟡 ──────────────────────────
                try:
                    _status4 = '⚪'
                    if df4 is not None and not df4.empty:
                        _p4      = float(df4['close'].iloc[-1])
                        _ma20_4  = float(df4['close'].tail(20).mean())
                        _bias4   = (_p4 - _ma20_4) / _ma20_4 * 100 if _ma20_4 else 0
                        _vol4    = float(df4['volume'].iloc[-1])      if 'volume' in df4.columns else 0
                        _avgvol4 = float(df4['volume'].tail(20).mean()) if 'volume' in df4.columns else 1
                        _shrink4 = _avgvol4 > 0 and _vol4 < _avgvol4 * 0.7
                        _near20_4= abs(_bias4) < 3
                        if health4 >= 80 and '多頭' in str(trend4) and _shrink4 and _near20_4:
                            _status4 = '🔵 加碼'
                        elif _bias4 > 25:
                            _status4 = '🟡 警示'
                        elif '昂貴' in str(val4) or '超貴' in str(val4):
                            _status4 = '🟠 減碼'
                    if results_t3:
                        results_t3[-1]['操作狀態'] = _status4
                except Exception:
                    pass

                # ── 多因子評分 ─────────────────────────────────
                if df4 is not None and not df4.empty:
                    try:
                        df4_full, _, name4_full = loader_t3.get_combined_data(sid4, 300, True)
                        if df4_full is not None and not df4_full.empty:
                            # name4_full 可能等於 sid4（代碼），需排除才能使用後備
                            _n4_use = (name4_full if name4_full and name4_full != sid4 else None) or name4 or _gsn(sid4)
                            sf = _sss(df4_full, sid4, _n4_use)
                            score_t3.append(sf)
                    except Exception:
                        pass

            except Exception:
                results_t3.append({
                    'stock_id': sid4, '代碼': sid4, '名稱': '失敗', '現價': '-',
                    '健康度': 0, '評級': '-', 'RSI': '-', '量比': '-',
                    'IBS': '-', 'KD': '-', '趨勢': '-', '357評價': '-',
                    'VCP': '-', '合約負債': '-', '舊評分': 0,
                    '_health': 0, '_val': '-', '_trend': '-',
                })
            time.sleep(0.2)

        prog_t3.empty()

        # ── AI 風控警示 ────────────────────────────────────────
        _t3_mkt = st.session_state.get('mkt_info', {}) or {}  # 從 Tab1 更新後取得
        risk_alerts_t3 = []
        if _t3_mkt.get('regime') == 'bear':
            risk_alerts_t3.append('大盤偏空，建議降低持股至20%以下')
        if _t3_mkt.get('foreign_net', 0) < -5e9:
            risk_alerts_t3.append('外資大量賣超，注意籌碼面壓力')

        st.session_state['t3_data'] = {
            'results':     results_t3,
            'score_t3':    score_t3,
            'risk_alerts': risk_alerts_t3,
        }

    # ══ 顯示結果 ════════════════════════════════════════════════
    t3_data = st.session_state.get('t3_data')
    results_t3 = []  # 確保 results_t3 在 if t3_data 外部也有定義

    if t3_data:
        results_t3  = t3_data['results']
        score_t3    = t3_data['score_t3']
        risk_alerts = t3_data.get('risk_alerts', [])

        # ── 預先計算基本面（③④⑤ 共用）─────────────────────────
        _fund_map = {}
        for _r3 in results_t3:
            _sid3 = _r3.get('stock_id', _r3.get('代碼',''))
            _qtr3 = None
            try:
                _qtr3, _ = fetch_quarterly(_sid3)
            except Exception:
                pass
            _avg3 = None
            try:
                _avg3, _, _ = fetch_dividend_data(_sid3)
            except Exception:
                pass
            _eps3 = _gp3 = None
            if _qtr3 is not None and not _qtr3.empty:
                _ec3 = next((c for c in _qtr3.columns if 'EPS' in str(c).upper() or '每股盈餘' in str(c)), None)
                _gc3 = '毛利率' if '毛利率' in _qtr3.columns else None  # 精確比對，避免命中'毛利率名稱'
                if _ec3:
                    _es3 = pd.to_numeric(_qtr3[_ec3].tail(4), errors='coerce').dropna()
                    if len(_es3) >= 1:
                        _eps3 = round(float(_es3.sum()), 2)
                if _gc3:
                    # 取最後一個非NaN值（避免最新季度尚未公布時取到NaN）
                    _gs3 = pd.to_numeric(_qtr3[_gc3], errors='coerce').dropna()
                    if len(_gs3) >= 1:
                        _gp3 = round(float(_gs3.iloc[-1]), 1)
            # 獲利品質得分 (SQ)
            _sq3 = None
            try:
                from scoring_engine import calc_quality_score as _cqs3
                _sq_r3 = _cqs3(_qtr3)
                if _sq_r3.get('sq') is not None:
                    _sq3 = f"{_sq_r3['sq']:.0f}({_sq_r3['sq_label']})"
            except Exception:
                pass
            # 前瞻動能 FGMS
            _fgms3 = None
            try:
                _qex3 = None
                try:
                    _qex3, _ = fetch_quarterly_extra(_sid3)
                except Exception:
                    pass
                from scoring_engine import calc_forward_momentum_score as _cfgms3
                _is_fin3 = bool(_qtr3['是否金融股'].iloc[0]) if _qtr3 is not None and '是否金融股' in _qtr3.columns else False
                _fg_r3 = _cfgms3(_qtr3, _qex3, is_finance=_is_fin3)
                if _fg_r3.get('fgms') is not None:
                    _fgms3 = f"{_fg_r3['fgms']:.0f}({_fg_r3['fgms_label']})"
            except Exception:
                pass
            _fund_map[_sid3] = {
                '近4季EPS': f'{_eps3:.2f}' if _eps3 is not None else '-',
                '毛利率%':  f'{_gp3:.1f}'  if _gp3  is not None else '-',
                '殖利率%':  f'{_avg3:.1f}' if _avg3  is not None else '-',
                'SQ評分':   _sq3   if _sq3   is not None else '-',
                'FGMS':     _fgms3 if _fgms3 is not None else '-',
            }

        # ── ⑤ 最終綜合建議卡 ──────────────────────────────────
        if results_t3:
            score_map = {s['stock_id']: s for s in score_t3}

            def _final_rec(row):
                health   = row.get('_health', 0)
                val      = row.get('_val', '')
                trend    = row.get('_trend', '')
                mf_total = score_map.get(row['stock_id'], {}).get('total', 0)
                pts = 0
                if health >= 80:
                    pts += 3
                elif health >= 50:
                    pts += 1
                if mf_total >= 75:
                    pts += 3
                elif mf_total >= 55:
                    pts += 1
                if '便宜' in val:
                    pts += 2
                elif '合理' in val:
                    pts += 1
                if '多頭' in trend:
                    pts += 1
                if pts >= 7:
                    return '🟢 積極', '#3fb950'
                elif pts >= 4:
                    return '🟡 觀察', '#d29922'
                else:
                    return '🔴 等待', '#f85149'

            st.markdown('#### ⑤ 最終綜合建議')
            # 動態：計算積極/觀察/等待各有幾支
            _rec_counts = {'積極': 0, '觀察': 0, '等待': 0}
            for _rr in results_t3:
                _rl, _ = _final_rec(_rr)
                _rec_counts[_rl.split()[-1]] = _rec_counts.get(_rl.split()[-1], 0) + 1
            _active_n = _rec_counts.get('積極', 0)
            _wait_n = _rec_counts.get('等待', 0)
            if _active_n >= 2:
                _r5c = f'本批 {_active_n} 支達積極布局條件'
                _r5a = '可同步建倉，停損設健康度跌破50'
            elif _active_n == 1:
                _r5c = '僅 1 支達積極條件，其餘觀察或等待'
                _r5a = '單一標的建倉，其餘等訊號確認'
            else:
                _r5c = f'本批無積極訊號（{_wait_n} 支等待），市場擇股難度高'
                _r5a = '空手等待，勿強求進場'
            st.markdown(teacher_conclusion('宏爺', f'健康+多因子+357三重確認，共 {len(results_t3)} 支', _r5c, _r5a), unsafe_allow_html=True)
            rec_cols = st.columns(min(len(results_t3), 5))
            for ci, row in enumerate(results_t3[:5]):
                rec_label, rec_color = _final_rec(row)
                mf2 = score_map.get(row['stock_id'], {}).get('total', 0)
                _fd2 = _fund_map.get(row['stock_id'], {})
                with rec_cols[ci]:
                    st.markdown(f"""<div style="background:#0d1117;border:2px solid {rec_color};
border-radius:10px;padding:12px;text-align:center;margin:2px 0;">
<div style="font-size:20px;font-weight:900;color:{rec_color};">{row['代碼']}</div>
<div style="font-size:11px;color:#8b949e;">{row['名稱']}</div>
<div style="font-size:13px;font-weight:700;color:{rec_color};margin:6px 0;">{rec_label}</div>
<div style="font-size:11px;color:#8b949e;">健康:{row.get('健康度',0):.0f} | 多因子:{mf2:.0f}</div>
<div style="font-size:11px;color:#8b949e;">EPS:{_fd2.get('近4季EPS','-')} | 毛利:{_fd2.get('毛利率%','-')}%</div>
</div>""", unsafe_allow_html=True)

        # ── RS 走勢對比 ─────────────────────────────────────────
        if score_t3 and len(score_t3) >= 2:
            st.markdown('---')
            _sdf = pd.DataFrame([{
                '代碼': r['stock_id'], '總分': r.get('total',0),
                '趨勢': r.get('trend',0), '動能': r.get('momentum',0),
                '籌碼': r.get('chip',0), '量價': r.get('volume',0),
                'RS': r.get('rs_score',50),
            } for r in score_t3]).sort_values('總分', ascending=False)
            st.markdown('##### 📈 多因子維度對比')
            # 動態：找出 RS 最高與 RS 向上的股票
            _rs_top = _sdf.iloc[0] if not _sdf.empty else None
            _rs_up_pre = [r['stock_id'] for r in score_t3 if r.get('rs_up')]
            if _rs_top is not None and _rs_up_pre:
                _rs27c = f'RS 最強 {_rs_top["代碼"]}（{_rs_top["RS"]:.0f}分），{len(_rs_up_pre)} 支 RS 向上'
                _rs27a = '優先佈局 RS 向上標的，動能最強'
            elif _rs_top is not None:
                _rs27c = f'RS 最強 {_rs_top["代碼"]}（{_rs_top["RS"]:.0f}分），無 RS 向上訊號'
                _rs27a = '等待突破，趨勢+動能>70再行動'
            else:
                _rs27c = 'RS 資料計算中'
                _rs27a = '等待資料載入後判斷'
            st.markdown(teacher_conclusion('朱家泓', 'RS相對強度對比', _rs27c, _rs27a), unsafe_allow_html=True)
            _score_pivot = _sdf.head(5).set_index('代碼')[['趨勢','動能','籌碼','量價','RS']]
            st.dataframe(_score_pivot, use_container_width=True,
                column_config={c: st.column_config.ProgressColumn(c, min_value=0, max_value=100, format='%.0f')
                               for c in ['趨勢','動能','籌碼','量價','RS']})
            _rs_up_list = [r['stock_id'] for r in score_t3 if r.get('rs_up')]
            if _rs_up_list:
                st.success(f"📊 RS曲線向上（強勢動能）：{' / '.join(_rs_up_list)}")

        st.markdown('---')

        # ── ③+④ 雙欄：多因子排行（含EPS/毛利率）vs 汰弱留強 ──
        col_left, col_right = st.columns([1, 1])

        with col_left:
            st.markdown('##### ③ 多因子評分排行')
            st.caption('趨勢×0.30 + 動能×0.25 + 籌碼×0.20 + 量價×0.15 + 風險×0.10')
            # 動態：找出最高分與門檻達標數
            _top_score_r = max(score_t3, key=lambda r: r.get('total', 0)) if score_t3 else None
            _pass70 = [r for r in score_t3 if r.get('total', 0) >= 70]
            if _top_score_r:
                _mf3c = f'最高分 {_top_score_r["stock_id"]} {_top_score_r.get("total",0):.0f}分，{len(_pass70)}/{len(score_t3)} 支≥70分'
                _mf3a = '≥70分方可列入候選，其餘繼續觀察'
            else:
                _mf3c = '多因子資料計算中'
                _mf3a = '等待評分載入'
            st.markdown(teacher_conclusion('孫慶龍', '多因子總分排行', _mf3c, _mf3a), unsafe_allow_html=True)
            if score_t3:
                from scoring_engine import rank_stocks as _rk3
                _ranked3 = _rk3(score_t3)
                _rank_rows = []
                for _ri, _r in enumerate(_ranked3):
                    _sid_r = _r.get('stock_id','')
                    _fd = _fund_map.get(_sid_r, {})
                    _rank_rows.append({
                        '排名': _ri + 1, '代碼': _sid_r,
                        '名稱': (_r.get('stock_name','') or '')[:6],
                        '總分': _r.get('total', 0),
                        '近4季EPS': _fd.get('近4季EPS', '-'),
                        '毛利率%':  _fd.get('毛利率%',  '-'),
                        'SQ評分':   _fd.get('SQ評分',   '-'),
                        'FGMS前瞻': _fd.get('FGMS',     '-'),
                        '殖利率%':  _fd.get('殖利率%',  '-'),
                        '評級': _r.get('grade', '-'),
                    })
                _rank_df = pd.DataFrame(_rank_rows)
                st.dataframe(_rank_df, use_container_width=True, hide_index=True,
                             column_config={
                                 '總分':     st.column_config.ProgressColumn('總分', min_value=0, max_value=100, format='%.1f'),
                                 '近4季EPS': st.column_config.TextColumn('近4Q EPS'),
                                 '毛利率%':  st.column_config.TextColumn('毛利率%'),
                                 'SQ評分':   st.column_config.TextColumn('SQ品質分'),
                                 'FGMS前瞻': st.column_config.TextColumn('FGMS前瞻'),
                                 '殖利率%':  st.column_config.TextColumn('殖利率%'),
                             })
            else:
                st.info('多因子評分資料載入中')

        with col_right:
            st.markdown('##### ④ 汰弱留強明細')
            st.caption('健康度 · 357評價 · VCP · KD · RSI')
            # 動態：計算被淘汰（健康度<50 或 357超貴）的數量
            _elim_n = sum(1 for r in results_t3
                          if r.get('健康度', 100) < 50 or '超貴' in str(r.get('357評價', '')))
            _keep_n = len(results_t3) - _elim_n
            if _elim_n > 0:
                _e4c = f'{_elim_n} 支被淘汰（健康<50 或 357超貴），剩 {_keep_n} 支候選'
                _e4a = '只看留下的 {_keep_n} 支，被淘汰直接跳過'.format(_keep_n=_keep_n)
            else:
                _e4c = f'本批 {len(results_t3)} 支全數通過汰弱篩選'
                _e4a = '品質整齊，可從多因子排行取前2~3支'
            st.markdown(teacher_conclusion('弘爺', f'汰弱留強（共 {len(results_t3)} 支）', _e4c, _e4a), unsafe_allow_html=True)
            if results_t3:
                _elim_rows = []
                for _r3 in results_t3:
                    _sid3 = _r3.get('stock_id', _r3.get('代碼',''))
                    _row = {k: v for k, v in _r3.items() if not k.startswith('_') and k != 'stock_id'}
                    _row.update(_fund_map.get(_sid3, {}))
                    _elim_rows.append(_row)
                df_cmp = pd.DataFrame(_elim_rows).sort_values(['舊評分', '健康度'], ascending=[False, False]).reset_index(drop=True)
                # 確保名稱欄位存在
                if '名稱' not in df_cmp.columns and '代碼' in df_cmp.columns:
                    df_cmp.insert(0, '名稱', df_cmp['代碼'])
                _col_order = [c for c in ['名稱','代碼','現價','操作狀態','健康度','評級','舊評分',
                                           'RSI','KD','量比','IBS','趨勢','357評價','VCP',
                                           '合約負債','近4季EPS','毛利率%','殖利率%']
                              if c in df_cmp.columns]
                st.dataframe(df_cmp[_col_order], use_container_width=True,
                             hide_index=True,
                             column_config={
                                 '名稱':     st.column_config.TextColumn('名稱', width='small'),
                                 '代碼':     st.column_config.TextColumn('代碼', width='small'),
                                 '現價':     st.column_config.TextColumn('現價'),
                                 '健康度':   st.column_config.NumberColumn('健康度',  format='%d 🏥'),
                                 '舊評分':   st.column_config.NumberColumn('評分',    format='%d ⭐'),
                                 '近4季EPS': st.column_config.TextColumn('近4Q EPS'),
                                 '毛利率%':  st.column_config.TextColumn('毛利率%'),
                                 '殖利率%':  st.column_config.TextColumn('殖利率%'),
                             })

        st.markdown('---')

        # ── 風控警示 ────────────────────────────────────────────
        if risk_alerts:
            st.markdown('#### ⚠️ 風控警示')
            for alert in risk_alerts:
                st.warning(alert)

    # ══ 批次財報體檢（自動執行）══════════════════════════════════
    if results_t3 and stock_list_t3:
        st.markdown('---')
        st.markdown("""<div style="margin:16px 0 8px;padding:8px 16px;background:linear-gradient(90deg,#d2a8ff18,#0d1117);border-left:4px solid #d2a8ff;border-radius:0 6px 6px 0;"><span style="font-size:15px;font-weight:900;color:#d2a8ff;">🏥 批次財報體檢（MJ林明樟體系）</span><span style="font-size:11px;color:#8b949e;margin-left:8px;">4力1棒子 · 現金流矩陣 · OPM護城河</span></div>""", unsafe_allow_html=True)
        _fh3_trigger = '_'.join(sorted(r.get('stock_id', r.get('代碼','')) for r in results_t3[:10]))
        if st.session_state.get('_fh_t3_last_key') != _fh3_trigger or not st.session_state.get('_fh_t3_results'):
            _asc = as_completed  # L2: 使用頂層已匯入的 as_completed
            _fk3 = FINMIND_TOKEN    # 使用全域 FINMIND_TOKEN（含 os.environ fallback）
            if not _fk3:
                st.warning('⚠️ 未設定 FINMIND_TOKEN，無法抓取財報資料。請在 Streamlit Secrets 或環境變數中設定 FINMIND_TOKEN。')
            _fh3_new = {}
            _prog3 = st.progress(0, text='財報體檢中（純計算，無 AI 呼叫）...')
            def _fh3_fn(sid):
                _fd3 = fetch_financial_statements(sid, _fk3)
                if not _fd3.get('error'):
                    try:
                        from tw_stock_data_fetcher import fetch_5_years_cash_flow
                        _fd3['b_item_5y'] = fetch_5_years_cash_flow(sid, _fk3)
                    except Exception:
                        pass
                return sid, analyze_financial_health("", sid, _fd3)
            _done3 = 0
            with ThreadPoolExecutor(max_workers=3) as _ex3:
                _fts3 = {_ex3.submit(_fh3_fn, s): s for s in stock_list_t3}
                for _ft3 in _asc(_fts3):
                    _done3 += 1
                    _prog3.progress(_done3 / len(stock_list_t3), text=f'體檢 {_done3}/{len(stock_list_t3)}...')
                    _sid3, _res3 = _ft3.result()
                    _fh3_new[_sid3] = _res3
            _prog3.empty()
            st.session_state['_fh_t3_results'] = _fh3_new
            st.session_state['_fh_t3_last_key'] = _fh3_trigger

    _fh_t3_cached = st.session_state.get('_fh_t3_results', {})

    if _fh_t3_cached:
        # ── 摘要比較表 ────────────────────────────────────────────
        st.markdown('##### 📊 體檢摘要比較表')
        _fh_rows = []
        for _sid_f, _fd_f in _fh_t3_cached.items():
            _scores_f = _fd_f.get('radar_scores', {})
            _avg_f = round(sum(_scores_f.values()) / len(_scores_f), 1) if _scores_f else 0
            _fh_rows.append({
                '代碼':     _sid_f,
                '現金水位':  _fd_f.get('cash_ratio_status', '?') + ' ' + _fd_f.get('cash_ratio_value', ''),
                'OCF':      _fd_f.get('ocf_status', '?') + ' ' + _fd_f.get('ocf_value', ''),
                '負債比':   _fd_f.get('debt_ratio_status', '?') + ' ' + _fd_f.get('debt_ratio_value', ''),
                '企業DNA':  _fd_f.get('business_model_dna', 'N/A'),
                '雷達均分': _avg_f,
                '紅旗':     '⚠️' if (_fd_f.get('red_flags', 'None') not in ('None', '', None)) else '✅',
            })
        _df_fh = pd.DataFrame(_fh_rows).sort_values('雷達均分', ascending=False).reset_index(drop=True)
        st.dataframe(
            _df_fh, use_container_width=True, hide_index=True,
            column_config={
                '代碼':     st.column_config.TextColumn('代碼',   width='small'),
                '現金水位': st.column_config.TextColumn('現金水位'),
                'OCF':      st.column_config.TextColumn('OCF'),
                '負債比':   st.column_config.TextColumn('負債比'),
                '企業DNA':  st.column_config.TextColumn('企業DNA', width='medium'),
                '雷達均分': st.column_config.NumberColumn('雷達均分', format='%.1f ⭐'),
                '紅旗':     st.column_config.TextColumn('紅旗', width='small'),
            }
        )

        # ── 個股詳細展開卡片 ──────────────────────────────────────
        st.markdown('##### 🔍 個股詳細體檢報告')
        for _sid_f, _fd_f in _fh_t3_cached.items():
            _dna_f = _fd_f.get('business_model_dna', '無法判斷')
            _dna_color = ('#3fb950' if _dna_f.startswith('A+') else
                          '#2ea043' if _dna_f.startswith('A') else
                          '#d29922' if _dna_f.startswith('B') else
                          '#f97316' if _dna_f.startswith('C') else
                          '#f85149')
            with st.expander(f'🏥 {_sid_f} — DNA: {_dna_f}', expanded=False):
                # 生死燈號
                _gc1, _gc2, _gc3 = st.columns(3)
                _gc1.metric('現金佔總資產', _fd_f.get('cash_ratio_value', 'N/A'),
                            _fd_f.get('cash_ratio_status', '🔴'))
                _gc2.metric('營業活動現金流', _fd_f.get('ocf_value', 'N/A'),
                            _fd_f.get('ocf_status', '🔴'))
                _gc3.metric('負債比率', _fd_f.get('debt_ratio_value', 'N/A'),
                            _fd_f.get('debt_ratio_status', '🔴'))

                # 雷達圖
                _scores_f = _fd_f.get('radar_scores', {})
                if _scores_f:
                    import plotly.graph_objects as go
                    _cats_f = list(_scores_f.keys())
                    _vals_f = list(_scores_f.values()) + [list(_scores_f.values())[0]]
                    _cats_f_closed = _cats_f + [_cats_f[0]]
                    _fig_f = go.Figure(go.Scatterpolar(
                        r=_vals_f, theta=_cats_f_closed,
                        fill='toself', fillcolor='rgba(63,185,80,0.15)',
                        line=dict(color='#3fb950', width=2),
                        marker=dict(size=6, color='#3fb950'),
                    ))
                    _fig_f.update_layout(
                        polar=dict(
                            radialaxis=dict(range=[0, 100], tickfont=dict(size=9), showticklabels=True),
                            angularaxis=dict(tickfont=dict(size=11)),
                            bgcolor='#0d1117',
                        ),
                        paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
                        showlegend=False, height=280,
                        margin=dict(l=40, r=40, t=20, b=20),
                    )
                    st.plotly_chart(_fig_f, width='stretch',
                                    key=f'radar_t3_{_sid_f}')

                # DNA + OPM
                st.markdown(
                    f'<div style="display:inline-block;background:{_dna_color}22;'
                    f'border:1px solid {_dna_color}66;border-radius:6px;'
                    f'padding:4px 12px;font-size:13px;color:{_dna_color};font-weight:700;">'
                    f'企業DNA：{_dna_f}</div>',
                    unsafe_allow_html=True
                )
                _opm_f = _fd_f.get('opm_data', {})
                if _opm_f:
                    _pay_f = _opm_f.get('payable_days', 0)
                    _rec_f = _opm_f.get('receivable_days', 0)
                    _adv_f = _opm_f.get('advantage', False)
                    if _adv_f:
                        st.success(f'OPM護城河 ✅ 付款天數({_pay_f}天) > 收款天數({_rec_f}天)，具議價優勢')
                    else:
                        st.warning(f'OPM護城河 ⚠️ 付款天數({_pay_f}天) ≤ 收款天數({_rec_f}天)，議價能力待強化')

                # ── 存活能力精細模組（Survival Module）──────────
                _surv_f = _fd_f.get('survival_module', {})
                if _surv_f and not _fd_f.get('error'):
                    st.markdown('**🏥 存活能力精細診斷（MJ 3大生死指標）**')
                    _s_cols = st.columns(3)
                    _status_color = {'Pass': '#3fb950', 'Acceptable': '#d29922', 'Fail': '#f85149'}
                    for _col, (_key, _label) in zip(_s_cols, [
                        ('Cash_Ratio', '💰 氣長不長'),
                        ('DSO_Speed',  '⚡ 收現速度'),
                    ]):
                        _si = _surv_f.get(_key, {})
                        _sc = _status_color.get(_si.get('Status', 'Fail'), '#f85149')
                        with _col:
                            st.markdown(
                                f'<div style="background:{_sc}18;border:1px solid {_sc}55;'
                                f'border-radius:8px;padding:10px;text-align:center;">'
                                f'<div style="font-size:11px;color:#8b949e;">{_label}</div>'
                                f'<div style="font-size:18px;font-weight:900;color:{_sc};">{_si.get("Value","N/A")}</div>'
                                f'<div style="font-size:11px;color:{_sc};">{_si.get("Status","?")}</div>'
                                f'<div style="font-size:10px;color:#8b949e;margin-top:4px;">{_si.get("Insight","")}</div>'
                                f'</div>', unsafe_allow_html=True)
                    _r110 = _surv_f.get('Rule_100_100_10', {})
                    _r110_sc = _status_color.get(_r110.get('Status', 'Fail'), '#f85149')
                    # 各分項勾叉（門檻：A>100% / B≥100% / C>10%，與 financial_health_engine:416/423/431 對齊）
                    import re as _re_r110b
                    def _r110_ok_b(_s, _thr, _strict):
                        _ss = str(_s or '')
                        if not _ss or 'N/A' in _ss:
                            return None
                        _mn = _re_r110b.search(r'(-?\d+(?:\.\d+)?)\s*%', _ss)
                        if not _mn:
                            return None
                        _vn = float(_mn.group(1))
                        return (_vn > _thr) if _strict else (_vn >= _thr)
                    _a_ok = _r110_ok_b(_r110.get('Cash_Flow_Ratio',''), 100, True)
                    _b_ok = _r110_ok_b(_r110.get('Cash_Flow_Adequacy',''), 100, False)
                    _c_ok = _r110_ok_b(_r110.get('Cash_Reinvestment',''), 10, True)
                    def _tk(x):
                        return '✅' if x is True else ('❌' if x is False else '⚪')
                    with _s_cols[2]:
                        st.markdown(
                            f'<div style="background:{_r110_sc}18;border:1px solid {_r110_sc}55;'
                            f'border-radius:8px;padding:10px;text-align:center;">'
                            f'<div style="font-size:11px;color:#8b949e;">🔄 100/100/10</div>'
                            f'<div style="font-size:11px;color:#c9d1d9;">'
                            f'A{_tk(_a_ok)}{_r110.get("Cash_Flow_Ratio","N/A")} '
                            f'B{_tk(_b_ok)}{_r110.get("Cash_Flow_Adequacy","N/A")} '
                            f'C{_tk(_c_ok)}{_r110.get("Cash_Reinvestment","N/A")}</div>'
                            f'<div style="font-size:12px;font-weight:700;color:{_r110_sc};">{_r110.get("Status","?")}</div>'
                            f'<div style="font-size:10px;color:#8b949e;margin-top:4px;">{_r110.get("Insight","")}</div>'
                            f'</div>', unsafe_allow_html=True)
                    _verdict_f = _surv_f.get('Final_Survival_Verdict', '')
                    if _verdict_f:
                        st.caption(f'🎯 {_verdict_f}')

                # ── 經營能力模組（Operating Module）──────────────
                _oper_f = _fd_f.get('operating_module', {})
                if _oper_f and not _fd_f.get('error'):
                    st.markdown('**⚙️ 經營能力診斷（MJ DSO/DIO/DPO）**')
                    _o4c = st.columns(4)
                    with _o4c[0]:
                        st.metric('DSO 應收天數', _oper_f.get('DSO', 'N/A'))
                    with _o4c[1]:
                        st.metric('DIO 存貨天數', _oper_f.get('DIO', 'N/A'))
                    with _o4c[2]:
                        st.metric('DPO 應付天數', _oper_f.get('DPO', 'N/A'))
                    with _o4c[3]:
                        st.metric('總資產翻桌率', _oper_f.get('Asset_Turnover', 'N/A'))
                    _o2c = st.columns(2)
                    with _o2c[0]:
                        st.markdown(
                            f'<div style="text-align:center;padding:8px;background:#161b22;border-radius:6px;">'
                            f'<div style="font-size:11px;color:#8b949e;">完整循環天數</div>'
                            f'<div style="font-size:18px;font-weight:900;color:#58a6ff;">{_oper_f.get("Complete_Cycle","N/A")}</div>'
                            f'</div>', unsafe_allow_html=True)
                    with _o2c[1]:
                        _ccc_f = str(_oper_f.get('Cash_Gap_Days', '0'))
                        _ccc_num_f = float(''.join(c for c in _ccc_f if c in '0123456789.-') or '0')
                        _ccc_color_f = '#3fb950' if _ccc_num_f <= 0 else ('#d29922' if _ccc_num_f <= 30 else '#f85149')
                        _opm_yes_f = _oper_f.get('OPM_Strategy', 'No') == 'Yes'
                        st.markdown(
                            f'<div style="text-align:center;padding:8px;background:#161b22;border-radius:6px;">'
                            f'<div style="font-size:11px;color:#8b949e;">現金缺口天數 {"🏰 OPM護城河" if _opm_yes_f else ""}</div>'
                            f'<div style="font-size:18px;font-weight:900;color:{_ccc_color_f};">{_ccc_f}</div>'
                            f'</div>', unsafe_allow_html=True)
                    if _oper_f.get('Verdict'):
                        st.caption(f'💡 {_oper_f["Verdict"]}')

                # ── 獲利能力模組（Profitability Module）─────────
                _prof_f = _fd_f.get('profitability_module', {})
                if _prof_f and not _fd_f.get('error'):
                    st.markdown('**💰 獲利能力診斷（MJ 5大指標）**')
                    _p5f = st.columns(5)
                    _gm_f = _prof_f.get('Gross_Margin', {})
                    _gm_f_ok = _gm_f.get('Status', '') == 'Good'
                    with _p5f[0]:
                        st.markdown(
                            f'<div style="background:{"#3fb95018" if _gm_f_ok else "#f8514918"};border:1px solid {"#3fb95055" if _gm_f_ok else "#f8514955"};'
                            f'border-radius:8px;padding:8px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">毛利率</div>'
                            f'<div style="font-size:15px;font-weight:900;color:{"#3fb950" if _gm_f_ok else "#f85149"};">{_gm_f.get("Value","N/A")}</div>'
                            f'<div style="font-size:9px;color:{"#3fb950" if _gm_f_ok else "#f85149"};">{"好生意" if _gm_f_ok else "辛苦"}</div>'
                            f'</div>', unsafe_allow_html=True)
                    _om_f = _prof_f.get('Operating_Margin', {})
                    _om_f_ok = _om_f.get('Core_Business_Profitable', 'No') == 'Yes'
                    with _p5f[1]:
                        st.markdown(
                            f'<div style="background:{"#3fb95018" if _om_f_ok else "#f8514918"};border:1px solid {"#3fb95055" if _om_f_ok else "#f8514955"};'
                            f'border-radius:8px;padding:8px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">營業利益率</div>'
                            f'<div style="font-size:15px;font-weight:900;color:{"#3fb950" if _om_f_ok else "#f85149"};">{_om_f.get("Value","N/A")}</div>'
                            f'<div style="font-size:9px;color:{"#3fb950" if _om_f_ok else "#f85149"};">{"本業獲利✅" if _om_f_ok else "本業虧損❌"}</div>'
                            f'</div>', unsafe_allow_html=True)
                    _mos_f = _prof_f.get('Margin_Of_Safety', {})
                    _mos_f_ok = _mos_f.get('Status', '') == 'Strong'
                    with _p5f[2]:
                        st.markdown(
                            f'<div style="background:{"#3fb95018" if _mos_f_ok else "#d2992218"};border:1px solid {"#3fb95055" if _mos_f_ok else "#d2992255"};'
                            f'border-radius:8px;padding:8px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">安全邊際</div>'
                            f'<div style="font-size:15px;font-weight:900;color:{"#3fb950" if _mos_f_ok else "#d29922"};">{_mos_f.get("Value","N/A")}</div>'
                            f'<div style="font-size:9px;color:{"#3fb950" if _mos_f_ok else "#d29922"};">{"抗震極強" if _mos_f_ok else "費用偏高"}</div>'
                            f'</div>', unsafe_allow_html=True)
                    _nm_f = _prof_f.get('Net_Margin', {})
                    _nm_f_s = _nm_f.get('Status', '')
                    _nm_f_c = '#3fb950' if _nm_f_s == 'Pass' else ('#d29922' if _nm_f_s == 'Thin Profit' else '#f85149')
                    with _p5f[3]:
                        st.markdown(
                            f'<div style="background:{_nm_f_c}18;border:1px solid {_nm_f_c}55;'
                            f'border-radius:8px;padding:8px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">稅後淨利率</div>'
                            f'<div style="font-size:15px;font-weight:900;color:{_nm_f_c};">{_nm_f.get("Value","N/A")}</div>'
                            f'<div style="font-size:9px;color:{_nm_f_c};">{_nm_f_s}</div>'
                            f'</div>', unsafe_allow_html=True)
                    _roe_f = _prof_f.get('ROE', {})
                    _roe_f_warn = _roe_f.get('Leverage_Warning', 'None') != 'None'
                    try:
                        _roe_f_num = float(_roe_f.get('Value', '0').replace('%', '').strip())
                    except (ValueError, AttributeError):
                        _roe_f_num = None
                    _roe_f_positive = _roe_f_num is not None and _roe_f_num > 0
                    _roe_f_c = '#d29922' if _roe_f_warn else ('#3fb950' if _roe_f_positive else '#f85149')
                    with _p5f[4]:
                        st.markdown(
                            f'<div style="background:{_roe_f_c}18;border:1px solid {_roe_f_c}55;'
                            f'border-radius:8px;padding:8px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">ROE</div>'
                            f'<div style="font-size:15px;font-weight:900;color:{_roe_f_c};">{_roe_f.get("Value","N/A")}</div>'
                            f'<div style="font-size:9px;color:{_roe_f_c};">{"⚠️ 高槓桿" if _roe_f_warn else ("✅ 真實獲利" if _roe_f_positive else "❌ 本業虧損")}</div>'
                            f'</div>', unsafe_allow_html=True)
                    if _prof_f.get('Final_Insight'):
                        st.caption(f'🎯 {_prof_f["Final_Insight"]}')

                # ── 財務結構模組（Financial Structure Module）────
                _fstr_f = _fd_f.get('financial_structure_module', {})
                if _fstr_f and not _fd_f.get('error'):
                    st.markdown('**🏗️ 財務結構診斷（那根棒子 + 以長支長）**')
                    _fsf2c = st.columns(2)
                    _dr_f = _fstr_f.get('Debt_Ratio', {})
                    _dr_f_s = _dr_f.get('Status', '')
                    _dr_f_c = {'Pass': '#3fb950', 'Warning': '#d29922', 'Fail': '#f85149', 'N/A': '#8b949e'}.get(_dr_f_s, '#8b949e')
                    with _fsf2c[0]:
                        st.markdown(
                            f'<div style="background:{_dr_f_c}18;border:1px solid {_dr_f_c}55;'
                            f'border-radius:8px;padding:10px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">負債佔資產比率</div>'
                            f'<div style="font-size:20px;font-weight:900;color:{_dr_f_c};">{_dr_f.get("Value","N/A")}</div>'
                            f'<div style="font-size:10px;color:{_dr_f_c};">'
                            f'{"✅ 穩健" if _dr_f_s=="Pass" else ("⚠️ 偏高" if _dr_f_s=="Warning" else ("🔴 高危" if _dr_f_s=="Fail" else ("🏦 特許行業" if "金融" in _dr_f.get("Value","") else "⚪ 資料缺漏")))}'
                            f'</div></div>', unsafe_allow_html=True)
                    _ltf_f = _fstr_f.get('Long_Term_Funding_Ratio', {})
                    _ltf_f_s = _ltf_f.get('Status', '')
                    _ltf_f_c = '#3fb950' if _ltf_f_s == 'Pass' else ('#8b949e' if _ltf_f_s == 'N/A' else '#f85149')
                    _ltf_f_label = ('✅ 資金配置正確' if _ltf_f_s == 'Pass'
                                    else ('⚪ 資料不足' if _ltf_f_s == 'N/A'
                                          else '🔴 短債長投危機'))
                    with _fsf2c[1]:
                        st.markdown(
                            f'<div style="background:{_ltf_f_c}18;border:1px solid {_ltf_f_c}55;'
                            f'border-radius:8px;padding:10px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">以長支長比率</div>'
                            f'<div style="font-size:20px;font-weight:900;color:{_ltf_f_c};">{_ltf_f.get("Value","N/A")}</div>'
                            f'<div style="font-size:10px;color:{_ltf_f_c};">'
                            f'{_ltf_f_label}'
                            f'</div></div>', unsafe_allow_html=True)
                    if _fstr_f.get('Final_Insight'):
                        st.caption(f'🏗️ {_fstr_f["Final_Insight"]}')

                # ── 償債能力模組（Solvency Module）─────────────
                _solv_f = _fd_f.get('solvency_module', {})
                if _solv_f and not _fd_f.get('error'):
                    st.markdown('**🛡️ 短期償債能力（MJ 300/150 嚴格標準）**')
                    _sv_f_v = _solv_f.get('Final_Solvency_Verdict', '')
                    _sv_f_pass = 'Pass' in _sv_f_v
                    _sv_f_exc  = 'Exception' in _sv_f_v
                    _sv_f_bc   = '#3fb950' if _sv_f_pass and not _sv_f_exc else ('#d29922' if _sv_f_exc else '#f85149')
                    _sv_f_icon = '✅' if _sv_f_pass and not _sv_f_exc else ('⚡' if _sv_f_exc else '🔴')
                    st.markdown(
                        f'<div style="background:{_sv_f_bc}18;border:1px solid {_sv_f_bc}55;'
                        f'border-radius:8px;padding:6px 12px;margin-bottom:6px;">'
                        f'<span style="font-size:12px;font-weight:700;color:{_sv_f_bc};">'
                        f'{_sv_f_icon} {_sv_f_v}</span></div>', unsafe_allow_html=True)
                    _is_dso_exc_f  = "條件B：天天收現" in _sv_f_v
                    _is_cash_exc_f = "條件A：現金充足" in _sv_f_v
                    _is_any_exc_f  = _is_dso_exc_f or _is_cash_exc_f
                    _cr_thresh_f   = 150 if _is_dso_exc_f else (100 if _is_cash_exc_f else 300)
                    _cr_label_f    = (f'流動比率（保命符放寬 >{_cr_thresh_f}%）'
                                      if _is_any_exc_f else '流動比率 >300%')
                    _svf2c = st.columns(2)
                    for _col_s, (_key_s, _label_s) in zip(_svf2c, [
                        ('Current_Ratio', _cr_label_f),
                        ('Quick_Ratio',   '速動比率 >150%'),
                    ]):
                        _si_f = _solv_f.get(_key_s, {})
                        _si_f_s = _si_f.get('Status', '')
                        if _key_s == 'Current_Ratio' and _is_any_exc_f:
                            try:
                                _cr_f_num = float(_si_f.get('Value', '0').replace('%', '').strip())
                                if _cr_f_num > _cr_thresh_f:
                                    _si_f_c, _si_f_s = '#3fb950', f'Pass（保命符 >{_cr_thresh_f}%）'
                                else:
                                    _si_f_c = '#f85149'
                            except (ValueError, AttributeError):
                                _si_f_c = '#3fb950' if 'Pass' in _si_f_s else '#f85149'
                        else:
                            _si_f_c = '#3fb950' if 'Pass' in _si_f_s else '#f85149'
                        with _col_s:
                            st.markdown(
                                f'<div style="background:{_si_f_c}18;border:1px solid {_si_f_c}55;'
                                f'border-radius:8px;padding:8px;text-align:center;">'
                                f'<div style="font-size:10px;color:#8b949e;">{_label_s}</div>'
                                f'<div style="font-size:18px;font-weight:900;color:{_si_f_c};">{_si_f.get("Value","N/A")}</div>'
                                f'<div style="font-size:10px;color:{_si_f_c};">{_si_f_s}</div>'
                                f'</div>', unsafe_allow_html=True)
                    if _is_dso_exc_f:
                        st.info('🔍 收現行業保命符（DSO ≤ 15天，流動比率門檻 >150%）')
                    elif _is_cash_exc_f:
                        st.info('💰 現金充足保命符（現金佔總資產 >25%，流動比率門檻 >100%）')
                    if _solv_f.get('Final_Insight'):
                        st.caption(f'🛡️ {_solv_f["Final_Insight"]}')

                # ── 綜合診斷模組（Advanced Diagnostic Module）────
                _adv_f = _fd_f.get('advanced_diagnostic_module', {})
                if _adv_f and not _fd_f.get('error'):
                    st.markdown('**🔬 綜合診斷與避雷（跨表勾稽）**')
                    _adf3c = st.columns(3)
                    # 盈餘品質
                    _eq_f = _adv_f.get('Earnings_Quality', {})
                    _eq_f_s = _eq_f.get('Status', '')
                    _eq_f_c = '#3fb950' if _eq_f_s == 'Pass' else ('#f85149' if _eq_f_s == 'Fail' else '#8b949e')
                    with _adf3c[0]:
                        st.markdown(
                            f'<div style="background:{_eq_f_c}18;border:1px solid {_eq_f_c}55;'
                            f'border-radius:8px;padding:8px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">盈餘含金量</div>'
                            f'<div style="font-size:16px;font-weight:900;color:{_eq_f_c};">{_eq_f.get("Value","N/A")}</div>'
                            f'<div style="font-size:10px;color:{_eq_f_c};">{"✅ 真金白銀" if _eq_f_s=="Pass" else ("🔴 紙上富貴" if _eq_f_s=="Fail" else "N/A")}</div>'
                            f'</div>', unsafe_allow_html=True)
                    # 雙高危機
                    _dh_f = _adv_f.get('Double_High_Warning', '')
                    _dh_f_c = '#f85149' if 'Triggered' in _dh_f else ('#3fb950' if 'Clear' in _dh_f else '#8b949e')
                    with _adf3c[1]:
                        st.markdown(
                            f'<div style="background:{_dh_f_c}18;border:1px solid {_dh_f_c}55;'
                            f'border-radius:8px;padding:8px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">雙高危機</div>'
                            f'<div style="font-size:13px;font-weight:900;color:{_dh_f_c};">{"🔴 觸發！" if "Triggered" in _dh_f else ("✅ 安全" if "Clear" in _dh_f else "⬜ N/A")}</div>'
                            f'</div>', unsafe_allow_html=True)
                    # 企業 DNA
                    _dna_f = _adv_f.get('Business_DNA', 'N/A')
                    _dna_f_c = '#3fb950' if 'A+' in _dna_f else ('#f85149' if '瀕死' in _dna_f else '#58a6ff')
                    with _adf3c[2]:
                        st.markdown(
                            f'<div style="background:{_dna_f_c}18;border:1px solid {_dna_f_c}55;'
                            f'border-radius:8px;padding:8px;text-align:center;">'
                            f'<div style="font-size:10px;color:#8b949e;">企業 DNA</div>'
                            f'<div style="font-size:11px;font-weight:900;color:{_dna_f_c};">{_dna_f}</div>'
                            f'</div>', unsafe_allow_html=True)
                    if _adv_f.get('Final_Verdict'):
                        st.caption(f'🔬 {_adv_f["Final_Verdict"]}')

                # AI 診斷
                _insight_f = _fd_f.get('ai_insight', '')
                if _insight_f:
                    st.markdown(
                        f'<div style="background:#161b22;border-left:3px solid #3fb950;'
                        f'padding:10px 14px;border-radius:0 6px 6px 0;'
                        f'font-size:13px;color:#c9d1d9;margin-top:8px;">'
                        f'🤖 {_insight_f}</div>',
                        unsafe_allow_html=True
                    )

                # 紅旗
                _flags_f = _fd_f.get('red_flags', 'None')
                if _flags_f and _flags_f not in ('None', ''):
                    st.error(f'🚩 紅旗警示：{_flags_f}')
                else:
                    st.success('✅ 未發現財報紅旗異常')

    # ── AI 投資組合綜合判讀 ───────────────────────────────────────
    if results_t3:
        st.markdown('---')
        st.markdown("""<div style="margin:16px 0 8px;padding:8px 16px;background:linear-gradient(90deg,#76e3ea18,#0d1117);border-left:4px solid #76e3ea;border-radius:0 6px 6px 0;"><span style="font-size:15px;font-weight:900;color:#76e3ea;">🤖 AI 投資組合綜合判讀</span><span style="font-size:11px;color:#8b949e;margin-left:8px;">台股資深基金經理人 · 強弱排序 · 汰弱留強 · 風險診斷</span></div>""", unsafe_allow_html=True)
        _t3ai_key = 't3_port_' + '_'.join(sorted(r.get('stock_id', r.get('代碼','')) for r in results_t3[:10]))
        _t3ai_cached = st.session_state.get(_t3ai_key, '')
        _t3ai_c1, _t3ai_c2 = st.columns([3, 1])
        with _t3ai_c1:
            _t3ai_btn = st.button('🤖 生成 AI 投資組合分析報告', key='t3_ai_gen', type='primary')
        with _t3ai_c2:
            if st.button('🔄 重新生成', key='t3_ai_regen'):
                st.session_state.pop(_t3ai_key, None)
                st.rerun()
        if _t3ai_btn:
            _port_lines = []
            for _rp in results_t3:
                _sid_p = _rp.get('stock_id', _rp.get('代碼',''))
                _nm_p  = _rp.get('stock_name', _rp.get('名稱', _sid_p))
                _ht_p  = _rp.get('_health', 0)
                _sc_p  = _rp.get('total', _rp.get('舊評分', 0))
                _fd_p  = _fund_map.get(_sid_p, {})
                _fhp   = _fh_t3_cached.get(_sid_p, {})
                _dna_p = _fhp.get('business_model_dna', 'N/A') if _fhp else 'N/A'
                _fb_p  = _rp.get('foreign_buy', 0) or 0
                _rsi_p = _rp.get('rsi', 'N/A')
                _ma_p  = '多頭排列' if (_rp.get('ma_above', 0) or 0) >= 2 else '空頭排列'
                _vcp_p = 'VCP突破' if _rp.get('vcp_signal') else '未突破'
                _port_lines.append(
                    f"[{_sid_p} {_nm_p}] 健康度={_ht_p:.0f} 評分={_sc_p:.0f} | "
                    f"技術: 均線={_ma_p} RSI={_rsi_p} {_vcp_p} | "
                    f"籌碼: 外資{'買超' if _fb_p>0 else '賣超'}{abs(_fb_p)/1e8:.1f}億 | "
                    f"基本面: EPS={_fd_p.get('近4季EPS','-')} 毛利={_fd_p.get('毛利率%','-')}% | "
                    f"財報DNA={_dna_p}"
                )
            _reg_p = st.session_state.get('mkt_info', {}).get('regime', 'neutral')
            _reg_txt_p = '多頭市場（積極操作）' if _reg_p == 'bull' else ('空頭市場（縮減部位）' if _reg_p == 'bear' else '震盪整理（謹慎觀望）')
            _exp_p = st.session_state.get('macro_state', {}).get('exposure_limit_pct', 'N/A')
            # ── 抓取組合中各股個別新聞（最多前4檔，每檔2則）──────────
            _t3_news_lines = []
            for _rp_n in results_t3[:4]:
                _sid_n = _rp_n.get('stock_id', _rp_n.get('代碼',''))
                _nm_n  = _rp_n.get('stock_name', _rp_n.get('名稱', _sid_n))
                _nn    = _fetch_stock_news(_sid_n, _nm_n, 2)
                _nn_lines = '\n'.join(
                    f'  - {_ni["title"]}（{_ni.get("published","")}）'
                    for _ni in _nn
                ) if _nn else '  （暫無新聞）'
                _t3_news_lines.append(f'[{_sid_n} {_nm_n}]\n{_nn_lines}')
            _t3_news_str = '\n'.join(_t3_news_lines) if _t3_news_lines else '（暫無相關新聞）'
            _prompt_parts = [
                "你是一位掌管百億資金的「台股資深基金經理人」與「量化策略師」。",
                "專長是從投資組合高度進行資金效能最大化、汰弱留強與風險對沖。分析冷靜、客觀。",
                "禁止出現「一定要買」「保證獲利」等字眼。統一使用繁體中文。",
                "",
                f"大盤格局={_reg_txt_p} | 建議持股上限={_exp_p}%",
                "",
                "投資組合數據：",
            ] + _port_lines + [
                "",
                "【近期各股相關新聞】（RSS即時，輔助研判用）",
                _t3_news_str,
                "",
                "請依以下格式輸出《投資組合戰略優化報告》：",
                "",
                "#### 一、組合強弱排序矩陣",
                "| 梯隊 | 股票 | 核心催化劑 | 法人態度 | 綜合評分 |",
                "|:---|:---|:---|:---|:---|",
                "| S級（強勢領漲）| ... | ... | 偏多 | ... |",
                "| A級（蓄勢待發）| ... | ... | 中立 | ... |",
                "| B級（弱勢汰換）| ... | ... | 偏空 | ... |",
                "",
                "#### 二、投資組合體質與風險診斷",
                "- 產業集中度分析：",
                "- 總經環境適配度：",
                "",
                "#### 三、汰弱留強戰術建議（僅供策略參考，不構成投資邀約）",
                "- 建議減碼/剔除名單：",
                "- 建議加碼/核心名單（含資金分配比例建議）：",
                "",
                "#### 四、組合防禦底線",
                "（設定整個組合的綜合防禦觀測指標）",
            ]
            _t3ai_prompt = '\n'.join(_prompt_parts)
            with st.spinner('AI 基金經理人分析中（約 30 秒）...'):
                _t3ai_result = gemini_call(_t3ai_prompt, max_tokens=2000)
            st.session_state[_t3ai_key] = _t3ai_result
        if _t3ai_cached:
            st.markdown(_t3ai_cached)
        elif not _t3ai_btn:
            st.caption('▲ 點擊上方按鈕，AI 將生成投資組合強弱排序矩陣與汰弱留強建議。')
