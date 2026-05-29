# OS Install Isolation Checklist (C0) — Hosted VPS

> Host-side hardening for the new OVH VPS (51.81.82.221). Executed during/after migration, separate from the in-repo security plan (`docs/superpowers/specs/2026-05-29-security-hardening-multitenant.md`). This is the permission contract that makes the "separate process + filesystem root per account" model real — without it, the in-repo sandbox (C1) is the *only* cross-install boundary.

**Verified gap this fixes:** the old `deploy.sh:34-38` runs `/opt/odigos`, `/opt/odigos-rachel`, `/opt/odigos-honey`, `/opt/odigos-homerun` **all as the same Unix user `odigos_agent`** → every install can read every sibling's `.env`, DB, and data. On the new VPS, Bob and Jessica must run as **distinct users**.

## Acceptance invariant
From Bob's app process it must be impossible to read Jessica's install files, reach Jessica's local service, or read Jessica's backups — and vice versa.

## Checklist

### Distinct Unix users
- [ ] Create `odigos_bob` and `odigos_jessica` (no shared `odigos_agent`); no shared supplementary group with read access to the other's root.
- [ ] `chown -R odigos_bob:odigos_bob /opt/odigos` ; `chown -R odigos_jessica:odigos_jessica /opt/odigos-jessica`.
- [ ] Update `deploy.sh` install table so each dir maps to its **own** service user (in-repo touchpoint); the deploy `chown` uses that user. Add a lint/test asserting the user column has no duplicates across distinct accounts.

### Filesystem permissions
- [ ] `chmod 700 /opt/odigos /opt/odigos/data` and the equivalents for Jessica; `chmod 600` on `.env` and `config.yaml`, owned by the install user.
- [ ] Verify a sibling user gets permission-denied: as `odigos_bob`, `cat /opt/odigos-jessica/.env` → denied; same for `config.yaml`, `data/odigos.db`, and any backup artifact.

### systemd unit hardening (per service: odigos / odigos-jessica)
- [ ] `User=odigos_bob` (and `odigos_jessica`) — the dedicated user.
- [ ] `NoNewPrivileges=yes`
- [ ] `ProtectSystem=strict`
- [ ] `ProtectHome=yes`
- [ ] `PrivateTmp=yes`
- [ ] `ReadWritePaths=/opt/odigos/data` (only this install's data; equivalent for Jessica)
- [ ] `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`
- [ ] **Verify bubblewrap still works under the chosen `RestrictNamespaces`/`SystemCallFilter`** — bwrap needs user namespaces; do not lock these so tight that the sandbox (C1) breaks. Run the sandbox self-test after applying the unit.

### Backups
- [ ] Backup/export artifacts (from `storage.py` / `core/data_export.py`) write under the install's `0700` data dir, owned by the install user. No world/group read. No install user can read another's backups.

### Fleet conformance (run in deploy preflight + on demand)
- [ ] Every hosted install: `deployment.mode=hosted`, distinct `User=`, all systemd hardening directives present, `0700` root/data, same app version, `bwrap` present, no `ODIGOS_SANDBOX_ALLOW_INSECURE` in env.
- [ ] Deploy preflight fails the release if any of the above is missing or the sandbox self-test fails.

## Cross-references
- In-repo sandbox enforcement + escape tests: spec C1.
- SSRF blocking of sibling local ports (8002/5432/2019): spec H1–H4.
- `deployment.mode=hosted` invariant: spec "Deployment security mode".
