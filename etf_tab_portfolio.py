"""ETF 組合配置 TAB — 從 etf_dashboard.py 抽出（PR P2-B Phase 6-B）

依賴策略
========
- Top-level: streamlit
- 函式內 late import 14 個依賴：
  * stdlib: numpy, pandas
  * 外部: unified_decision.render_unified_decision
  * etf_dashboard.py 內部 helper (10):
    _check_sector_exposure / _colored_box / _compute_etf_warroom_row
    / _plot_correlation / _teacher_conclusion
    / fetch_etf_dividends / fetch_etf_info / fetch_etf_price
    / macro_allocation_banner

呼叫端
======
- app.py 經 etf_dashboard re-export 取用
"""
from __future__ import annotations

import streamlit as st

from etf_helpers import auto_role


def render_etf_portfolio(gemini_fn=None):
    # ─ Late imports（避免循環 import）─
    import numpy as np
    import pandas as pd
    from unified_decision import render_unified_decision
    from etf_dashboard import (
        _check_sector_exposure, _colored_box, _compute_etf_warroom_row,
        _plot_correlation, _plot_holdings_overlap, _render_weakness_table,
        _teacher_conclusion,
        build_holdings_overlap_matrix, compute_etf_weakness_row,
        fetch_etf_dividends, fetch_etf_holdings, fetch_etf_info, fetch_etf_price,
        macro_allocation_banner,
    )

    mkt_info = st.session_state.get('mkt_info', {})
    regime   = mkt_info.get('regime', 'neutral')
    macro_allocation_banner(regime)

    st.markdown('#### 📋 輸入持股組合')
    st.caption('💡 表格欄位：**股票代號 / 持有張數 / 平均買入價格**。'
               '系統自動：① 1 張 = 1000 股換算 ② 核心/衛星判讀 ③ 即時收盤價算現值、資本利得、已領配息。'
               '可用「+」新增列、勾選後 Del 刪除列。')

    # ── 結構化表單輸入（取代 text_area）─────────────────────
    _default_df = pd.DataFrame(
        st.session_state.get('etf_p_loaded_df') or {
            '股票代號':       ['0050.TW', '00713.TW', 'BND', '00878.TW'],
            '持有張數':       [1.0, 0.5, 0.2, 2.0],
            '平均買入價格':   [135.50, 82.30, 72.50, 20.10],
        }
    )
    edited_df = st.data_editor(
        _default_df, num_rows='dynamic', hide_index=True,
        use_container_width=True, key='etf_p_table',
        column_config={
            '股票代號':     st.column_config.TextColumn(
                '股票代號', required=True, width='medium',
                help='台股加 .TW / .TWO 後綴；海外 ETF 直接代號（如 BND、VOO）'),
            '持有張數':     st.column_config.NumberColumn(
                '持有張數', required=True, min_value=0.0, format='%.2f', width='small',
                help='台股 1 張 = 1000 股；可填小數（如 0.2 張 = 200 股）'),
            '平均買入價格': st.column_config.NumberColumn(
                '平均買入價格', required=True, min_value=0.0, format='%.2f', width='small',
                help='你過去買入此檔的成本均價'),
        })

    # ── 雲端儲存（Google Sheet）─────────────────────────────
    _render_cloud_storage(edited_df)

    tolerance = st.slider('再平衡容忍偏離度（%）', 1, 15, 5, key='etf_p_tol')

    if st.button('📊 計算組合', key='etf_p_btn', use_container_width=True):
        st.session_state['etf_p_active'] = True

    if not st.session_state.get('etf_p_active'):
        st.info('💡 填好上方表格後點擊「計算組合」')
        return

    # ── 解析 data_editor 表格 → rows（1 張 = 1000 股換算）─────
    rows = []
    for _, _row in edited_df.iterrows():
        _tk_raw = str(_row.get('股票代號') or '').strip().upper()
        if not _tk_raw:
            continue
        try:
            _lots      = float(_row.get('持有張數') or 0)
            _avg_price = float(_row.get('平均買入價格') or 0)
        except (TypeError, ValueError):
            st.warning(f'⚠️ {_tk_raw} 張數/均價非數字，已略過')
            continue
        if _lots <= 0 or _avg_price <= 0:
            st.warning(f'⚠️ {_tk_raw} 張數或均價為 0，已略過')
            continue
        _shares = _lots * 1000  # 1 張 = 1000 股
        rows.append({
            'ticker':     _tk_raw,
            'lots':       _lots,
            'shares':     _shares,
            'avg_price':  _avg_price,
            'cost':       _shares * _avg_price,
            'target_pct': None,         # 不再有「希望比例」輸入 → 以實際現值權重為目標
            'role':       auto_role(_tk_raw),
        })
    if not rows:
        st.error('❌ 請至少填入一筆有效持股（代號 + 張數 + 均價皆 > 0）')
        return

    # ── 批次抓現價 + 配息（每檔 yfinance 已有 @st.cache_data 護身）──
    _cur_prices = {}
    _div_received = {}
    with st.spinner('抓取現價與配息資料...'):
        import datetime as _dt_pf
        _cutoff = pd.Timestamp(_dt_pf.date.today() - _dt_pf.timedelta(days=365))
        for r in rows:
            _tk = r['ticker']
            try:
                _df_p = fetch_etf_price(_tk, period='5d')
                _cur_prices[_tk] = float(_df_p['Close'].iloc[-1]) if _df_p is not None and not _df_p.empty else 0.0
            except Exception:
                _cur_prices[_tk] = 0.0
            try:
                _div_s = fetch_etf_dividends(_tk)
                if _div_s is not None and not _div_s.empty:
                    _div_s = _div_s.copy()
                    _div_s.index = pd.to_datetime(_div_s.index, errors='coerce')
                    # 移除 tz info 避免 cutoff 比對失敗
                    try:
                        _div_s.index = _div_s.index.tz_localize(None)
                    except Exception:
                        pass
                    _recent = _div_s[_div_s.index >= _cutoff]
                    _div_received[_tk] = float(_recent.sum()) * r['shares']
                else:
                    _div_received[_tk] = 0.0
            except Exception:
                _div_received[_tk] = 0.0

    # ── 算現值/資本利得/已領配息 ──
    for r in rows:
        _cp = _cur_prices.get(r['ticker'], 0.0)
        r['current_price']   = _cp
        r['current_value']   = r['shares'] * _cp
        r['capital_gain']    = r['current_value'] - r['cost']
        r['capital_gain_pct']= (r['capital_gain'] / r['cost'] * 100) if r['cost'] > 0 else 0.0
        r['dividend_received'] = _div_received.get(r['ticker'], 0.0)
        # 總損益 = 資本利得 + 已領配息（粗略不含稅費）
        r['total_pnl']       = r['capital_gain'] + r['dividend_received']

    total_value = sum(r['current_value'] for r in rows)
    total_cost  = sum(r['cost'] for r in rows)
    total_gain  = sum(r['capital_gain'] for r in rows)
    total_div   = sum(r['dividend_received'] for r in rows)

    # target_pct 全為 None（新表格輸入無希望比例欄）→ 直接用實際現值權重作目標
    # 偏離度 = 0，下游再平衡邏輯仍可運作（按實際權重平衡 = 不需動作）
    for r in rows:
        if r['target_pct'] is None:
            r['target_pct'] = round(r['current_value'] / total_value * 100, 2) if total_value > 0 else 0

    for r in rows:
        r['actual_pct'] = round(r['current_value'] / total_value * 100, 2) if total_value > 0 else 0
        r['deviation']  = round(r['actual_pct'] - r['target_pct'], 2)

    # ── 共享給下游模組（葡萄串領息法 / AI 評斷）──
    st.session_state['etf_portfolio_rows'] = rows

    # ── 資產總覽卡（總成本 / 總現值 / 資本利得 / 已領配息 / 總損益）──
    _gain_color = '#3fb950' if total_gain >= 0 else '#f85149'
    _gain_sign  = '+' if total_gain >= 0 else ''
    _total_pnl  = total_gain + total_div
    _pnl_color  = '#3fb950' if _total_pnl >= 0 else '#f85149'
    _pnl_sign   = '+' if _total_pnl >= 0 else ''
    st.markdown(
        f'<div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;'
        f'padding:16px 20px;margin:8px 0 16px;display:flex;gap:24px;flex-wrap:wrap;">'
        f'<div><div style="font-size:11px;color:#8b949e;">總投入成本</div>'
        f'<div style="font-size:18px;font-weight:700;color:#c9d1d9;">{total_cost:,.0f}</div></div>'
        f'<div><div style="font-size:11px;color:#8b949e;">總現值</div>'
        f'<div style="font-size:18px;font-weight:700;color:#c9d1d9;">{total_value:,.0f}</div></div>'
        f'<div><div style="font-size:11px;color:#8b949e;">資本利得</div>'
        f'<div style="font-size:18px;font-weight:700;color:{_gain_color};">'
        f'{_gain_sign}{total_gain:,.0f} ({_gain_sign}{(total_gain/total_cost*100 if total_cost else 0):.2f}%)</div></div>'
        f'<div><div style="font-size:11px;color:#8b949e;">已領配息（近1年）</div>'
        f'<div style="font-size:18px;font-weight:700;color:#d29922;">+{total_div:,.0f}</div></div>'
        f'<div><div style="font-size:11px;color:#8b949e;">總損益（利得+配息）</div>'
        f'<div style="font-size:18px;font-weight:900;color:{_pnl_color};">'
        f'{_pnl_sign}{_total_pnl:,.0f} ({_pnl_sign}{(_total_pnl/total_cost*100 if total_cost else 0):.2f}%)</div></div>'
        f'</div>', unsafe_allow_html=True)

    # ── 持股明細表 ──
    # 查詢 ETF 名稱（去掉 .TW/.TWO 後綴後查 stock_names）
    try:
        from stock_names import get_stock_name as _gsn_etf
        def _etf_name(tk):
            code = tk.replace('.TWO','').replace('.TW','')
            n = _gsn_etf(code)
            return n if n and n != code else (fetch_etf_info(tk).get('shortName') or fetch_etf_info(tk).get('longName') or tk)
    except Exception:
        def _etf_name(tk): return tk
    overview_df = pd.DataFrame([{
        'ETF':       r['ticker'],
        '名稱':       _etf_name(r['ticker']),
        '類型':       r.get('role', '—'),
        '張數':       f'{r.get("lots", r["shares"]/1000):.2f}',
        '股數':       f'{int(r["shares"]):,}',
        '均價':       f'{r["avg_price"]:.2f}',
        '現價':       f'{r["current_price"]:.2f}' if r['current_price'] > 0 else '-',
        '成本(元)':   f'{r["cost"]:,.0f}',
        '現值(元)':   f'{r["current_value"]:,.0f}',
        '資本利得':   f'{"+" if r["capital_gain"]>=0 else ""}{r["capital_gain"]:,.0f}',
        '利得%':      f'{"+" if r["capital_gain_pct"]>=0 else ""}{r["capital_gain_pct"]:.2f}%',
        '已領配息':   f'+{r["dividend_received"]:,.0f}' if r['dividend_received'] > 0 else '-',
        '目標比例%':  f'{r["target_pct"]:.1f}',
        '實際比例%':  f'{r["actual_pct"]:.1f}',
        '偏離度%':    f'{"+" if r["deviation"]>=0 else ""}{r["deviation"]:.1f}',
    } for r in rows])
    st.dataframe(overview_df, use_container_width=True, hide_index=True)

    # ── 🛰️ ETF 追蹤戰情室（核心/衛星分流燈號 + Sparkline）─────
    st.markdown('#### 🛰️ ETF 追蹤戰情室（核衛分流健檢）')
    st.caption('💡 **核心**看「總報酬 vs 殖利率 + MA60 趨勢」；**衛星**看「MA20 ± σ 五階分級買賣點」')
    with st.spinner('批次計算 ETF 健檢指標...'):
        _war_rows = [_compute_etf_warroom_row(r['ticker'], _etf_name(r['ticker']),
                                              r.get('role', '—'))
                     for r in rows]

    # 核心戰情室 column_config
    _core_cols = {
        '代號':         st.column_config.TextColumn('代號', width='small'),
        '名稱':         st.column_config.TextColumn('名稱', width='medium'),
        '市價':         st.column_config.NumberColumn('市價', format='%.2f'),
        '折溢價%':      st.column_config.NumberColumn('折溢價%', format='%+.2f%%',
                          help='> +1% 追高；< 0% 折價撿便宜（MK 條件 C）'),
        '年化配息率%':  st.column_config.NumberColumn('年化配息率%', format='%.2f%%'),
        '1年含息報酬%': st.column_config.NumberColumn('1年含息報酬%', format='%+.2f%%',
                          help='含息總報酬，與年化配息率比較'),
        '距季線%':      st.column_config.NumberColumn('距 MA60%', format='%+.2f%%',
                          help='負值=跌破季線 → 🟡 趨勢轉弱'),
        '走勢':         st.column_config.LineChartColumn('近30日走勢'),
        '健康燈號':     st.column_config.TextColumn('體質燈號', width='large',
                          help='🟢 體質健康 / 🔴 賺息賠本 / 🟡 趨勢轉弱'),
        '動作建議':     st.column_config.TextColumn('動作建議', width='medium'),
    }

    # 衛星戰情室 column_config：突顯 σ 位階 + 加碼比例
    _sat_cols = {
        '代號':         st.column_config.TextColumn('代號', width='small'),
        '名稱':         st.column_config.TextColumn('名稱', width='medium'),
        '市價':         st.column_config.NumberColumn('市價', format='%.2f'),
        '距月線%':      st.column_config.NumberColumn('距 MA20%', format='%+.2f%%',
                          help='相對月線乖離；σ 分級的基準'),
        'σ位階':        st.column_config.TextColumn('σ 位階', width='medium',
                          help='-3σ 股災 / -2σ 超跌 / -1σ 便宜 / +2σ 停利'),
        '1年含息報酬%': st.column_config.NumberColumn('1年含息報酬%', format='%+.2f%%'),
        '走勢':         st.column_config.LineChartColumn('近30日走勢'),
        '健康燈號':     st.column_config.TextColumn('σ 燈號', width='medium',
                          help='🟢🟢🟢 大買 50% / 🟢🟢 買 30% / 🟢 小買 20% / 🔴 停利'),
        '動作建議':     st.column_config.TextColumn('動作建議', width='medium',
                          help='依 σ 位階自動推導加碼/停利比例'),
    }

    # 其他角色簡表
    _other_cols = {
        '代號':         st.column_config.TextColumn('代號', width='small'),
        '名稱':         st.column_config.TextColumn('名稱', width='medium'),
        '市價':         st.column_config.NumberColumn('市價', format='%.2f'),
        '年化配息率%':  st.column_config.NumberColumn('年化配息率%', format='%.2f%%'),
        '1年含息報酬%': st.column_config.NumberColumn('1年含息報酬%', format='%+.2f%%'),
        '走勢':         st.column_config.LineChartColumn('近30日走勢'),
        '健康燈號':     st.column_config.TextColumn('燈號', width='medium'),
    }

    # ── 核心資產戰情室（佔比 80%）────────────────────────────
    _core_rows = [w for w in _war_rows if w.get('類型') == '核心']
    _sat_rows  = [w for w in _war_rows if w.get('類型') == '衛星']
    _other_rows = [w for w in _war_rows if w.get('類型') not in ('核心', '衛星')]

    if _core_rows:
        st.markdown('##### 🏛️ 核心資產戰情室（目標 80%）— 穩領息')
        st.caption('🔴 賺息賠本（總報酬<殖利率）→ 換股 ｜ 🟡 跌破 MA60 → 趨勢轉弱 ｜ 🟢 體質健康（雙條件全綠）')
        _core_df = pd.DataFrame(_core_rows)[
            ['代號', '名稱', '市價', '折溢價%', '年化配息率%',
             '1年含息報酬%', '距季線%', '走勢', '健康燈號', '動作建議']
        ]
        st.dataframe(_core_df, column_config=_core_cols,
                     use_container_width=True, hide_index=True)
    if _sat_rows:
        st.markdown('##### 🚀 衛星資產戰情室（目標 20%）— 跌了就買 σ 分級')
        st.caption('🟢🟢🟢 < MA20-3σ 股災價(大買 50%) ｜ 🟢🟢 < -2σ 超跌(30%) ｜ 🟢 < -1σ 便宜(20%) ｜ 🔴 ≥ +2σ 停利')
        _sat_df = pd.DataFrame(_sat_rows)[
            ['代號', '名稱', '市價', '距月線%', 'σ位階',
             '1年含息報酬%', '走勢', '健康燈號', '動作建議']
        ]
        st.dataframe(_sat_df, column_config=_sat_cols,
                     use_container_width=True, hide_index=True)
    if _other_rows:
        st.markdown('##### 📦 其他持倉（未分類）')
        _oth_df = pd.DataFrame(_other_rows)[
            ['代號', '名稱', '市價', '年化配息率%', '1年含息報酬%', '走勢', '健康燈號']
        ]
        st.dataframe(_oth_df, column_config=_other_cols,
                     use_container_width=True, hide_index=True)

    # ── MK 框架 #9：核心 / 衛星比例 vs regime 目標 ────────────
    _core_value = sum(r['current_value'] for r in rows if r.get('role') == '核心')
    _sat_value  = sum(r['current_value'] for r in rows if r.get('role') == '衛星')
    _core_pct = _core_value / total_value * 100 if total_value > 0 else 0.0
    _sat_pct  = _sat_value / total_value * 100 if total_value > 0 else 0.0
    try:
        from portfolio_manager import CoreSatelliteManager as _CSM
        _mgr = _CSM(total_value, regime=regime)
        _target_core_pct = _mgr.core_ratio * 100
        _target_sat_pct  = _mgr.satellite_ratio * 100
        _rebal_info = _mgr.check_rebalance(satellite_current_value=_sat_value)
        st.markdown('#### 🎯 核心 / 衛星 配置 vs MK regime 目標')
        _cs1, _cs2 = st.columns(2)
        _core_dev = _core_pct - _target_core_pct
        _sat_dev  = _sat_pct  - _target_sat_pct
        _cs1.metric(f'核心比 (目標 {_target_core_pct:.0f}%)', f'{_core_pct:.1f}%',
                    delta=f'{_core_dev:+.1f}pp',
                    delta_color='normal' if abs(_core_dev) <= 10 else 'inverse')
        _cs2.metric(f'衛星比 (目標 {_target_sat_pct:.0f}%)', f'{_sat_pct:.1f}%',
                    delta=f'{_sat_dev:+.1f}pp',
                    delta_color='normal' if abs(_sat_dev) <= 10 else 'inverse')
        if isinstance(_rebal_info, dict) and _rebal_info.get('rebalance_needed'):
            _excess = _rebal_info.get('excess_pct', 0) * 100 if _rebal_info.get('excess_pct', 0) < 1 else _rebal_info.get('excess_pct', 0)
            _colored_box(
                f'⚠️ <b>衛星超標</b> {_excess:.1f}pp（regime={regime} 目標衛星 {_target_sat_pct:.0f}%）<br>'
                f'<b>建議</b>：{_rebal_info.get("action", "考慮停利衛星部位轉入核心")}',
                'red')
            _teacher_conclusion('郭俊宏',
                                f'衛星 {_sat_pct:.1f}% > 目標 {_target_sat_pct:.0f}%',
                                '衛星部位超標，違背核衛宿命',
                                '停利衛星轉入核心（葡萄串閉環）')
        else:
            _colored_box(
                f'✅ 核衛比例符合 regime={regime} 目標範圍（±10pp 容忍）',
                'green')
            _teacher_conclusion('郭俊宏',
                                f'核 {_core_pct:.0f}% / 衛 {_sat_pct:.0f}%',
                                f'符合 regime={regime} 目標 {_target_core_pct:.0f}/{_target_sat_pct:.0f}',
                                '維持當前配置')
        st.caption('💡 **regime 目標**：多頭 60/40 / 中性 70/30 / 保守 80/20 / 空頭 85/15（核/衛）')
    except Exception as _csm_e:
        st.info(f'ℹ️ 核衛分離計算暫時不可用：{type(_csm_e).__name__}')

    # ── 再平衡交易指令（含具體股數）────────────────────────────
    st.markdown('#### ⚖️ 再平衡交易指令')
    # 現價 dict 已於上方資產追蹤段批次抓取，此處直接複用

    rebal_actions = []
    for r in rows:
        if abs(r['deviation']) > tolerance:
            target_val = total_value * r['target_pct'] / 100
            adj        = target_val - r['current_value']
            action     = '買進' if adj > 0 else '賣出'
            cur_price  = _cur_prices.get(r['ticker'], 0)
            shares     = int(abs(adj) / cur_price) if cur_price > 0 else 0
            rebal_actions.append({
                'ETF': r['ticker'], '動作': action,
                '金額(元)': abs(adj), '偏離度%': r['deviation'],
                '現價': cur_price, '建議股數': shares,
            })

    if rebal_actions:
        ra_df = pd.DataFrame([{
            'ETF':    a['ETF'],
            '動作':   a['動作'],
            '現價':   f'{a["現價"]:.2f}' if a['現價'] > 0 else '-',
            '建議股數': f'{a["建議股數"]:,}' if a['建議股數'] > 0 else '-',
            '金額(元)': f'{a["金額(元)"]:,.0f}',
            '偏離度%': a['偏離度%'],
        } for a in rebal_actions])
        st.dataframe(ra_df, use_container_width=True, hide_index=True)
        for act in rebal_actions:
            color = 'green' if act['動作'] == '買進' else 'red'
            icon  = '📈' if act['動作'] == '買進' else '📉'
            _share_txt = (f'約 <b>{act["建議股數"]:,} 股</b>（現價 {act["現價"]:.2f} 元）'
                          if act['建議股數'] > 0 else '（無法取得現價）')
            _colored_box(
                f'{icon} <b>{act["動作"]} {act["ETF"]}</b> {_share_txt}，'
                f'預估金額 <b>{act["金額(元)"]:,.0f} 元</b>（偏離 {act["偏離度%"]:+.1f}%）',
                color)
    else:
        _colored_box(f'✅ 所有標的偏離度均在 ±{tolerance}% 內，無需再平衡', 'green')

    # ── 產業曝險上限檢查（單一類股 ≤ 30%）─────────────────────
    st.markdown('#### 🏗️ 產業曝險上限檢查（單一 GICS 類股 ≤ 30%）')
    _check_sector_exposure(rows, total_value)

    # ── 相關係數矩陣 ──────────────────────────────────────────
    st.markdown('#### 🔗 相關係數矩陣（近1年）')
    st.caption('💡 此矩陣用「日報酬率」算 Pearson 相關係數，'
               '反映**價格走勢同步度**（不看持股名單）。值越接近 1 表示分散效益越差。')
    tickers = [r['ticker'] for r in rows]
    ret_dict = {}
    with st.spinner('計算相關係數...'):
        for t in tickers:
            df_t = fetch_etf_price(t, period='1y')
            if not df_t.empty:
                ret_dict[t] = df_t['Close'].pct_change()
    if len(ret_dict) >= 2:
        ret_df = pd.DataFrame(ret_dict).ffill().dropna()
        corr   = ret_df.corr()
        _plot_correlation(corr)
        for i in range(len(corr)):
            for j in range(i + 1, len(corr)):
                val = corr.iloc[i, j]
                if val > 0.85:
                    _colored_box(
                        f'⚠️ <b>{corr.index[i]} × {corr.columns[j]}</b> '
                        f'相關係數 {val:.2f} > 0.85，資產同質性過高', 'red')
    else:
        st.warning('資料不足，無法計算相關係數')

    # ── 持股 Overlap 矩陣（PR — claude/etf-holdings-overlap）────
    st.markdown('#### 🧬 持股 Overlap 矩陣（成份股重疊度）')
    st.caption('💡 與上方「價格相關」對照看：價格相關高可能因市場連動（如全市場股災），'
               '但**持股 overlap 高**代表組合在「真正持有的股票」層面高度雷同 — '
               '即使換成不同名稱的 ETF，本質上也沒分散到。')
    _ov_method = st.radio(
        '演算法',
        ('權重 Overlap%（業界標準）', 'Jaccard 集合重疊（不看權重）'),
        horizontal=True, key='ov_method_radio',
        help='權重 Overlap%：兩 ETF 共同持股取較小權重加總；Jaccard：|A∩B|/|A∪B| 只看股票名單'
    )
    _method_key = 'jaccard' if 'Jaccard' in _ov_method else 'weight'
    _h_dict = {}
    _h_miss = []
    with st.spinner('抓取成份股清單（首次約 10-20 秒，之後 1 日快取）...'):
        for t in tickers:
            _h = fetch_etf_holdings(t)
            if _h:
                _h_dict[t] = _h
            else:
                _h_miss.append(t)
    if _h_miss:
        st.warning(f'⚪ 以下 ETF 拿不到成份股，對應行列顯示 N/A：{", ".join(_h_miss)}'
                   f'（MoneyDJ 暫無資料或為新 ETF）')
    _valid_count = len(_h_dict)
    if _valid_count >= 2:
        _ov_mat = build_holdings_overlap_matrix(_h_dict, method=_method_key)
        # 補齊缺資料 ETF（讓矩陣 ticker 順序與上方價格矩陣一致）
        for _t_miss in _h_miss:
            if _t_miss not in _ov_mat.index:
                _ov_mat.loc[_t_miss] = np.nan
                _ov_mat[_t_miss]     = np.nan
        _ov_mat = _ov_mat.reindex(index=tickers, columns=tickers)
        _plot_holdings_overlap(
            _ov_mat,
            title=f'{"權重 Overlap%" if _method_key == "weight" else "Jaccard%"}（成份股 N={_valid_count}/{len(tickers)}）'
        )
        # 同質性警示（門檻：權重 > 30%；Jaccard > 50%）
        _threshold = 30.0 if _method_key == 'weight' else 50.0
        _warn_lines = []
        for i in range(len(_ov_mat)):
            for j in range(i + 1, len(_ov_mat)):
                val = _ov_mat.iloc[i, j]
                if pd.notna(val) and val > _threshold:
                    _warn_lines.append(
                        f'⚠️ <b>{_ov_mat.index[i]} × {_ov_mat.columns[j]}</b> '
                        f'{val:.1f}% > {_threshold:.0f}%，建議擇一保留'
                    )
        if _warn_lines:
            _colored_box('<br>'.join(_warn_lines), 'red')
        else:
            st.success(f'✅ 任兩檔 ETF 持股 {"權重重疊" if _method_key == "weight" else "Jaccard 重疊"} '
                       f'皆 < {_threshold:.0f}%，組合分散度健康。')
    elif _valid_count == 1:
        st.info('⚪ 僅 1 檔 ETF 抓到成份股，無法兩兩比對。')
    else:
        st.warning('⚪ 所有 ETF 都抓不到成份股清單，無法計算持股重疊（MoneyDJ 端點可能變動）。')

    # ── 主動 ETF 弱勢度檢測（PR — claude/etf-weakness-manager）──
    # Gemini 邏輯：大跌時跌得比大盤深 + 反彈時漲得比大盤慢 + 連兩季輸盤 = 該換
    st.markdown('#### 🎯 主動 ETF 弱勢度檢測（vs 大盤被動式）')
    st.caption('💡 主動式 ETF 你付 1% 經理費，**就該打贏大盤**。如果近1年大跌時它跌更深、'
               '反彈時它漲更慢，連 2 季輸盤 → 該考慮換到被動式（如 0050）。'
               '⏳ 但若**剛換新經理人 <6 個月**，建議再給時間觀察。')
    _w_rows = []
    with st.spinner('檢測弱勢度（含經理人查詢，首次約 5-15 秒）...'):
        for _r in rows:
            _w_rows.append(compute_etf_weakness_row(_r['ticker'], _r.get('name', '')))
    if _w_rows:
        _render_weakness_table(_w_rows)
        # 換股建議匯總
        _switch_targets = [r for r in _w_rows
                           if r.get('主被動') == '主動式' and (r.get('連敗季數') or 0) >= 2]
        if _switch_targets:
            _lines = []
            for _r in _switch_targets:
                _mgr_note = (f'（⏳ 新經理人 {_r["任期"]}，可再觀察）'
                             if isinstance(_r.get('任期'), str) and '個月' in _r['任期']
                             and any(ch.isdigit() for ch in _r['任期'])
                             and int(''.join(filter(str.isdigit, _r['任期'].split('個月')[0]))) < 6
                             else '')
                _lines.append(
                    f'🚨 <b>{_r["代號"]} {_r["名稱"]}</b> 已連續 {_r["連敗季數"]} 季輸 '
                    f'{_r.get("benchmark", "大盤")} — 經理人 {_r["經理人"]} '
                    f'(任期 {_r["任期"]}){_mgr_note}'
                )
            _colored_box('<br>'.join(_lines), 'red')

    # ── 壓力測試（S&P500 下跌20%）────────────────────────────
    st.markdown('#### 🧨 壓力測試（模擬 S&P 500 下跌 20%）')
    stress_results = []
    total_stress   = 0.0
    for r in rows:
        info_i  = fetch_etf_info(r['ticker'])
        beta_i  = info_i.get('beta') or info_i.get('beta3Year') or 1.0
        try:
            beta_i = float(beta_i)
        except Exception:
            beta_i = 1.0
        est_loss       = r['actual_pct'] / 100 * beta_i * (-0.20) * total_value
        total_stress  += est_loss
        stress_results.append({
            'ETF': r['ticker'], 'Beta': round(beta_i, 2),
            '實際權重%': r['actual_pct'],
            '預估虧損(元)': f'{est_loss:,.0f}',
        })
    st.dataframe(pd.DataFrame(stress_results), use_container_width=True, hide_index=True)
    loss_pct = abs(total_stress) / total_value * 100
    color    = 'red' if loss_pct > 20 else 'green'
    _colored_box(
        f'組合預估總虧損：<b>{total_stress:,.0f} 元</b>（{loss_pct:.1f}%）'
        + ('&nbsp; ⚠️ 超過20%，建議增加避險部位' if loss_pct > 20 else '&nbsp; ✅ 風險可控'),
        color)
    if loss_pct > 20:
        _teacher_conclusion('孫慶龍',
                            f'S&P500↓20% 壓力測試損失 {loss_pct:.1f}%',
                            '尾部風險超標，組合過於進攻型',
                            '增加債券 ETF 或現金部位，降低整體 Beta')
    else:
        _teacher_conclusion('孫慶龍',
                            f'S&P500↓20% 壓力測試損失 {loss_pct:.1f}%',
                            '壓力測試風險可控，組合防禦性足夠',
                            '維持現有配置，定期再平衡')

    # ── VaR 風險值（歷史模擬法 + 參數法）────────────────────────
    st.markdown('#### 📉 VaR 風險值（Value at Risk）')
    st.caption('衡量正常市況下單日最大可能虧損：歷史模擬法取近1年最差分位數，參數法假設常態分布')
    _var_rets = {}
    with st.spinner('計算 VaR...'):
        for r in rows:
            _df_v = fetch_etf_price(r['ticker'], period='1y')
            if not _df_v.empty:
                _var_rets[r['ticker']] = _df_v['Close'].pct_change().dropna()
    if len(_var_rets) >= 1:
        # 組合日報酬（加權合并）
        _all_idx = sorted(set().union(*[s.index for s in _var_rets.values()]))
        _port_ret = pd.Series(0.0, index=_all_idx)
        for r in rows:
            if r['ticker'] in _var_rets:
                _w = r['actual_pct'] / 100
                _port_ret = _port_ret.add(
                    _var_rets[r['ticker']].reindex(_all_idx).ffill().fillna(0) * _w)
        _port_ret = _port_ret.dropna()
        if len(_port_ret) >= 20:
            # 歷史模擬法
            _h95 = float(_port_ret.quantile(0.05)) * total_value
            _h99 = float(_port_ret.quantile(0.01)) * total_value
            # 參數法
            _mu  = float(_port_ret.mean())
            _sig = float(_port_ret.std())
            _p95 = (_mu - 1.645 * _sig) * total_value
            _p99 = (_mu - 2.326 * _sig) * total_value
            # 月度 VaR（√21 近似）
            _m99 = _h99 * (21 ** 0.5)

            _vc1, _vc2 = st.columns(2)
            with _vc1:
                st.markdown('**📊 歷史模擬法**')
                st.metric('95% 日 VaR', f'{abs(_h95):,.0f} 元',
                          f'{abs(_h95)/total_value*100:.2f}% 組合市值')
                st.metric('99% 日 VaR', f'{abs(_h99):,.0f} 元',
                          f'{abs(_h99)/total_value*100:.2f}% 組合市值')
                st.caption('95% VaR：正常市況下100天中，95天的虧損不超過此值')
            with _vc2:
                st.markdown('**📐 參數法（常態分布）**')
                st.metric('95% 日 VaR', f'{abs(_p95):,.0f} 元',
                          f'{abs(_p95)/total_value*100:.2f}% 組合市值')
                st.metric('99% 日 VaR', f'{abs(_p99):,.0f} 元',
                          f'{abs(_p99)/total_value*100:.2f}% 組合市值')
                st.caption('金融市場有肥尾效應，歷史模擬法通常比參數法更保守')
            _var_warn = abs(_m99) / total_value > 0.10
            _colored_box(
                f'📅 月度 99% VaR（√21 近似）：<b>{abs(_m99):,.0f} 元</b>'
                f'（{abs(_m99)/total_value*100:.2f}%）'
                + ('&nbsp; ⚠️ 超過10%，尾部風險偏高，建議增加防禦部位'
                   if _var_warn else '&nbsp; ✅ 月度尾部風險在可接受範圍內'),
                'red' if _var_warn else 'green')
            if _var_warn:
                _teacher_conclusion('弘爺',
                                    f'月度 99% VaR {abs(_m99)/total_value*100:.2f}%',
                                    '月度尾部風險 > 10%，組合波動過大',
                                    '增加低相關資產（如 BND/AGGG），降低整體波動')
            else:
                _teacher_conclusion('弘爺',
                                    f'月度 99% VaR {abs(_m99)/total_value*100:.2f}%',
                                    '月度尾部風險在可接受範圍，組合穩健',
                                    '維持現有風險配置，按計畫再平衡')
        else:
            st.warning('歷史資料不足（<20筆），無法計算 VaR')
    else:
        st.warning('無法取得價格資料，跳過 VaR 計算')

    # ── 配息日曆 × 年度現金流預估 ──────────────────────────────
    st.markdown('#### 💰 配息日曆 × 年度現金流預估')
    st.caption('依過去12個月配息紀錄 × 持有股數（市值/現價）推估未來現金流入')
    _div_data = []
    _monthly_cf = {m: 0.0 for m in range(1, 13)}
    with st.spinner('抓取配息資料...'):
        for r in rows:
            _div_s  = fetch_etf_dividends(r['ticker'])
            _price  = _cur_prices.get(r['ticker'], 0)
            _shares = int(r['current_value'] / _price) if _price > 0 else 0
            if _div_s.empty or _shares == 0:
                continue
            _cutoff  = pd.Timestamp.now() - pd.DateOffset(years=1)
            _recent  = _div_s[_div_s.index >= _cutoff]
            if _recent.empty:
                continue
            _sum = _recent.sum()
            _annual_per_share = float(np.ravel(_sum)[0]) if hasattr(_sum, '__len__') else float(_sum)
            _n_pay = len(_recent)
            _est_income = _annual_per_share * _shares
            _div_data.append({
                'ETF': r['ticker'],
                '持有股數': _shares,
                '近1年每股配息': round(_annual_per_share, 4),
                '預估年收入(元)': round(_est_income),
                '配息次數/年': _n_pay,
            })
            # 月度分配（依歷史配息月份）
            _pay_months = sorted(set(_recent.index.month.tolist()))
            for _m in _pay_months:
                _ms = _recent[_recent.index.month == _m].sum()
                _month_div = (float(np.ravel(_ms)[0]) if hasattr(_ms, '__len__') else float(_ms)) * _shares
                _monthly_cf[_m] = _monthly_cf.get(_m, 0) + _month_div

    if _div_data:
        _div_df = pd.DataFrame(_div_data)
        _div_df['預估年收入(元)'] = _div_df['預估年收入(元)'].apply(lambda x: f'{x:,}')
        st.dataframe(_div_df, use_container_width=True, hide_index=True)
        _total_annual = sum(d['預估年收入(元)'].replace(',', '')
                            if isinstance(d['預估年收入(元)'], str)
                            else d['預估年收入(元)']
                            for d in _div_data
                            if isinstance(d.get('預估年收入(元)'), (int, float)))
        # recalc from raw
        _total_annual_raw = sum(
            d['近1年每股配息'] * d['持有股數'] for d in _div_data)
        _yoc = _total_annual_raw / total_value * 100 if total_value > 0 else 0
        _colored_box(
            f'💰 組合預估年度現金流入：<b>{_total_annual_raw:,.0f} 元</b>'
            f'（組合殖利率 {_yoc:.2f}%）'
            + ('&nbsp; ✅ 每年現金流穩定，適合存股策略'
               if _yoc >= 3 else '&nbsp; 🟡 殖利率偏低，可考慮增加高息ETF比例'),
            'green' if _yoc >= 3 else 'yellow')
        if _yoc >= 5:
            _teacher_conclusion('郭俊宏',
                                f'組合殖利率 {_yoc:.2f}%，年現金流 {_total_annual_raw:,.0f} 元',
                                '殖利率優異，現金流充沛，以息養股目標達成',
                                '持續持有，配息再投入複利滾動')
        elif _yoc >= 3:
            _teacher_conclusion('郭俊宏',
                                f'組合殖利率 {_yoc:.2f}%，年現金流 {_total_annual_raw:,.0f} 元',
                                '殖利率合格，現金流穩定',
                                '可維持，視需要提高高息 ETF 比例')
        else:
            _teacher_conclusion('郭俊宏',
                                f'組合殖利率 {_yoc:.2f}%，年現金流 {_total_annual_raw:,.0f} 元',
                                '殖利率偏低，現金流不足以息養股',
                                '增加 00878/00713 等高息 ETF 比例')

        # 月度現金流長條圖
        import plotly.graph_objects as _go_div
        _fig_div = _go_div.Figure(_go_div.Bar(
            x=[f'{m}月' for m in range(1, 13)],
            y=[_monthly_cf[m] for m in range(1, 13)],
            marker_color='#3fb950',
            text=[f'{_monthly_cf[m]:,.0f}' if _monthly_cf[m] > 0 else ''
                  for m in range(1, 13)],
            textposition='auto',
        ))
        _fig_div.update_layout(
            title='未來12個月預估配息現金流（元，依歷史月份分配）',
            template='plotly_dark', height=260,
            paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
            margin=dict(l=0, r=0, t=32, b=0),
            yaxis_title='配息金額（元）',
        )
        st.plotly_chart(_fig_div, width='stretch')
    else:
        st.info('⏳ 配息資料無法取得（可能為非配息型ETF或yfinance資料限制）')

    # 存入 session_state
    st.session_state['etf_portfolio_data'] = {
        'rows': rows, 'war_rows': _war_rows, 'rebal_actions': rebal_actions,
        'total_value': total_value, 'regime': regime,
        'loss_pct': loss_pct,
    }

    # ── 統一投資決策分析模組（AI 首席顧問決策中心）──────────────
    render_unified_decision(gemini_fn, {
        'type': 'portfolio',
        'id':   'etf_portfolio',
        'data': {
            '組合明細': [
                {'ETF': r['ticker'],
                 '目標%': r['target_pct'],
                 '實際%': r['actual_pct'],
                 '偏離%': round(r['deviation'], 1)}
                for r in rows
            ],
            '壓力測試損失(S&P500跌20%)': f'{loss_pct:.1f}%',
            '再平衡筆數':                len(rebal_actions),
            '大盤狀態':                  regime,
        },
    })


