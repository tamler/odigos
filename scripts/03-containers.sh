#!/usr/bin/env bash
# ============================================================================
# 03-containers.sh — create the project containers. No file cleanup, no merges.
#
# Run:  cd ~/Projects/test/odigos && bash scripts/03-containers.sh
#
# WHAT A GIT WORKTREE IS
#   git worktree add <path> <branch>  gives you a second working directory
#   checked out to a different branch, sharing ONE .git and one history.
#   Not a clone: no duplicated objects, no remote to sync, no drift.
#
#   That's what makes a container work — each worktree is its own Claude Code
#   project with its own CLAUDE.md, so a session sees one slice of the tree and
#   one set of fences, while still being one repository.
#
#   Undo any of them with:  git worktree remove .worktrees/<name>
# ============================================================================

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()  { printf '   \033[32mok\033[0m  %s\n' "$*"; }

find .git -name '*.lock' -delete 2>/dev/null || true

[ -z "$(git status --porcelain --untracked-files=no)" ] || {
  printf '\n   Working tree is dirty. Run scripts/02-git.sh first.\n\n'; exit 1; }

# ----------------------------------------------------------------------------
say "In-repo containers (worktrees)"
# ----------------------------------------------------------------------------
# name | branch | charter
for row in \
  "cleanup|chore/cleanup|01-cleanup.md" \
  "tier2|feat/tier2-provisioning|02-tier2.md"
do
  IFS='|' read -r name branch charter <<< "$row"
  path=".worktrees/$name"

  if [ -d "$path" ]; then
    ok "$path already exists"
  else
    if git show-ref --verify --quiet "refs/heads/$branch"; then
      git worktree add "$path" "$branch" >/dev/null
    else
      git worktree add -b "$branch" "$path" >/dev/null
    fi
    ok "worktree $path on branch $branch"
  fi

  cp "docs/containers/$charter" "$path/CLAUDE.md"
  ok "charter $charter -> $path/CLAUDE.md"
done

# ----------------------------------------------------------------------------
say "Escalation log"
# ----------------------------------------------------------------------------
# A container that needs something outside its fence writes here and STOPS.
if [ ! -f docs/containers/ESCALATIONS.md ]; then
  cat > docs/containers/ESCALATIONS.md <<'EOF'
# Escalations

A container that finds it needs something outside its fence writes an entry here
and STOPS. It does not reach across. Whoever is orchestrating resolves these.

## YYYY-MM-DD — <container> — <one-line summary>
**Wants:** what it needs to do
**Blocked by:** which fence or non-goal
**Case:** why it looks necessary
**Decision:**

---
EOF
  ok "created docs/containers/ESCALATIONS.md"
fi

# ----------------------------------------------------------------------------
say "Separate repos — NOT worktrees"
# ----------------------------------------------------------------------------
# C and D must not inherit Odigos's import graph. D's entire product thesis is
# "zero Odigos imports"; C is a different language.
cat <<'EOF'
   Project D — tool-router. Any time after Project A:

     mkdir -p ../tool-router && cd ../tool-router && git init
     cp ../odigos/docs/containers/04-tool-router.md CLAUDE.md
     cp ../odigos/docs/superpowers/anti-patterns.md .

   Project C — ZOdigos. ONLY after Project A writes docs/DESIGN-DECISIONS.md:

     mkdir -p ../zodigos && cd ../zodigos && git init
     cp ../odigos/docs/containers/03-zodigos.md CLAUDE.md
     cp ../odigos/docs/DESIGN-DECISIONS.md .     # the bill of materials
     cp ../odigos/docs/superpowers/anti-patterns.md .
     touch DIVERGENCE.md
EOF

say "Worktrees now"
git worktree list | sed 's/^/   /'

cat <<'EOF'

   Launch ONE Claude Code session: .worktrees/cleanup  (Project A).
   Its CLAUDE.md is the charter. First action inside it: evolution.enabled: false.

   B, C, D stay unstarted until A is done.

EOF
