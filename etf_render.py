"""
ETF 渲染層（render layer）
從 etf_dashboard.py 抽出的 Streamlit / Plotly UI 元件：橫幅 / 走勢圖 / BIAS / 蒙地卡羅 / 類股熱力圖
依賴：etf_fetch（新聞 + 類股漲跌）；不被 fetch / calc 反向依賴。
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from etf_fetch import _fetch_news_for, _fetch_sector_returns


# ── 總經連動配置建議表 ────────────────────────────────────────
MACRO_ALLOC = {
    'bull':    {'股票型ETF': 70, '債券型ETF': 15, '貨幣/現金': 15},
    'neutral': {'股票型ETF': 50, '債券型ETF': 30, '貨幣/現金': 20},
    'bear':    {'股票型ETF': 20, '債券型ETF': 50, '貨幣/現金': 30},
}
MACRO_DESC = {
    'bull':    '🟢 多頭市場：加大股票型ETF比重，可佈局成長型/科技型ETF',
    'neutral': '🟡 中性市場：股債平衡，降低單一類型集中度',
    'bear':    '🔴 空頭市場：大幅降低股票曝險，增加投資級債券ETF + 現金',
}


def macro_allocation_banner(regime: str) -> None:
    """總經連動配置建議橫幅"""
    alloc = MACRO_ALLOC.get(regime, MACRO_ALLOC['neutral'])
    desc  = MACRO_DESC.get(regime, MACRO_DESC['neutral'])
    bg_map  = {'bull': '#0d2618', 'neutral': '#1e1a00', 'bear': '#2a0d0d'}
    brd_map = {'bull': '#2ea043',  'neutral': '#d29922',  'bear': '#f85149'}
    bg  = bg_map.get(regime, '#1a1f2e')
    brd = brd_map.get(regime, '#1f6feb')
    alloc_html = ' &nbsp;|&nbsp; '.join(
        f'<b>{k}</b>&nbsp;<span style="color:#58a6ff;">{v}%</span>'
        for k, v in alloc.items()
    )
    st.markdown(
        f'''<div style="background:{bg};border:1px solid {brd};border-radius:10px;
padding:10px 16px;margin-bottom:14px;">
<div style="font-size:12px;font-weight:700;color:#8b949e;margin-bottom:2px;">
📡 總經連動配置建議（來源：Tab① 市場評估）</div>
<div style="font-size:13px;color:#c9d1d9;">{desc}</div>
<div style="font-size:13px;margin-top:6px;">{alloc_html}</div>
</div>''', unsafe_allow_html=True)


def _colored_box(text: str, color: str = 'green') -> None:
    """統一彩色提示框"""
    cfg = {
        'green':  ('#0d2618', '#2ea043'),
        'yellow': ('#1e1a00', '#d29922'),
        'red':    ('#2a0d0d', '#f85149'),
        'blue':   ('#0a1628', '#1f6feb'),
    }
    bg, brd = cfg.get(color, cfg['blue'])
    st.markdown(
        f'<div style="background:{bg};border:1px solid {brd};border-radius:8px;'
        f'padding:10px 14px;margin:6px 0;">{text}</div>',
        unsafe_allow_html=True)


def _teacher_conclusion(teacher: str, indicator_val: str, conclusion: str,
                        action: str = '', color: str | None = None) -> None:
    """ETF dashboard 策略結論卡（teacher 字串透過 ui_widgets._to_strategy 對應到 策略1/2/3 顯示）"""
    from ui_widgets import _to_strategy as _t2s
    if color is None:
        _neg_kw = ['警戒', '危險', '賣超', '空單', '減碼', '停損', '撤離', '跌破', '過熱', '回調', '降倉', '空頭', '侵蝕', '高估']
        _pos_kw = ['強勢', '買超', '多頭', '安全', '健康', '買進', '加碼', '流入', '突破', '進攻', '上漲', '低估', '特價']
        if any(k in conclusion + action for k in _neg_kw):
            color = '#2ea043'
        elif any(k in conclusion + action for k in _pos_kw):
            color = '#da3633'
        else:
            color = '#d29922'
    _label, _icon = _t2s(teacher)
    _action_str = f'，{action}' if action else ''
    st.markdown(
        f'<div style="border-left:3px solid {color};padding:6px 10px;margin:4px 0;'
        f'background:rgba(0,0,0,0.2);border-radius:0 6px 6px 0;">'
        f'<span style="color:#ffd700;font-weight:700;font-size:12px;">{_icon} {_label}</span>'
        f'<span style="color:#8b949e;font-size:12px;">：</span>'
        f'<span style="color:#c9d1d9;font-size:12px;">{indicator_val} → </span>'
        f'<span style="color:{color};font-size:12px;font-weight:600;">{conclusion}</span>'
        f'<span style="color:#8b949e;font-size:11px;">{_action_str}</span>'
        f'</div>',
        unsafe_allow_html=True)


def _plot_etf_chart(df: pd.DataFrame, ticker: str,
                    benchmark: str, bench_df: pd.DataFrame) -> None:
    """ETF 走勢圖 + MA50/MA200 + 標準化基準（Y軸：漲幅%，以起始日為0%）"""
    fig   = go.Figure()
    close = df['Close']
    base  = float(close.iloc[0])   # 起始價，用來換算漲幅%

    def _pct(s): return ((s / base) - 1) * 100   # → 相對起始點的漲幅%

    _hover = '%{x|%Y-%m-%d}  %{y:.2f}%<extra></extra>'
    fig.add_trace(go.Scatter(x=df.index, y=_pct(close).round(2),
                              name=ticker, line=dict(color='#58a6ff', width=2),
                              hovertemplate=_hover))
    fig.add_trace(go.Scatter(x=df.index, y=_pct(close.rolling(50).mean()).round(2),
                              name='MA50', line=dict(color='#ffa657', width=1, dash='dot'),
                              hovertemplate=_hover))
    fig.add_trace(go.Scatter(x=df.index, y=_pct(close.rolling(200).mean()).round(2),
                              name='MA200', line=dict(color='#f85149', width=1, dash='dash'),
                              hovertemplate=_hover))
    if not bench_df.empty:
        _bc   = bench_df['Close'].reindex(df.index).ffill().dropna()
        _bc_b = float(_bc.iloc[0])
        _bc_pct = ((_bc / _bc_b) - 1) * 100   # 基準也從0%起算
        fig.add_trace(go.Scatter(x=_bc.index, y=_bc_pct.round(2),
                                  name=f'{benchmark}（基準）',
                                  line=dict(color='#3fb950', width=1.2, dash='dash'),
                                  hovertemplate=_hover))
    fig.update_layout(
        template='plotly_dark', height=380,
        margin=dict(l=0, r=0, t=20, b=0),
        paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
        legend=dict(orientation='h', yanchor='bottom', y=1.01),
        yaxis=dict(title='漲幅 (%)', ticksuffix='%', zeroline=True,
                   zerolinecolor='#444', zerolinewidth=1),
    )
    st.plotly_chart(fig, width='stretch')


def _plot_correlation(corr: pd.DataFrame) -> None:
    """相關係數熱力圖"""
    labels = list(corr.columns)
    z      = corr.values.tolist()
    text   = [[f'{v:.2f}' for v in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=labels, y=labels,
        text=text, texttemplate='%{text}',
        colorscale='RdBu_r', zmid=0, zmin=-1, zmax=1,
        colorbar=dict(thickness=10),
    ))
    fig.update_layout(
        template='plotly_dark', height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
    )
    st.plotly_chart(fig, width='stretch')


def _plot_holdings_overlap(mat: pd.DataFrame, title: str = '') -> None:
    """持股 Overlap 熱力圖：0-100% 單向配色（白→紅，越紅越重疊）。

    與 `_plot_correlation` 的差異：
      - 值域 0-100（非 -1 到 1）；不需 zmid
      - 單向 colorscale（紅色越深越同質），跟報酬相關矩陣視覺區分
      - NaN 灰色顯示（資料拿不到的 ETF）
    """
    labels = list(mat.columns)
    z      = mat.values.tolist()
    text   = [[(f'{v:.1f}' if pd.notna(v) else 'N/A') for v in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=labels, y=labels,
        text=text, texttemplate='%{text}',
        colorscale=[[0.0, '#0d1117'], [0.3, '#5a2a1e'],
                    [0.6, '#a73c2a'], [1.0, '#f85149']],
        zmin=0, zmax=100,
        hoverongaps=False,
        colorbar=dict(thickness=10, title=dict(text='%', font=dict(size=11))),
    ))
    fig.update_layout(
        template='plotly_dark', height=320,
        title=title if title else None,
        margin=dict(l=0, r=0, t=30 if title else 10, b=0),
        paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
    )
    st.plotly_chart(fig, width='stretch')


def _render_bias(df: pd.DataFrame, ticker: str) -> None:
    """BIAS 乖離率：(Close - MAn) / MAn × 100%，顯示 MA20/MA60/MA120"""
    if df is None or len(df) < 20:
        st.info('資料不足，無法計算 BIAS')
        return
    close = df['Close'] if 'Close' in df.columns else df['close']
    bias_rows = []
    for n, label in [(20, 'MA20'), (60, 'MA60'), (120, 'MA120')]:
        if len(close) >= n:
            ma  = float(close.rolling(n).mean().iloc[-1])
            cur = float(close.iloc[-1])
            bias = (cur - ma) / ma * 100
            if bias > 10:
                hint = '🔴 嚴重高估，注意拉回'
            elif bias > 5:
                hint = '🟡 偏高，謹慎追高'
            elif bias < -10:
                hint = '🟢 嚴重低估，逢低佈局機會'
            elif bias < -5:
                hint = '🟡 偏低，可分批承接'
            else:
                hint = '⚪ 中性偏離，正常波動'
            bias_rows.append({'均線': label, 'MA值': f'{ma:.2f}',
                               'BIAS(%)': f'{bias:+.2f}%', '訊號': hint})
    if bias_rows:
        st.dataframe(pd.DataFrame(bias_rows), use_container_width=True, hide_index=True)
        # 視覺化近60日 BIAS(MA20)
        if len(close) >= 60:
            ma20 = close.rolling(20).mean()
            b20  = (close - ma20) / ma20 * 100
            b20  = b20.dropna().tail(60)
            fig  = go.Figure(go.Bar(
                x=b20.index, y=b20.values,
                marker_color=['#f85149' if v > 0 else '#3fb950' for v in b20.values],
                name='BIAS(MA20)',
            ))
            fig.add_hline(y=10,  line_dash='dot', line_color='#f85149',
                          annotation_text='+10%')
            fig.add_hline(y=-10, line_dash='dot', line_color='#3fb950',
                          annotation_text='-10%')
            fig.update_layout(
                template='plotly_dark', height=220,
                yaxis_title='BIAS %', margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
            )
            st.plotly_chart(fig, width='stretch')


# ETF → GICS 類股對照（僅涵蓋常見 ETF，未知 ETF 歸入「其他」）
_ETF_SECTOR_MAP = {
    'XLK': '資訊科技', 'QQQ': '資訊科技', '00631L.TW': '資訊科技',
    'XLF': '金融', 'KBE': '金融',
    'XLE': '能源',
    'XLV': '醫療保健',
    'XLI': '工業',
    'XLP': '必需消費', 'XLY': '非必需消費',
    'XLU': '公用事業',
    'XLB': '原材料',
    'XLRE': '房地產', '00712.TW': '房地產',
    'XLC': '通訊服務',
    'SPY': '廣泛市場', 'IVV': '廣泛市場', 'VOO': '廣泛市場',
    '0050.TW': '廣泛市場', '00646.TW': '廣泛市場',
    'BND': '債券', 'AGG': '債券', 'TLT': '債券',
    '00678.TW': '債券', '00720B.TW': '債券',
    '00878.TW': '高股息', '00713.TW': '高股息', '0056.TW': '高股息',
    'GLD': '黃金/原物料', 'IAU': '黃金/原物料',
}


def _check_sector_exposure(rows: list, total_value: float) -> None:
    """計算各 GICS 類股曝險，標記超過 30% 的集中風險"""
    sector_vals: dict = {}
    for r in rows:
        sector = _ETF_SECTOR_MAP.get(r['ticker'], '其他')
        sector_vals[sector] = sector_vals.get(sector, 0) + r['current_value']

    sector_rows = []
    warnings = []
    for sec, val in sorted(sector_vals.items(), key=lambda x: -x[1]):
        pct = val / total_value * 100
        flag = '⚠️ 超限' if pct > 30 else '✅'
        sector_rows.append({'類股': sec, '合計現值(元)': f'{val:,.0f}',
                             '佔比': f'{pct:.1f}%', '狀態': flag})
        if pct > 30:
            warnings.append((sec, pct))

    st.dataframe(pd.DataFrame(sector_rows), use_container_width=True, hide_index=True)
    if warnings:
        for sec, pct in warnings:
            _colored_box(
                f'⚠️ <b>{sec}</b> 類股佔比 <b>{pct:.1f}%</b> 超過 30% 上限，'
                f'建議分散至其他類股或降低持倉', 'red')
    else:
        _colored_box('✅ 所有類股曝險均在 30% 以內，產業分散度良好', 'green')


def _render_monte_carlo(port_val: pd.Series, initial: float, ann_vol: float,
                        n_paths: int = 10_000, n_days: int = 252) -> None:
    """
    蒙地卡羅模擬 10,000 路徑，1 年期
    使用歷史年化波動率計算日報酬標準差，幾何布朗運動隨機遊走
    顯示 10th/50th/90th percentile 區間與最終分布直方圖
    """
    try:
        daily_ret  = port_val.pct_change().dropna()
        mu_daily   = float(daily_ret.mean())
        sig_daily  = float(daily_ret.std())
        if sig_daily == 0:
            st.info('波動率為 0，無法執行蒙地卡羅模擬')
            return

        rng      = np.random.default_rng(42)
        # shape: (n_paths, n_days)
        shocks   = rng.normal(mu_daily, sig_daily, size=(n_paths, n_days))
        paths    = np.cumprod(1 + shocks, axis=1) * float(port_val.iloc[-1])

        p10  = np.percentile(paths[:, -1], 10)
        p50  = np.percentile(paths[:, -1], 50)
        p90  = np.percentile(paths[:, -1], 90)
        prob_profit = float((paths[:, -1] > float(port_val.iloc[-1])).mean() * 100)

        ca, cb, cc, cd = st.columns(4)
        ca.metric('P10（悲觀）',  f'{(p10/float(port_val.iloc[-1])-1)*100:+.1f}%')
        cb.metric('P50（中位）',  f'{(p50/float(port_val.iloc[-1])-1)*100:+.1f}%')
        cc.metric('P90（樂觀）',  f'{(p90/float(port_val.iloc[-1])-1)*100:+.1f}%')
        cd.metric('獲利機率',     f'{prob_profit:.1f}%')

        # 繪製路徑分布（取前100條 + 百分位帶）
        days_axis = list(range(n_days))
        sample_paths = paths[:100]
        fig = go.Figure()
        for i, sp in enumerate(sample_paths):
            fig.add_trace(go.Scatter(
                x=days_axis, y=sp.tolist(),
                mode='lines',
                line=dict(color='rgba(88,166,255,0.05)', width=1),
                showlegend=False,
            ))
        for label, pct, color in [
            ('P10', 10, '#f85149'), ('P50', 50, '#e3b341'), ('P90', 90, '#3fb950'),
        ]:
            band = np.percentile(paths, pct, axis=0)
            fig.add_trace(go.Scatter(
                x=days_axis, y=band.tolist(),
                mode='lines', name=label,
                line=dict(color=color, width=2),
            ))
        fig.add_hline(y=float(port_val.iloc[-1]),
                      line_dash='dot', line_color='#ffffff',
                      annotation_text='目前淨值')
        fig.update_layout(
            template='plotly_dark', height=320,
            xaxis_title='交易日', yaxis_title='資產價值（元）',
            margin=dict(l=0, r=0, t=20, b=0),
            paper_bgcolor='#0d1117', plot_bgcolor='#0d1117',
            legend=dict(orientation='h', yanchor='bottom', y=1.01),
        )
        st.plotly_chart(fig, width='stretch')
        st.caption(f'模擬條件：{n_paths:,} 路徑，日均報酬 μ={mu_daily*100:.4f}%，σ={sig_daily*100:.3f}%（基於歷史資料）⚠️ 僅供參考')
    except Exception as e:
        st.warning(f'蒙地卡羅模擬失敗：{e}')


def _etf_ai_backtest(gemini_fn, cagr, sharpe, mdd, vol, weights, regime):
    with st.expander('🤖 AI 回測評斷（展開）', expanded=False):
        w_txt  = ' | '.join(f'{t}: {w*100:.0f}%' for t, w in weights.items())
        if st.button('🤖 生成回測AI評斷', key='etf_ai_bt_btn'):
            # 為回測組合中每檔 ETF 抓取新聞（最多各 2 則）
            _bt_news_lines = []
            for _tk in list(weights.keys())[:4]:
                _nn = _fetch_news_for(_tk, _tk, 2)
                if _nn and _nn != '（暫無相關新聞）':
                    _bt_news_lines.append(f'[{_tk}]\n{_nn}')
            _bt_news_str = '\n'.join(_bt_news_lines) if _bt_news_lines else '（暫無相關新聞）'
            prompt = (
                f"你是回測績效分析師，依據以下數字給出精準評斷，不超過300字，嚴禁捏造：\n"
                f"組合：{w_txt}\n"
                f"CAGR：{cagr:.2f}%\n"
                f"夏普值：{sharpe:.2f}\n"
                f"最大回撤：{mdd:.1f}%\n"
                f"年化波動率：{vol:.2f}%\n"
                f"當前市場狀態：{regime}\n\n"
                f"【近期各ETF相關新聞】\n{_bt_news_str}\n\n"
                f"輸出：\n"
                f"1.【績效評級】優秀/良好/普通/劣（請說明標準）\n"
                f"2.【風險評估】MDD和波動率是否在可接受範圍\n"
                f"3.【改善建議】基於春哥/郭俊宏/孫慶龍觀點，如何優化配置\n"
                f"4.【前瞻建議】在{regime}環境下，此組合的下一步行動\n"
                f"⚠️ 僅供學術研究，非投資建議"
            )
            with st.spinner('AI 分析中...'):
                result = gemini_fn(prompt, max_tokens=900)
            if result and not result.startswith('⚠️'):
                st.session_state['etf_ai_bt_result'] = result
                st.rerun()
            else:
                st.session_state['etf_ai_bt_result'] = None
                st.warning(result or 'AI 回傳為空')
        _bt_saved = st.session_state.get('etf_ai_bt_result')
        if _bt_saved:
            st.markdown(_bt_saved)
            if st.button('🔄 清除', key='etf_ai_bt_clear'):
                st.session_state.pop('etf_ai_bt_result', None)
                st.rerun()


# ── 美股 11 大 GICS 類股 ETF ─────────────────────────────────
_US_SECTORS = {
    'XLK':  {'name': '科技',        'sub': ['AAPL','MSFT','NVDA','AVGO','AMD']},
    'XLF':  {'name': '金融',        'sub': ['JPM','BAC','WFC','GS','MS']},
    'XLE':  {'name': '能源',        'sub': ['XOM','CVX','COP','SLB','MPC']},
    'XLV':  {'name': '醫療',        'sub': ['LLY','UNH','JNJ','ABBV','MRK']},
    'XLI':  {'name': '工業',        'sub': ['GE','CAT','HON','UPS','BA']},
    'XLP':  {'name': '必需消費',    'sub': ['PG','KO','PEP','COST','WMT']},
    'XLU':  {'name': '公用事業',    'sub': ['NEE','SO','DUK','AEP','D']},
    'XLB':  {'name': '原物料',      'sub': ['LIN','APD','ECL','NEM','FCX']},
    'XLRE': {'name': '房地產',      'sub': ['PLD','AMT','EQIX','CCI','SPG']},
    'XLY':  {'name': '非必需消費',  'sub': ['AMZN','TSLA','HD','MCD','NKE']},
    'XLC':  {'name': '通訊服務',    'sub': ['META','GOOGL','NFLX','DIS','T']},
}

# ── 台股類股代表 ETF/指數成分 ────────────────────────────────
_TW_SECTORS = {
    '2330.TW': {'name': '半導體',    'sub': ['2303.TW','2308.TW','2454.TW','3711.TW','2379.TW']},
    '2317.TW': {'name': '電子製造',  'sub': ['2354.TW','2356.TW','3008.TW','2382.TW','3034.TW']},
    '2412.TW': {'name': '電信',      'sub': ['3045.TW','4904.TW','2409.TW']},
    '2882.TW': {'name': '金融',      'sub': ['2881.TW','2883.TW','2884.TW','2886.TW','2891.TW']},
    '1301.TW': {'name': '塑化',      'sub': ['1303.TW','1326.TW','1402.TW']},
    '2002.TW': {'name': '鋼鐵',      'sub': ['2006.TW','2007.TW','2010.TW']},
    '1216.TW': {'name': '食品',      'sub': ['1201.TW','1210.TW','1225.TW']},
    '2603.TW': {'name': '航運',      'sub': ['2609.TW','2615.TW','2617.TW']},
    '9910.TW': {'name': '觀光',      'sub': ['2706.TW','2707.TW','2727.TW']},
    '3008.TW': {'name': '光電',      'sub': ['2409.TW','3481.TW','2475.TW']},
}

_PERIOD_MAP = {'1日': '5d', '5日': '1mo', '1月': '3mo', '3月': '6mo'}


def _build_treemap_data(sectors: dict, returns: dict, market: str) -> go.Figure:
    """建立 Plotly Treemap 熱力圖"""
    ids, labels, parents, values, texts, colors = [], [], [], [], [], []

    # root
    ids.append(market)
    labels.append(market)
    parents.append('')
    values.append(0)
    texts.append('')
    colors.append(0)

    for ticker, meta in sectors.items():
        sec_ret = returns.get(ticker)
        sec_label = f"{meta['name']}<br>{sec_ret:+.1f}%" if sec_ret is not None else meta['name']
        ids.append(ticker)
        labels.append(sec_label)
        parents.append(market)
        values.append(max(abs(sec_ret) if sec_ret is not None else 1, 0.5))
        texts.append(ticker)
        colors.append(sec_ret if sec_ret is not None else 0)

        # sub-items
        for sub in meta.get('sub', []):
            sub_ret = returns.get(sub)
            sub_label = f"{sub.replace('.TW','')}<br>{sub_ret:+.1f}%" if sub_ret is not None else sub
            ids.append(f'{ticker}/{sub}')
            labels.append(sub_label)
            parents.append(ticker)
            values.append(max(abs(sub_ret) if sub_ret is not None else 0.5, 0.3))
            texts.append(sub)
            colors.append(sub_ret if sub_ret is not None else 0)

    # 顏色：最大值對稱
    max_abs = max(abs(c) for c in colors if c != 0) or 5
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents,
        values=values, text=texts,
        textinfo='label',
        marker=dict(
            colors=colors,
            colorscale=[[0, '#0f5132'], [0.35, '#1a6e36'], [0.5, '#1e2530'],
                        [0.65, '#c0392b'], [1, '#7b1212']],  # 台灣慣例：漲=紅 跌=綠
            cmid=0, cmin=-max_abs, cmax=max_abs,
            colorbar=dict(title='漲跌%', thickness=12),
            line=dict(width=1, color='#0d1117'),
        ),
        hovertemplate='<b>%{text}</b><br>漲跌：%{marker.color:+.2f}%<extra></extra>',
    ))
    fig.update_layout(
        template='plotly_dark',
        height=600,
        margin=dict(l=0, r=0, t=30, b=0),
        paper_bgcolor='#0d1117',
    )
    return fig


def render_sector_heatmap():
    st.markdown('### 🗺️ 產業熱力圖')
    st.caption('即時抓取各類股漲跌幅，紅=漲 / 綠=跌（台灣慣例）。點選區塊可展開子類股。')

    col_m, col_p, col_r = st.columns([2, 2, 1])
    market = col_m.selectbox('市場', ['🇺🇸 美股（GICS 11大類）', '🇹🇼 台股（主要類股）'],
                              key='heatmap_market')
    period_label = col_p.selectbox('計算區間', list(_PERIOD_MAP.keys()),
                                    index=0, key='heatmap_period')
    col_r.markdown('<br>', unsafe_allow_html=True)
    refresh = col_r.button('🔄 刷新', key='heatmap_refresh', use_container_width=True)

    is_us = '美股' in market
    sectors = _US_SECTORS if is_us else _TW_SECTORS
    period  = _PERIOD_MAP[period_label]

    # 收集所有需抓取的 ticker（類股代表 + 子成分）
    all_tickers = list(sectors.keys())
    for meta in sectors.values():
        all_tickers.extend(meta.get('sub', []))
    all_tickers = tuple(set(all_tickers))

    if refresh:
        _fetch_sector_returns.clear()

    with st.spinner(f'抓取 {len(all_tickers)} 個標的資料（{period_label}）...'):
        returns = _fetch_sector_returns(all_tickers, period)

    if not returns:
        st.error('❌ 無法取得任何類股資料，請確認網路連線')
        return

    # ── Treemap 主圖 ──────────────────────────────────────────
    market_label = '美股 GICS' if is_us else '台股類股'
    fig = _build_treemap_data(sectors, returns, market_label)
    st.plotly_chart(fig, width='stretch')

    # ── 數值排行表（補充用）──────────────────────────────────
    st.markdown(f'#### 📊 {market_label} 類股漲跌排行（{period_label}）')
    rank_rows = []
    for ticker, meta in sectors.items():
        ret = returns.get(ticker)
        rank_rows.append({
            '類股': meta['name'],
            '代號': ticker,
            f'{period_label}漲跌%': ret if ret is not None else 'N/A',
            '方向': ('📈 上漲' if ret and ret > 0 else ('📉 下跌' if ret and ret < 0 else '➡️ 持平')),
        })
    rank_rows.sort(key=lambda x: x[f'{period_label}漲跌%']
                   if isinstance(x[f'{period_label}漲跌%'], float) else 0, reverse=True)
    rank_df = pd.DataFrame(rank_rows)
    st.dataframe(rank_df, use_container_width=True, hide_index=True)

    # 覆蓋率說明
    fetched = sum(1 for t in sectors if returns.get(t) is not None)
    total_s = len(sectors)
    if fetched < total_s:
        _colored_box(
            f'⚠️ 僅取得 {fetched}/{total_s} 個類股資料，部分可能因 yfinance 限速或市場休市而缺失',
            'yellow')
    else:
        _colored_box(f'✅ 全部 {total_s} 個類股資料取得完整', 'green')
