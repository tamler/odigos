# Container 02 — tier 2: team / company self-host

**Outcome:** a company admin can provision, manage and cost-account **N fully isolated
single-person installs** on hardware they control.

Starts after Container 01. Read `docs/superpowers/specs/2026-05-29-security-hardening-multitenant.md`
and `docs/deployment/2026-05-29-os-isolation-checklist.md` first — they define the boundary you
are building, and 32 commits of it already shipped to `main` in the Phase 0 closeout.

---

## The model — do not reinterpret this

Each person gets **their own instance**. One process, one SQLite DB, one filesystem root, one
brain. "Multi-user" means *more installs*, not shared data.

- ❌ **Never** add `user_id`/`tenant_id` to data tables. 68 of 69 tables have no tenancy
  column and 642 raw SQL sites; that is the design, not a gap.
- ❌ No shared-row tenancy, no cross-install object scoping, no per-tenant cache keys. The
  security spec names these explicitly out of scope.
- ✅ Isolation is the **OS/filesystem/network/process boundary** between installs.

The acceptance invariant is already written, and it is your test:

> From Bob's app process, Bob's sandboxed code, and Bob's URL-capable tools, it must be
> impossible to read Jessica's install files, reach Jessica's local service, reach host-local
> admin services, or perform state-changing actions without Bob's authenticated browser
> session and CSRF proof.

**The admin control plane lives OUTSIDE every instance — a separate process with no read access
to any instance's DB or data dir.** Putting fleet management inside an agent would breach the
boundary you are building. This is what `odigos-platform` was; un-archive and reuse it rather
than growing a second one.

---

## Work

1. **Prove the boundary.** Stand up two real installs and write the cross-install A→B tests at
   all four boundaries (filesystem, network, backup, process). The sandbox-escape,
   SSRF-guard and arg-guard tests merged in Phase 0 are the primitives; this is the
   integration proof. **Nothing else in this container matters until this is green.**
2. **Provisioning CLI.** One command creates an isolated install: OS user, filesystem root,
   `data/` + SQLite DB, port assignment, reverse-proxy vhost, service unit, generated secrets
   in `.env` (not `config.yaml` — see commit `a73ceef`), first-login credentials. Idempotent,
   and with a matching deprovision that archives before removing. Raw material:
   `deploy.sh`, `deploy-testers.sh`, `install-bare.sh`, and `core/spawner.py` (256) +
   `core/template_index.py` (317) — but see the note below.
3. **Admin control plane.** List installs with health/version/last-login, create, suspend,
   deprovision, and **fleet cost aggregation** — each instance's `/api/budget` is per-instance
   today, and ROADMAP already flags the missing cross-agent aggregator. Runs as its own service.
4. **Fleet operations.** Rolling update across N installs, per-install backup/restore verified
   by an actual restore, and a schema-drift check (this bit the OVH Postgres already — indexes
   declared in migrations were missing live).

### Open question for the manager, not for you

`core/spawner.py` and `core/template_index.py` currently live **inside** the agent. Provisioning
is a control-plane concern, so they probably belong in the control plane instead. Don't move
them unilaterally — write the case to `ESCALATIONS.md`.

## Hard non-goals

❌ Billing, subscriptions, public signup, SSO beyond what exists — that is tier 3.
❌ Any change to the agent's own data model.
❌ Touching container 01's cleanup surface, ZOdigos, or the tool-router.

## Definition of done

- [ ] Cross-install A→B tests green at all four boundaries, in CI
- [ ] `provision <name>` → working isolated install in one command; `deprovision` archives first
- [ ] Control plane lists/creates/suspends installs and reports fleet-wide spend
- [ ] Rolling update and a *verified* restore, both exercised
- [ ] A deployment doc a company sysadmin can follow without you
