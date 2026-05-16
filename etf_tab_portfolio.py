"""ETF 組合配置 TAB — 從 etf_dashboard.py 抽出（PR P2-B Phase 6-B）

依賴策略
========
- Top-level: streamlit
- 函式內 late import 14 個依賴：
  * stdlib: numpy, pandas
  * 外部: unified_decision.render_unified_decision
  * etf_dashboard.py 內部 helper (10):
    _check_sector_exposure / _colored_box / _compute_etf_warroom_row
    / _etf_ai_portfolio / _plot_correlation / _teacher_conclusion
    / fetch_etf_dividends / fetch_etf_info / fetch_etf_price
    / macro_allocation_banner

呼叫端
======
- app.py 經 etf_dashboard re-export 取用
"""
from __future__ import annotations

import streamlit as st


def render_etf_portfolio(gemini_fn=None):
    # ─ Late imports（避免循環 import）─
    import numpy as np
    import pandas as pd
    from unified_decision import render_unified_decision
    from etf_dashboard import (
        _check_sector_exposure, _colored_box, _compute_etf_warroom_row,
        _etf_ai_portfolio, _plot_correlation, _teacher_conclusion,
        fetch_etf_dividends, fetch_etf_info, fetch_etf_price,
        macro_allocation_banner,
    )

    mkt_info = st.session_state.get('mkt_info', {})
    regime   = mkt_info.get('regime', 'neutral')
    macro_allocation_banner(regime)

    st.markdown('#### 📋 輸入持股組合（格式：代號,股數,均價[,希望比例%][,類型]）')
    st.caption('💡 第 4 欄「希望比例%」省略 → 以實際現值權重為目標；第 5 欄「核心/衛星」省略 → 依代號自動分類。'
               '系統會自動以即時收盤價算現值、資本利得與已領配息。')
    default_input = ("0050.TW,1000,135.50,40,核心\n"
                     "00713.TW,500,82.30,30,核心\n"
                     "BND,200,72.50,20,核心\n"
                     "00878.TW,2000,20.10,10,核心")
    raw       = st.text_area('組合輸入', value=default_input, height=130,
                              key='etf_p_input', label_visibility='collapsed')
    tolerance = st.slider('再平衡容忍偏離度（%）', 1, 15, 5, key='etf_p_tol')

    if st.button('📊 計算組合', key='etf_p_btn', use_container_width=True):
        st.session_state['etf_p_active'] = True

    if not st.session_state.get('etf_p_active'):
        st.info('💡 填入持股後點擊「計算組合」')
        return

    # MK 框架 #9：核心 / 衛星預設分類（高股息大型 / 全市場 / 債券 → 核心；其他 → 衛星）
    _CORE_TICKERS = {'0050','0051','0056','006208','00713','00878','00919','00929',
                     '00940','00946','00713B','00679B','00937B','BND','AGG','VTI',
                     'VOO','SPY','VT','SCHD','VEA','VWO','VNQ'}
    def _auto_role(tk: str) -> str:
        code = tk.replace('.TWO', '').replace('.TW', '').upper()
        return '核心' if code in _CORE_TICKERS else '衛星'

    # ── 解析輸入：代號,股數,均價[,希望比例%][,類型] ───────────
    rows = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 3:
            st.warning(f'⚠️ 欄位不足（至少需 代號,股數,均價）：{line}')
            continue
        try:
            _tk        = parts[0].upper()
            _shares    = float(parts[1])
            _avg_price = float(parts[2])
            # 第 4 欄：希望比例% 或 類型；第 5 欄：類型
            _target_pct = None
            _role = None
            for _p in parts[3:5]:
                if not _p:
                    continue
                if _p in ('核心', '衛星'):
                    _role = _p
                else:
                    try:
                        _target_pct = float(_p)
                    except ValueError:
                        pass
            if _role is None:
                _role = _auto_role(_tk)
            rows.append({
                'ticker':     _tk,
                'shares':     _shares,
                'avg_price':  _avg_price,
                'cost':       _shares * _avg_price,
                'target_pct': _target_pct,   # 可能 None，下面 fallback
                'role':       _role,
            })
        except ValueError:
            st.warning(f'⚠️ 無法解析（股數/均價需為數字）：{line}')
    if not rows:
        st.error('❌ 請輸入有效的持股資料')
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

    # 沒給 target_pct 的列 → 用實際現值權重補；給了的 → 校驗加總
    _filled_target_sum = sum(r['target_pct'] for r in rows if r['target_pct'] is not None)
    _missing_target = [r for r in rows if r['target_pct'] is None]
    if _missing_target and _filled_target_sum < 100:
        _remain = 100 - _filled_target_sum
        _per    = _remain / len(_missing_target) if _missing_target else 0
        for r in _missing_target:
            r['target_pct'] = round(_per, 2)
    elif _missing_target:
        # 全靠實際權重做目標
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
        '股數':       f'{int(r["shares"]):,}',
        '均價':       f'{r["avg_price"]:.2f}',
        '現價':       f'{r["current_price"]:.2f}' if r['current_price'] > 0 else '-',
        '成本(元)':   f'{r["cost"]:,.0f}',
        '現值(元)':   f'{r["current_value"]:,.0f}',
        '資本利得':   f'{"+" if r["capital_gain"]>=0 else ""}{r["capital_gain"]:,.0f}',
        '利得%':      f'{"+" if r["capital_gain_pct"]>=0 else ""}{r["capital_gain_pct"]:.2f}%',
        '已領配息':   f'+{r["dividend_received"]:,.0f}' if r['dividend_received'] > 0 else '-',
        '希望比例%':  f'{r["target_pct"]:.1f}',
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
        'rows': rows, 'rebal_actions': rebal_actions,
        'total_value': total_value, 'regime': regime,
        'loss_pct': loss_pct,
    }

    if gemini_fn:
        _etf_ai_portfolio(gemini_fn, rows, rebal_actions, regime, loss_pct)

    # ── 統一投資決策分析模組 ──────────────────────────────────
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
