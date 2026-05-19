# 專案戰情室 (Project State)

## 📌 當前狀態
- **專案**: 台股 AI 戰情室 — Streamlit Cloud 多 Tab 投資儀表板（市場 / 個股 / 組合 / 總經 / ETF）
- **Stack**: Python · Streamlit · FinMind · yfinance · Gemini AI · NAS Squid Proxy
- **入口**: `app.py`
- **Secrets**: `FINMIND_TOKEN` · `GEMINI_API_KEY` · `PROXY_URL` · `FRED_API_KEY`

## 🏗️ 主要模組
| 層 | 檔案 |
|---|---|
| **UI** | `app.py`（主入口，PR #73 後 **1378 行**，−85%，4/4 TAB 已抽至獨立模組）· `tab_macro.py` (4031) · `tab_stock.py` (2521) · `tab_stock_grp.py` (1073) · `tab_edu.py` (401) · `etf_dashboard.py`（Phase 7C 後 **49 行 shim**，−97%，三層全拆）· `etf_tab_single.py` (616) · `etf_tab_portfolio.py` (531) · `etf_tab_backtest.py` (284) · `etf_tab_ai.py` (169) · `ui_widgets.py`（PR #60 抽出 8 個純 HTML 函式 + Phase 7F `cond_badge` 第 9 個 / Phase 7G 補完 9 函式 + 1 常數測試，71 unit test 全綠） |
| **ETF 三層** | `etf_fetch.py` (572 / Phase 7C 純 I/O：價格 / 配息 / NAV / 費用率 / 類股漲跌 / 新聞) · `etf_calc.py` (465 / 純算：殖利率 / 總報酬 / 折溢價 / 風險指標 / 同儕排名 / 戰情室列) · `etf_render.py` (505 / Streamlit UI：橫幅 / 走勢 / BIAS / 蒙地卡羅 / 類股熱力圖) |
| **跨 tab 共用** | `tab_helpers.py` (135 / Phase 7A+7A-Ext 純函式：parse_cash_flow_ratio / format_condition_emoji / safe_get / safe_ma / final_recommendation — 取代 tab_stock + tab_stock_grp + tab_macro 內 5 個重複 closure；零 Streamlit 依賴，34 unit test) · `macro_helpers.py` (Phase 7A-Ext+7E：calc_traffic_light + rp_ts / rp_entry / rp_scalar — tab_macro 紅綠燈決策核心 + data_registry 三函式抽出；30 unit test) · `etf_helpers.py` (53 / Phase 7B：norm_return / norm_lower_better / auto_role — 抽 etf_tab_backtest 雷達正規化 + etf_tab_portfolio 核心/衛星分類；29 unit test) |
| **資料抓取** | `data_loader.py` · `macro_core.py`（含 PR #53 `diagnose_tw_pmi_sources`）· `tw_macro.py` · `daily_checklist.py` · `leading_indicators.py` · `tw_stock_data_fetcher.py` |
| **資料註冊** | `data_registry.py` · `data_config.py` · `config.py` |
| **引擎** | `scoring_engine.py` · `scoring_helpers.py`（PR #61 抽 3 純函式：fundamental_score / health_score / health_grade — Phase 7H 補 50 unit test）· `financial_health_engine.py` · `market_strategy.py` · `risk_control.py` · `backtest_engine.py` · `unified_decision.py` · `v4_strategy_engine.py` · `v5_modules.py` · `yield_screener.py` |
| **技術指標** | `tech_indicators.py`（PR #58 從 app.py 抽出 6 個純函式：RSI/IBS/VR/KD/BB/VCP，零 Streamlit 依賴 — Phase 7H 補 47 unit test）|
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
| #86 | fix(app): `_AppProxy` 取代 `sys.modules.setdefault` — 線上 Streamlit Cloud `__main__` ≠ script module 時 PR #82 失效，改用 ModuleType proxy 轉發 live globals() 徹底解 4 檔 from-app ImportError | 40741be |
| #88 | fix(app): proxy v2 — globals 從 closure 改塞 `proxy.__dict__['__app_globals__']`，無條件 refresh，徹底解線上 tab_stock 11-name `from app import` 殘留 ImportError | 07a7321 |
| #90 | fix(tab_stock): 殖利率河流圖 TTM=0 三閃門 — PR #84 後 6770 力積電等個股因合成 ex-div 落未來導致 365D rolling 抓不到 → 河流消失；加 (1) 跳未來事件 (2) fallback 改去年 7/1 (3) 安全網退 avg_div2 橫帶並改 title 標示 | b6f07cc |
| #92 | fix(tab_stock): 殖利率河流圖 fallback 模式移除「便宜/合理/昂貴/⛔超昂貴」分區判讀（橫帶僅作歷史對照，避免誤導使用者拿過時資料做估值決策）+ 補強 TTM=0 三閃門 | 9f8c5ad |
| #94 | fix(app+data_loader): 個股現價慢一天 — pickle 快取（app.py:225）TTL 4h→0.5h + 命中路徑加 `latest_date` freshness gate（5 day grace 涵蓋週末連假）+ FinMind `taiwan_stock_daily` 明確帶 `end_date`。修盤前抓到 yesterday close、盤後 cache HIT 仍回舊價 bug | 152b52b |
| #96 | feat(tab_stock): 新增本益比 (PE) + 股價淨值比 (PB) 河流圖（殖利率河流圖之後）。PE 用 qtr2['EPS'] 4Q rolling sum + asof 對應公告生效日（季末+60天）避免穿越；三組閾值 selectbox 切換（通用 10/15/20、保守 8/12/16 景氣循環、成長 12/18/25）；TTM EPS≤0 虧損股 warning 不畫帶。PB 從 yfinance bookValue 取最新值畫橫帶（0.8/1.5/2.5），雙後綴 .TW/.TWO 重試 | 55f7f2f |
| #98 | refactor(etf): 移除「AI ETF 存股決策總結」與 AI 首席顧問決策中心併軌（兩者功能重疊都做 BIAS240+KD+殖利率三維判讀）。刪 _etf_ai_hokei() 函數 98 行 + 順手清 3 個 pre-existing dead imports（render_unified_decision/calc_stats/re as _re2） | 2350d72 |
| #99 | feat(etf): ETF 組合 4 分頁整合為 1 + 持股資產追蹤改造。Phase A：app.py 移除內嵌 tab，改 tab_etf_grp 順序呼叫 4 個 render + hr 分隔線。Phase B：輸入格式 `代號,目標權重%,現值元` → `代號,股數,均價[,希望比例%][,類型]`；新增自動計算現價/現值/成本/資本利得/已領配息（近1年除息×股數）/總損益；資產總覽卡 5 大 metric；批次抓現價並 dedup 下游再平衡 fetch 迴圈 | b6e4562 |
| #101 | refactor(etf): 葡萄串改用持股 + AI 移到最底（單一輸入來源）。etf_tab_portfolio 把 rows 存 session_state['etf_portfolio_rows']；grape_ladder _render_evaluate_subtab 移除自己的 text_area，改讀 session_state 用真實股數估算月配息；app.py 順序改 組合配置→回測→葡萄串→AI（壓軸避免 anchor bias） | 19f0052 |
| #102 | refactor(grape): 「評估我的組合」拉到主頁面，系統提議改 expander 折疊。子 tab 結構展平，主視圖直接顯示「評估我的組合」（讀組合配置持股），「系統提議」（高股息 10 檔挑選）改 st.expander 預設收起 | c4fcb41 |
| #103 | refactor(etf): 回測也共用持股組合（單一輸入來源全面收斂）。移除 etf_tab_backtest 的 text_area，改讀 session_state['etf_portfolio_rows']；新增 radio 切換「希望比例%（規劃驗證）/ 現值比例%（實況回放）」做回測權重。ETF 組合 tab 全頁面唯一輸入來源達成 | 3204666 |
| #104 | feat(diag): 資料診斷新增 ETF 組合「逐檔個別判斷」。health_inspector ETF Raw Data expander 內加 N×2 行（每檔現價+配息），三態探測：海外 ETF 配息標 ⚪ na、台股無配息標 🔵 zero、現價失敗標 🔴；所有 rows 加入底部異常清單彙總 | f82c121 |
| (branch `claude/fix-yield-river-bands-YK8i7`) | refactor(ui) 老師名稱統一改為「策略 1/2/3」（按方法論分 3 類，僅改 UI 顯示文字） | cd50c48 |
| (同上) | fix(tab_stock_grp): 批次分析空 K 線改為標記 error 並跳過快取（修「🔴 未取得」靜默失敗） | 26da8fb |
| (同上) | fix(etf): 私募/特殊 ETF 三項全空時改判 na（⚪不適用）— AUM+費用率+NAV 啟發式 | c3250d7 |
| (同上) | fix(macro): TW PMI 8 段備援補上每段失敗原因追蹤（無回應 / HTTP 狀態碼） | 8d3fb71 |
| (同上) | refactor(etf): Phase 7C 三層分檔 — etf_dashboard 1667 → 49 行 shim；新增 etf_fetch / etf_calc / etf_render 共 1542 行；40 個 symbol 全 re-export，6 個下游 importer 零修改 | 44a0e87 |
| (同上) | feat(tab_stock): Phase 7D — 停利停損面板下方新增關鍵價位 K 線圖（K + 量 + MA20/MA100 + 9 條 add_hline 水平線：停利 1/2、減碼/硬停損、支撐/壓力、月線停損、5MA、初步目標、加碼點） | 461d465 |
| (同上) | docs: Phase 7C/7D 三檔同步 — STATE/ARCHITECTURE/SPEC 補三層架構章節 + 9 條水平線對照表 + §5 三層職責邊界規約 | ab0b34d |
| (同上) | refactor: Phase 7A — 抽 4 個跨 tab 重複純函式至 tab_helpers.py（parse_cash_flow_ratio / format_condition_emoji / safe_get / safe_ma），消除 tab_stock + tab_stock_grp 之間 _r110_ok_a/_b EXACT DUPLICATE；+27 unit test | 0ef1991 |
| (同上) | refactor: Phase 7A-Ext 雙抽純函式 + 修復 B 項 1Q fallback — `_calc_traffic_light` (71 行) → `macro_helpers.calc_traffic_light` + `_final_rec` (26 行) → `tab_helpers.final_recommendation`；補 `_no_ai_survival` 「呼叫端未預填 b_item_5y」的單季 fallback 分支（修 4 個 pre-existing TestNoAiSurvivalBItem 紅燈）；+19 unit test，全套件 519/519 全綠 | e678d22 |
| (同上) | refactor: Phase 7B — 抽 `etf_helpers.py` (norm_return / norm_lower_better / auto_role)，消除 etf_tab_backtest 雷達正規化 + etf_tab_portfolio 核心/衛星分類兩個 render 內部 closure；`_CORE_TICKERS` 改 frozenset 防呆；+29 unit test，全套件 **548/548 全綠** | 5f299d5 |
| (同上) | refactor: Phase 7E — 抽 `macro_helpers.{rp_ts, rp_entry, rp_scalar}` — tab_macro.py render 內 data_registry patch 三函式（季度標籤/年度/DatetimeIndex/_date 多源時間解析 + scalar proxy date metadata）；`_QE_MAP` 提至模組級；47 行 closure 刪除 + 26 callsites 重接 + `_proxy_rp` 顯式參數化；+18 unit test，全套件 **566/566 全綠** | ec7e39f |
| (同上) | refactor: Phase 7F — 抽 `ui_widgets.cond_badge(ok, label)` — tab_macro.py 五維點火條件徽章 closure（HTML span，True 綠 / False 灰）；3 行 closure 刪除 + 7 callsite 重接；新增 `tests/test_ui_widgets.py` 8 cases；全套件 **574/574 全綠** | fde8047 |
| (同上) | test: Phase 7G — `ui_widgets.py` PR #60 既有 9 函式 + 1 常數補完單元測試（TERM_EXPLAIN / explain_box / traffic_light / beginner_kpi / show_term_help / kpi / _to_strategy / teacher_box / teacher_conclusion / signal_box），零生產碼變動；+63 unit test，全套件 **637/637 全綠** | 114f17f |
| (同上) | test: Phase 7H — `tech_indicators.py` (PR #58) + `scoring_helpers.py` (PR #61) 9 純函式補完單元測試（calc_rsi / calc_ibs / calc_volume_ratio / calc_kd / calc_bollinger / calc_vcp + calc_fundamental_score / calc_health_score / health_grade），零生產碼變動；+97 unit test，全套件 **734/734 全綠** | 8b26a13 |
| (同上) | chore: 產出 `cleanup_stale_branches.sh` — 49 條 stale 遠端分支清理腳本（48 merged 主清單 + 2 unmerged opt-in 區段）；含 DRY_RUN 預設、白名單保護（main / 當前分支）、刪前重新驗證 ancestor of origin/main；對應 STATE.md Backlog「環境工」條目 | (本輪) |
| (debug) | feat(diag): `api_diagnostic.py` — 「Key 對但全站抓不到」根因診斷面板（掛 tab_diag 第一格）：逐 key 來源/遮罩、proxy vs 直連 雙跑、結果判讀指南；側邊欄連線狀態 fallback 補 os.environ；**結案結論**：用戶 PROXY_URL 拼字錯（`cheng→chen`）導致 DNS NameResolutionError，Streamlit Cloud 改正即復原；分支 `claude/debug-api-key-JmH9N` 保留為診斷工具，不發 PR | 7f02af3 |
| #1 | fix(macro): 進頁完全不抓資料 + 按鈕觸發全清快取 + conf<70 擋燈號（v10.56.0）— 修「沒按按鈕資料就跑出來、信心 20% 卻仍顯示 🔴 空頭防禦燈號、多頭行動建議與空頭燈號並存」三項用戶實證 bug。三檔四改：(1) `tab_macro.py:472` 條件 `if do_refresh or 'cl_data' not in st.session_state` → `if do_refresh:` 冷啟動 0 並發 0 抓取；(2) `_on_refresh_click` 全清三層快取（`st.cache_data` / `proxy_helper._URL_CACHE`+`reset_proxy_cache` / 11 個 session_state key）；(3) `macro_helpers.calc_traffic_light` 回傳新增 `missing_sources: list[str]`（15→16 keys）；(4) `_render_traffic_light` 加 conf<70 early-return：橘色「⏸️ 資料不足」卡 + 逐項列缺失資料。`tests/test_macro_helpers.py` **30/30 全綠**（missing_sources 嚴格擴充）| 58cad2c |
| #2 | feat(etf): 新增持股 Overlap 矩陣 — 補價格相關係數矩陣盲點。價格 Pearson 反映「走勢同步度」（拿不到「持股名單同質性」）；新增 `etf_fetch.fetch_etf_holdings`（yfinance funds_data → MoneyDJ Basic0007/0008/RankA0001 三段備援；curl_cffi 繞反爬；TTL 1日）+ `etf_calc` 三純函式（`calc_holdings_overlap_pct` Σmin 業界標準 / `calc_jaccard_overlap` 集合 / `build_holdings_overlap_matrix` N×N）+ `etf_render._plot_holdings_overlap`（0-100% 單向 colormap）+ `etf_tab_portfolio` 新 section（st.radio 切兩種演算法 + 同質性警示權重 >30%/Jaccard >50%）。`tests/test_etf_holdings_overlap.py` +18 cases，全套件 734 → **752/752 全綠** | ade2a53 |
| #3 | feat(etf): 主動 ETF 弱勢度檢測 + 經理人標註（淘汰不適任邏輯）— Gemini 提案核心：「主動 ETF 付 1% 經理費就該打贏大盤；近 1 年大跌時跌更深 + 反彈時漲更慢 + 連 2 季輸盤 = 該換」。⏳ 新經理人 <6 個月給機會。新增 `etf_fetch.is_active_etf`（白名單 + 代號字尾 A/D/T/B/K 啟發式）+ `fetch_etf_manager`（MoneyDJ Basic0001 regex 抓「經理人 + 到職日」TTL 7日）+ `etf_calc.calc_weakness_metrics` 純函式（每日 pct_change 對齊 → 大跌弱勢率 / 反彈弱勢率 / 季 cumprod 連敗計數 / 年化 TE）+ `compute_etf_weakness_row` 高階組裝 + `etf_render._render_weakness_table`（ProgressColumn 視覺化）+ `etf_tab_portfolio` 新 section（自動跑全持股 + 連 2 季輸盤紅卡換股建議含經理人任期註記）。僅對主動式 ETF 顯示弱勢度；被動式標 ⚪ 免測。`tests/test_etf_weakness.py` +16 cases，全套件 752 → **768/768 全綠** | 7ec67e9 |
| #4 | feat(macro): 頂部 🧭 總經指南針 (VIX × 10Y × S&P 500) 改為按鈕觸發 — 修「進頁顯示上次抓到的舊值（收盤後/盤前/離線時的過時數字）誤導判斷」。`app.py:1073-1110` `render_macro_compass()` 重寫：移除 15 分鐘 session_state 自動快取；改用 `st.columns([6,1])` header + 右上「📡 抓取最新 / 🔄 重抓」按鈕；`_do_fetch()` callback 寫 `st.session_state['_macro_compass_cache']`（含 `_ts` 時間戳）；無快取時 `st.info` 引導；副標動態切「即將抓取（無快取）」or「更新於 HH:MM:SS」。語意：按鈕當下＝盤面當下 = 決策當下真實狀態 | 3b043a7 |

## 🎯 Backlog
- **環境工**：49 條 stale remote branches 清理 → ✅ 產出 `cleanup_stale_branches.sh`（48 merged 主清單 + 2 unmerged opt-in），預設 DRY_RUN=1；sandbox HTTP 403 擋 push --delete，需本機 clone 後 `DRY_RUN=0 ./cleanup_stale_branches.sh` 執行
- **部署驗證**：PR #42-#78 累積 Streamlit Cloud 上線驗收項目（重點：Phase 5 + Phase 6 共抽出 8 個 tab/render 模組，每個都需手動驗證 happy path）
- **PMI 真實異常**：PR #53 加好診斷工具，下次 PMI 紅燈時用 `🔬 8 段備援源詳細診斷` 按鈕定位根因（proxy 死 / regex 過時 / 端點改版）
- **ETF 組合單一輸入來源 ✅ 全收斂（PR #99→#101→#102→#103→#104）**：
  - ✅ 組合配置（唯一輸入：股數+均價+希望比例%+類型）
  - ✅ 葡萄串領息法（自動讀持股，真實股數估月配息）
  - ✅ 歷史回測（radio 切希望/現值比例）
  - ✅ AI 綜合評斷（自由提問，整合上方分析）
  - ✅ 資料診斷（逐檔現價+配息三態探測）
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
- **P2-B Phase 7 ✅ 收官（三層分檔 + 跨 tab 共用 helper + UI 強化）**：
  - ✅ 7C `etf_fetch.py` (572 行 / 純 I/O，0 內部依賴) + `etf_calc.py` (465 行 / 純算，依賴 etf_fetch) + `etf_render.py` (505 行 / Streamlit UI，依賴 etf_fetch) — commit `44a0e87`
  - ✅ `etf_dashboard.py` 由 1667 → **49 行 shim**（re-export 40 個 symbol + 4 個 tab 入口），6 個下游 importer (app / etf_quality / grape_ladder / 4 個 etf_tab_*) 零修改
  - ✅ 7D `tab_stock.py` 停利停損面板 K 線圖 +9 條水平線（+65 行）— commit `461d465`
  - ✅ 7A `tab_helpers.py` (89 行) — 抽 4 個跨 tab 重複純函式（parse_cash_flow_ratio / format_condition_emoji / safe_get / safe_ma），消除 tab_stock vs tab_stock_grp 之間 _r110_ok 的 EXACT DUPLICATE；3 tab 檔合計 −41 行；+27 unit test 全綠 — commit `0ef1991`
  - ✅ 7A-Ext `macro_helpers.py` (110 行) + `tab_helpers.final_recommendation` — 抽 `_calc_traffic_light` (71 行 / tab_macro) + `_final_rec` (26 行 / tab_stock_grp)；同 commit 修復 `_no_ai_survival` 缺 1Q fallback 的 4 個 pre-existing 紅燈；+19 unit test，全套件 **519/519 全綠** — commit `e678d22`
  - ✅ 7B `etf_helpers.py` (53 行 / 3 函式：`norm_return` / `norm_lower_better` / `auto_role`) — 抽 etf_tab_backtest 雷達正規化 + etf_tab_portfolio 核心/衛星分類；`_CORE_TICKERS` 改 frozenset 防呆；+29 unit test，全套件 **548/548 全綠**
  - ✅ 7E `macro_helpers.{rp_ts, rp_entry, rp_scalar}` + `_QE_MAP` 常數 — 抽 tab_macro.py L1663-1709 data_registry patch 三函式（4 種時間源解析：DatetimeIndex / 季度標籤 / 年度 / _date|date|datetime|...）；`_proxy_rp` 改顯式參數，消除 closure capture；47 行 closure 刪除 + 26 callsite 重接；+18 unit test，全套件 **566/566 全綠**
  - ✅ 7F `ui_widgets.cond_badge(ok, label)` — 抽 tab_macro.py L3392-3394 五維點火條件徽章 closure（HTML span 模板）；3 行 closure 刪除 + 7 callsite 重接；+8 unit test，全套件 **574/574 全綠**
  - ✅ 7G `tests/test_ui_widgets.py` 補測 — 將 PR #60 既有 9 函式 + 1 常數補完單元測試（TERM_EXPLAIN / explain_box / traffic_light / beginner_kpi / show_term_help / kpi / _to_strategy / teacher_box / teacher_conclusion / signal_box）；零生產碼變動，純測試補完；+63 unit test，全套件 **637/637 全綠**
  - ✅ 7H `tests/test_tech_indicators.py` + `tests/test_scoring_helpers.py` 補測 — PR #58/#61 抽出 6+3 = 9 純函式時遺漏的單測技術債一次補完（calc_rsi / calc_ibs / calc_volume_ratio / calc_kd / calc_bollinger / calc_vcp / calc_fundamental_score / calc_health_score / health_grade）；零生產碼變動；+97 unit test（tech 47 + scoring 50），全套件 **734/734 全綠**
- **技術債（已全面清乾淨）**：
  - 🎯 `app.py` ruff errors **681 → 0（100% clean）**（PR #56/#57/#60/#63/#64）
  - `app.py` 9622 → **1378 行**（**−8244，−85.7%**，PR #58/#60/#61 抽純函式 + #66/#68 wrap def + #70-#73 抽 4 TAB）
  - `etf_dashboard.py` 3122 → **49 行 shim**（**−3073，−98.4%**，PR #75-#78 抽 4 render + Phase 7C 三層全拆）
  - **兩大入口檔合計** 12744 → **1427 行**（**−11317，−88.8%**）
- **剩餘候選**（可選）：
  - tab_*.py / etf_tab_*.py 內仍有大量 closure 嵌在 Streamlit render 函式中，整體 mock 化成本高；後續若再抽，沿用 7A/7B 模式（純函式提到 module-level → +unit test）逐 closure 處理
  - 註：`_li_futures_scoring` 經 Explore 驗證**從未存在於 codebase**（前次清單誤記）

## 🧱 開發協議
依 `CLAUDE.md` v2.0 核心協議運行（§1-§5 嚴格三步法 / 防幻覺 / 精準讀寫 / 鋼鐵自省 / 卡關救援）。

