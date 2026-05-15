# 專案戰情室 (Project State)

## 📌 當前狀態
- **專案**: 台股 AI 戰情室 — Streamlit Cloud 多 Tab 投資儀表板（市場 / 個股 / 組合 / 總經 / ETF）
- **Stack**: Python · Streamlit · FinMind · yfinance · Gemini AI · NAS Squid Proxy
- **入口**: `app.py`
- **Secrets**: `FINMIND_TOKEN` · `GEMINI_API_KEY` · `PROXY_URL` · `FRED_API_KEY`

## 🏗️ 主要模組
| 層 | 檔案 |
|---|---|
| **UI** | `app.py`（主入口，PR #73 後 **1378 行**，−85%，4/4 TAB 已抽至獨立模組）· `tab_macro.py` (4031) · `tab_stock.py` (2456) · `tab_stock_grp.py` (1073) · `tab_edu.py` (401) · `etf_dashboard.py`（PR #78 後 **1667 行**，−47%，4/4 ETF render 已抽出）· `etf_tab_single.py` (616) · `etf_tab_portfolio.py` (531) · `etf_tab_backtest.py` (284) · `etf_tab_ai.py` (169) · `ui_widgets.py`（PR #60 抽出 8 個純 HTML 函式） |
| **資料抓取** | `data_loader.py` · `macro_core.py`（含 PR #53 `diagnose_tw_pmi_sources`）· `tw_macro.py` · `daily_checklist.py` · `leading_indicators.py` · `tw_stock_data_fetcher.py` |
| **資料註冊** | `data_registry.py` · `data_config.py` · `config.py` |
| **引擎** | `scoring_engine.py` · `scoring_helpers.py`（PR #61 抽 3 純函式：fundamental_score / health_score / health_grade）· `financial_health_engine.py` · `market_strategy.py` · `risk_control.py` · `backtest_engine.py` · `unified_decision.py` · `v4_strategy_engine.py` · `v5_modules.py` · `yield_screener.py` |
| **技術指標** | `tech_indicators.py`（PR #58 從 app.py 抽出 6 個純函式：RSI/IBS/VR/KD/BB/VCP，零 Streamlit 依賴）|
| **ETF 工具鏈** | `etf_categories.py`（同儕分類）· `merrill_clock.py`（景氣循環）· `grape_ladder.py`（月配組合最佳化）· `etf_quality.py`（4 因子品質評等） |
| **健診** | `health_inspector.py`（Raw Data 資料健診儀表板，PR #52 從 etf_dashboard 抽出）|
| **AI / 警示** | `ai_engine.py` · `macro_alert.py` · `macro_state_locker.py` · `persona.py` |
| **基建** | `proxy_helper.py`（NAS proxy + Storm Shield 快取）· `nas_server.py`（FastAPI 中繼）· `chart_plotter.py` · `portfolio_manager.py` · `stock_names.py` |

## 📂 周邊
- `.streamlit/config.toml` · `requirements.txt`
- 設計文件：`ARCHITECTURE.md` · `DATASTATION.md` · `STRATEGY_MANUAL.md`
- 測試：`test_*.py`

