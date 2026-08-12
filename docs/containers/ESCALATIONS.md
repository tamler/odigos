# Escalations

A container that needs something outside its fence writes an entry here and
STOPS. It does not reach across. Whoever is orchestrating resolves these.

## YYYY-MM-DD — <container> — <one-line summary>
**Wants:** what it needs to do
**Blocked by:** which fence or non-goal
**Case:** why it looks necessary
**Decision:**

---

## 2026-08-12 — 01-cleanup — migration 015's WebAuthn backfill becomes live and can bind a passkey to the wrong user

**Wants:** change `migrations/015_webauthn_user_id.sql` before the §0d migration-runner
fix reaches any real install — either drop the backfill `UPDATE`, or make it a no-op when
`users` holds more than one row.

**Blocked by:** the charter's escalation rule — `migrations/` is outside
`odigos/` + `tests/` + `docs/`. This is a data-model and security decision, not cleanup.

**Case:**

`015_webauthn_user_id.sql` is two statements:

```sql
ALTER TABLE webauthn_credentials ADD COLUMN user_id TEXT;
UPDATE webauthn_credentials SET user_id = (SELECT id FROM users LIMIT 1) WHERE user_id IS NULL;
```

`_evolve_schema()` adds `user_id` from `schema.sql:878` before migrations run, so the
`ALTER` always raises duplicate-column. Under the old runner that aborted the file, so
**the `UPDATE` has never executed anywhere**. The §0d fix (commit `df13c43`) makes it run.

Three facts make that dangerous rather than routine catch-up:

1. **It is unapplied everywhere.** 015 was added 2026-05-29 (`c7e8d60`) on the security
   branch merged into `main` today, so no existing install has it recorded in
   `_migrations`. It runs on the next boot of every install. (By contrast 005 and 010,
   raised in the same review, were added 2026-04-09/04-10 and *are* recorded, so
   `db.py:278` skips them — they do not re-run. Those two are not a concern.)
2. **`users` can hold more than one row.** `api/platform_auth.py:71` inserts a user with
   no zero-user gate, and disambiguates collisions by appending a numeric suffix — it
   anticipates multiple users. `api/auth.py:302` is a second ungated insert path.
   `SELECT id FROM users LIMIT 1` with no `ORDER BY` picks an arbitrary row.
3. **`user_id` is the authorization decision.** `api/webauthn.py:339-368` resolves the
   login session from `stored["user_id"]` after crypto verification and mints a session
   for that user, with no check that it matches the requesting party — correct for
   discoverable-credential login, but it means a mis-assigned row logs the passkey holder
   into someone else's account.

So on an install with 2+ users and any passkey whose `user_id` is NULL, this silently
binds those credentials to one arbitrary account. Single-user installs — the documented
tenancy model — are unaffected, which is likely why it was never noticed.

Found by adversarial review of the §0d change, then verified against the tree. Not
introduced by §0d; §0d only ends the swallowing that kept it dead.

**Recommendation:** guard the `UPDATE` with `WHERE (SELECT COUNT(*) FROM users) = 1`, or
delete it and let orphaned credentials fail closed at login (they already raise 400
"Credential is not associated with a user"). Failing closed is the safer default for an
auth path.

**Decision:** RESOLVED 2026-08-12 — delete the backfill, fail closed. Authorised by the
repo owner; the container did not edit `migrations/` on its own authority or on a peer
reviewer's request. The `UPDATE` is gone from `015_webauthn_user_id.sql`, replaced by a
comment recording why. Orphaned credentials now raise 400 at login and the holder
re-registers the passkey. Pinned by
`tests/test_webauthn_user.py::test_login_with_orphaned_credential_fails_closed`, which
asserts no session cookie is issued.

---
