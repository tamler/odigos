# Prompts to paste into Claude Code

Two prompts. Run the first now in your existing `odigos` session. Run the second only after the
first reports green.

---

## PROMPT 1 — Phase 0 closeout

> Paste this into the Claude Code instance already open in `~/Projects/test/odigos`.

```
You're doing Phase 0 closeout on this repo. Read /THE-PLAN.md first — section 2 is your
scope, section 2.1 is the complete file inventory. Then read scripts/01-files.sh,
scripts/02-git.sh and scripts/03-containers.sh before running any of them. They were
written against a snapshot of this tree; verify each one matches reality and tell me
about any mismatch instead of adapting silently.

Then, in order:

1. Tag the current state first, so all of this is reversible:
   git tag pre-cleanup-2026-08-12 && git push origin pre-cleanup-2026-08-12
   If the push fails, stop and tell me — I want a remote copy before anything destructive.

2. bash scripts/01-files.sh
   Deletes ~434MB of junk, 11 stale GEMINI-* handoff docs, orphaned test-DB sidecars, and
   5 files of superseded planning scaffolding. Adds gitignore entries.

3. bash scripts/02-git.sh
   Fast-forwards main to security/hardening-hosted-launch (32 commits, unmerged since
   2026-05-29 — this is the tier-2 security foundation), then deletes 8 dead branches and
   commits.

4. uv sync
   .venv/bin/python is currently a broken symlink, so the venv is dead.

5. uv run pytest tests/ -q
   Report the actual result. Do not fix failures yet — I want to know what those 32
   merged commits did before anyone changes code.

6. bash scripts/03-containers.sh
   Creates .worktrees/cleanup and .worktrees/tier2 with their charters as CLAUDE.md.

Hard rules:
- Never use `git branch -D`. Only `-d`, which refuses unmerged branches. If it refuses,
  stop and tell me.
- Do not `git push` anything except the tag in step 1. I'll push main myself after
  reading the test output.
- Do not touch data/brain/ or data/agent/ — memory/brain_writer.py writes them and
  brain_reader.py rebuilds the DB from them. They're content, not runtime state.
- Do not touch data/kanban/ or data/notebooks/ (14MB of real content). Leave the decision
  to me.
- Do not change any code in odigos/ or tests/. This is closeout only; the code cleanup is
  a separate session with its own charter.
- If a script's assumptions don't match the tree, stop and report rather than improvising.

When done, report: what got deleted (with sizes), what main is now at, which branches
remain, the pytest summary line, and anything that surprised you.
```

---

## PROMPT 2 — Project A, the actual code cleanup

> Only after Prompt 1 reports green. Open `~/Projects/test/odigos/.worktrees/cleanup` as its
> own Claude Code project — its `CLAUDE.md` is the charter, so it self-briefs.

```
Read your CLAUDE.md. It's the charter for this container and it is binding — especially
the "Hard non-goals" section.

Start with item 1 (the live bugs), and within that, set evolution.enabled: false FIRST,
before anything else. evolution.py:191 currently auto-promotes LLM-generated text into
data/agent/identity.md and guardrails.md based on trials whose treatment is never applied.

Work through the numbered sections in order. After each numbered section: run the test
suite, commit, and give me a one-paragraph summary. Do not batch multiple sections into
one commit.

Two things I want you to actively resist:
- Any urge to collapse tool families or tighten context budgets. Read
  docs/superpowers/anti-patterns.md — all 8 logged incidents came from changes that
  looked exactly like sensible cleanup. §3.2 and §3.4 of the brittleness spec forbid
  these two specifically.
- Deleting ContextAssembler.build() before porting its four live features into
  build_planned(). One of them is a prompt-injection canary. Port first, verify, then
  delete.

If you think you need something the charter forbids, write it to
docs/containers/ESCALATIONS.md and stop. Don't decide it yourself.
```

---

## Repo layout — tag, don't copy

**Don't copy odigos to a fresh folder.** The repo's history *is* the asset: it's how we proved
those 7 `feat/*` branches were fully merged, how the reflog recovered the tree when the Cowork
bridge stranded git locks, and how `git branch -d` can refuse to lose work. A parallel copy has
none of that — and the moment you hesitate over which folder is canonical, you've created
abandoned fork #6, which is the exact disease this cleanup exists to cure.

If what you want is a safety net before destructive work, that's a tag plus the remote, not a
copy:

```bash
git tag pre-cleanup-2026-08-12
git push origin pre-cleanup-2026-08-12
```

Free, permanent, unambiguous, and `git checkout pre-cleanup-2026-08-12` gets the old tree back
whenever you want it. It's step 1 of Prompt 1.

**Isolation without divergence** is what the worktrees are for. `.worktrees/cleanup` and
`.worktrees/tier2` are separate folders you can open as separate Claude Code projects, each with
its own `CLAUDE.md` and its own branch, sharing one `.git`. That's the "copy and start clean"
feeling with none of the drift.

**New folders are right for the siblings**, because those genuinely share no code:

```
Projects/test/
├── odigos/                     the kitchen sink (existing repo — keep it)
│   ├── .worktrees/cleanup/     Project A
│   └── .worktrees/tier2/       Project B
├── zodigos/                    Project C — new repo, TypeScript
└── tool-router/                Project D — new repo, zero Odigos imports
```

`scripts/03-containers.sh` prints the exact `git init` commands for those two when you get there.
Don't create them yet — C needs `docs/DESIGN-DECISIONS.md` from Project A first, and that's the
whole reason A gates it.