## 🚀 最近完工（PR #42-#82，2026-05）
| PR | 任務 | SHA |
|---|---|---|
| #42 | ETF 折溢價 G1+G2 守門員（NAV-Price gap + 主動式 ETF 異常閾值） | c21e577 |
| #43 | ETF 折溢價 G3 守門員 + data_date 透明化 | a5ff133 |
| #44 | ETF 費用率加 MoneyDJ 第 3 源 + PMI 標籤對齊 8 段 | dfbff76 |
| #45 | ETF 同儕近 3M/6M/1Y 排名（總報酬率含息） | bb6337e |
| #46 | 美林時鐘景氣循環圖（PMI YoY × CPI YoY） | cdfd4a8 |
| #47 | 葡萄串領息法（高股息 ETF 月配組合最佳化） | 87edcd1 |
| #48 | ETF 自製品質評等（4 因子合成 1-5 顆星） | b848816 |
| #49 | STATE.md 治理同步 | 9041a95 |
| #50 | etf_quality.py 排毒重構（5 毒素清除） | 0cc5b81 |
| #51 | etf_dashboard.py fetch_etf_nav_history 排毒（8 毒素清除，ruff −27） | 2ffc6f6 |
| #52 | health_inspector.py 抽出 + 刪 render_data_health dead code (1019 行) | 11f165a |
| #53 | hotfix `_US_SECTORS` / `_TW_SECTORS` 還原 + PMI 8 段備援源診斷面板 | 9b9bec8 |
| #54 | docs 同步：STATE.md + ARCHITECTURE.md 收錄 PR #53 | 8e0c36e |
| #55 | fix(etf) 海外 ETF regex 漏字母後綴 → 誤判台灣主動式 ETF | acfb2b9 |
| #56 | app.py ruff 排毒 P2 第一波（F401 + F541 + E401 + F841，−69） | fd0607d |
| #57 | app.py ruff 排毒 P2 第二波（E701 + E702，−557，−91%） | 59d0b71 |
| #58 | app.py P2-B Phase 1：抽 tech_indicators.py（6 純函式，−111 行） | 620b5e0 |
| #59 | docs 同步 PR #54-#58 | 1684c3c |
| #60 | app.py P2-B Phase 2：抽 ui_widgets.py（8 純 HTML 函式，−109 行） | bd548d0 |
| #61 | app.py P2-B Phase 3：抽 scoring_helpers.py（3 純函式，−221 行） | f935b49 |
| #62 | docs 同步 PR #59-#61 | 2a0f433 |
| #63 | app.py ruff 排毒 P2 第三波（E722 + E741 + E731，−33） | 9320c52 |
| #64 | app.py ruff 排毒 P2 收尾（E402 + F821 noqa，21 → **0 errors** 🎯） | 8345b40 |
| #65 | docs 同步 PR #62-#64（ruff 0 errors 達成） | b9b7d0e |
| #66 | app.py P2-B Phase 4-A/B/C：wrap 3 個 TAB def + PHASE4_AUDIT.md | d1e9c5a |
| #67 | docs 同步 PR #65-#66 | dd8afd5 |
| #68 | app.py P2-B Phase 4-D：wrap tab_macro（4/4 全收官）🏆 | a6dea89 |
| #69 | docs 同步 PR #67-#68（Phase 4 全收官） | b4c7d92 |
| #70 | app.py P2-B Phase 5-A：抽 tab_edu.py（387 行） | dc62b90 |
| #71 | app.py P2-B Phase 5-B：抽 tab_stock_grp.py（1030 行，27 依賴） | d99c19e |
| #72 | app.py P2-B Phase 5-C：抽 tab_stock.py（2401 行，41 依賴，bonus 清 21 F401） | 877638c |
| #73 | app.py P2-B Phase 5-D：抽 tab_macro.py（3970 行，44 依賴，bonus 清 33 F401）🏆 收官 | eca00a0 |
| #74 | docs 同步 PR #69-#73（Phase 5 全收官） | 1c5d710 |
| #75 | etf_dashboard P2-B Phase 6-A：抽 etf_tab_single.py（569 行，22 依賴，bonus 清 36 風格債） | 169c776 |
| #76 | etf_dashboard P2-B Phase 6-B：抽 etf_tab_portfolio.py（496 行，14 依賴） | 3420ab6 |
| #77 | etf_dashboard P2-B Phase 6-C：抽 etf_tab_backtest.py（243 行，13 依賴，順手清 10 E701/E702） | 2533ff0 |
| #78 | etf_dashboard P2-B Phase 6-D：抽 etf_tab_ai.py（146 行，5 依賴）🏆 收官 | 8a089cb |
| #80 | fix(config): 新增 `FINMIND_TOKEN` 匯出 — 修復 tab_stock / tab_stock_grp 線上 ImportError | fc897fd |
| #82 | fix(app): `sys.modules['app']` 別名 — 修復線上 `StreamlitSetPageConfigMustBeFirstCommandError`（治 4 處 `from app import` re-execute） | 0b993b2 |
| #84 | fix(tab_stock): 殖利率河流圖三條 band 改用逐日 TTM（修水平直線 bug）+ 風控警示卡帶上 asset_type/sid/name 三件套 | 3068494 |

## 🎯 Backlog
- **環境工**：33 條 stale remote branches 清理（PR #42-#78 累積，sandbox token 無 delete 權）
- **部署驗證**：PR #42-#78 累積 Streamlit Cloud 上線驗收項目（重點：Phase 5 + Phase 6 共抽出 8 個 tab/render 模組，每個都需手動驗證 happy path）
- **PMI 真實異常**：PR #53 加好診斷工具，下次 PMI 紅燈時用 `🔬 8 段備援源詳細診斷` 按鈕定位根因（proxy 死 / regex 過時 / 端點改版）
- **P2-B Phase 5 ✅ 全收官（4/4 app.py TAB 抽至獨立 .py 模組）**：
  - ✅ P5-A `tab_edu.py` (387 行 / 1 依賴) — PR #70
  - ✅ P5-B `tab_stock_grp.py` (1030 行 / 27 依賴) — PR #71
  - ✅ P5-C `tab_stock.py` (2401 行 / 41 依賴) — PR #72
  - ✅ P5-D `tab_macro.py` (3970 行 / 44 依賴) — PR #73
- **P2-B Phase 6 ✅ 全收官（4/4 etf_dashboard render 抽至獨立 .py 模組）**：
  - ✅ P6-A `etf_tab_single.py` (569 行 / 22 依賴) — PR #75
  - ✅ P6-B `etf_tab_portfolio.py` (496 行 / 14 依賴) — PR #76
  - ✅ P6-C `etf_tab_backtest.py` (243 行 / 13 依賴) — PR #77
  - ✅ P6-D `etf_tab_ai.py` (146 行 / 5 依賴) — PR #78
- **技術債（已全面清乾淨）**：
  - 🎯 `app.py` ruff errors **681 → 0（100% clean）**（PR #56/#57/#60/#63/#64）
  - `app.py` 9622 → **1378 行**（**−8244，−85.7%**，PR #58/#60/#61 抽純函式 + #66/#68 wrap def + #70-#73 抽 4 TAB）
  - `etf_dashboard.py` 3122 → **1667 行**（**−1455，−46.6%**，PR #75-#78 抽 4 render + 順手清 55+ 個風格債）
  - **兩大入口檔合計** 12744 → **3045 行**（**−9699，−76%**）
- **Phase 7 候選**（可選）：
  - 各 tab_*.py / etf_tab_*.py 模組內部進一步抽純函式（如各 TAB 共用的 helper）
  - 補測試：`tests/test_tab_*.py` / `tests/test_etf_tab_*.py` 個別 mock 化測試
  - `etf_dashboard.py` 剩餘 1667 行內部 36 個 helper 函式進一步分檔（fetch/calc/render 分層）

## 🧱 開發協議
依 `CLAUDE.md` v2.0 核心協議運行（§1-§5 嚴格三步法 / 防幻覺 / 精準讀寫 / 鋼鐵自省 / 卡關救援）。

