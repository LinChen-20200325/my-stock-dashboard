# 台股 AI 戰情室 — 技術規格書

> **版本**：v7.1　|　**最後更新**：2026-05-15　|　**狀態**：完成 ✅
>
> 本文件為系統架構師視角的唯讀規格書，不含任何實作程式碼。

---

## 目錄

1. [目錄結構](#1-目錄結構)
2. [分層架構](#2-分層架構)
3. [資料流向](#3-資料流向)
4. [核心函式 IO 定義](#4-核心函式-io-定義)

---

## 1. 目錄結構

### 1.1 專案根目錄

```
my-stock-dashboard/
│
├── 🔵 應用層 (Application)
│   └── app.py
│
├── 🟢 資料層 (Data Layer)
│   ├── data_loader.py
│   ├── daily_checklist.py
│   └── leading_indicators.py
│
├── 🟡 評分層 (Scoring Layer)
│   ├── scoring_engine.py
│   ├── v4_strategy_engine.py
│   └── v5_modules.py
│
├── 🟠 策略層 (Strategy Layer)
│   ├── market_strategy.py
│   ├── risk_control.py
│   └── backtest_engine.py
│
├── 🟣 視覺化層 (Visualization Layer)
│   ├── chart_plotter.py
│   └── etf_dashboard.py
│
├── 🔴 AI 層 (AI Layer)
│   ├── ai_engine.py
│   └── unified_decision.py
│
├── ⚙️ 基礎設施 (Infrastructure)
│   ├── config.py
│   ├── stock_names.py
│   └── financial_debug_helper.py
│
└── 📁 支援檔案 (Support Files)
    ├── .streamlit/config.toml
    ├── requirements.txt
    ├── pytest.ini
    ├── STATE.md
    └── CLAUDE.md
```

### 1.2 各檔案職責說明

#### 應用層

| 檔案 | 行數 | 職責 |
|------|-----:|------|
| `app.py` | ~7,300 | Streamlit 主程式；協調所有模組、渲染 10 個分析 Section 與 6 個主頁籤；管理 session_state 生命週期 |

#### 資料層

| 檔案 | 行數 | 職責 |
|------|-----:|------|
| `data_loader.py` | ~1,435 | 從 TWSE T86/TPEx、FinMind API 抓取個股 OHLCV 與三大法人進出明細；含 process-level cache 與備援邏輯 |
| `daily_checklist.py` | ~1,300 | 每日市場總覽資料抓取（三大法人、融資餘額、ADL、yfinance 國際指數）；同時提供 `section_header`、`kpi` 等共用 UI 元件；含 `_pkl_get/put/clear_all` 快取基礎設施 |
| `leading_indicators.py` | ~1,173 | 抓取 TAIFEX 期貨/選擇權/PCR、FinMind 未平倉量、TWSE 成交量、組建先行指標 DataFrame |

#### 評分層

| 檔案 | 行數 | 職責 |
|------|-----:|------|
| `scoring_engine.py` | ~1,201 | 多因子健康評分（趨勢 25% + 動能 20% + 籌碼 20% + 量價 15% + 風險 10% + 基本面 10%）；VCP/ATR/Bollinger 訊號偵測 |
| `v4_strategy_engine.py` | ~371 | v4 相對籌碼計算（外資/投信佔流通股比）與總體否決訊號（VIX + 外資期貨 → 紅黃綠燈限倉） |
| `v5_modules.py` | ~443 | v5 進階模組：基本面領先指標、RS 相對強度 Z-Score、估值區間（P/E + P/B）、Bollinger 突破、股息殖利率情境 |

#### 策略層

| 檔案 | 行數 | 職責 |
|------|-----:|------|
| `market_strategy.py` | ~213 | 市場多空判斷（5 分制評分 → bull / neutral / caution / bear）與對應建議持股比例 |
| `risk_control.py` | ~221 | 固定停損 (-8%)、追蹤停利 (-7%)、ATR 動態停損、投資組合層級風控（最大回撤 / 現金下限） |
| `backtest_engine.py` | ~264 | MA 交叉與 MA+RSI 策略回測；Walk-Forward Test（3 年訓練 / 12 個月測試滾動窗口）|

#### 視覺化層

| 檔案 | 行數 | 職責 |
|------|-----:|------|
| `chart_plotter.py` | ~574 | Plotly 5 子圖（K 線 + 成交量 + 外資 + 投信 + 自營/融資）、月營收趨勢圖、季度財務圖 |
| `etf_dashboard.py` | 49 | Phase 7C 後：純 re-export shim；維持 6 個下游 importer 既有 `from etf_dashboard import ...` 不變 |
| `etf_fetch.py` | 572 | Phase 7C 新增 — 純 I/O 層：價格 / 配息 / 基本資訊 / 費用率 (SITCA/MoneyDJ) / NAV 5 源備援 / 類股漲跌 / 新聞 |
| `etf_calc.py` | 465 | Phase 7C 新增 — 純計算層：殖利率 / 總報酬 / 折溢價 G1-G3 守門員 / 風險指標 (TE/MDD/CAGR/Sharpe) / 同儕排名 / 戰情室列 |
| `etf_render.py` | 505 | Phase 7C 新增 — Streamlit UI 層：MACRO 配置橫幅 / 走勢圖 / BIAS / 蒙地卡羅 / 類股熱力圖 |

#### AI 層

| 檔案 | 行數 | 職責 |
|------|-----:|------|
| `ai_engine.py` | ~734 | Gemini 2.5-Flash 個股趨勢分析、新聞摘要（Google Search Grounding）、每日市場摘要、先行指標解讀 |
| `unified_decision.py` | ~231 | 統一投資決策模組；自動路由 stock / ETF / portfolio 三套 Prompt；輸出結構化 JSON → 3-Card UI |

#### 基礎設施

| 檔案 | 行數 | 職責 |
|------|-----:|------|
| `config.py` | ~83 | 全域常數：均線週期、因子權重表、停損參數、回測手續費、市場曝險比例等 |
| `stock_names.py` | ~174 | 台股代號 ↔ 中文名稱靜態映射表 |
| `financial_debug_helper.py` | ~504 | FinMind 財務欄位別名對應、資料有效性驗證、財務科目分類邏輯 |

### 1.3 支援檔案說明

| 檔案 | 用途 |
|------|------|
| `.streamlit/config.toml` | 暗色主題（base `#0e1117`）、主色 `#1f6feb`、關閉遙測與 CORS |
| `requirements.txt` | 17 個生產依賴（streamlit / pandas / plotly / yfinance / FinMind / google-generativeai 等） |
| `pytest.ini` | 測試探索路徑 `tests/test_*.py`、pythonpath 設定 |
| `STATE.md` | 專案戰情室；版本號、異動紀錄、已知限制（由 CLAUDE.md 規範必讀） |
| `CLAUDE.md` | Claude Code 開發協議 v2.0；規範探索→計劃→執行三步法、防幻覺機制、Anti-Loop 上限 |

### 1.4 程式碼規模概覽

| 分類 | 檔案數 | 總行數 |
|------|-------:|-------:|
| 應用層 | 1 | ~9,082 |
| 資料層 | 4 | ~4,920 |
| 評分層 | 3 | ~2,015 |
| 策略層 | 3 | ~698 |
| 視覺化層 | 2 | ~2,837 |
| AI 層 | 2 | ~965 |
| 基礎設施 | 4 | ~806 |
| **合計** | **19** | **~21,323** |

> 資料層新增 `data_config.py`（快取 TTL + 來源優先順序）；基礎設施新增 `data_config.py`。`daily_checklist.py` 因 v4.1/v4.5 重構，從 733 行增至 1,465 行。

---

## 2. 分層架構

### 2.1 整體架構圖

```
╔══════════════════════════════════════════════════════════════════════╗
║                    台股 AI 戰情室 v4.0 Pro                            ║
║              Streamlit Cloud  ·  Python 3.14  ·  GitHub              ║
╚══════════════════════════════════════════════════════════════════════╝
                              │
                    ┌─────────▼─────────┐
                    │   app.py (L0)      │  ← 唯一入口；協調所有層
                    │   Streamlit 主程式  │    session_state 管理
                    └─────┬──────┬──────┘
          ┌───────────────┘      └───────────────┐
          ▼                                       ▼
┌─────────────────┐                   ┌─────────────────────┐
│  L5 · AI 層     │                   │  L4 · 視覺化層       │
│  ai_engine.py   │                   │  chart_plotter.py    │
│  unified_       │                   │  etf_dashboard.py    │
│  decision.py    │                   │  daily_checklist.py  │
│  ↕ Gemini API   │                   │  (UI 元件)           │
└────────┬────────┘                   └──────────┬──────────┘
         │                                        │
         └──────────────┬─────────────────────────┘
                        ▼
          ┌─────────────────────────┐
          │  L3 · 策略層             │
          │  market_strategy.py     │  ← 多空判斷 / 倉位比例
          │  risk_control.py        │  ← 停損 / 追蹤停利
          │  backtest_engine.py     │  ← 策略回測 / WFT
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  L2 · 評分層             │
          │  scoring_engine.py      │  ← 多因子評分 (0-100)
          │  v4_strategy_engine.py  │  ← 相對籌碼 / 總體否決
          │  v5_modules.py          │  ← RS 強度 / 估值區間
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  L1 · 資料層             │
          │  data_loader.py         │  ← 個股 OHLCV + 法人
          │  daily_checklist.py     │  ← 大盤 / 外資 / ADL
          │  leading_indicators.py  │  ← 期貨 / PCR / 先行
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  L0 · 基礎設施           │
          │  config.py              │  ← 全域常數
          │  stock_names.py         │  ← 代號映射
          │  financial_debug_       │
          │  helper.py              │  ← 欄位別名
          └─────────────────────────┘

外部服務（唯讀，不屬於任何層）：
  TWSE / TPEx API  ·  TAIFEX POST  ·  FinMind API
  yfinance (Yahoo)  ·  Gemini 2.5-Flash API  ·  dbnomics
```

---

### 2.2 各層職責與設計原則

#### L0 — 基礎設施層（Infrastructure）

| 模組 | 類型 | 設計原則 |
|------|------|---------|
| `config.py` | 純常數（無邏輯） | 所有閾值集中在此，其他層只讀不寫 |
| `stock_names.py` | 靜態映射表 | 不依賴任何外部 API；冷資料 |
| `financial_debug_helper.py` | 工具函式 | 欄位別名標準化，隔離 API 格式變動 |

**設計原則**：零外部依賴；任何層可自由引用；變更只影響此層。

---

#### L1 — 資料層（Data Layer）

| 模組 | 主要外部源 | 快取策略 |
|------|-----------|---------|
| `data_loader.py` | TWSE T86、TPEx、FinMind | `@st.cache_data(ttl=3600)` + process-level dict |
| `daily_checklist.py` | TWSE BFI82U、yfinance、FinMind ADL | `@st.cache_data(ttl=1800)` |
| `leading_indicators.py` | TAIFEX POST、FinMind 未平倉、TWSE 成交量 | `@st.cache_data(ttl=3600)` |

**設計原則**：
- 每個函式只抓一種資料源（單一職責）
- 所有 HTTP 呼叫有 retry + fallback（TWSE IP 封鎖 → FinMind 備援）
- 回傳純 `pd.DataFrame` 或 `dict`，不含任何 UI 邏輯

---

#### L2 — 評分層（Scoring Layer）

| 模組 | 輸入來源 | 輸出格式 |
|------|---------|---------|
| `scoring_engine.py` | L1 DataFrame | `dict`（各因子分數 + 總分 + 訊號） |
| `v4_strategy_engine.py` | L1 DataFrame + L3 市場狀態 | `dict`（相對籌碼比 + 限倉燈號） |
| `v5_modules.py` | L1 DataFrame + 財務數據 | `dict`（RS Z-Score / 估值標籤 / 突破訊號） |

**設計原則**：
- 純函式（Pure Functions）—— 相同輸入永遠相同輸出
- 不呼叫任何 API；不依賴 `st.session_state`
- 評分結果以 0–100 正規化，便於跨模組比較

**因子權重表（依市場狀態動態切換）**：

```
              趨勢    動能    籌碼    量價    風險    基本面
bull（多頭）  30%     25%     20%     15%      5%      5%
neutral（中性）25%    20%     20%     15%     10%     10%
bear（空頭）  15%     10%     15%     15%     25%     20%
```

---

#### L3 — 策略層（Strategy Layer）

| 模組 | 核心判斷邏輯 | 輸出給 |
|------|------------|--------|
| `market_strategy.py` | 5 分制評分 → regime（bull/neutral/caution/bear） | L4 UI、L5 AI、`session_state` |
| `risk_control.py` | 固定停損 / 追蹤停利 / ATR 動態停損 / 最大回撤 | L4 UI |
| `backtest_engine.py` | MA 交叉 / MA+RSI 策略 + Walk-Forward Test | L4 視覺化 |

**設計原則**：
- 策略邏輯與 UI 完全分離
- `market_strategy.regime` 的結果寫入 `session_state['mkt_info']`，供全站各 Tab 共用
- `risk_control.RiskController` 為有狀態類別，封裝單一交易週期的風控計算

---

#### L4 — 視覺化層（Visualization Layer）

| 模組 | 渲染目標 | 依賴層 |
|------|---------|--------|
| `chart_plotter.py` | 個股 K 線 5 子圖、月營收、季度財務 | L1、L2 |
| `etf_dashboard.py` | ETF 四子頁 Public API shim（Phase 7C 後 49 行 re-export）；實際邏輯下沉至 `etf_fetch` (L1) / `etf_calc` (L2) / `etf_render` (L4) | L1、L2、L3、L5 |
| `daily_checklist.py` (UI 部分) | 共用 UI 元件（`section_header`、`kpi`、`sparkline`） | L1 |

**設計原則**：
- 所有 `render_*` 函式接受純資料 dict，不自行抓取資料
- Plotly 圖表以 `st.plotly_chart` 渲染，支援互動縮放
- `st.session_state` gate pattern：大按鈕（開始診斷/計算組合）觸發後持久化狀態，避免 AI 按鈕 rerun 時閘門失效
- **瀑布流動線（Waterfall UI）**：採「結論先行，數據在後」渲染順序
  1. 第一層（頂部）：AI 三卡決策 + 市場號誌燈
  2. 第二層（中段）：多因子評分雷達圖
  3. 第三層（底部）：K 線技術圖表與原始數據
- **禁止 `st.expander` 隱藏核心結論**：停損點位、體制燈號、評分結果全展開顯示，確保決策透明度
- **延遲執行（Lazy Execution）**：ETF 蒙地卡羅模擬（10,000 路徑）與策略回測需點擊獨立按鈕觸發，嚴禁在頁面載入或切換 Tab 時自動執行

---

#### L5 — AI 層（AI Layer）

| 模組 | 呼叫方式 | Prompt 架構 |
|------|---------|------------|
| `ai_engine.py` | 直接呼叫 Gemini REST API | 個股分析 / 新聞摘要 / 每日摘要（各自獨立 Prompt） |
| `unified_decision.py` | 透過 `gemini_fn` 回呼（Callback） | `_BASE_RULES` + 型別路由（stock/etf/portfolio） → JSON 輸出 |

**設計原則（L5 嚴格邊界）**：
- AI 層**只讀傳入的靜態 data dict**——不依賴任何評分或策略計算，不自行呼叫 TWSE / FinMind / yfinance 等外部 API
- **禁止 Google Search Grounding**：Gemini Prompt 不得包含 `"tools": [{"google_search": {}}]` 或任何連網查詢指令（已於 `ai_engine.py` 移除）
- 單向資料流：L1 資料層 → 清洗為靜態 dict → 傳給 L5 純文字推理
- Gemini 回傳強制為 JSON 格式，`re.search` 提取後 `json.loads` 解析
- 結果以 `session_state[_sess_key]` 持久化，跨 rerun 不消失（Gate Pattern 防止重複觸發 LLM）
- **AI 串流輸出（Streaming）**：個股 AI 首席顧問報告使用 `st.write_stream()` + 打字機 generator，消除介面等待焦慮
- Fallback 模型順序：`gemini-2.5-flash-preview` → `gemini-2.0-flash-exp` → `gemini-1.5-flash-latest`

---

### 2.3 跨層依賴矩陣

```
           L0   L1   L2   L3   L4   L5
L0 基礎     ─    ✗    ✗    ✗    ✗    ✗
L1 資料     ✓    ─    ✗    ✗    ✗    ✗
L2 評分     ✓    ✓    ─    ✗    ✗    ✗
L3 策略     ✓    ✓    ✓    ─    ✗    ✗
L4 視覺     ✓    ✓    ✓    ✓    ─    ✗
L5 AI       ✓    ✗    ✗    ✗    ✗    ─
app.py      ✓    ✓    ✓    ✓    ✓    ✓

✓ = 可引用上層  ✗ = 禁止反向依賴（無循環）
```

> **關鍵約束**：資料永遠向上流（L1 → L2 → L3）；AI 層（L5）直接由 app.py 驅動，繞過評分與策略層，避免增加 LLM 呼叫延遲。

---

### 2.4 環境變數與 Secrets

| 變數名 | 作用範圍 | 用途 |
|--------|---------|------|
| `GEMINI_API_KEY` | L5（ai_engine、unified_decision） | Gemini 2.5-Flash API 金鑰 |
| `FINMIND_TOKEN` | L1（data_loader、leading_indicators） | FinMind 免費帳號（每小時 600 次） |
| `PROXY_URL` | L0（proxy_helper） | NAS Squid Proxy 上游 URL |
| `FRED_API_KEY` | L1（macro_core） | FRED 經濟資料 API 金鑰 |
| `[gcp_service_account]` | 雲端儲存（gsheet_portfolio）| **SA 模式**：管理員部署用 Service Account JSON（向後相容） |
| `portfolio_sheet_id` | 雲端儲存（gsheet_portfolio）| **SA 模式**：Google Sheet ID（OAuth 模式下由使用者 in-app 輸入，存 `session_state`） |
| `[google_oauth]` | 雲端儲存（oauth_state）| **OAuth 模式**（推薦）：`client_id` / `client_secret` / `redirect_uri`；亦可由使用者透過 in-app wizard 寫入 `session_state['custom_oauth_cfg']` |

前 4 項儲存於 Streamlit Secrets（`st.secrets`），部署時不進版控。OAuth 雙模式契約見 SPEC.md §8。

---

## 3. 資料流向

### 3.1 全域 Session State 架構

`st.session_state` 是全站各 Tab 的共用記憶體，所有資料載入後寫入此處，避免重複抓取。

```
                       st.session_state（全站共用）
  ┌────────────────────────────────────────────────────────────┐
  │  mkt_info          市場多空評分 dict（regime / score / signals）│
  │  jingqi_info       旌旗均值（有幾% 股票站在均線上）            │
  │  cl_data           每日總覽資料（inst / margin / adl / tw / intl）│
  │  cl_ts             上次更新時間戳（判斷快取是否新鮮）           │
  │  li_latest         先行指標 DataFrame（期貨/PCR/韭菜指數）      │
  │  m1b_m2_info       M1B-M2 Gap + 趨勢方向                      │
  │  bias_info         年線乖離率 BIAS240                          │
  │  defense_mode      bool（全站 AI 衛星訊號是否鎖定）             │
  │  warroom_summary   戰情總結 dict（供 Section 10 AI 總結使用）    │
  │  total_capital_twd 使用者設定的總資金（NT$）                    │
  │  satellite_used    衛星資金已使用量                             │
  └────────────────────────────────────────────────────────────┘
```

---

### 3.2 流程一：個股分析

**觸發**：使用者在「🔬 台股」Tab 輸入股票代號並點擊查詢。

```
使用者輸入
  股票代號 (sid)
  分析週期 (days)
       │
       ▼
┌──────────────────────────────────┐
│  L1 · data_loader                │
│  StockDataLoader.fetch()         │
│  ├─ yfinance：OHLCV 日K線        │
│  ├─ TWSE T86 / TPEx：三大法人     │
│  └─ FinMind：法人備援             │
│                                  │
│  輸出：df_price (DataFrame)       │
│        df_inst  (DataFrame)       │
└──────────┬───────────────────────┘
           │
    ┌──────▼──────┐    ┌──────────────────────────────────────┐
    │ L2·scoring  │    │  L2 · v4_strategy_engine              │
    │  engine     │    │  V4StrategyEngine(df, df_macro, shares)│
    │             │    │  ├─ check_macro_veto()                 │
    │ calc_*()    │    │  │   VIX + 外資期貨 → 紅黃綠燈限倉      │
    │ 趨勢/動能/   │    │  └─ calc_relative_chips()             │
    │ 籌碼/量價/   │    │      外資佔流通股比 / 投信佔流通股比     │
    │ 風險/基本面  │    └──────────────────────────────────────┘
    │             │
    │  輸出：      │    ┌──────────────────────────────────────┐
    │  score dict │    │  L2 · v5_modules                      │
    │  (0~100)    │    │  ├─ calc_relative_strength()  RS Z-Score│
    └──────┬──────┘    │  ├─ calc_valuation_zone()    估值區間   │
           │           │  └─ detect_bollinger_breakout() 突破訊號 │
           │           └──────────────────────────────────────┘
           │                        │
           └────────────┬───────────┘
                        ▼
          ┌─────────────────────────┐
          │  L3 · market_strategy   │
          │  market_regime()        │
          │                         │
          │  輸入：指數/均線/外資/廣度│
          │  輸出：regime dict       │
          │   ├─ regime: bull/neutral│
          │   │          caution/bear│
          │   ├─ score: 0~5         │
          │   └─ exposure_pct       │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  L4 · chart_plotter     │
          │  plot_combined_chart()  │
          │  ├─ K 線 + 均線         │
          │  ├─ 成交量              │
          │  ├─ 外資/投信/自營子圖   │
          │  └─ 融資餘額            │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  L5 · ai_engine         │
          │  analyze_stock_trend()  │
          │  fetch_news_summary()   │
          │                         │
          │  + unified_decision     │
          │  render_unified_        │
          │  decision()             │
          │  → 3-Card JSON UI       │
          │  (①技術②進場③停損④風控) │
          └─────────────────────────┘

最終輸出：個股分析頁（K線圖 + 評分雷達 + AI 決策三卡）
```

**關鍵資料轉換節點**：

| 節點 | 輸入型別 | 輸出型別 | 備註 |
|------|---------|---------|------|
| `StockDataLoader.fetch()` | `str`（代號）, `int`（天數） | `DataFrame` | yfinance + TWSE/FinMind 合併 |
| `score_single_stock()` | `DataFrame`, 法人資料 | `dict`（各因子分數） | 所有分數正規化至 0–100 |
| `market_regime()` | 指數價/均線/外資/ADL | `dict`（regime + score） | 寫入 `session_state['mkt_info']` |
| `_build_prompt()` | context `dict` | `str`（完整 Prompt） | 路由至 `_STOCK_LOGIC` |

---

### 3.3 流程二：ETF 分析

**觸發**：使用者在「🏦 ETF」Tab 輸入代號並點擊「開始診斷」。

```
使用者輸入
  ETF 代號 (ticker)
       │
       ▼
┌──────────────────────────────────────────────┐
│  L4 · etf_dashboard · render_etf_single()    │
│                                              │
│  並行抓取（ThreadPoolExecutor）：              │
│  ├─ fetch_etf_price()     ← yfinance 日K      │
│  ├─ fetch_etf_nav_history() ← 基金公司 API     │
│  ├─ fetch_etf_dividends()  ← 歷史配息紀錄      │
│  └─ fetch_etf_info()       ← 基本資料/規模      │
│                                              │
│  輸出：price_df / nav_df / div_df / info_dict │
└─────────────────┬────────────────────────────┘
                  │
    ┌─────────────▼──────────────────────────────────┐
    │  指標計算層（純函式，無外部 I/O）                  │
    │                                                │
    │  calc_current_yield()    現金殖利率              │
    │  calc_avg_yield()        近 3 年平均殖利率        │
    │  calc_premium_discount() 折溢價率（市價/NAV-1）   │
    │  calc_tracking_error()   追蹤誤差（vs 指數）      │
    │  calc_mdd()              最大回撤                │
    │  calc_cagr()             年化報酬率              │
    │  calc_sharpe()           Sharpe Ratio           │
    │  check_vcp_signal()      VCP 波動收縮訊號         │
    │  _render_bias()          BIAS240 年線乖離率       │
    └─────────────┬──────────────────────────────────┘
                  │
    ┌─────────────▼──────────────────────────────────┐
    │  AI 決策（選用）                                 │
    │                                                │
    │  unified_decision · render_unified_decision()  │
    │  context type = 'etf'                          │
    │  data = { 殖利率 / BIAS240 / KD / 折溢價 / 大盤 }│
    │                                                │
    │  → Gemini Prompt（_ETF_LOGIC 左側交易鐵血紀律）  │
    │  → JSON → 3-Card UI                            │
    └────────────────────────────────────────────────┘

ETF 組合子頁（render_etf_portfolio）額外流程：
  使用者輸入多支 ETF + 持倉比例
       │
       ├─ 相關係數矩陣計算 → 熱力圖（價格報酬 Pearson）
       ├─ 持股 Overlap 矩陣（PR #2）→ 熱力圖（fetch_etf_holdings + Σmin / Jaccard）
       ├─ 主動 ETF 弱勢度檢測（PR #3）→ ProgressColumn 表格
       │     │  is_active_etf 過濾 → calc_weakness_metrics
       │     │  大跌弱勢率 / 反彈弱勢率 / 連敗季數 / TE%
       │     └  fetch_etf_manager 標註經理人任期；連敗 ≥ 2 季 → 紅卡換股建議
       ├─ 組合績效回測（CAGR / Sharpe / MDD）
       ├─ _render_monte_carlo()：蒙地卡羅模擬（1000 次路徑）
       └─ _etf_ai_portfolio()：組合 AI 評斷

ETF 回測子頁（render_etf_backtest）額外流程：
  使用者選擇策略 + 時間範圍
       │
       └─ backtest_engine · run_backtest()
            └─ walk_forward_test() → 績效統計 → _etf_ai_backtest()
```

---

### 3.4 流程三：每日市場總覽

**觸發**：使用者點擊「🚀 一鍵更新全部數據（總經 + 籌碼 + 先行指標）」。

> **v10.56.0 嚴格原則（PR #1）**：進頁 0 並發 0 抓取，必須使用者明確點按鈕才觸發。
> 副作用：所有資料區塊冷啟動顯示「更新後顯示」placeholder，由 `_show_market_data` gate 統一控制。

```
點擊更新按鈕
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│  並發任務（ThreadPoolExecutor，6 個 worker）               │
│                                                          │
│  _job_intl()   yfinance 國際指數（SOX/DJI/DXY/10Y）        │
│  _job_tw()     yfinance 台股指數（^TWII/匯率）              │
│  _job_tech()   yfinance 科技股（NVDA/TSMC/AAPL…）          │
│  _job_inst()   daily_checklist · fetch_institutional()    │
│                  └─ TWSE BFI82U → FinMind 備援             │
│  _job_margin() daily_checklist · fetch_margin_balance()   │
│                  └─ TWSE MI_MARGN                         │
│  _job_adl()    daily_checklist · fetch_adl()              │
│                  └─ FinMind TaiwanStockMarketValue         │
└──────────────────────┬───────────────────────────────────┘
                       │（全部完成後合併）
                       ▼
         ┌─────────────────────────┐
         │  leading_indicators     │
         │  build_leading_fast()   │
         │  ├─ TAIFEX 外資期貨淨部位 │
         │  ├─ 選擇權 PCR           │
         │  └─ 韭菜指數             │
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────┐
         │  market_strategy        │
         │  market_regime()        │
         │                         │
         │  輸入（5 個評分維度）：   │
         │  ① 指數 vs MA60/MA120   │
         │  ② 外資現貨淨買賣        │
         │  ③ ADL 廣度指標          │
         │  ④ 均線斜率方向          │
         │  ⑤ 成交量 vs 20日均量    │
         │                         │
         │  輸出：mkt_info dict     │
         │   regime / score /       │
         │   label / exposure_pct  │
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────┐
         │  macro_helpers          │
         │  calc_traffic_light()   │
         │  （Phase 7A-Ext 抽出）  │
         │                         │
         │  主要驅動：regime        │
         │  緊急覆蓋：defense /     │
         │           health < 40   │
         │                         │
         │  輸出：tl dict (16 keys) │
         │   icon / label /         │
         │   color / action / sub  │
         │   health / conf /        │
         │   missing_sources (PR#1) │
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────┐
         │  _render_traffic_light()│
         │  + mkt_info（合併看板）  │
         │                         │
         │  PR #1 信心門檻 gate：   │
         │  conf<70 → 橘色「⏸️ 資料 │
         │  不足」卡 + 列缺失資料   │
         │  early-return，不渲染燈號│
         │                         │
         │  conf≥70 渲染：          │
         │  ① 主燈號 + 操作建議     │
         │  ② 市場評分/指數/持股%   │
         │  ③ 信號 badges           │
         │  ④ 核心/衛星資金看板     │
         │  ⑤ 衛星資金使用進度條    │
         └─────────────────────────┘
                      │
                      ▼
          後續 Section 渲染（順序執行）：
          Section 一  國際市場（SOX×DXY 四象限）
          Section 二  台股大盤（股匯四象限/ADL）
          Section 三  籌碼（外資/融資門檻）
          Section 四  期現貨（期貨口數）
          Section 七  M1B-M2 Gap + BIAS240
          Section 八  總經拼圖（VIX/NDC/CPI/OECD CLI）
          Section 九  總經 AI 五維度規則分析
          Section 十  AI 總結（Gemini × RSS 新聞）
```

---

### 3.5 資料新鮮度管理

| 快取機制 | 適用資料 | 有效期 | 過期策略 |
|---------|---------|-------|---------|
| **`_URL_CACHE` dict（Storm Shield）** | **`fetch_url()` 所有外部 HTTP 請求** | **300 秒** | **相同 URL+params 直接命中記憶體快取，嚴禁重複衝擊 NAS/外部 API** |
| `@st.cache_data(ttl=3600)` | 個股 OHLCV、法人、先行指標 | 60 分鐘 | Streamlit 自動失效，重新抓取 |
| `@st.cache_data(ttl=1800)` | 每日大盤資料（BFI82U / ADL） | 30 分鐘 | 同上 |
| `_pkl_get/put` pickle 檔 | 三大法人(600s)、融資餘額(600s) | 見 `data_config.TTL_CONFIG` | 手動按「🔄更新」觸發 `_pkl_clear_all()` 強制清除；跨日自動過期 |
| `session_state['success_cache']` | `safe_fetch_strict` 成功值 | 同日有效，跨日清除 | 日期比對，昨日快取當日自動視為過期 |
| `session_state['cl_ts']` | 最後更新時間戳 | 30 分鐘 | 超過後燈號顯示「等待中」，拒絕渲染過期數據 |
| process-level `dict` | TWSE T86 / TPEx 當日資料 | 程序生命週期 | 僅限同一 Python 程序，Cloud 重啟後清除 |

> **v4.5 嚴格原則**：任何資料來源全部失敗時，回傳 `None`（N/A），禁止使用跨次執行的舊資料，避免誤判市場訊號。

> **防誤判設計**：燈號渲染前先比對 `cl_ts` 與當前時間。若快取超過 30 分鐘，`_tl_placeholder` 顯示「燈號等待中（已過期）」，不渲染過時的多空訊號，避免誤導投資決策。

> **v5.0 App 初始化閘門**：`app.py` 在 `st.set_page_config()` 後立即執行 `'_app_boot_done' not in st.session_state` 檢查。每個 Session 僅清除一次 `st.cache_data`（首次啟動），後續 rerun 直接跳過，防止背景任務衝突導致的無限重載迴圈。

> **Streamlit 環境封印（`.streamlit/config.toml`）**：`runOnSave = false`（禁止存檔自動重載）、`[logger] level = "error"`（過濾 Info/Warning 雜訊，減少日誌風暴）。

#### 冷啟動完全停機：使用者點按鈕才抓資料（v10.56.0 / PR #1，取代 v10.54.0 Lazy Load）

**演進歷程**：
- v10.54.0：冷啟動跑 3 輕量 job（intl/tw/tech）+ 按鈕載入 4 重資料 → 結果寫進
  `cl_data` 使 `_cache_fresh=True`，部分資料即觸發燈號計算，新舊混雜誤導決策。
- **v10.56.0（PR #1）**：冷啟動 **0 並發 0 抓取**，必須使用者明確點按鈕。

```
冷啟動：                [無動作] 所有資料區塊顯示 placeholder「更新後顯示」
                        燈號區顯示「⏳ 燈號等待中（尚無資料）」
                        │
                        ▼
使用者點「🚀 一鍵更新全部數據」 (do_refresh=True，同步 chips_loaded=True)
                        │
                        ▼ on_click callback 全清三層快取：
                          ① st.cache_data.clear()
                          ② proxy_helper._URL_CACHE.clear() + reset_proxy_cache()
                          ③ session_state pop 11 key（cl_data / cl_ts / mkt_info /
                             jingqi_info / li_latest / warroom_summary /
                             _last_inst / _last_inst_date / _last_margin /
                             futures_net / adl_debug_msg）
                        │
                        ▼ 7 job 全量並發：
                          [輕量] intl + tw + tech
                          [重量] inst + margin + adl + li_fast
```

**設計理由**：
- 燈號渲染必須建立在**完整資料**之上，否則 conf<70 仍會被 `_render_traffic_light` early-return（顯示橘色「⏸️ 資料不足」+ 逐項列缺失資料）
- 全清快取保證「禁用暫存資料、全部都要重新下載」的用戶意圖落實
- `chips_loaded=True` query_params 同步機制仍保留（WebSocket 重連恢復用）

#### 頂部總經指南針：按鈕觸發即時抓取（PR #4，取代 15 分鐘 session_state 自動快取）

`app.py:1073-1110` `render_macro_compass()` 渲染頂部三卡（VIX × 10Y × S&P 500 vs 60MA）。

**演進**：
- 舊：進頁觸發 `fetch_macro_compass()`，結果以 15 分鐘 TTL 存 `st.session_state['_macro_compass_cache']`；下次進頁直接讀快取，避免重複打 yfinance。
- **PR #4**：進頁不抓資料；右上「📡 抓取最新 / 🔄 重抓」按鈕觸發 `_do_fetch()` callback，按了才寫 cache。

**設計理由**：避免「進頁顯示上次抓到的舊值」誤判 — 收盤後、盤前、離線時的過時數字會讓使用者以為是當下行情。改成按鈕觸發後，**按的當下＝盤面當下＝決策當下真實狀態**，語意一致。副標動態顯示「即將抓取（無快取）」or「更新於 HH:MM:SS」讓資料新鮮度可追溯。

#### Google Sheet 雲端儲存：使用者持股組合可攜（PR #5）

`gsheet_portfolio.py` 提供 5 純函式 API（`is_configured` / `list_portfolios` / `load_portfolio` / `save_portfolio` / `delete_portfolio`），讓 ETF 組合配置 TAB 支援多組命名持股組合（攻擊組合 / 存股組合 / 老婆帳戶 …）跨 session、跨裝置儲存。

**Schema**（單一 worksheet `portfolios`）：

| 欄位 | 型別 | 說明 |
|------|------|------|
| `name` | str | 組合名稱（多組以多列共用同表） |
| `ticker` | str | 股票/ETF 代號（自動 upper） |
| `lots` | float | 持有張數（1 張 = 1000 股） |
| `avg_price` | float | 平均買入價格 |
| `updated_at` | str | `YYYY-MM-DD HH:MM:SS` 寫入時間戳 |

**設計**：
- 依賴 `gspread` + `google-auth`，憑證從 `st.secrets['gcp_service_account']` 讀（Service Account JSON），Sheet ID 從 `st.secrets['portfolio_sheet_id']` 讀
- OAuth client + worksheet handle 用 `st.cache_resource` 共享（同 session 不重複認證）
- 未配置 secrets 時 `is_configured()` 回 `False`，UI 顯 warning 不爆炸 — 純可選增強功能
- 同名儲存：先過濾掉舊列再 append，不堆疊重複；刪除：rebuild 整張 worksheet 跳過該組
- 載入後在 UI 層 `pop('etf_p_table')` 清 `st.data_editor` widget state，觸發 rerun 讓新資料流入 `_default_df`
- 儲存讀 `edited_df`（data_editor 回傳值）而非 `st.session_state['etf_p_table']` — 後者在 data_editor 場景儲存的是 edit-deltas (`{'edited_rows', 'added_rows', 'deleted_rows'}`)，不是完整 DataFrame

**設計理由**：Streamlit Cloud 多人共用且容器重啟會洗，本地檔不持久；下載/上傳 JSON 則需手動管理檔案。Google Sheet 一次設定、跨裝置自動同步、Sheet 也可手動編輯查看，是兼具可攜性與低門檻的方案。憑證在 `secrets.toml` 不入 git，安全性與 FINMIND_TOKEN 等 secrets 同層級。

> **融資維持率已於 v10.54.0 移除**：原三段備援（TWSE MI_MARGN / wantgoo / OpenAPI）
> 因 Streamlit Cloud 不在台灣 IP 段，透過代理仍經常 8s+ 失敗，且 v4 引擎的
> `is_margin_danger` 分支貢獻有限，整段拆除以瘦身冷啟動。

---

## 4. 核心函式 I/O 定義

> 本節按分層列出各模組的核心公開函式。格式統一為：函式簽名（無實作）、輸入參數、回傳值、副作用。

---

### 4.1 L1 資料層

#### `data_loader.py`

---

**`_get_t86_day(ds)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `ds: str` — 日期字串，格式 `YYYYMMDD` |
| 輸出 | `dict` — `{ '外資': int, '投信': int, '自營商': int }`（單位：仟元），抓取失敗回傳 `{}` |
| 副作用 | 無；結果寫入 process-level `_t86_cache` dict |
| 備援 | TWSE T86 失敗時由 `_fetch_finmind_inst_raw()` 接手 |

---

**`StockDataLoader.fetch(stock_id, days)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `stock_id: str` — 台股代號（如 `'2330'`）；`days: int` — 回溯天數 |
| 輸出 | `tuple[DataFrame, DataFrame]` — `(df_price, df_inst)` |
| `df_price` | 欄位：`Date / Open / High / Low / Close / Volume`（日頻，按日期升序） |
| `df_inst` | 欄位：`Date / 外資 / 投信 / 自營商`（單位：張，正買負賣） |
| 副作用 | `@st.cache_data(ttl=3600)` 快取；TWSE/TPEx → FinMind 備援自動切換 |

---

**`fetch_institutional(date_str)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `date_str: str` — 查詢日期 `YYYYMMDD`（預設當日） |
| 輸出 | `tuple[dict, str]` — `(inst_dict, source_label)` |
| `inst_dict` | `{ '外資及陸資(不含外資自營商)': { 'buy': int, 'sell': int, 'net': int }, ... }` |
| `source_label` | 資料來源標籤（`'TWSE BFI82U'` 或 `'FinMind'`） |
| 副作用 | 無 |

---

**`fetch_margin_balance(date_str)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `date_str: str` — 查詢日期 |
| 輸出 | `tuple[float|None, str]` — `(margin_billion, source_label)` |
| `margin_billion` | 全市場融資餘額（單位：億元）；無資料時回傳 `None` |
| 副作用 | 無 |

---

#### `leading_indicators.py`

---

**`build_leading_fast(days, token)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `days: int` — 回溯天數（建議 7–14）；`token: str` — FinMind API Token |
| 輸出 | `DataFrame \| None` — 欄位：`Date / 外資大小 / PCR / 韭菜指數 / ...`；無資料時回傳 `None` |
| 副作用 | `@st.cache_data(ttl=3600)` 快取；結果存入 `session_state['li_latest']` |
| 用途 | 每日總覽快速版；ETF 多空判斷輸入來源 |

---

**`finmind_get(dataset, data_id, start_ymd, end_ymd, token)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `dataset: str` — FinMind 資料集代號；`data_id: str` — 標的代號；`start/end_ymd: str` — 日期範圍 `YYYYMMDD` |
| 輸出 | `DataFrame` — 原始 FinMind JSON 轉換結果；失敗回傳空 DataFrame |
| 副作用 | 無；HTTP 錯誤時 `print('[FinMind] ❌ ...')` 至 Cloud log |

---

**`taifex_pcr(start_ymd, end_ymd)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `start_ymd, end_ymd: str` — 日期範圍 `YYYYMMDD` |
| 輸出 | `DataFrame` — 欄位：`Date / PCR_OI / PCR_Volume`（Put/Call 比） |
| 副作用 | TAIFEX POST 請求；失敗時回傳空 DataFrame |

---

### 4.2 L2 評分層

#### `tech_indicators.py`（PR #58 新增 — 從 app.py 抽出）

**設計原則**：純技術指標計算，**零 Streamlit / 零 session state 依賴**，可在 CLI / pytest 環境直接 import。輸入皆為 `pandas.DataFrame`（必含 `close / high / low / volume` 欄位），失敗統一回 `None`（不丟例外）。

| 函式 | 簽名 | 用途 |
|---|---|---|
| `calc_rsi` | `(df, period=14) -> float \| None` | 相對強弱指標 RSI |
| `calc_ibs` | `(df) -> float \| None` | 內部強度 `(Close-Low)/(High-Low)` |
| `calc_volume_ratio` | `(df, period=5) -> float \| None` | 量比 = 今日量 / N 日均量 |
| `calc_kd` | `(df, period=9) -> tuple[float, float] \| (None, None)` | KD 隨機指標（EMA 平滑） |
| `calc_bollinger` | `(df, window=20, mult=2) -> dict \| None` | 布林通道（含 `upper/lower/ma/bw/near_upper`） |
| `calc_vcp` | `(df, n_swings=3) -> dict \| None` | Volatility Contraction Pattern |

**呼叫端**：`app.py:594` 統一 import，於 L5704-5709（個股深度分析）+ L8169-8174（比較排行）使用。

---

#### `scoring_helpers.py`（PR #61 新增 — 從 app.py 抽出）

**設計原則**：純評分函式，**零 Streamlit / 零 session state 依賴**。

| 函式 | 簽名 | 用途 |
|---|---|---|
| `calc_fundamental_score` | `(qtr_df, yearly_df, avg_div) -> dict` | 基本面四維評分（獲利 / 成長 / 股利 / 估值，各 0-3 分） |
| `calc_health_score` | `(df, rsi, ibs, vr, k_val, d_val, bb) -> tuple[int, dict]` | 綜合健康度評分 0-100（6 因子：趨勢 30 + RSI 20 + 量比 15 + IBS 10 + KD 15 + 布林 10） |
| `health_grade` | `(score) -> tuple[str, str, str, str]` | 分數 → (等級標籤, 顏色 hex, css class, emoji) |

**呼叫端**：`app.py` render_health_score / render_etf_single / TAB 2 個股 / TAB 3 比較排行 等多處。

---

#### `ui_widgets.py`（PR #60 新增 — 從 app.py 抽出）

**設計原則**：純 HTML 字串生成器，**零 Streamlit / 零 session state 依賴**，呼叫端用 `st.markdown(..., unsafe_allow_html=True)` 渲染。

| 函式 / 常數 | 用途 | Callers |
|---|---|---|
| `explain_box(term, simple_explain, detail='')` | 術語說明框 | 內部 |
| `traffic_light(value, good_cond, bad_cond, ...)` | 紅綠燈指示器 | 5 |
| `beginner_kpi(title, value, plain_meaning, ...)` | 初學者 KPI 卡 | 5 |
| `show_term_help(term)` | 術語對照表查詢 | 2 |
| `kpi(title, value, sub='', color, border)` | 一般 KPI 卡 | **53** |
| `teacher_box(icon, teacher, logic)` | 舊版老師建議框（保留向下相容；內含 `_to_strategy()` 自動翻譯） | 0 |
| `teacher_conclusion(teacher, indicator_val, conclusion, ...)` | 老師結論（自動配色；老師→策略翻譯統一在此） | **25** |
| `_STRATEGY_MAP: dict` + `_to_strategy(teacher)` | **集中翻譯**：老師 → 策略 1/2/3（按方法論分 3 類：估值/存股、財報體檢、技術/動能） | 內部 + `etf_dashboard._teacher_conclusion` |
| `signal_box(label, color, desc='')` | 訊號方塊 | 4 |
| `TERM_EXPLAIN: dict` | 13 個常見術語白話對照 | 內部 |

---

#### `etf_dashboard.py` 結構演進（PR #75-#78 — P2-B Phase 6 全收官 ✅✅）

**最終戰績**：etf_dashboard.py 3122 → **1667 行（−46.6%）**，4 個大 `render_etf_*` 函式全部抽到獨立 `.py` 模組。

| 模組 | 行數 | 依賴 | 角色 | PR |
|---|---|---|---|---|
| `etf_tab_single.py` | 616 | 22 | ETF 單一深度診斷（NAV / 折溢價 / 費用率 / 品質評等） | #75 |
| `etf_tab_portfolio.py` | 531 | 14 | ETF 組合配置（相關性矩陣 / 類股暴露 / AI 投組） | #76 |
| `etf_tab_backtest.py` | 284 | 13 | ETF 歷史回測（CAGR / MDD / Sharpe / Monte Carlo） | #77 |
| `etf_tab_ai.py` | 169 | 5 | ETF AI 教練（MACRO_ALLOC 配置 / news / banner） | #78 |

**Phase 6 依賴策略**：
- **Top-level**：僅 `import streamlit as st`
- **函式內 late import**：所有其他依賴（stdlib / 外部模組 / etf_dashboard.py 內部 helper）
- **循環 import 處理**：etf_dashboard.py 底部 re-export 4 個 render_etf_*，維持 app.py 既有 import 不變

**etf_dashboard.py 內部 helper 跨檔使用統計（從各 etf_tab_*.py late import）**：

| Helper | etf_tab_single | etf_tab_portfolio | etf_tab_backtest | etf_tab_ai |
|---|---|---|---|---|
| `_colored_box` | ✅ | ✅ | ✅ | — |
| `_teacher_conclusion` | ✅ | ✅ | ✅ | — |
| `macro_allocation_banner` | ✅ | ✅ | — | ✅ |
| `fetch_etf_price` | ✅ | ✅ | ✅ | — |
| `fetch_etf_dividends` | ✅ | ✅ | ✅ | — |
| `fetch_etf_info` | ✅ | ✅ | — | — |
| `calc_*` 系列 (cagr/mdd/sharpe/avg_yield/...) | ✅ | — | ✅ | — |
| `_compute_etf_warroom_row` | — | ✅ | — | — |
| `_etf_ai_*` 系列 | ✅ (hokei) | ✅ (portfolio) | ✅ (backtest) | — |
| `MACRO_ALLOC` / `_fetch_news_for` | — | — | — | ✅ |

**已清除繼承風格債（55+ 個）**：
- P6-A: 36 個（13 E701 + 9 E702 + 9 F541 + 3 E401 + 2 F401，autopep8 + ruff --fix）
- P6-B: 1 個 E701
- P6-C: 10 個 E701/E702
- P6-D: 8 個 F541

#### `etf_dashboard.py` 三層分檔（commit `44a0e87` — P2-B Phase 7C 收官 ✅）

**最終戰績**：etf_dashboard.py 1667 → **49 行 shim（−97.1%）**，36 個內部 helper 全部下沉到 3 個按職責分離的子模組。

| 模組 | 行數 | 角色 | 依賴 |
|---|---|---|---|
| `etf_fetch.py` | 572 | 純 I/O：價格 / 配息 / 基本資訊 / 費用率 (SITCA→MoneyDJ→yfinance 3 源備援) / NAV (FinMind→goodinfo→TWSE→MoneyDJ→yfinance 5 源備援+stale fallback) / 類股漲跌 / 新聞 | streamlit + pandas + yfinance（**零內部依賴**） |
| `etf_calc.py` | 465 | 純算：殖利率 / 總報酬 / 折溢價 G1-G3 守門員 / 風險指標 (TE/MDD/CAGR/Sharpe) / VCP / 同儕排名 / `_compute_etf_warroom_row` | `etf_fetch` |
| `etf_render.py` | 505 | Streamlit UI：MACRO_ALLOC 配置橫幅 / 走勢圖 / BIAS / 蒙地卡羅 / 類股熱力圖 / `_teacher_conclusion` / `_check_sector_exposure` | `etf_fetch`（只取 `_fetch_news_for` / `_fetch_sector_returns`） |
| `etf_dashboard.py` | 49 | Public API shim — re-export 40 個 symbol + 4 個 tab 入口 | 上述 3 檔 + 4 個 etf_tab_*.py |

**Phase 7C 依賴方向**：

```
   etf_fetch  (葉節點 / 純 I/O)
       ↑
   etf_calc   (依賴 etf_fetch)
       ↑
   etf_render (依賴 etf_fetch)
       ↑
 etf_dashboard.py  (re-export shim)
       ↑
 6 個下游 importer (app / etf_quality / grape_ladder / etf_tab_*)
```

**關鍵設計決策**：
- `_compute_etf_warroom_row` 雖混 fetch + calc，仍歸 `etf_calc`（calc 可依賴 fetch，反向不可）
- `_safe_float` / `_NAV_MIN` / `_NAV_MAX` 留 `etf_fetch`（NAV 解析配套）
- `_fetch_sector_returns` 留 `etf_fetch`（雖含 st.warning，但本質仍是 I/O）
- `_teacher_conclusion` 內部對 `ui_widgets._to_strategy` 採 late import，避免 render 直接依賴

**驗證結果**：
- ✅ py_compile 4 檔全綠
- ✅ 40 個 re-export symbol import 驗證通過
- ✅ 6 個下游 importer (app / etf_quality / grape_ladder / etf_tab_single / etf_tab_portfolio / etf_tab_backtest / etf_tab_ai) 零修改載入成功
- ✅ pytest 469 pass / 4 unrelated fail（與 ETF 無關，financial_health_engine 既有問題）

#### `tab_stock.py` 停利停損面板 K 線圖（commit `461d465` — Phase 7D）

**動機**：「停利停損建議 + 近期支撐壓力」面板僅有數字 metric，使用者需手動腦補價位在 K 線的相對位置。新增精簡 K 線圖直接視覺化所有關鍵價位。

**位置**：`tab_stock.py:507-570`（緊接 `_sig_cols[2]` 目標+停損段之後，原 F 段 5-row 完整圖保持不動）。

**結構**：
- Plotly subplots 2 rows（價 78% / 量 22% 共享 x 軸）
- 近 180 個交易日，MA20 (粉紅) + MA100 (青)
- 9 條 add_hline 水平線（每條有顏色 + 虛線樣式 + 左上角價位標籤）：

| 線 | 來源變數 | 顏色 | 樣式 |
|---|---|---|---|
| 停利 2 (+10%) | `_tp2_p` | #58a6ff | dash |
| 停利 1 (+5%) | `_tp1_p` | #3fb950 | dash |
| 壓力 (20D high) | `_hi20_p` | #f0883e | dot |
| 初步目標（1:1對稱） | `_target1` | #2ea043 | dashdot |
| 5MA 停利 | `_ma5` | #FFD700 | solid |
| 支撐 (20D low) | `_lo20_p` | #1f6feb | dot |
| 月線停損 | `_sl_ma20` | #8b949e | dot |
| 停損 (-8%) | `_sl_p` | #f85149 | dash |
| 硬停損 (-7%) | `_sl_hard` | #a40e26 | dashdot |
| 加碼點（條件性） | `_add_pt` | #a371f7 | dashdot |

**邊界處理**：try/except 包覆；`_add_pt` 用 `locals().get()` 防 NameError；MA 欄位缺失即時 rolling 補算；y ≤ 0 時不畫線。

#### `tab_helpers.py` 跨 tab 共用純函式（commit `0ef1991` — P2-B Phase 7A）

**動機**：tab_stock.py 與 tab_stock_grp.py 內出現 EXACT DUPLICATE 的 `_r110_ok_a` / `_r110_ok_b`（cash flow 比率解析）與 `_tk` / `_tk2`（bool → emoji），各自還 local re-import `re`；tab_macro 也有相似的 `_v`（NaN 過濾）與 tab_stock 的 `_safe_ma`。Phase 7A 把這 4 個 closure 合併到模組頂層、零 Streamlit 依賴、可獨立 unit test。

| 函式 | 取代 | 來源 | Lines saved |
|---|---|---|---|
| `parse_cash_flow_ratio(value, threshold, strict)` | `_r110_ok_a` / `_r110_ok_b` | tab_stock:2157 + tab_stock_grp:723 | 20 |
| `format_condition_emoji(value)` | `_tk2` / `_tk` | tab_stock:2169 + tab_stock_grp:735 | 4 |
| `safe_get(value)` | `_v` | tab_macro:2667 | 6 |
| `safe_ma(df, n)` | `_safe_ma` | tab_stock:378 | 7 |

**依賴方向**：

```
tab_helpers.py  (葉節點 / 純 Python + pandas，零 streamlit / plotly)
       ↑
tab_stock.py / tab_stock_grp.py / tab_macro.py  (module-level import)
```

**設計原則**：
- 零 Streamlit / Plotly：可被任何模組安全引用
- 防呆優先：對 None / NaN / 缺欄位皆有 fallback path
- 顯式參數：`strict=True/False` 取代隱式 bool 位置參數
- 對應測試覆蓋：`tests/test_tab_helpers.py` 27 case（13 cash flow + 4 emoji + 6 safe_get + 4 safe_ma）

**驗證結果**：
- ✅ py_compile + ruff 全綠
- ✅ pytest 全套 500 → 496 pass / 4 unrelated fail（test_financial_health_engine.TestNoAiSurvivalBItem 既有問題，已於 7A-Ext 一併修復）
- ✅ 3 tab 檔合計 −41 行（移除 closure + 重複 import）

#### `macro_helpers.py` + `tab_helpers.final_recommendation` + B 項 1Q fallback（commit `e678d22` — P2-B Phase 7A-Ext）

**動機**：Phase 7A 抽出 4 個跨 tab 重複 helper 後仍有 2 個 tab 內部 closure 阻擋 unit test：
- `tab_macro._calc_traffic_light`（71 行 nested def，紅綠燈決策核心）
- `tab_stock_grp._final_rec`（26 行 closure，含 `score_map` 閉包）

同時發現 `financial_health_engine._no_ai_survival` 對 B 項（現金流量允當比率）**缺少「呼叫端未預填 b_item_5y」的單季 fallback 分支**，導致 4 個 pre-existing 紅燈（`test_financial_health_engine.TestNoAiSurvivalBItem`）長期未修。

| 抽出 | 從 | 至 | Lines saved |
|---|---|---|---|
| `calc_traffic_light(mkt_info, jq_info, cl_data, li_latest)` | tab_macro.render_tab_macro:71-141 | `macro_helpers.py` | 71 |
| `final_recommendation(row, score_map)` | tab_stock_grp.render_stock_grp:382-407 | `tab_helpers.py` | 26 |

**`macro_helpers.py` 設計**：獨立模組（非併入 `tab_helpers.py`），避免跨 tab 共用層引入 tab_macro 專屬決策邏輯；零 Streamlit/Plotly 依賴，僅用 stdlib + pandas DataFrame 偵測。同時清理 1 處 dead code（`_fk` fallback 重複 `next()` 呼叫）。

**`_no_ai_survival` B 項 4 分支策略**（修補後）：

| `b_item_5y.status` | b_val | b_display | b_st | 適用情境 |
|---|---|---|---|---|
| `"ok"` | 5y 實際值 | `"127.3%（5年實際）"` | Pass/Fail | 正常 production（tab_stock/tab_stock_grp 預填） |
| `"insufficient_data"` | None | `"N/A（上市未滿5年）"` | Fail | 新上市股票 |
| `"error"` | None | `"N/A（5年歷史資料未取得）"` | N/A | API 失敗（保守標 N/A 不單季推估） |
| **缺 key** | **1Q 估算** | **`"XX.X%(1Q估)"`** | **Pass/Fail** | **unit test / legacy 呼叫端** |

公式：`b_val = OCF / (capex + max(inv-inv_p, 0) + div) × 100`；`b_denom ≤ 0` → display `"N/A"`、status N/A。

**驗證結果**：
- ✅ py_compile + ruff（僅 3 個 pre-existing financial_health_engine.py 紅燈，非本次修改）
- ✅ pytest 全套 **519/519 全綠**（原 500 + 新增 19 + 解 4 pre-existing failures）
- ✅ tests/test_macro_helpers.py 12 case（regime × defense 矩陣 + health 公式 + conf 計分）
- ✅ tests/test_tab_helpers.py +7（TestFinalRecommendation：積極/觀察/等待 × 邊界值）

#### `etf_helpers.py` ETF tab 共用純函式（P2-B Phase 7B）

**動機**：Phase 7A/7A-Ext 已抽完 tab_macro / tab_stock(_grp) 的 closure，但 `etf_tab_backtest.py` 與 `etf_tab_portfolio.py` 仍各有純邏輯 closure 嵌在 render 內無法獨立測試：
- `etf_tab_backtest._norm_return` / `_norm_lower_better`（雷達圖 5 維 0-100 正規化，12 行；組合 + 基準共 10 個 callsites）
- `etf_tab_portfolio._auto_role` + `_CORE_TICKERS`（MK 框架 #9 核心/衛星分類，6 行）

| 抽出 | 從 | 至 | Lines saved |
|---|---|---|---|
| `norm_return(v, lo, mid, hi)` | etf_tab_backtest.render_etf_backtest:186-190 | `etf_helpers.py` | 5 |
| `norm_lower_better(v, best, mid, worst)` | etf_tab_backtest.render_etf_backtest:192-197 | `etf_helpers.py` | 6 |
| `auto_role(tk)` + `_CORE_TICKERS` | etf_tab_portfolio.render_etf_portfolio:45-51 | `etf_helpers.py` | 7 |

**`etf_helpers.py` 設計**：零 Streamlit/Plotly 依賴；`_CORE_TICKERS` 改用 `frozenset` 防呆（測試實證 `.add()` raise AttributeError）。命名去 underscore prefix（`_norm_return` → `norm_return`、`_auto_role` → `auto_role`）改為 public module API，與 `tab_helpers` 慣例一致。Module-level import 於兩個 consumer 頂部（無循環風險）。

**驗證結果**：
- ✅ py_compile + ruff (`All checks passed!`)
- ✅ pytest 全套 **548/548 全綠**（原 519 + 新增 29）
- ✅ tests/test_etf_helpers.py：TestNormReturn 9 + TestNormLowerBetter 10 + TestAutoRole 10
- 涵蓋：邊界值（≥hi/≤lo/at mid）、線性段、custom bounds（實際 callsite 參數）、abs 取值、`.TWO` / `.TW` 後綴剝離、`None` / 空字串、frozenset 不可變

#### `macro_helpers.{rp_ts, rp_entry, rp_scalar}` data_registry 三函式（P2-B Phase 7E）

**動機**：`tab_macro.py:1663-1709` 內三個互相協作的 closure（`_rp_ts` / `_rp_entry` / `_rp_scalar`）負責「Registry 常態 Patch」段把 session_state 的個股 / ETF / 比較 / 回測資料轉成 `data_registry` entry dict。30 行核心邏輯（DataFrame 4 種時間源解析），但被 `_proxy_rp` closure capture 綁死，不能單元測試；其它 tab 若也想做 registry patch 也無法重用。

**抽出明細**：

| 函式 | 原 closure 位置 | 抽至 | 行數 |
|---|---|---|---|
| `rp_ts(df)` | tab_macro.render_tab_macro:1663-1698 | `macro_helpers.py` | 36 |
| `rp_entry(df, cat, freq)` | tab_macro.render_tab_macro:1700-1703 | `macro_helpers.py` | 4 |
| `rp_scalar(val, cat, freq, proxy_date)` | tab_macro.render_tab_macro:1705-1709 | `macro_helpers.py` | 5 |

**設計理念**：
- `_QE_MAP`（季度標籤映射）由原 closure scope 提至 `macro_helpers.py` 模組級私有常數，方便 unit test 直接驗證 Q1-Q4 對應。
- `rp_scalar` 的 `proxy_date` 改為**顯式參數**（原 closure capture `_proxy_rp`）— 純函式化的關鍵，移除對 `st.session_state.cl_ts` 的隱式依賴；單元測試可傳任意日期字串驗證行為。
- 命名去 underscore prefix（`_rp_ts` → `rp_ts` 等）改為 public API，與 `calc_traffic_light` 同一模組並列。
- `rp_ts` 內 pandas import 改為 macro_helpers.py 頂部 `import pandas as pd`（與既有 `calc_traffic_light` 的 duck-typing 風格不同 — 因為 `rp_ts` 必須用 `pd.to_datetime` / `pd.Timestamp` / `pd.isna` API）。

**callsite 衝擊**：
- `tab_macro.py` 刪 47 行 closure 區塊 + 26 callsite 重接（`rp_scalar` 21 + `rp_entry` 3 + `rp_ts` 2）
- `_proxy_rp` 變數**保留**於 tab_macro.py（外層 `_cl_ts_rp` 解析仍需），每次 `rp_scalar(..., _proxy_rp)` 顯式傳入

**驗證**：
- ✅ py_compile + ruff (`All checks passed!`)
- ✅ pytest 全套 **566/566 全綠**（原 548 + 新增 18）
- ✅ tests/test_macro_helpers.py：TestRpTs 11 + TestRpEntry 3 + TestRpScalar 4
- 涵蓋：`None` / 非 DataFrame / 空 DataFrame、DatetimeIndex、季度標籤 Q1-Q4 + 無效 Q 數、年度 int、`_date` strict format vs 一般 `date` 自動推斷、無法 parse → 'N/A'、scalar `0` / `''` 不被誤判為 None

#### `ui_widgets.cond_badge` 條件徽章函式（P2-B Phase 7F）

**動機**：`tab_macro.py:3392` 內 `_cond_badge(ok, label)` 是 SECTION 八 五維點火條件列（A-G 共 7 個徽章）專用 HTML span 模板，零 Streamlit 依賴 + 7 callsite，符合 `ui_widgets.py` 既有 PR #60 純 HTML 函式集合的設計風格，自然合併。

**抽出明細**：

| 函式 | 原 closure 位置 | 抽至 | 行數 |
|---|---|---|---|
| `cond_badge(ok, label)` | tab_macro.render_tab_macro:3392-3394 | `ui_widgets.py`（既有 9 函式集合 + 1） | 3 |

**設計理念**：
- 命名去 underscore prefix（`_cond_badge` → `cond_badge`）成 public API，與 `ui_widgets` 其他 9 個函式（`explain_box` / `traffic_light` / `kpi` / `signal_box` ...）並列。
- 配色語意：`True` → `#3fb950` 綠（達成）；`False` → `#484f58` 灰（未達成）。利用 `f'{c}22'` 的 hex `+22` alpha 製造背景淡色 + 邊框 / 文字深色的對比。
- 真值判斷：直接用 Python `if ok else`，0 / None / '' 自動視為 False（與呼叫端 `_ring1_pass`、`_cA`-`_cG` 等 boolean / int / None 變數混用相容）。
- 首次為 `ui_widgets.py` 建立 `tests/test_ui_widgets.py`（之前 9 函式無對應測試），開啟未來逐個補測試的入口。

**callsite 衝擊**：
- `tab_macro.py` 刪 3 行 closure + import 補 `cond_badge` + 7 callsite 重接（A VIX / B 期貨 / C 出口 / D M1B-M2 / E 外資 / F 股匯雙漲 / G SOX/NVDA 點火）

**驗證**：
- ✅ py_compile + ruff (`All checks passed!`)
- ✅ pytest 全套 **574/574 全綠**（原 566 + 新增 8）
- ✅ tests/test_ui_widgets.py：TestCondBadge 8 cases
- 涵蓋：truthy 綠色 / falsy 灰色 / label 嵌入 / HTML 結構（span + border-radius + font-size）/ `0` / `None` / `''` 邊界 / 空 label

#### `ui_widgets.py` 既有 9 函式 + 1 常數補完單測（P2-B Phase 7G）

**動機**：PR #60 從 `app.py` 抽出 `ui_widgets.py` 時未附對應單測，Phase 7F 雖建立 `tests/test_ui_widgets.py` 但僅涵蓋新增的 `cond_badge`，留下 9 函式 + 1 常數無單測。7G 補完此技術債，零生產碼變動。

**測試明細**：

| 測試類別 | 涵蓋函式/常數 | cases | 重點邊界 |
|---|---|---|---|
| `TestTermExplain` | `TERM_EXPLAIN` 常數 | 3 | 13 個術語 keys / 每 entry 為 2-tuple / 字串非空 |
| `TestExplainBox` | `explain_box` | 5 | detail 有/無 → `<br>` 條件渲染 |
| `TestTrafficLight` | `traffic_light` | 7 | good>bad 優先序 / 預設與自訂 neutral_label / value 參數預留 |
| `TestBeginnerKpi` | `beginner_kpi` | 7 | tip 有/無 → `💡` 條件渲染 / 自訂 color |
| `TestShowTermHelp` | `show_term_help` | 5 | 已知 / 未知 / 空字串 / 中文 term / 復用 explain_box |
| `TestKpi` | `kpi` | 6 | sub / 自訂 color & border |
| `TestToStrategy` | `_to_strategy` + `_STRATEGY_MAP` | 6 | 策略 1/2/3 全 10 老師 + 未知 fallback `('策略', '👤')` |
| `TestTeacherBox` | `teacher_box` | 5 | logic 嵌入 / 已知 vs 未知 teacher |
| `TestTeacherConclusion` | `teacher_conclusion` | 10 | 台股紅綠慣例（正面 → `#da3633` 紅、負面 → `#2ea043` 綠）+ 手動 color 覆寫 + action 關鍵字觸發 |
| `TestSignalBox` | `signal_box` | 9 | green/red/yellow/blue 4 keys + 未知 color fallback |

**驗證**：
- ✅ ruff (`All checks passed!`) — 純測試碼，無 py_compile 變動
- ✅ pytest 全套 **637/637 全綠**（原 574 + 新增 63）
- ✅ 7F 8 cases + 7G 63 cases = 71 cases 全綠（ui_widgets.py 模組 100% 函式 coverage）
- 涵蓋：所有預設參數路徑 / 條件渲染分支（detail/tip/desc 有無）/ 配色 fallback / 未知 key fallback / 11 個關鍵字觸發 teacher_conclusion 自動配色

#### `tech_indicators.py` + `scoring_helpers.py` 9 純函式補完單測（P2-B Phase 7H）

**動機**：PR #58（`tech_indicators.py` 6 純函式）和 PR #61（`scoring_helpers.py` 3 純函式）抽出時皆未附對應單測，留下技術債。Phase 7H 補完此缺口，零生產碼變動，跨 tab 共用層 + 技術指標層 + 評分引擎層全部達 100% 函式 coverage。

**測試明細**：

| 測試檔 | 測試類別 | 涵蓋函式 | cases | 重點邊界 |
|---|---|---|---|---|
| `test_tech_indicators.py` | `TestCalcRsi` | `calc_rsi` | 7 | None / 不足 rows / 全漲全跌極端值 / 四捨五入 / 缺欄位 |
| ↑ | `TestCalcIbs` | `calc_ibs` | 8 | high==low 防呆 0.5 / 取最後一列 / 四捨五入 3 位 |
| ↑ | `TestCalcVolumeRatio` | `calc_volume_ratio` | 6 | avg_vol=0 防呆 / 排除今日 / custom period |
| ↑ | `TestCalcKd` | `calc_kd` | 8 | 回傳 tuple / k,d ∈ [0,100] / 全漲 k>80 |
| ↑ | `TestCalcBollinger` | `calc_bollinger` | 7 | 7 keys 結構 / lower≤ma≤upper / 常數價 std=0 → bw=0 |
| ↑ | `TestCalcVcp` | `calc_vcp` | 5+1 | 需≥30 rows / 平坦無 swing → None / n_swings 過大 → None |
| `test_scoring_helpers.py` | `TestCalcFundamentalScore` | `calc_fundamental_score` | 16 | 4 維度 dict 結構 / list 視為 None / 357 估值 4 段 / 殖利率穩定性 |
| ↑ | `TestCalcHealthScore` | `calc_health_score` | 19 | 5 種趨勢分支 / 5 段 RSI 評分 / 5 段量比 / 4 種 KD 排列 / 4 種布林位置 |
| ↑ | `TestHealthGrade` | `health_grade` | 11 (含 7 parametrize) | 80/50 二級閥值 / 完整 threshold 表 |

**驗證**：
- ✅ ruff (`All checks passed!`) — 純測試碼，無生產碼變動
- ✅ pytest 全套 **734/734 全綠**（原 637 + 新增 97：tech 47 + scoring 50）
- 涵蓋：所有 None / 空資料 / 不足資料的 fallback；所有評分閾值；所有回傳結構完整性

**累積成果**：跨 tab 共用層（`tab_helpers` / `macro_helpers` / `etf_helpers` / `ui_widgets`）+ 技術指標層（`tech_indicators`）+ 評分引擎層（`scoring_helpers`）共 **6 個 helper 模組 100% 函式 coverage**，總計 **300+ unit test 全綠**。

#### `app.py` 結構演進（PR #66/#68/#70-#73 — P2-B Phase 4+5 全收官 ✅✅）

**最終戰績**：app.py 9622 → **1378 行（−85.7%）**，4 個 TAB 全部抽到獨立 `.py` 模組。

| 模組 | 行數 | 角色 | PR |
|---|---|---|---|
| `tab_macro.py` | 4031 | 總經紅綠燈 + 多指標儀表板（44 依賴 late import） | #73 |
| `tab_stock.py` | 2456 | 個股深度分析 + 健康度評分（41 依賴 late import） | #72 |
| `tab_stock_grp.py` | 1073 | 比較 × 排行 / 多股批次分析（27 依賴 late import） | #71 |
| `tab_edu.py` | 401 | 教學說明書 / 指標解讀手冊（1 依賴） | #70 |

**Phase 5 依賴策略**：
- **Top-level**：僅 `import streamlit as st`
- **函式內 late import**：所有其他依賴（stdlib / 外部模組 / app.py 內部 helper）
- **循環 import 風險**：tab_xxx.py 與 app.py 互相 import；由 late import inside function 完美解決（呼叫時 app 模組已完整載入）

**app.py 內部 helper 跨檔使用統計（從各 tab_*.py late import）**：

| Helper | tab_macro | tab_stock | tab_stock_grp | tab_edu |
|---|---|---|---|---|
| `gemini_call` | ✅ | ✅ | ✅ | — |
| `_fetch_stock_news` | — | ✅ | ✅ | — |
| `_fetch_macro_news` | ✅ | — | — | — |
| `fetch_*` 系列 (price/dividend/financials/quarterly/revenue) | — | ✅ | ✅ | — |
| `_get_loader` / `_load_cache` / `_save_cache` | — | — | ✅ | — |
| `_bps` / `_tw_now_str` / `_get_fm_token` | ✅ | — | — | — |
| `generate_ai_comment` / `render_health_score` | — | ✅ | — | — |
| `parse_stocks` | — | — | ✅ | — |
| `api_key` | — | ✅ | — | — |

**`with tab_xxx:` dispatch 模式**：

```python
# app.py（極簡呼叫端）
from tab_macro import render_tab_macro
from tab_stock import render_tab_stock
from tab_stock_grp import render_stock_grp
from tab_edu import render_tab_edu

with tab_macro:
    render_tab_macro()
with tab_stock:
    render_tab_stock()
with tab_stock_grp:
    render_stock_grp()
with tab_edu:
    render_tab_edu()
```

**前置審計**：`PHASE4_AUDIT.md`（141 行）— AST-based cross-TAB leak scan，0 真實洩漏，動工綠燈。

**已清除死碼總計**：
- P4: `cx4` (tab_stock_grp) + redundant `from scoring_engine import calc_rs_score, rs_slope` (tab_stock)
- P5-C: ruff 自動清掉 21 個 F401 (chart_plotter / tech_indicators / scoring_helpers / scoring_engine / ui_widgets 等)
- P5-D: ruff 自動清掉 33 個 F401 (macro_state_locker / v4_strategy_engine / daily_checklist / macro_alert / market_strategy / leading_indicators / ui_widgets 等)

#### `app.py` Phase 4 wrap def 紀錄（已並入 Phase 5，僅供歷史參考）

**動機**：將 module-level `with tab_xxx:` 巨型區塊包成 `render_<tab>()` 純函式，達成：
1. **scope 隔離**：消除跨 TAB 變數隱性洩漏風險
2. **暴露 ruff F841**：module-level 不檢查 unused locals，wrap 後可清出歷次 refactor 殘留
3. **未來抽檔橋樑**：下一階段（Phase 5）可逐 TAB 抽到獨立 `tab_xxx.py`

**已 wrap 函式（4/4 ✅）**：

| 函式 | 對應 TAB | 行數 | PR |
|---|---|---|---|
| `render_tab_macro()` | 總經紅綠燈 | 3970 | #68 |
| `render_tab_stock()` | 個股深度分析 | 2402 | #66 |
| `render_stock_grp()` | 比較 × 排行 | 1031 | #66 |
| `render_tab_edu()` | 教學說明書 | 387 | #66 |

合計 **7790 行** module-level Streamlit code 全部變成 dispatch 模式。

**呼叫端模式**：
```python
with tab_macro:
    render_tab_macro()
with tab_stock:
    render_tab_stock()
with tab_stock_grp:
    render_stock_grp()
with tab_edu:
    render_tab_edu()
```

**前置審計**：`PHASE4_AUDIT.md`（141 行）— AST-based cross-TAB leak scan，補抓 4 種 Store 場景（except/import/def args/class），嚴格規則 0 真實洩漏，動工綠燈。

**已暴露死碼清除**：
- `cx4 = _d4.get('cx')` (tab_stock_grp 內，PR #66)
- redundant `from scoring_engine import calc_rs_score, rs_slope` (tab_stock 內，PR #66)
- tab_macro / tab_edu 內部已乾淨，無新死碼暴露

**Phase 5 候選**：逐函式抽到獨立檔案（如 `tab_macro.py`），預估 app.py 可瘦身至 ~1500 行。

---

#### `scoring_engine.py`

---

**`score_single_stock(df, stock_id, stock_name, **kwargs)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `df: DataFrame` — 個股 OHLCV；`stock_id / stock_name: str`；`kwargs`：`foreign_buy / trust_buy / dealer_buy: int`、`revenue_df / quarterly_df: DataFrame` |
| 輸出 | `dict` — 完整評分結果（見下表） |
| 副作用 | 無（純函式） |

輸出 dict 結構：

| 鍵 | 型別 | 說明 |
|----|------|------|
| `total` | `float` | 綜合總分 0–100 |
| `trend` | `float` | 趨勢分 0–100 |
| `momentum` | `float` | 動能分 0–100 |
| `chip` | `float` | 籌碼分 0–100 |
| `volume` | `float` | 量價分 0–100 |
| `risk` | `float` | 風險分 0–100（分越高風險越低） |
| `fundamental` | `float` | 基本面分 0–100 |
| `grade` | `str` | 評級 `'A+'/'A'/'B'/'C'/'D'` |
| `momentum_signal` | `bool` | VCP 突破訊號 |
| `vcp` | `dict` | VCP 詳細結果（見 `check_vcp_atr_filter`） |

---

**`calc_trend_score(df)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `df: DataFrame` — 需含 `Close / High / Low`（≥120 筆） |
| 輸出 | `float` — 趨勢分 0–100 |
| 邏輯摘要 | MA5>MA20>MA60>MA120 完整多頭排列=100；每跌破一條均線扣分；價格在年線上方加分 |

---

**`check_vcp_atr_filter(df)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `df: DataFrame` — 需含 `High / Low / Close / Volume`（≥60 筆） |
| 輸出 | `dict` — `{ 'signal': bool, 'stage': int, 'contraction': float, 'volume_dry': bool, 'breakout': bool, 'message': str }` |
| 說明 | `stage`：收縮次數（0–3）；`contraction`：最新波幅（越小越好）；`volume_dry`：成交量是否低於 50 日均量 50% |

---

**`calc_atr_stop(df, entry_price, multiplier)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `df: DataFrame`；`entry_price: float`；`multiplier: float`（預設 `config.ATR_MULTIPLIER=1.5`） |
| 輸出 | `dict` — `{ 'stop_price': float, 'atr': float, 'distance_pct': float }` |
| 說明 | `stop_price = entry_price - ATR × multiplier`；`distance_pct`：停損距離佔進場價百分比 |

---

#### `v4_strategy_engine.py`

---

**`V4StrategyEngine.check_macro_veto()`**

| 項目 | 說明 |
|------|------|
| 輸入 | 無（使用 `self.df_macro`：需含 `vix / futures_net / pcr`） |
| 輸出 | `dict` — `{ 'light': 'red'|'yellow'|'green', 'max_position': float, 'reason': str }` |
| 燈號邏輯 | 🔴 red（VIX>25 或外資期貨空單>20,000口）→ max_position ≤ 20%；🟡 yellow（VIX>20 或>10,000口）→ ≤ 50%；🟢 green → ≤ 100% |

---

**`V4StrategyEngine.calc_relative_chips(days)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `days: int` — 計算週期（預設 60） |
| 輸出 | `dict` — `{ 'foreign_ratio': float, 'trust_ratio': float, 'foreign_trend': str, 'trust_trend': str }` |
| 說明 | `foreign_ratio` = 外資近 N 日累積買超 ÷ 發行股數（%）；`trend`：`'accumulate'/'distribute'/'neutral'` |

---

#### `v5_modules.py`

---

**`calc_relative_strength(df_stock, df_market, periods)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `df_stock / df_market: DataFrame`（需含 `Close`）；`periods: list[int]`（預設 `[20, 60, 120]`） |
| 輸出 | `dict` — `{ 'rs_20': float, 'rs_60': float, 'rs_120': float, 'z_score': float, 'label': str }` |
| 說明 | `rs_N = 個股 N 日報酬 - 大盤 N 日報酬`；`z_score`：三週期 RS 的標準化分數；`label`：`'強勢'/'中性'/'弱勢'` |

---

**`calc_valuation_zone(price, eps_ttm, bvps, pb_target)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `price: float`；`eps_ttm: float`（近 12 月 EPS）；`bvps: float`（每股淨值）；`pb_target: float`（目標 P/B，預設 1.5） |
| 輸出 | `dict` — `{ 'pe': float, 'pb': float, 'zone': 'cheap'|'fair'|'rich', 'target_price': float }` |
| 說明 | `zone` 判斷：P/E<15 且 P/B<1 → cheap；P/E>25 或 P/B>2 → rich；其餘 → fair |

---

**`analyze_fundamental_leading(cl_now, cl_prev, capex_now, capex_prev, equity)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `cl_now / cl_prev: float` — 本季/上季合約負債；`capex_now / capex_prev: float` — 本季/上季資本支出；`equity: float` — 實收資本額 |
| 輸出 | `dict` — `{ 'cl_qoq': float, 'capex_ratio': float, 'dragon_signal': bool, 'message': str }` |
| 說明 | `cl_qoq>20% 且 capex_ratio>0.8` → `dragon_signal=True`（龍多股訊號） |

---

### 4.3 L3 策略層

#### `market_strategy.py`

---

**`market_regime(index_close, ma60, ma120, foreign_buy, ad_ratio, ma60_prev, ma120_prev, vol_today, avg_vol_20)`**

| 項目 | 說明 |
|------|------|
| 輸入 | 全部為 `float`；`foreign_buy`：外資現貨淨買超（億元，正買負賣）；`ad_ratio`：ADL 廣度（0–100%） |
| 輸出 | `dict`（mkt_info） — 見下表 |
| 副作用 | 無（純函式）；呼叫方負責寫入 `session_state['mkt_info']` |

輸出 dict 完整欄位：

| 鍵 | 型別 | 說明 |
|----|------|------|
| `regime` | `str` | `'bull' / 'neutral' / 'caution' / 'bear'` |
| `score` | `int` | 0–5（五個維度各 1 分） |
| `max_score` | `int` | 固定為 `5` |
| `label` | `str` | UI 顯示標籤（含 emoji） |
| `color` | `str` | 十六進位色碼 |
| `exposure_pct` | `str` | 建議持股比例（如 `'80%'`） |
| `signals` | `list[str]` | 觸發的加分條件文字清單 |
| `bullrun` | `bool` | 是否進入強多頭（score=5） |
| `index_price` | `float` | 傳入的大盤指數 |
| `ma60 / ma120` | `float` | 傳入的均線值 |

---

**`portfolio_exposure(regime)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `regime: str` — `'bull' / 'neutral' / 'caution' / 'bear'` |
| 輸出 | `float` — 建議股票曝險比例（`0.80 / 0.50 / 0.30 / 0.20`） |
| 副作用 | 無 |

---

#### `risk_control.py`

---

**`RiskController.position_size(price, weight)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `price: float`（股價）；`weight: float`（目標佔衛星資金比例，0–1） |
| 輸出 | `dict` — `{ 'shares': int, 'lots': int, 'cost': float, 'pct_of_portfolio': float }` |
| 限制 | 單檔不超過 `config.MAX_POSITION_PER_STOCK`（10%）；受 `RiskController.max_stock_budget` 上限約束 |

---

**`RiskController.check_exit(stock_id, buy_price, current_price)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `stock_id: str`；`buy_price / current_price: float` |
| 輸出 | `dict` — `{ 'action': 'stop_loss'|'trailing'|'hold', 'reason': str, 'pnl_pct': float }` |
| 邏輯 | 優先檢查固定停損（-8%）→ 再檢查追蹤停利（峰值回落 7%，且已獲利 3%）→ 否則 hold |

---

**`trailing_stop_trigger(buy_price, peak_price, current_price, trail_pct, min_profit_pct)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `buy_price / peak_price / current_price: float`；`trail_pct: float`（預設 `0.07`）；`min_profit_pct: float`（預設 `0.03`） |
| 輸出 | `bool` — `True` 表示觸發追蹤停利，應賣出 |
| 條件 | `current_price ≤ peak_price × (1 - trail_pct)` 且 `peak_price ≥ buy_price × (1 + min_profit_pct)` |

---

### 4.4 L5 AI 層

#### `unified_decision.py`

---

**`render_unified_decision(gemini_fn, context)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `gemini_fn: Callable[[str, int], str]` — Gemini API 回呼函式；`context: dict` — 見下表 |
| 輸出 | `None`（直接渲染至 Streamlit） |
| 副作用 | 寫入 `session_state[f'unified_{type}_{id}']`；呼叫 `st.rerun()` 觸發畫面更新 |

`context` dict 格式：

| 鍵 | 型別 | 說明 |
|----|------|------|
| `type` | `str` | `'stock' / 'etf' / 'portfolio'` |
| `id` | `str` | 唯一識別字（如 `'2330'` / `'0050'` / `'portfolio'`） |
| `data` | `dict` | 傳給 LLM 的結構化數據（自由欄位，依 type 不同而異） |

---

**`_build_prompt(context)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `context: dict`（同上） |
| 輸出 | `str` — 完整 Prompt 字串（`_BASE_RULES` + 型別路由邏輯 + JSON 化 data） |
| 路由 | `type='stock'` → `_STOCK_LOGIC`；`type='etf'` → `_ETF_LOGIC`；`type='portfolio'` → `_PORTFOLIO_LOGIC` |

---

**`_render_cards(parsed, ctx_type)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `parsed: dict` — Gemini 回傳的 JSON（需含 `summary / action_advice / precautions`）；`ctx_type: str` |
| 輸出 | `None`（渲染 3 張卡片至 Streamlit） |
| Card 1 | 全寬主卡：`summary`（依 🟢/🟡/🔴 自動變色） |
| Card 2 | 左欄：`action_advice`（股票模式標籤：②進場③停損；其他模式：具體建議） |
| Card 3 | 右欄：`precautions`（股票模式標籤：④風控；其他模式：風險警示） |

---

#### `ai_engine.py`

---

**`analyze_stock_trend(api_key, stock_id, stock_name, df, fundamental_summary)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `api_key: str`；`stock_id / stock_name: str`；`df: DataFrame`（OHLCV）；`fundamental_summary: str`（選填） |
| 輸出 | `str` — Gemini 生成的趨勢分析文字（Markdown 格式） |
| 副作用 | 無；API 失敗時回傳 `'⚠️ ...'` 開頭的錯誤訊息 |
| Fallback | `gemini-2.5-flash-lite` → `gemini-2.5-flash` → `gemini-2.0-flash` → `gemini-2.0-flash-lite` |

---

**`generate_daily_report(api_key, market_info, top_stocks, risk_alerts)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `api_key: str`；`market_info: dict`（regime/score）；`top_stocks: list[dict]`；`risk_alerts: list[str]` |
| 輸出 | `str` — 每日市場摘要（300 字內，含多空評估與今日重點） |
| 副作用 | 無 |

---

### 4.5 app.py 核心協調函式

---

**`_calc_traffic_light(mkt_info, jingqi_info, cl_data, li_latest)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `mkt_info: dict`（`market_regime()` 輸出）；`jingqi_info: dict`（旌旗均值）；`cl_data: dict`（每日總覽）；`li_latest: DataFrame \| None` |
| 輸出 | `dict \| None` — `None` 表示資料不足；否則見下表 |
| 保守優先 | `_defense=True` 或 `_health<40` → 強制紅燈（覆蓋 regime） |

輸出 dict 欄位：

| 鍵 | 型別 | 說明 |
|----|------|------|
| `regime` | `str` | 來自 `mkt_info`（bull/neutral/caution/bear） |
| `icon / color / label` | `str` | 顯示用（🔴/🟡/🟢 + 十六進位色 + 操作標籤） |
| `action / sub` | `str` | 主要操作建議與補充說明 |
| `health` | `float` | 綜合健康度 0–100（`jqavg×0.4 + score_norm×0.4 + fnet_bonus×0.2`） |
| `defense` | `bool` | Defense Mode 是否觸發 |
| `conf` | `int` | 資料信心指數 0–100%（5 個資料源各 20%） |

---

**`_render_traffic_light(placeholder, tl, mkt_info)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `placeholder: st.empty`；`tl: dict \| None`；`mkt_info: dict \| None`（選填，用於顯示評分/信號） |
| 輸出 | `None`（渲染至 placeholder） |
| 副作用 | 渲染：主燈號卡（含信號 badges + 指數 + 持股建議）→ Defense Mode 警告 → 核心/衛星資金看板 → 進度條 |
| 合併邏輯 | `mkt_info` 提供的原始 regime 資訊整合顯示，以 `tl` 的保守信號為主 |

---

**`gemini_call(prompt, max_tokens)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `prompt: str`；`max_tokens: int`（預設 800） |
| 輸出 | `str` — Gemini 回傳文字；失敗時回傳 `'⚠️ ...'` |
| Fallback 順序 | `gemini-2.5-flash-lite` → `gemini-2.5-flash` → `gemini-2.0-flash` → `gemini-2.0-flash-lite` |
| 副作用 | 失敗時 `print('[AI-LLM/Gemini] ❌ ...')` 寫入 Cloud log |

---

**`_reg_add(_rname, _rdf, category, frequency)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `_rname: str` — registry 鍵名（如 `'[先行指標] PCR'`）；`_rdf: DataFrame` — 資料本體（僅讀取最新時間戳，不儲存）；`category: str` — 類別標籤（如 `'大盤'` / `'個股'` / `'ETF'`，可任意擴充）；`frequency: str` — 更新頻率（`'daily'` / `'monthly'` / `'quarterly'`） |
| 輸出 | `None` |
| 副作用 | 寫入 `st.session_state['data_registry'][_rname]`，格式：`{ 'last_updated': str, 'rows': int, 'category': str, 'frequency': str }` |
| 時間戳邏輯 | 優先搜尋 `_date` 欄（`YYYYMMDD` 格式）→ DatetimeIndex → 其他 date 型欄位；解析失敗時 `last_updated='N/A'` |

---

**`_reg_missing(_rname, category, frequency)`**

| 項目 | 說明 |
|------|------|
| 輸入 | `_rname: str`；`category: str`；`frequency: str` |
| 輸出 | `None` |
| 副作用 | 寫入 `st.session_state['data_registry'][_rname]`，格式：`{ 'last_updated': 'N/A', 'rows': 0, 'category': str, 'frequency': str, 'missing': True }` |
| 用途 | API 未回傳資料時呼叫，確保診斷面板始終顯示 ⚫ 缺失而非隱藏項目 |

---

### 4.6 etf_dashboard.py 診斷核心

---

**`render_data_health()`** — ⚠️ **已於 PR #52 刪除（dead code，1019 行）**

> 此函式為被取代的舊版健診儀表板，整個 codebase 無任何 caller。實際使用的是
> `health_inspector.render_data_health_raw()`（PR #52 抽出至獨立模組）。
> 對應的 `_check_icon` / `_check_etf_health` / `_HEALTH_CHECKS` /
> `_HEALTH_ETF_TW` / `_HEALTH_ETF_US` 連帶刪除。

---

**`render_data_health_raw()`**（資料健診儀表板 — Raw Data 嚴格版）

| 項目 | 說明 |
|------|------|
| 位置 | `health_inspector.py`（PR #52 抽出，前身為 `etf_dashboard.py:4137`）|
| 輸入 | 無（從 `st.session_state` 與各模組已抓的資料中組裝）|
| 輸出 | `None`（全部渲染至 Streamlit UI） |
| 原則 | 只顯示「從網路 API 直接抓取的第一手原始資料」；嚴禁均線 / RSI / 乖離率 / AI 評分等任何計算值 |
| 欄位 | `資料名稱 / 最後更新 / 狀態燈號（🟢🟡🔴⚪🔵）`|
| 呼叫端 | `app.py:9055 render_data_health_raw()` |
| **PMI 診斷** | 當「🇹🇼 台灣製造業 PMI」進入「資料異常清單」時，自動於下方加 `🔬 8 段備援源詳細診斷` expander；按鈕觸發 `macro_core.diagnose_tw_pmi_sources()` 逐源探測，輸出 {method, status (✅/⚠️/❌/⚪), detail, url} 表格（PR #53）。此外 `fetch_tw_pmi` 本身 8 段備援於 commit `8d3fb71` 補完每段 `errs` 追蹤（無回應 / HTTP 非 200），讓 `_err_pmi` 完整呈現所有源根因 |
| **私募 ETF 判別** | `etf_tab_single._likely_private` 啟發式：台股 ETF 但 AUM + 費用率 + NAV 三主流源皆空 → 視為私募/特殊 ETF；health_inspector 將三列同步標記 `probe_status='na'`，訊息「私募/特殊 ETF — AUM、費用率、NAV 主流資料源皆未揭露」（commit `c3250d7`）|
| **批次分析空 K 線** | `tab_stock_grp._fetch_single_t3` 當 yfinance + FinMind 雙源皆空時，於 result 帶入 `error` 訊息（供 `_fetch_err` → `error_msg` 顯示），且**跳過 4hr 快取**避免短期持續空轉（commit `26da8fb`）|

---

**`diagnose_tw_pmi_sources()`**（PMI 8 段備援源診斷工具 — PR #53）

| 項目 | 說明 |
|------|------|
| 位置 | `macro_core.py`（緊接 `fetch_tw_pmi` 之後）|
| 用途 | 當 `fetch_tw_pmi` 全失敗時，**純讀**探測 8 段備援源 HTTP / proxy / JSON shape，定位是哪段真死、哪段被 proxy 截掉、哪段網站改版（regex 過時）|
| 輸入 | 無 |
| 輸出 | `list[dict]` — 每筆 `{method, status, detail, url}` |
| 狀態語意 | `✅` 端點 OK 且關鍵欄位存在 ｜ `⚠️` HTTP 200 但內容形狀變了 ｜ `❌` HTTP 非 200 / fetch_url 回 None / 例外 ｜ `⚪` 跳過（無 token 等） |

---

### 4.7 雲端儲存（Cloud Storage — Google Sheet 持股組合）

對應 PR #5（初版 SA-only，commit `48de077`）+ commit `0c6e0b9`（OAuth 移植自基金 dashboard）。
契約見 SPEC.md §8；Secrets 對照見 §2.4。

```
┌─────────────────────────────────────────────────────────┐
│ etf_tab_portfolio._render_cloud_storage  ← UI 層         │
│    └─ _render_oauth_panel (OAuth wizard + Sheet ID 輸入) │
└────────────────────┬────────────────────────────────────┘
                     │ is_configured / load / save / delete
                     ▼
┌─────────────────────────────────────────────────────────┐
│ gsheet_portfolio                          ← 純函式 API   │
│   _oauth_active / _sa_configured / _get_active_sheet_id │
│   _build_client（OAuth 優先 → SA fallback）             │
│   list_portfolios / load / save / delete                │
└─────────┬──────────────────────────────┬───────────────┘
          │ OAuth                        │ SA fallback
          ▼                              ▼
┌──────────────────────┐    ┌────────────────────────────┐
│ oauth_state          │    │ google.oauth2.service_     │
│  _resolve_oauth_cfg  │    │ account.Credentials         │
│  _get_oauth_client   │    │ （st.secrets['gcp_service_ │
│  handle_oauth_       │    │  account']）               │
│  callback            │    └────────────────────────────┘
└─────────┬────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│ infra/oauth (純 HTTP，零 streamlit 依賴)                 │
│   build_authorize_url / exchange_code_for_tokens        │
│   refresh_access_token / build_credentials_from_tokens  │
│   is_token_expired / ensure_fresh_tokens / OAuthError   │
└─────────────────────────────────────────────────────────┘
```

**`gsheet_portfolio.py`** — 雙模式持股組合儲存

| 項目 | 說明 |
|------|------|
| Schema | 單一 worksheet `portfolios`：`name | ticker | lots | avg_price | updated_at` |
| 多組命名 | 同 worksheet 多列共用，以 `name` 欄分組 |
| `is_configured()` | `_oauth_active() or _sa_configured()`；任一條件即可（contract 跨兩模式不變）|
| `_oauth_active()` | OAuth Client 已設 + `session_state['gsheet_tokens']` 存在 + 有 sheet id |
| `_sa_configured()` | `st.secrets['portfolio_sheet_id']` + `[gcp_service_account]` 皆有 |
| `_get_active_sheet_id()` | 優先 `session_state['portfolio_sheet_id']`（OAuth 模式使用者輸入）→ 退 `st.secrets['portfolio_sheet_id']` |
| `_build_client()` | OAuth → `oauth_state._get_oauth_client()`；否則 SA Credentials.from_service_account_info |
| `_ws()` | 每次重新建立（OAuth token 可能 refresh，**不可** `st.cache_resource` 化）|
| 寫入策略 | `save_portfolio` 先取 `get_all_values` → 過濾舊 name 列 → `clear` + `append_row(HEADERS)` + `append_rows(keep + new)` |

**`oauth_state.py`** — OAuth 設定解析 + gspread client + callback handler

| 函式 | 說明 |
|------|------|
| `_resolve_oauth_cfg()` | 優先 `st.secrets['google_oauth']`；缺則 `st.session_state['custom_oauth_cfg']`（in-app wizard）|
| `_get_oauth_client()` | 從 `session_state['gsheet_tokens']` 建 gspread client，順便 `ensure_fresh_tokens` refresh |
| `handle_oauth_callback()` | URL `?code=...` → `exchange_code_for_tokens` → 寫 `session_state['gsheet_tokens']` → `query_params.clear()` + `st.rerun()`；`app.py` 在 `set_page_config` 後立即呼叫一次 |

**`infra/oauth.py`** — 純 HTTP OAuth 2.0 flow（零 streamlit 依賴，移植自基金 dashboard，202 行）

| 函式 | 說明 |
|------|------|
| `build_authorize_url(client_id, redirect_uri, state=None)` | Google OAuth consent URL（scopes：spreadsheets + drive + userinfo.email）|
| `exchange_code_for_tokens(code, client_id, client_secret, redirect_uri)` | `code` → `{access_token, refresh_token, expires_at, ...}` dict |
| `refresh_access_token(refresh_token, client_id, client_secret)` | 用 refresh token 換新 access token |
| `build_credentials_from_tokens(tokens, client_id, client_secret)` | dict → `google.oauth2.credentials.Credentials` |
| `is_token_expired(tokens, leeway=60)` / `ensure_fresh_tokens(...)` | 過期前 60 秒自動 refresh |
| `OAuthError` | 統一例外類別（HTTP 非 200 / JSON 缺欄）|

**Sidebar Google 帳號區（app.py）**：已登入顯示 `🟢 已登入 + 🚪 登出`；OAuth Client 已設未登入顯示 `🔐 用 Google 登入` link_button；SA 模式顯示 `ℹ️ 使用 Service Account`；未設定顯示 `⚙️ OAuth 尚未設定 — 至「ETF 組合」Tab 展開「💾 雲端儲存」設定`。
| 探測源 | ① data.gov.tw ② NDC ③ MacroMicro ④ CIER cid=21 ⑤ StockFeel ⑥ 鉅亨網 ⑦ FinMind（需 token）⑧ MoneyDJ |
| 設計原則 | **不改 `fetch_tw_pmi`**（零 regression）；**lazy 載入**（只在使用者點按鈕才探測）；timeout=8s × 8 段 worst case ≤ 1 分鐘 |
| 呼叫端 | `health_inspector.py` 異常清單 expander 內按鈕觸發 |

---