def _render_oauth_panel(_gsp) -> bool:
    """OAuth 登入 + Sheet ID 設定面板。

    回傳 True 代表雲端儲存可用（OAuth 已登入＋有 Sheet ID，或 SA 已備齊）。
    False 代表需要先完成設定，後續 UI 應跳過。
    """
    import re as _re

    try:
        from oauth_state import (
            get_oauth_cfg, _gsa_secret, _sheet_id_secret,
        )
        from infra.oauth import build_authorize_url
    except Exception as _ie:
        st.error(f'❌ OAuth 模組載入失敗：{_ie}')
        # 降級：只看 SA
        return _gsp._sa_configured()

    # 每次呼叫動態解析（避免 module-level cache 讓 in-app wizard 套用後仍 stale）
    _oauth_cfg = get_oauth_cfg()
    _oauth_configured = _oauth_cfg is not None
    _logged_in = bool(st.session_state.get('gsheet_tokens'))

    # ── 狀態列 ──────────────────────────────────────
    if _oauth_configured:
        if _logged_in:
            _c_st1, _c_st2 = st.columns([3, 1])
            _c_st1.success('🟢 已用 Google 登入（OAuth）')
            if _c_st2.button('🚪 登出', key='etf_p_oauth_logout',
                              use_container_width=True):
                st.session_state.pop('gsheet_tokens', None)
                st.rerun()
        else:
            _login_url = build_authorize_url(
                _oauth_cfg['client_id'], _oauth_cfg['redirect_uri'])
            st.info('ℹ️ 尚未登入 Google — 點下方按鈕完成登入即可使用個人 Sheet。')
            st.link_button('🔐 用 Google 登入', _login_url,
                            use_container_width=True)
    elif _gsa_secret and _sheet_id_secret:
        st.info('ℹ️ 偵測到 Service Account 設定，走管理員部署模式（向後相容）')
    else:
        # In-app OAuth Client 設定 wizard（不必碰 secrets.toml）
        # 註：本面板已位於外層「💾 雲端儲存」expander 內，這裡不能再 st.expander（Streamlit 禁巢狀）
        st.warning('尚未設定 OAuth Client。請依下方步驟在 GCP console 建一個，'
                    '再回到這裡貼三個值即可登入。')
        st.markdown('**🧙 OAuth Client 設定引導（5 分鐘完成）**')
        st.markdown(
            """
            **一次性 GCP 設定**（之後你就只要按「🔐 用 Google 登入」即可）：

            1. **啟用 API**：[GCP Console → APIs Library](https://console.cloud.google.com/apis/library) →
               啟用 `Google Sheets API` + `Google Drive API`
            2. **OAuth consent screen**：
               [連結](https://console.cloud.google.com/apis/credentials/consent) → User Type: **External**
               → 填 App name / email → Scopes 加 `spreadsheets` + `drive.file` + `openid` + `userinfo.email`
               → Test users 加自己的 Gmail
            3. **建 OAuth Client ID**：
               [連結](https://console.cloud.google.com/apis/credentials) → Create Credentials →
               OAuth client ID → Web application
               → **Authorized redirect URIs** 必須加上**這個 app 的 URL**（含尾巴 `/`）
            4. 把下面三個值貼進來：
            """
        )
        _wz_cfg = st.session_state.get('custom_oauth_cfg', {})
        _wz_cid  = st.text_input('client_id',
            value=_wz_cfg.get('client_id', ''),
            key='wz_oauth_cid',
            placeholder='xxx.apps.googleusercontent.com')
        _wz_csec = st.text_input('client_secret',
            value=_wz_cfg.get('client_secret', ''),
            key='wz_oauth_csec', type='password')
        _wz_ru   = st.text_input('redirect_uri',
            value=_wz_cfg.get('redirect_uri', ''),
            key='wz_oauth_ru',
            placeholder='https://<your-app>.streamlit.app/')
        if st.button('💾 套用 OAuth Client 設定',
                      key='wz_oauth_apply', use_container_width=True):
            if _wz_cid and _wz_csec and _wz_ru:
                st.session_state['custom_oauth_cfg'] = {
                    'client_id':     _wz_cid.strip(),
                    'client_secret': _wz_csec.strip(),
                    'redirect_uri':  _wz_ru.strip(),
                }
                st.success('✅ 已套用，下方會出現「🔐 用 Google 登入」按鈕')
                st.rerun()
            else:
                st.error('三個欄位都要填')
        return False

    # ── OAuth 已登入：個人 Sheet ID 設定 ────────────────────────
    if _oauth_configured and _logged_in:
        _sid_cur = str(st.session_state.get('portfolio_sheet_id', '') or '').strip()
        _sid_raw = st.text_input(
            'Google Sheet ID 或完整 URL（系統會自動解析 ID）',
            value=_sid_cur, key='etf_p_sheet_id_input',
            placeholder='貼上 https://docs.google.com/spreadsheets/d/...',
        )
        _m = _re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', _sid_raw)
        _sid = _m.group(1) if _m else _sid_raw.strip()
        if _sid and _sid != _sid_cur:
            st.session_state['portfolio_sheet_id'] = _sid
            st.caption(f'✅ 已設定 Sheet ID：`{_sid}`')
        if not _sid:
            st.info('💡 還沒輸入 Sheet ID — 請在 Google Drive 建一份試算表（檔案完全空白即可），'
                    '貼上完整 URL 或 ID，本工具會自動建立 `portfolios` 分頁。')
            return False

    # 兩條路徑都通：給 caller 繼續渲染存取 UI
    if not _gsp.is_configured():
        st.warning('⚠️ 雲端儲存尚未就緒（請檢查上方設定）')
        return False

    st.markdown('---')
    return True


