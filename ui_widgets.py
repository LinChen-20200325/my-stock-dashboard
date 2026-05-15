"""UI 元件純函式（HTML 字串生成器） — 從 app.py 抽出（PR P2-B Phase 2）

零 Streamlit / 零 session state 依賴，只回傳 HTML 字串給呼叫端做
`st.markdown(..., unsafe_allow_html=True)` 渲染。

收錄函式
========
- explain_box(term, simple_explain, detail='')        — 術語說明框
- traffic_light(value, good_cond, bad_cond, ...)      — 紅綠燈指示器
- beginner_kpi(title, value, plain_meaning, ...)      — 初學者版 KPI 卡
- show_term_help(term)                                — 顯示術語對照表內容
- kpi(title, value, sub='', color, border)            — 一般 KPI 卡
- teacher_box(icon, teacher, logic)                   — 老師建議框（舊版）
- teacher_conclusion(teacher, indicator_val, ...)     — 老師結論（自動配色）
- signal_box(label, color, desc='')                   — 訊號方塊

常數
====
- TERM_EXPLAIN: dict — 13 個常見術語的白話對照表
"""
from __future__ import annotations


# 術語白話對照表
TERM_EXPLAIN = {
    'RSI':      ('強弱指數', '衡量股票最近漲跌的「溫度」。<70正常，>70過熱，<30過冷。'),
    'KD':       ('買賣時機指標', 'K線和D線的交叉代表買賣時機。K>D往上穿越=可能要漲了。'),
    'ADL':      ('漲跌家數累積線', '今天台股漲的股票多還是跌的多。越多股票一起漲=市場越健康。'),
    'VCP':      ('波動收縮形態', '股價震盪越來越小，像彈弓拉緊。突破時可能大漲。'),
    'IBS':      ('K棒位置指標', '今天收盤在今天高低價的哪個位置。越靠近低點=隔天可能反彈。'),
    'M1B-M2':   ('資金流向指標', '活錢(M1B)比定存(M2)跑得快=錢往股市跑=行情要來了。'),
    '旌旗指數':  ('全市場健康度', '台股1800支股票，現在有幾%的股票站在均線之上。>60%=健康。'),
    '騰落指標':  ('市場廣度', '今天漲的股票-跌的股票。正數且持續往上=真正的多頭。'),
    '乖離率':    ('偏離正常值多少', '股價離平均成本線差多少%。>20%=可能過熱了，<-20%=可能太便宜。'),
    '多頭排列':  ('均線向上排列', '短期均線>中期>長期均線，代表趨勢向上，可以操作多方。'),
    '布林通道':  ('價格正常範圍', '統計出來的「正常價格範圍」。突破上軌=強勢但可能過熱。'),
    '量比':      ('成交量比較', '今天的成交量是過去20天平均的幾倍。>2=放量異常，要注意。'),
    'PCR':      ('多空情緒比', '選擇權市場的多空比例。>1偏多，<1偏空。'),
}


def explain_box(term, simple_explain, detail=''):
    """顯示一個術語說明框"""
    return (
        f'<div style="background:#161b22;border-left:3px solid #58a6ff;'
        f'padding:8px 12px;margin:4px 0;border-radius:0 6px 6px 0;">'
        f'<span style="font-size:12px;font-weight:700;color:#58a6ff;">{term}</span>'
        f'<span style="font-size:12px;color:#c9d1d9;"> = {simple_explain}</span>'
        + (f'<br><span style="font-size:11px;color:#8b949e;">{detail}</span>' if detail else '') +
        '</div>'
    )


def traffic_light(value, good_cond, bad_cond, good_label, bad_label, neutral_label='⚪ 觀察'):
    """紅綠燈指示器"""
    if good_cond:
        color, label = '#3fb950', f'🟢 {good_label}'
    elif bad_cond:
        color, label = '#f85149', f'🔴 {bad_label}'
    else:
        color, label = '#d29922', neutral_label
    return color, label


def beginner_kpi(title, value, plain_meaning, color='#e6edf3', tip=''):
    """初學者版 KPI 卡（有說明文字）"""
    return (
        f'<div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;'
        f'padding:12px;text-align:center;">'
        f'<div style="font-size:10px;color:#484f58;margin-bottom:2px;">{title}</div>'
        f'<div style="font-size:22px;font-weight:900;color:{color};">{value}</div>'
        f'<div style="font-size:11px;color:#8b949e;margin-top:3px;">{plain_meaning}</div>'
        + (f'<div style="font-size:10px;color:#484f58;margin-top:2px;">💡 {tip}</div>' if tip else '') +
        '</div>'
    )


