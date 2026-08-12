#!/usr/bin/env bash
# ============================================================================
# 03-containers.sh — create the project containers. Nothing else.
#
# Run:  cd ~/Projects/test/odigos && bash scripts/03-containers.sh
#
# WHAT A GIT WORKTREE IS
#   git worktree add <path> <branch>  gives you a second working directory
#   checked out to a different branch, sharing ONE .git and one history.
#   Not a clone: no duplicated objects, no remote to sync, no drift.
#
#   Each worktree is its own Claude Code project. Undo any of them with:
#     git worktree remove .worktrees/<name>
#
# NOTE (v2): an earlier version of this script copied each charter over the
# worktree's CLAUDE.md. That was wrong on two counts — it clobbered the tracked
# project CLAUDE.md and left every worktree permanently dirty, and it was
# pointless: worktrees share the repo, so docs/containers/*.md is ALREADY
# present in every worktree. The charter is referenced at session start
# instead. Nothing is copied and no worktree starts dirty.
# ============================================================================

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()  { printf '   \033[32mok\033[0m  %s\n' "$*"; }

find .git -name '*.lock' -delete 2>/dev/null || true

[ -z "$(git status --porcelain --untracked-files=no)" ] || {
  printf '\n   Working tree is dirty. Commit first.\n\n'; exit 1; }

# ----------------------------------------------------------------------------
say "In-repo containers (worktrees)"
# ----------------------------------------------------------------------------
for row in \
  "cleanup|chore/cleanup|docs/containers/01-cleanup.md" \
  "tier2|feat/tier2-provisioning|docs/containers/02-tier2.md"
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

  # Sanity: the charter must be visible from inside the worktree. It will be —
  # same repo, same commit — this just proves it before you launch a session.
  [ -f "$path/$charter" ] && ok "charter reachable at $path/$charter" \
    || { printf '   MISSING: %s/%s — commit the charter first\n' "$path" "$charter"; exit 1; }
done

# ----------------------------------------------------------------------------
say "Escalation log"
# ----------------------------------------------------------------------------
if [ ! -f docs/containers/ESCALATIONS.md ]; then
  cat > docs/containers/ESCALATIONS.md <<'EOF'
# Escalations

A container that needs something outside its fence writes an entry here and
STOPS. It does not reach across. Whoever is orchestrating resolves these.

## YYYY-MM-DD — <container> — <one-line summary>
**Wants:** what it needs to do
**Blocked by:** which fence or non-goal
**Case:** why it looks necessary
**Decision:**

---
EOF
  ok "created docs/containers/ESCALATIONS.md — commit it"
fi

# ----------------------------------------------------------------------------
say "Launching a container"
# ----------------------------------------------------------------------------
cat <<'EOF'
   Open the worktree as its own Claude Code project, then open with:

     Project A:  "Read docs/containers/01-cleanup.md. It is your charter and it
                  is binding, especially the Hard non-goals. Start with section 0."

     Project B:  "Read docs/containers/02-tier2.md. It is your charter and it is
                  binding."

   If you'd rather the charter load automatically every session, add ONE tracked
   line to that worktree's CLAUDE.md (Claude Code follows @-imports):

     echo '@docs/containers/01-cleanup.md' >> .worktrees/cleanup/CLAUDE.md

   That's a deliberate 1-line commit rather than clobbering the file.
EOF

# ----------------------------------------------------------------------------
say "Separate repos — NOT worktrees"
# ----------------------------------------------------------------------------
cat <<'EOF'
   C and D must not inherit Odigos's import graph. D's whole thesis is zero
   Odigos imports; C is TypeScript.

   Project D — tool-router. Any time after Project A:

     mkdir -p ../tool-router && cd ../tool-router && git init
     cp ../odigos/docs/containers/04-tool-router.md CLAUDE.md
     cp ../odigos/docs/superpowers/anti-patterns.md .

   Project C — ZOdigos. ONLY after Project A writes docs/DESIGN-DECISIONS.md:

     mkdir -p ../zodigos && cd ../zodigos && git init
     cp ../odigos/docs/containers/03-zodigos.md CLAUDE.md
     cp ../odigos/docs/DESIGN-DECISIONS.md .
     cp ../odigos/docs/superpowers/anti-patterns.md .
EOF

say "Worktrees now"
git worktree list | sed 's/^/   /'
printf '\n'
