#!/usr/bin/env bash
# cleanup_stale_branches.sh — 清理已合併入 main 的遠端分支
#
# 用法：
#   ./cleanup_stale_branches.sh           # 預設 DRY_RUN=1，僅印出將要刪除的指令
#   DRY_RUN=0 ./cleanup_stale_branches.sh # 實際執行刪除
#
# 安全保護：
#   1. 跳過 main 與目前分支
#   2. 每個分支刪除前重新檢查是否已合併入 origin/main
#   3. 未合併分支放在 OPTIONAL_UNMERGED 區段，需手動取消註解
#
# 產生時間：2026-05-16
# 對應 repo：CornCorn-2015/my-stock-dashboard
# 對應 STATE.md 條目：33 條 stale remote branches 清理（Blocked → 本腳本解鎖）

set -euo pipefail

DRY_RUN="${DRY_RUN:-1}"
REMOTE="${REMOTE:-origin}"

# ─────────────────────────────────────────────────────────────
# 已合併入 main 的分支（48 條）— 安全刪除
# ─────────────────────────────────────────────────────────────
MERGED_BRANCHES=(
  claude/app-extract-scoring-helpers
  claude/app-extract-tech-indicators
  claude/app-extract-ui-widgets
  claude/app-ruff-detox-p2
  claude/app-ruff-detox-p2-wave2
  claude/app-ruff-e722-cleanup
  claude/app-ruff-final-21
  claude/etf-dashboard-detox
  claude/etf-mk-framework-phase1
  claude/etf-peer-ranking-p1
  claude/etf-quality-detox
  claude/etf-quality-p3
  claude/evaluate-database-compatibility-PN9zB
  claude/fix-data-diagnostics-ku96v
  claude/fix-overseas-etf-regex
  claude/fix-yield-river-and-risk-header-YK8i7
  claude/grape-ladder-p4
  claude/health-inspector-extract
  claude/merrill-clock-p2
  claude/p2b-phase4-macro
  claude/p2b-phase4-stock-grp
  claude/p2b-phase5a-tab-edu
  claude/p2b-phase5b-tab-stock-grp
  claude/p2b-phase5c-tab-stock
  claude/p2b-phase5d-tab-macro
  claude/p6a-etf-single
  claude/p6b-etf-portfolio
  claude/p6c-etf-backtest
  claude/p6d-etf-ai
  claude/state-arch-sync-phase123
  claude/state-arch-sync-pr53
  claude/state-arch-sync-pr58
  claude/state-arch-sync-pr64
  claude/state-arch-sync-pr66
  claude/state-arch-sync-pr68
  claude/state-arch-sync-pr73
  claude/state-arch-sync-pr78
  claude/state-sync
  claude/state-sync-pr80
  claude/state-sync-pr82
  claude/state-sync-pr84
  claude/state-sync-pr86
  claude/state-sync-pr90
  claude/state-sync-pr92
  claude/state-sync-pr94
  claude/state-sync-pr96
  claude/state-sync-pr98-104
  claude/state-sync-pr98-99
)

# ─────────────────────────────────────────────────────────────
# 未合併分支（2 條）— 預設不刪，需手動取消註解
# ─────────────────────────────────────────────────────────────
# claude/fix-data-retrieval-XFDpO   # 舊 bug fix 分支，未合併
# claude/testing-v1A6I              # 測試分支，未合併
OPTIONAL_UNMERGED=(
  # claude/fix-data-retrieval-XFDpO
  # claude/testing-v1A6I
)

# ─────────────────────────────────────────────────────────────
# 不可動分支（白名單，腳本會自動跳過）
# ─────────────────────────────────────────────────────────────
PROTECTED=(
  main
  master
  claude/fix-yield-river-bands-YK8i7  # 開發中分支（PR #112）
)

# ─────────────────────────────────────────────────────────────

current_branch=$(git symbolic-ref --short HEAD 2>/dev/null || echo "")

is_protected() {
  local b="$1"
  for p in "${PROTECTED[@]}"; do
    [[ "$b" == "$p" ]] && return 0
  done
  [[ "$b" == "$current_branch" ]] && return 0
  return 1
}

echo "== 重新驗證遠端狀態 =="
git fetch "$REMOTE" --prune

delete_branch() {
  local b="$1"
  local verify_merged="$2"  # "merged" | "skip-check"

  if is_protected "$b"; then
    echo "  [SKIP] $b（受保護）"
    return
  fi

  if ! git ls-remote --exit-code --heads "$REMOTE" "$b" >/dev/null 2>&1; then
    echo "  [GONE] $b（遠端已不存在）"
    return
  fi

  if [[ "$verify_merged" == "merged" ]]; then
    if ! git merge-base --is-ancestor "$REMOTE/$b" "$REMOTE/main" 2>/dev/null; then
      echo "  [ABORT] $b（重新檢查發現未合併，跳過）"
      return
    fi
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "  [DRY ] git push $REMOTE --delete $b"
  else
    echo "  [DEL ] $b"
    git push "$REMOTE" --delete "$b"
  fi
}

echo ""
echo "== 處理 ${#MERGED_BRANCHES[@]} 條 merged 分支 =="
for b in "${MERGED_BRANCHES[@]}"; do
  delete_branch "$b" "merged"
done

if [[ ${#OPTIONAL_UNMERGED[@]} -gt 0 ]]; then
  echo ""
  echo "== 處理 ${#OPTIONAL_UNMERGED[@]} 條 unmerged 分支 =="
  for b in "${OPTIONAL_UNMERGED[@]}"; do
    delete_branch "$b" "skip-check"
  done
fi

echo ""
if [[ "$DRY_RUN" == "1" ]]; then
  echo "✅ DRY RUN 完成。要實際執行請設定 DRY_RUN=0 重跑。"
else
  echo "✅ 清理完成。建議執行 git fetch --prune 同步本地 ref。"
fi