def show_term_help(term):
    """顯示術語說明 - 在任何 section 都可呼叫"""
    if term not in TERM_EXPLAIN:
        return ''
    name, desc = TERM_EXPLAIN[term]
    return explain_box(f'❓ {term}（{name}）', desc)


def kpi(title, value, sub='', color='#e6edf3', border='#21262d'):
    return (f'<div style="background:#161b22;border:1px solid {border};border-radius:8px;'
            f'padding:12px 14px;text-align:center;">'
            f'<div style="font-size:10px;color:#484f58;margin-bottom:3px;">{title}</div>'
            f'<div style="font-size:20px;font-weight:900;color:{color};">{value}</div>'
            f'<div style="font-size:10px;color:#8b949e;margin-top:3px;">{sub}</div></div>')


def teacher_box(icon, teacher, logic):
    # 保留向下相容，但建議用 teacher_conclusion()
    return (f'<div class="teacher-card">'
            f'<span style="font-size:12px;color:#ffd700;font-weight:700;">{icon} {teacher}</span>'
            f'<div style="font-size:12px;color:#8b949e;margin-top:4px;line-height:1.6;">{logic}</div>'
            f'</div>')


def teacher_conclusion(teacher, indicator_val, conclusion, action='', color=None):
    """
    統一老師結論格式：
    老師：指標數值 → 結論，行動建議

    teacher:       老師名稱（宏爺 / 孫慶龍 / 弘爺 / 朱家泓 / 妮可）
    indicator_val: 指標與數值（如 '費半 7837(+0.5%)'）
    conclusion:    目前結論（如 '半導體強勢'）
    action:        建議行動（如 '台股多方加分'）
    color:         顏色（自動依結論判斷，或手動指定 green/red/yellow）
    """
    # 自動判斷顏色
    if color is None:
        # 台股慣例: 正/漲/多=紅, 負/跌/空=綠, 中性=黃, 預設=藍
        _neg_kw = ['警戒', '危險', '賣超', '空單', '減碼', '停損', '撤離', '跌破', '過熱', '回調', '降倉', '空頭']
        _pos_kw = ['強勢', '買超', '多頭', '安全', '健康', '買進', '加碼', '流入', '突破', '進攻', '上漲']
        if any(k in conclusion+action for k in _neg_kw):
            color = '#2ea043'   # 跌=綠
        elif any(k in conclusion+action for k in _pos_kw):
            color = '#da3633'   # 漲=紅
        else:
            color = '#d29922'
    _icon = {'宏爺': '🎯', '孫慶龍': '💡', '弘爺': '🎯', '朱家泓': '📊',
             '妮可': '📈', '春哥': '🌱', '蔡森': '📐'}.get(teacher, '👤')
    _action_str = f'，{action}' if action else ''
    return (
        f'<div style="border-left:3px solid {color};padding:6px 10px;margin:4px 0;'
        f'background:rgba(0,0,0,0.2);border-radius:0 6px 6px 0;">'
        f'<span style="color:#ffd700;font-weight:700;font-size:12px;">{_icon} {teacher}</span>'
        f'<span style="color:#8b949e;font-size:12px;">：</span>'
        f'<span style="color:#c9d1d9;font-size:12px;">{indicator_val} → </span>'
        f'<span style="color:{color};font-size:12px;font-weight:600;">{conclusion}</span>'
        f'<span style="color:#8b949e;font-size:11px;">{_action_str}</span>'
        f'</div>'
    )


def signal_box(label, color, desc=''):
    colors = {'green': ('#0d2818', '#3fb950'), 'red': ('#2a0d0d', '#f85149'),
              'yellow': ('#2a1f00', '#d29922'), 'blue': ('#0d1b2a', '#58a6ff')}
    bg, tc = colors.get(color, ('#161b22', '#8b949e'))
    return (f'<div style="background:{bg};border:1px solid {tc};border-radius:8px;'
            f'padding:10px 14px;margin:4px 0;">'
            f'<b style="color:{tc};">{label}</b>'
            f'<span style="color:#8b949e;font-size:12px;margin-left:8px;">{desc}</span></div>')
