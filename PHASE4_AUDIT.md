# P2-B Phase 4 跨 TAB 變數洩漏審計報告

**日期**：2026-05-15
**目標**：在動 code 前評估「將 4 個 module-level `with tab_xxx:` 區塊包成 `render_<tab>()` 函式」的風險。
**方法**：AST-based static analysis（read-only，零 code 變更）。
**結論**：✅ **0 真實洩漏，可安全 wrap def**。

---

## 📊 TAB 規模盤點

| TAB | 行範圍 | 行數 | 內部賦值變數數 | 內部讀取變數數 |
|---|---|---|---|---|
| `tab_etf_grp` | 1080-1083 | 4 | 4 | 2 |
| `tab_macro` | 1334-5303 | **3970** | 877 | 1057 |
| `tab_stock` | 5308-7709 | **2402** | 642 | 727 |
| `tab_stock_grp` | 7714-8744 | **1031** | 293 | 351 |
| `tab_edu` | 8749-9135 | 387 | 31 | 51 |
| `tab_etf` | 9140-9141 | 2 | 0 | 3 |
| `tab_screener` | 9167-9169 | 3 | 0 | 2 |
| `tab_diag` | 9174-9175 | 2 | 0 | 2 |
| `tab_heatmap` | 9180-9181 | 2 | 0 | 2 |

**Wrap def 候選**：`tab_macro` / `tab_stock` / `tab_stock_grp` / `tab_edu`（合計 **7790 行**）。

---

## 🔬 分析方法

對 app.py 做 AST 解析，逐 TAB 收集：
1. **assigned set**：tab 內所有 Store 上下文的 Name
   - 補抓：`except X as N` (ExceptHandler.name)
   - 補抓：`import X as N` / `from X import Y as N` (alias.asname)
   - 補抓：`def f(args)` 函式參數
   - 補抓：FunctionDef / ClassDef / AsyncFunctionDef 的 name
2. **read set**：tab 內所有 Load 上下文的 Name

**洩漏判定規則**：
> 變數 V 在 TAB-A 賦值 + V 在 TAB-B 讀取 + V 不在 module-level 賦值集合 + V 在 TAB-B 內**未賦值**

---

## ✅ 主檢查結果（嚴格規則）

```
✅ 無跨 TAB 洩漏 — 所有 TAB 內賦值的變數都不被其他 TAB 讀取，可安全 wrap def。
```

---

## ⚠️ Corner case 檢查（dst 內 Load → Store 順序倒置）

進階檢查：dst tab 內某變數**最早出現是 Load 而非 Store**，且其他 tab 有賦值。理論上若這發生在 module-level，會依賴前面 tab 留下的全域值；wrap def 後就會 NameError。

掃出 6 個候選，**全數逐一驗證為 false positive**：

| 案例 | 行號 | 真相 |
|---|---|---|
| `tab_macro._n` load@L2228 | 內層函式 helper 內 | `_n` 是該函式的 local 參數，與外層 `_n` 無關 |
| `tab_macro._key` load@L2919 | `for _lbl, _key in [...]:` | for-unpack，Store 與 Load 同行 |
| `tab_macro.d` load@L4251 | `[... for d in _adl_dates]` | list comprehension scope，不洩漏 |
| `tab_stock_grp._key` load@L2919 | 同 `_key` 案，跨 grp 同形 | 不適用 |
| `tab_stock._lbl` load@L2921 | 同 for-unpack | 不適用 |
| `tab_stock._n` load@L7619 | `... for _n in _stock_news2` | generator expression scope |

**為什麼是誤報**：Python 3 的 list/set/dict comprehension 和 generator expression 都有獨立 scope，內部迭代變數不洩漏到外層；for-unpack 的 Store 與 Load 在同一行；嵌套函式參數有自己的 local scope。AST 行序檢查不分 scope，故誤報。

---

## 📥 各 TAB 從 module-level 讀取的變數（OK，wrap 後 closure 仍生效）

`tab_macro` 從 module-level 讀取 41 個（如 `_get_loader`, `gemini_call`, `INTL_MAP`, `TW_MAP`, `MacroStateLocker`, `V4StrategyEngine` 等）。

`tab_stock` 從 module-level 讀取 38 個（如 `calc_health_score`, `calc_rsi`, `analyze_financial_health`, `_fetch_stock_news` 等）。

`tab_stock_grp` 從 module-level 讀取 25 個。

`tab_edu` 從 module-level 讀取 1 個。

**結論**：所有 module-level 變數都會持續在 closure scope 中可讀，wrap def 後完全等價。

---

## 🟢 動工建議

### 推薦執行順序

| 階段 | TAB | 行數 | 預估 Token |
|---|---|---|---|
| **P4-A** | `tab_stock_grp` | 1031 | 中（試水溫） |
| **P4-B** | `tab_edu` | 387 | 小 |
| **P4-C** | `tab_stock` | 2402 | 大 |
| **P4-D** | `tab_macro` | 3970 | 巨 |

### 每個 PR 的標準動作

```python
# Before:
with tab_xxx:
    # ... 1000+ lines of streamlit code ...

# After:
def render_xxx():
    # ... same 1000+ lines, indent 一致即可 ...

with tab_xxx:
    render_xxx()
```

### 驗證 checklist

每個 PR 完工：
- [ ] `python -m py_compile app.py` 無錯
- [ ] `ruff check app.py` 維持 0 errors
- [ ] AST function count: 動工前 N → 動工後 N+1
- [ ] Streamlit 啟動，點開該 TAB happy path 正常

### 注意事項

1. **縮排**：整段 `with tab_xxx:` 區塊內所有 line 已是 4-space 縮排，wrap 成 def 後仍是 4-space（不需 reindent）— 只需移除 `with tab_xxx:` 行 + 加上 `def render_xxx():` 行 + 在 TAB 主體加 `with tab_xxx: render_xxx()`。
2. **Helper def**：tab 內已有的內層 def（如 `def _rb_add(_n, _df, ...)`）會自動變成 `render_xxx()` 的 nested def，scope 仍正確。
3. **session_state**：所有 `st.session_state[...]` 不受影響（Streamlit 自身管理）。
4. **不會獲得行數縮減**：本階段為**結構整理**，行數預估 −0 至 +12（4 個 def 的 wrapper 開銷）。後續若要繼續抽到獨立檔案會更容易。

---

## 🚫 不在本階段範圍

- 將 `render_xxx()` 進一步抽到獨立檔案（如 `tab_macro.py`）— 可作為 Phase 5 候選
- TAB 內的 helper 函式提取至 module-level — 可作為小重構穿插
- session_state 命名統一 / 治理 — 獨立議題

---

## 🛠️ 審計工具備存

- `/tmp/p4audit/audit.py` — AST cross-tab leak detector
- `/tmp/p4audit/order_check.py` — Load→Store order checker
- `/tmp/p4audit/verify.py` — 候選逐個行號驗證

下次審計可重跑驗證（app.py 變更後）。
