# 介面與規約 (Interface SPEC)

> 集中記錄 **跨模組對外可見** 的命名、對應表、語意契約。修改本檔代表 UI / API 行為改動，需同步 STATE / ARCHITECTURE。

---

## §1 老師 → 策略 對應表（UI 顯示用）

> 來源：`ui_widgets._STRATEGY_MAP` + `_to_strategy(teacher)`。所有 `teacher_box` / `teacher_conclusion` / `etf_dashboard._teacher_conclusion` 內部自動套用，呼叫端**保留原老師字串**（變數 / 函數參數 / log / AI prompt 內部不動）。

| 策略 | 方法論 | 涵蓋老師 | 預設 icon |
|------|--------|---------|-----------|
| 策略 1 | 估值 / 存股 | 孫慶龍、郭俊宏 | 💡 / 💰 |
| 策略 2 | 財報體檢 | MJ、林明樟（MJ 林明樟） | 🏥 |
| 策略 3 | 技術 / 動能 | 蔡森、春哥（Mark Minervini）、弘爺、宏爺、妮可、朱家泓 | 📐 / 🌱 / 🎯 / 📈 / 📊 |

**未列表的老師字串** → `('策略', '👤')` fallback。

**範圍邊界**：
- ✅ **改**：`st.markdown` / `st.expander` / `st.caption` / `help=` 等 UI 顯示字串
- ❌ **不改**：Python 變數名、dict key、函式簽名、函式 docstring、檔案 docstring、AI prompt 內部結構、log 訊息

---

## §2 ETF 私募/特殊判別啟發式

> 來源：`etf_tab_single._likely_private`，輸出至 `session_state['etf_single_data']['_likely_private']`。

```python
_likely_private = (
    (not _is_overseas)        # 台股 4-6 碼代號（如 0050.TW / 00878.TW）
    and (not aum)              # yfinance .info[totalAssets] 也抓不到
    and (not expense)          # SITCA + MoneyDJ + yfinance 3 源皆空
    and (_nav_value is None)   # FinMind + goodinfo + TWSE + MoneyDJ + yfinance 5 源皆空
)
```

**health_inspector 行為**：
| 條件 | AUM | 費用率 | NAV |
|------|-----|--------|------|
| 海外 ETF（`_is_overseas`） | 不動 | `na` + 海外訊息 | `na` + 海外訊息 |
| 私募 ETF（`_likely_private`） | `na` + 私募訊息 | `na` + 私募訊息 | `na` + 私募訊息 |
| 一般 | 缺漏 → 紅 | 缺漏 → 紅 + 3源錯誤訊息 | 缺漏 → 紅 + 5源錯誤訊息 |

訊息字串：「私募/特殊 ETF — AUM、費用率、NAV 主流資料源皆未揭露」

---

## §3 批次分析個股 K 線 — 三態語意

> 來源：`tab_stock_grp._fetch_single_t3` 回傳 dict。

| 情境 | dict 內容 | 是否快取 4hr | UI 表現 |
|------|----------|----------|---------|
| 成功 | `{'sid','df','name','avg_div','cl','cx'}` | ✅ 快取 | 🟢 正常 |
| 空 K 線（雙源皆空） | + `'error': _err4 or '無 K 線資料...'` | ❌ 跳過快取 | 🔴 + 顯示原因 |
| Exception | `{'sid','error': str(_e4)}` | ❌ | 🔴 + 顯示原因 |
| Future timeout | `{'sid','error':'timeout'}` | ❌ | 🔴 + 顯示原因 |

下游 `health_inspector.py:853` 透過 `_fetch_err` 將 `error` 字串綁定到診斷列 `error_msg=`，不再「🔴 未取得」空白標。

---

## §4 TW PMI 8 段備援源 — 失敗追蹤格式

> 來源：`macro_core.fetch_tw_pmi`。失敗時回 `{'_err_pmi': str, 'value': None}`，`_err_pmi` 為各源失敗原因以 ` | ` 串接。

| 階段 | 來源 | 失敗 token 範例 |
|------|------|-----------------|
| 0 | data.gov.tw dataset/6100 | `dgtw./rest/dataset/6100:無回應` / `dgtw.xxx:HTTP503` |
| 0b | 國發會 NDC 景氣指標 | `NDC.a/indicator/PMI:無回應` / `NDC.xxx:HTTP404` |
| 1 | MacroMicro chart 22 / 16 | `MacroMicro.charts/22/taiwan-pmi:無回應` |
| 2 | CIER cid=21 / 首頁 | `CIER.ews/list?cid=21:無回應` |
| 3 | StockFeel 搜尋頁 | `StockFeel:無回應` |
| 4 | 鉅亨網 API | `Cnyes:無回應` |
| 5 | FinMind TaiwanEconomicIndicator | `FinMind:無 token` / `FinMind:JSONDecodeError` |
| 6 | CIER cid=8（PMI 專欄） | `CIER-cid8.news/list?cid=8:無回應` |
| 7 | MoneyDJ 知識庫搜尋 | `MoneyDJ:無回應` |

**設計原則**：每段失敗都必須寫入 `errs`，避免使用者只看到部分失敗訊息誤判系統。

---

## §5 文件治理連動

任何 §1–§4 規約變更必須同步：
- `STATE.md` — 加入 commit / PR 行
- `ARCHITECTURE.md` — 對應模組章節
- `SPEC.md`（本檔） — 直接更新對應表 / 啟發式

CLAUDE.md v2.0 §4：「請直接 merge PR + 存檔(STATE.md) 與也同步 ARCHITECTURE.md、SPEC.md」
