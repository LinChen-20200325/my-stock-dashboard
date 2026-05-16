"""TAB 教學：策略邏輯說明書（靜態 Markdown）— 從 app.py 抽出（PR P2-B Phase 5-A）

依賴極簡：僅 streamlit；內部所需 data_registry / shared.macro_card / pandas
皆在函式內 late import，避免循環 import 與啟動成本。

呼叫端
======
- app.py: `with tab_edu: render_tab_edu()`
"""
from __future__ import annotations

import streamlit as st


def render_tab_edu():
    st.markdown('## 📚 台股 AI 戰情室 — 策略邏輯說明書')
    st.caption('整理自各大師公開課程，僅供學術研究。投資涉及風險，本系統不構成買賣建議，盈虧自負。')

    # ── 📖 指標解讀手冊（從 data_registry 自動生成）──────────────
    # v17: 新增「即時數值 + 24M 趨勢圖」chip + sparkline，使用 shared/macro_card 共用模組
    with st.expander('📖 指標解讀手冊 — 數字 + 趨勢 + 完整教學', expanded=True):
        try:
            from data_registry import (
                get_categories, get_by_category, get_edu, get_edu_count,
                render_edu_card_html,
            )
            from shared.macro_card import calc_z_score, make_sparkline
            import pandas as _pd_edu

            # ─── identifier → (current_value, pd.Series|None, t_warn, t_crit, high_is_bad) ───
            def _get_indicator_data(identifier: str):
                """從 session_state 取出指標的即時值 + 24M series + 警戒/危險閾值。

                覆蓋範圍：
                  ✓ 有 series：^VIX / ^TNX / ^SOX / DX-Y.NYB（cl_data.intl 有 90D OHLC）
                  ✓ 僅單值：CPILFESL / NAPM / VALEXPTWM052N / NDC_signal /
                            ms1.json / MI_MARGN（macro_info / m1b_m2_info）
                  ✗ 無資料：BWIBBU_d / BFI82U（結構複雜，待後續 PR）
                """
                _macro = st.session_state.get('macro_info') or {}
                _cl    = st.session_state.get('cl_data') or {}
                _intl  = _cl.get('intl') or {}
                _m1b   = st.session_state.get('m1b_m2_info') or {}
                _bias  = st.session_state.get('bias_info') or {}

                # ─ 國際金融（有完整 OHLC DataFrame）─
                _intl_map = {
                    '^TNX':      ('10Y公債殖利率', 4,    5,   True),
                    '^SOX':      ('費城半導體 SOX', None, None, False),
                    'DX-Y.NYB':  ('美元指數 DXY',   105,  110, True),
                }
                if identifier in _intl_map:
                    _name, _tw, _tc, _hib = _intl_map[identifier]
                    _df = _intl.get(_name)
                    if _df is not None and not _df.empty:
                        _ccol = 'Close' if 'Close' in _df.columns else (
                            'close' if 'close' in _df.columns else None)
                        if _ccol:
                            _s = _df[_ccol].dropna()
                            if len(_s) >= 2:
                                return float(_s.iloc[-1]), _s, _tw, _tc, _hib
                    return None, None, _tw, _tc, _hib

                # ─ ^VIX：macro_info.vix 已有 60 天 series ─
                if identifier == '^VIX':
                    _v = _macro.get('vix') or {}
                    if _v.get('values') and _v.get('dates'):
                        try:
                            _s = _pd_edu.Series(_v['values'],
                                                index=_pd_edu.to_datetime(_v['dates']))
                            return _v.get('current'), _s, 22, 30, True
                        except Exception:
                            pass
                    return _v.get('current'), None, 22, 30, True

                # ─ 單值類（無 series，但顯示當前值 + 閾值線）─
                _single = {
                    'CPILFESL':       ((_macro.get('us_core_cpi') or {}).get('yoy'),         2.5,  4,    True),
                    'NAPM':           ((_macro.get('ism_pmi')     or {}).get('value') or
                                       (_macro.get('ism_pmi')     or {}).get('current'),     50,   45,   False),
                    'VALEXPTWM052N':  ((_macro.get('tw_export')   or {}).get('yoy'),         0,    -5,   False),
                    'NDC_signal':     ((_macro.get('ndc_signal')  or {}).get('score') or
                                       (_macro.get('ndc_signal')  or {}).get('value'),       32,   22,   None),
                    'ms1.json':       ((_m1b.get('m1b_yoy')      or 0) -
                                       (_m1b.get('m2_yoy')        or 0)
                                       if (_m1b.get('m1b_yoy') is not None
                                           and _m1b.get('m2_yoy') is not None)
                                       else None,                                            0,    -2,   False),
                }
                if identifier in _single:
                    _v, _tw, _tc, _hib = _single[identifier]
                    return _v, None, _tw, _tc, _hib

                # ─ 其他（暫無資料，後續 PR 處理）─
                return None, None, None, None, None

            _edu_total = get_edu_count()
            st.markdown(
                f"""
**新人最大的痛點**：指標一堆，但每個是什麼？要怎麼看？要搭配什麼一起看？
本手冊把每個核心指標拆解成 **6 個問題** + **24 個月趨勢圖**：

| 問題 | 內容 |
|------|------|
| 💡 **是什麼** | 用一句白話解釋這個指標在量什麼 |
| 📐 **怎麼判讀** | 數字到了哪個門檻代表什麼訊號 |
| 🔗 **搭配看什麼** | 不能只看單一指標，要對照哪些指標 |
| 📊 **歷史錨點** | 歷史上的關鍵數字（讓你有比例尺） |
| ⬆️ **上游因** | 誰會影響這指標（找根源） |
| ⬇️ **下游果** | 這指標會影響誰（找連動效應） |
| 📈 **即時值 + 24M 趨勢** | 當前值 + Z-Score + 趨勢圖（含警戒/危險閾值線） |

📌 目前已撰寫 **{_edu_total} 個** 核心指標教學卡（持續擴充中）。
未列出的指標請見「🔎 資料診斷」Tab → 各類別展開查看完整資料目錄。
""")
            st.markdown('---')
            for _cat in get_categories():
                _entries_in_cat = get_by_category(_cat)
                _edu_pairs = [(e, get_edu(e.get('identifier'))) for e in _entries_in_cat]
                _edu_pairs = [(e, ed) for e, ed in _edu_pairs if ed is not None]
                if not _edu_pairs:
                    continue
                st.markdown(f'### {_cat}')
                for _e, _edu in _edu_pairs:
                    _id = _e.get('identifier', '')
                    _val, _series, _tw, _tc, _hib = _get_indicator_data(_id)
                    # ─ 即時值 + Z-Score chip ─
                    _z = (calc_z_score(_series, _val)
                          if _series is not None and len(_series) >= 10 else None)
                    if _val is not None or _series is not None:
                        _val_str = (f"{_val:.2f}" if isinstance(_val, (int, float))
                                    else "—")
                        _z_str   = f"  Z={_z:+.2f}" if _z is not None else ""
                        _z_color = ("#f44336" if _z is not None and abs(_z) >= 2 and
                                    ((_hib and _z > 0) or (_hib is False and _z < 0))
                                    else ("#00c853" if _z is not None and abs(_z) >= 2
                                          else ("#ff9800" if _z is not None and abs(_z) >= 1.5
                                                else "#79c0ff")))
                        st.markdown(
                            f"<div style='display:flex;gap:14px;align-items:baseline;"
                            f"margin:14px 0 0;padding:8px 14px;background:#161b22;"
                            f"border:1px solid #30363d;border-radius:8px 8px 0 0;"
                            f"border-bottom:none'>"
                            f"<span style='color:#8b949e;font-size:11px;font-weight:600;"
                            f"letter-spacing:1px'>📈 即時值與趨勢</span>"
                            f"<span style='color:#e6edf3;font-size:18px;font-weight:700'>"
                            f"{_val_str}</span>"
                            f"<span style='color:{_z_color};font-size:12px'>{_z_str}</span>"
                            f"</div>",
                            unsafe_allow_html=True)
                        # ─ Sparkline（有 series 才畫）─
                        if _series is not None and len(_series) >= 2:
                            _fig = make_sparkline(
                                _series,
                                threshold_warn=_tw, threshold_crit=_tc,
                                high_is_bad=(_hib if _hib is not None else True),
                                lookback=60, height=70,
                            )
                            if _fig is not None:
                                st.plotly_chart(
                                    _fig, use_container_width=True,
                                    config={'displayModeBar': False},
                                    key=f'spark_{_id}_{_cat}')
                        else:
                            st.caption("⚠️ 此指標目前僅有單一最新值，趨勢圖待後續 PR 補齊（需擴充 macro fetcher）")
                    # ─ 既有 EDU HTML 卡（白話/判讀/搭配/上下游/歷史）─
                    st.markdown(render_edu_card_html(_e, _edu),
                                unsafe_allow_html=True)
        except ImportError as _ie:
            st.error(f'❌ 無法載入 data_registry：{_ie}')

    # ── 孫慶龍 ───────────────────────────────────────────────────
    with st.expander('📊 策略1（估值 / 存股）— 財報領先指標與盈餘成長選股', expanded=True):
        st.markdown("""
### 核心邏輯：在「業績加速成長」前提早佈局

本策略強調，股價長期反映的是企業「未來盈餘的折現值」。
市場往往落後財報數字，懂得讀「領先財報」的人就能在機構法人之前看見機會。

---

#### 🔑 財報領先指標一：合約負債（Contract Liabilities）

> **白話定義**：客戶已付錢但公司尚未交貨 → 代表「口袋裡的訂單」

| 門檻 | 訊號 | 意義 |
|------|------|------|
| 合約負債 **> 股本 50%** | 🟢 龍多信號 | 訂單爆滿，未來 1–2 季業績有保證 |
| 合約負債 **> 股本 100%** | 🔥 超強信號 | 產能供不應求，定價權在手 |
| 合約負債持續季增 | 🔼 加分項 | 訂單持續進來，成長趨勢確認 |

**篩選口訣**：合約負債高 → 代表「客戶先給錢」，這樣的公司最不怕景氣波動。

---

#### 🔑 財報領先指標二：資本支出（CapEx）

> **白話定義**：公司在大買機器、蓋廠房 → 代表對未來「投票」

| 門檻 | 訊號 | 意義 |
|------|------|------|
| 資本支出 **> 股本 80%** | 🟢 擴張信號 | 大膽押注未來需求，對訂單有把握才會花這麼多 |
| 資本支出連續 2 季增加 | 🔼 加分項 | 不是一次性，是持續擴產 |

---

#### 🔑 盈餘成長率：EPS 加速是關鍵

- **近 4 季 EPS 年增率加速**（從 +5% → +10% → +20%）= 最強選股信號
- 毛利率 ≥ 30% 且維持 or 提升 → 高護城河企業
- 營業利益率提升 → 靠本業賺錢，非業外收益

#### ✅ 龍多股完整篩選框架

```
合約負債 > 股本 50%  ✓
資本支出 > 股本 80%  ✓
近 4 季 EPS 加速成長  ✓
月營收 YoY 加速 (3個月均線上彎)  ✓
→ 龍多股確認，大型法人機構尚未追入前的黃金買點
```
""")

    # ── 蔡森 ─────────────────────────────────────────────────────
    with st.expander('📐 策略3（技術 / 動能）— 型態學：破底翻 × 頭肩底 × 頸線突破', expanded=True):
        st.markdown(r"""
### 核心邏輯：用「型態」讀懂主力換手完畢的訊號

本策略認為，K線型態是「資金博弈的足跡」。主力洗盤完畢後，往往留下可辨識的底部型態。

---

#### 🔑 型態一：破底翻（Fake Breakdown Reversal）

> 股價跌破前低 → 但**隔日收回**前低之上 → 散戶停損被洗出後主力拉抬

| 步驟 | 判斷標準 |
|------|---------|
| ① 量縮跌破前低 | 成交量明顯萎縮（代表散戶恐慌賣壓，非主力出貨） |
| ② 當日或隔日大量紅K | 量比 ≥ 1.5，收盤站回前低之上 |
| ③ 連續 2 根紅K確認 | 第 2 根紅 K 收盤突破近期高點 → 破底翻確認 |

**停損設定**：破底翻 K 棒低點即為硬停損，跌破即出場。

---

#### 🔑 型態二：頭肩底（Inverse Head & Shoulders）

```
         左肩          右肩
          /\            /\
         /  \    頭    /  \
        /    \  /  \  /    \
───────/──────\/────\/──────────  ← 頸線（Neckline）
                底部（最低點）
```

| 要素 | 判斷標準 |
|------|---------|
| 左肩 | 下跌後反彈，成交量萎縮 |
| 頭部 | 跌破左肩低點，量更小（洗盤） |
| 右肩 | 反彈至接近左肩高點，**量比頭部大** |
| 突破頸線 | 收盤站上頸線 + 成交量爆增 ≥ 均量 1.5 倍 → 買點 |

---

#### 🔑 操作細節：頸線突破買點

1. **等收盤確認**：不追日內突破，等收盤穩站頸線之上
2. **回測不破**：突破後如回測頸線不跌破 → 加碼機會
3. **目標價**：頸線 + 頭部到頸線距離（等幅量測）
4. **停損**：跌破右肩低點即出場
""")

    # ── 春哥 ─────────────────────────────────────────────────────
    with st.expander('🌀 策略3（技術 / 動能）— VCP 波幅收縮與爆量突破', expanded=True):
        st.markdown(r"""
### 核心邏輯：波幅每次比上次小 → 籌碼鎖定完成 → 等爆量突破

VCP（Volatility Contraction Pattern）找的是「橫盤整理中能量不斷蓄積」的股票，
波幅每次比前次更小，量能不斷萎縮，直到爆量突破才確認方向。

---

#### 🔑 VCP 四大關鍵條件

| 條件 | 標準 | 說明 |
|------|------|------|
| ① **多次波幅收縮** | ≥ 3 次 | 每次高低振幅比前次縮小 ≥ 1/3 |
| ② **成交量持續萎縮** | 量比 < 0.8 | 籌碼鎖定，浮額洗盡 |
| ③ **不跌破關鍵均線** | 站上 MA20 | 型態不能在均線下方整理 |
| ④ **突破需有爆量** | 量比 ≥ 2.0 | 收盤突破近期整理高點 + 巨量 = 有效突破 |

---

#### 🔑 VCP 示意圖

```
價格
│    /\        /\      /\
│   /  \      /  \    /  \  ← 波幅一次比一次小
│  /    \    /    \  /    \___________  突破!▲▲▲ (爆量)
│ /      \  /      \/
│/        \/
└─────────────────────────────── 時間
        收縮①  收縮②  收縮③   Pivot Point(突破點)
```

---

#### 🔑 進出場規則

| 動作 | 標準 |
|------|------|
| **進場** | 突破 Pivot Point（整理高點）+ 當日收盤接近最高（收盤在當日高點 95% 以上） |
| **加碼** | 突破後回測 Pivot 不破，再加 0.5 倍部位 |
| **停損** | 跌破進場 K 棒低點（通常約 7–8% 以內） |
| **停利** | 距停損 3 倍獲利（盈虧比 ≥ 3:1）先設目標；強勢股跟蹤 MA10 |

> **策略3 心法**：「量縮到極點就是爆發前夕。等的不是上漲，等的是籌碼。」
""")

    # ── 宏爺 ─────────────────────────────────────────────────────
    with st.expander('💰 宏爺 — 資金動能 M1B-M2 × 均線多頭家數 × 外資期貨防守', expanded=True):
        st.markdown("""
### 核心邏輯：用「總體資金」判斷大盤體質，而非個股

宏爺認為，股票市場是資金推動的遊戲。M1B-M2 利差是最領先的資金指標，
比任何技術指標都早 6–9 個月看到轉折。

---

#### 🔑 指標一：M1B – M2 利差（資金寬鬆度）

> **白話**：M1B 是活錢（活存），M2 是定存 + 活存。
> 活錢比例上升 → 錢從定存搬出來 → 準備進股市

| 利差 | 訊號 | 建議倉位 |
|------|------|---------|
| M1B YoY **> M2 YoY** 且擴大 | 🟢 資金寬鬆，多頭啟動 | **持股 70–100%** |
| M1B YoY **= M2 YoY**（利差收斂） | 🟡 轉折警戒，注意方向 | **持股 50%** |
| M1B YoY **< M2 YoY**（利差翻負） | 🔴 資金緊縮，熊市風險 | **持股 0–30%** |

---

#### 🔑 指標二：均線多頭排列家數

> **白話**：台股 1800 支股票中，有幾支站在 240 日均線（年線）之上？

| 家數比例 | 市場意義 |
|---------|---------|
| ≥ **60%** 站上年線 | 🟢 多頭格局強健，可積極持股 |
| **40–60%** 站上年線 | 🟡 多空拉鋸，選股不選市 |
| ≤ **40%** 站上年線 | 🔴 熊市格局，嚴控倉位 |

搭配「大盤 vs 個股」強弱：
- 指數創高但多頭家數不創高 → 警訊（領頭羊撐盤，底層崩潰）
- 多頭家數先反彈 → 領先大盤底部的信號

---

#### 🔑 指標三：外資期貨空單防守線

| 外資期貨淨部位 | 訊號 | 操作建議 |
|--------------|------|---------|
| 淨**多單** > 0 且擴大 | 🟢 外資看多台股 | 可積極作多 |
| 淨多單縮減中 | 🟡 外資降低多頭暴露 | 適度降低倉位 |
| 淨**空單** > 0 | 🔴 外資對沖台股風險 | 大盤需謹慎 |
| 淨空單急速擴大 | 🚨 系統性風險信號 | 立即減碼至 30% 以下 |

---

#### ✅ 宏爺完整多空判斷矩陣

| M1B-M2 | 多頭家數 | 外資期貨 | 建議倉位 |
|--------|---------|---------|---------|
| ✅ 寬鬆 | ✅ ≥60% | ✅ 多單 | **滿倉 80–100%** |
| ✅ 寬鬆 | ✅ ≥60% | ❌ 空單 | **七成 70%** |
| ✅ 寬鬆 | ❌ <40% | 任何 | **五成 50%，選股不選市** |
| ❌ 緊縮 | 任何 | 任何 | **防守 0–30%，保留現金** |

> **宏爺口訣**：「M1B-M2 翻正是起跑槍，年線家數過半是加速器，外資空單是急剎車。」

---

#### 📌 股匯四象限快查表（連動操作）

| 象限 | 台股 | 台幣 | 外資行為 | 持股建議 |
|------|------|------|---------|---------|
| 🟢 股匯雙漲 | ↑ | 升值 | 匯入真實資金 | **80–100%** |
| ⚠️ 股漲匯貶 | ↑ | 貶值 | 疑似拉高出貨 | **50%，不追高** |
| 🔴 股匯雙殺 | ↓ | 貶值 | 大舉提款撤出 | **0–30%，嚴格防守** |
| 🟡 股跌匯升 | ↓ | 升值 | 資金停泊台灣 | **50–70%，找錯殺股** |
""")

    st.markdown("""---
<div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;
padding:10px 14px;font-size:11px;color:#8b949e;margin-top:8px;text-align:center;">
⚠️ 本教學整理自各大師公開課程內容，僅供學術研究與教育用途。<br>
投資涉及風險，任何操作均應自行判斷，盈虧自負。本系統非投資顧問，不構成買賣建議。
</div>""", unsafe_allow_html=True)
