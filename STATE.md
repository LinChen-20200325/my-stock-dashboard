# 專案戰情室 (Project State)

## 📌 當前狀態
- **專案**: 台股 AI 戰情室 — Streamlit Cloud 多 Tab 投資儀表板（市場 / 個股 / 組合 / 總經 / ETF）
- **Stack**: Python · Streamlit · FinMind · yfinance · Gemini AI · NAS Squid Proxy
- **入口**: `app.py`
- **Secrets**: `FINMIND_TOKEN` · `GEMINI_API_KEY` · `PROXY_URL` · `FRED_API_KEY`

## 🏗️ 主要模組
| 層 | 檔案 |
|---|---|
| **UI** | `app.py`（主入口，PR #61 後 **9181 行**）· `etf_dashboard.py` · `ui_widgets.py`（PR #60 抽出 8 個純 HTML 函式） |
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

## 🚀 最近完工（PR #42-#64，2026-05）
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

## 🎯 Backlog
- **環境工**：19 條 stale remote branches 清理（PR #42-#64 累積，sandbox token 無 delete 權）
- **部署驗證**：PR #42-#64 累積 Streamlit Cloud 上線驗收項目
- **PMI 真實異常**：PR #53 加好診斷工具，下次 PMI 紅燈時用 `🔬 8 段備援源詳細診斷` 按鈕定位根因（proxy 死 / regex 過時 / 端點改版）
- **技術債（已全面清乾淨）**：
  - 🎯 `app.py` ruff errors **681 → 0（100% clean）**（PR #56/#57/#60/#63/#64）
  - `app.py` 9622 → **9183 行**（−439，−4.6%，PR #58/#60/#61 抽 17 函式至 3 新模組）
  - `etf_dashboard.py` 3122 行
- **P2-B Phase 4 候選**（高風險）：TAB 級 def wrap（拆 `with tab_xxx:` 巨型 block，~8000 行，需謹慎大重構）

## 🧱 開發協議
依 `CLAUDE.md` v2.0 核心協議運行（§1-§5 嚴格三步法 / 防幻覺 / 精準讀寫 / 鋼鐵自省 / 卡關救援）。

