#!/usr/bin/env bash
# ============================================================================
# 02-git.sh — branch operations and one commit. No file surgery.
#
# Run:  cd ~/Projects/test/odigos && bash scripts/02-git.sh
#
# Run 01-files.sh FIRST. This script commits its results.
#
# Every git command used, in plain terms:
#   git merge --ff-only <b>   move main's pointer forward to <b>. REFUSES rather
#                             than inventing a merge commit if that's not clean.
#   git branch -d <b>         delete branch, REFUSING if not fully merged.
#                             (-D would force. This script never uses -D.)
#   git stash push            park uncommitted changes; recover with git stash pop
# ============================================================================

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mok\033[0m  %s\n' "$*"; }
warn() { printf '   \033[33m!\033[0m   %s\n' "$*"; }

# ----------------------------------------------------------------------------
say "0. Preflight"
# ----------------------------------------------------------------------------
# The Cowork device bridge cannot unlink(), so git could not clean up after
# itself and stranded lock files. Git refuses to run while they exist.
if find .git -name '*.lock' | grep -q .; then
  find .git -name '*.lock' -delete
  ok "cleared stranded git locks"
fi
ok "on branch $(git branch --show-current), HEAD $(git log --oneline -1)"

# ----------------------------------------------------------------------------
say "1. Merge the multi-tenant security branch into main"
# ----------------------------------------------------------------------------
# 32 commits, unmerged since 2026-05-29. This is the tier-2 security foundation:
# sandbox fail-closed, SSRF guards (tools/url_guard.py), argument guards
# (tools/arg_guard.py), api/rate_limit.py (a ROADMAP pre-launch blocker, already
# built), a redacting security event log, CSRF + cookie + session-epoch
# hardening, ~35 new test files, and
# docs/superpowers/specs/2026-05-29-security-hardening-multitenant.md — which is
# where the "one install per person, never user_id on data tables" decision is
# already written down.
#
# This goes FIRST because deleting ~1,000 lines on main while 32 commits rot on
# a side branch is precisely how the abandoned-fork problem got created.
BR=security/hardening-hosted-launch

if ! git show-ref --verify --quiet "refs/heads/$BR"; then
  ok "$BR already merged and gone"
else
  ok "$BR is $(git rev-list --count main.."$BR") commits ahead of main"

  # Uncommitted work must be parked before switching branches.
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    warn "uncommitted changes present:"
    git status --short --untracked-files=no | sed 's/^/       /'
    read -rp "   Commit them to $BR now? [y/N] " a
    if [[ "$a" == [yY] ]]; then
      git add -A
      git commit -q -m "chore(closeout): file cleanup — junk, stale handoffs, gitignore

Removes _to_delete/ (434MB: orphaned WAL with no main DB, analysis snapshot,
stranded git locks), 11 stale GEMINI-* handoff docs, orphaned test-DB sidecars,
and superseded planning scaffolding. Ignores runtime state; leaves data/brain
and data/agent visible because brain_reader.py rebuilds the DB from them."
      ok "committed to $BR"
    else
      git stash push -m "02-git.sh autostash"
      ok "stashed (git stash pop to recover)"
    fi
  fi

  git checkout main
  if git merge-base --is-ancestor main "$BR"; then
    git merge --ff-only "$BR"
    ok "main fast-forwarded to $(git log --oneline -1)"
  else
    warn "not a clean fast-forward — inspect before continuing"
    git log --oneline --graph main.."$BR" | head -40
    exit 1
  fi
fi

# ----------------------------------------------------------------------------
say "2. Delete dead branches"
# ----------------------------------------------------------------------------
# The 7 feat/* branches are verified fully merged: 0 commits ahead of main, last
# touched 9-10 April. `-d` refuses anything unmerged, so this cannot lose work.
for b in \
  security/hardening-hosted-launch \
  feat/activity-page-v2 \
  feat/brain-compiler \
  feat/marp-research-present \
  feat/notebook-review-sidecar \
  feat/structured-memory \
  feat/subagent-foundation \
  feat/surrogate-verifier-prompt-evolution
do
  git show-ref --verify --quiet "refs/heads/$b" && git branch -d "$b" >/dev/null && ok "deleted $b"
done

printf '\n'
git branch -vv | sed 's/^/   /'

# ----------------------------------------------------------------------------
say "3. Commit anything left"
# ----------------------------------------------------------------------------
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -q -m "chore(closeout): planning docs, container charters, closeout scripts" && ok "committed"
else
  ok "nothing left to commit"
fi

# ----------------------------------------------------------------------------
say "4. Do these yourself, in this order"
# ----------------------------------------------------------------------------
cat <<'EOF'
   a) Rebuild the venv. .venv/bin/python is a BROKEN SYMLINK — nothing has been
      test-verified locally in a long time.

        uv sync
        uv run pytest tests/ -q 2>&1 | tail -40

      READ that output before pushing. If the 32 merged commits break something,
      you want to know now, not inside Project A.

   b) Push.

        git push origin main

   c) Then: bash scripts/03-containers.sh
EOF
printf '\n'