def _render_cloud_storage(edited_df):
    """💾 Google Sheet 雲端儲存 UI（expander 折疊）。

    Args:
        edited_df: data_editor 回傳的當下表格 DataFrame（含使用者剛編輯後的內容）

    - 未設定：顯示 OAuth 登入引導 / Sheet ID 設定
    - 已設定：提供「載入既有 / 儲存當前 / 刪除」三組操作
    """
    import gsheet_portfolio as _gsp

    with st.expander('💾 雲端儲存 (Google Sheet)', expanded=False):
        # ── OAuth 設定 / Sheet ID 設定 ──────────────────────────────
        if not _render_oauth_panel(_gsp):
            return

        # ── 載入既有組合 ──
        try:
            names = _gsp.list_portfolios()
        except Exception as e:
            st.error(f'❌ 無法連線到 Google Sheet：{e}')
            return

        _c1, _c2, _c3 = st.columns([2, 1, 1])
        if names:
            _sel = _c1.selectbox('載入既有組合', options=['—'] + names,
                                  key='etf_p_load_sel')
            if _c2.button('📂 載入', key='etf_p_load_btn',
                           use_container_width=True,
                           disabled=(_sel == '—')):
                try:
                    _loaded = _gsp.load_portfolio(_sel)
                except Exception as e:
                    st.error(f'❌ 載入失敗：{e}')
                else:
                    if not _loaded:
                        st.warning(f'⚠️ 組合「{_sel}」是空的')
                    else:
                        st.session_state['etf_p_loaded_df'] = {
                            '股票代號':     [r['ticker'] for r in _loaded],
                            '持有張數':     [r['lots'] for r in _loaded],
                            '平均買入價格': [r['avg_price'] for r in _loaded],
                        }
                        st.session_state.pop('etf_p_table', None)
                        st.session_state['etf_p_active'] = False
                        st.success(f'✅ 已載入「{_sel}」共 {len(_loaded)} 檔，請按下方「📊 計算組合」')
                        st.rerun()
            if _c3.button('🗑️ 刪除', key='etf_p_del_btn',
                           use_container_width=True,
                           disabled=(_sel == '—')):
                st.session_state['_etf_p_pending_del'] = _sel
            if st.session_state.get('_etf_p_pending_del'):
                _tgt = st.session_state['_etf_p_pending_del']
                _cc1, _cc2 = st.columns(2)
                if _cc1.button(f'⚠️ 確認刪除「{_tgt}」',
                                key='etf_p_del_confirm',
                                use_container_width=True):
                    try:
                        _n = _gsp.delete_portfolio(_tgt)
                    except Exception as e:
                        st.error(f'❌ 刪除失敗：{e}')
                    else:
                        st.session_state.pop('_etf_p_pending_del', None)
                        st.success(f'✅ 已刪除「{_tgt}」（{_n} 筆持股）')
                        st.rerun()
                if _cc2.button('取消', key='etf_p_del_cancel',
                                use_container_width=True):
                    st.session_state.pop('_etf_p_pending_del', None)
                    st.rerun()
        else:
            _c1.info('💡 雲端尚無儲存的組合，請於下方填好表格後按「💾 儲存當前」')

        st.markdown('---')

        # ── 儲存當前組合 ──
        _s1, _s2 = st.columns([3, 1])
        _name = _s1.text_input('組合名稱', value='',
                                placeholder='例如：攻擊組合 / 存股組合 / 老婆帳戶',
                                key='etf_p_save_name')
        if _s2.button('💾 儲存當前', key='etf_p_save_btn',
                       use_container_width=True,
                       disabled=(not _name.strip())):
            if edited_df is None or len(edited_df) == 0:
                st.warning('⚠️ 目前表格為空，請先填入持股')
            else:
                _rows_to_save = []
                for _r in edited_df.to_dict('records'):
                    _rows_to_save.append({
                        'ticker':    str(_r.get('股票代號') or '').strip().upper(),
                        'lots':      _r.get('持有張數'),
                        'avg_price': _r.get('平均買入價格'),
                    })
                try:
                    _n = _gsp.save_portfolio(_name, _rows_to_save)
                except Exception as e:
                    st.error(f'❌ 儲存失敗：{e}')
                else:
                    st.success(f'✅ 已儲存「{_name}」共 {_n} 檔到 Google Sheet')
