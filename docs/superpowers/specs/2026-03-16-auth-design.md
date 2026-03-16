# Standalone Authentication Design

## Goal

Replace the API key browser login with username/password authentication. Single owner per instance. API key remains for programmatic access (Telegram, peers, scripts). Designed so multi-user, service billing, and OAuth can layer on later without rework.

## Context

Current auth is a single API key stored in config.yaml. The dashboard prompts for it via `LoginPrompt.tsx`, stores it in localStorage, and sends it as `Authorization: Bearer <key>` on every request. This works but is poor UX -- users copy-paste a 43-character string.

The system is self-hosted and must work standalone with no external dependencies (no OAuth providers, no internet-dependent auth).

## Dependencies

- `passlib[bcrypt]` -- password hashing (bcrypt with cost factor 12)
- `itsdangerous` -- signed session cookies (must be added explicitly to pyproject.toml)

No heavy dependencies. No SQLAlchemy, no auth frameworks.

## Database Schema

New migration (025):

```sql
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    must_change_password INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
```

UUID `id` as primary key for future service integration stability. Single row for now, table supports multiple users if needed later.

## Auth Flows

### First-run (no users exist)

1. Browser visits dashboard
2. `GET /api/auth/status` returns `{setup_required: true}`
3. Dashboard shows "Create your account" form (username, password, confirm)
4. `POST /api/auth/setup` creates user, returns HTTP-only session cookie
5. User lands in dashboard

### Normal login

1. Browser visits dashboard
2. `GET /api/auth/status` returns `{setup_required: false, authenticated: false}`
3. Dashboard shows login form
4. `POST /api/auth/login` validates credentials, sets session cookie
5. If `must_change_password` is set, forces password change before proceeding

### Provisioned account (deploy script)

1. Deploy script inserts user with `must_change_password=1` and temporary password
2. Tester visits URL, logs in with temp password
3. Immediately prompted to change password
4. `POST /api/auth/change-password` updates hash, clears flag

### Legacy mode (migration path)

Existing installs have no `users` table and use API key for everything. On startup:
- Migration creates `users` table
- If API key is set but no users exist, system works in "legacy mode" -- API key accepted for both browser and API
- First time a user creates an account via setup wizard, a `auth_mode_enabled` flag is set in the `users` table (presence of any user row indicates auth mode)
- After transition: browser requires session cookie, API still accepts API key
- Existing users aren't locked out
- The transition is persistent (survives restarts) -- auth mode is active whenever the `users` table has at least one row

## Session Cookie

- Signed with `itsdangerous.URLSafeTimedSerializer`
- Secret key: `SESSION_SECRET` env var (auto-generated during install, stored in `.env`)
- Cookie name: `odigos_session`
- Payload: `{user_id, username, must_change_password, issued_at}`
- Flags: `HttpOnly`, `Secure` (when HTTPS), `SameSite=Lax`
- TTL: 7 days (configurable)
- Not accessible to JavaScript, not sent cross-origin

## API Endpoints

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/auth/status` | GET | None | Returns `{setup_required, authenticated, must_change_password}` |
| `/api/auth/setup` | POST | None | Create first user (only when no users exist) |
| `/api/auth/login` | POST | None | Validate credentials, set session cookie |
| `/api/auth/logout` | POST | Session | Clear session cookie |
| `/api/auth/change-password` | POST | Session | Update password, clear must_change_password flag |
| `/api/auth/me` | GET | Session | Current user info for account page |

### Auth setup endpoint

```
POST /api/auth/setup
Body: {username, password}
Response: 200 + Set-Cookie: odigos_session=<signed>
Guard: Fails with 403 if any user already exists
```

### Login endpoint

```
POST /api/auth/login
Body: {username, password}
Response: 200 + Set-Cookie: odigos_session=<signed>
         200 + {must_change_password: true} if flag is set
         401 if invalid credentials
```

### Change password endpoint

```
POST /api/auth/change-password
Body: {current_password, new_password}
Response: 200 + new Set-Cookie
Guard: Requires valid session
```

## Auth Middleware

The existing `require_api_key` dependency in `odigos/api/deps.py` is renamed to `require_auth` and extended to check three methods:

1. `Authorization: Bearer <api_key>` header -- existing behavior for programmatic access
2. `Authorization: Bearer card-sk-*` header -- existing card-scoped auth (via `require_card_or_api_key`)
3. `odigos_session` cookie -- new, for browser sessions

First match wins. No auth = 401. The `/api/auth/*` endpoints are exempt (no auth required for login/setup/status).

`require_card_or_api_key` is updated to also accept session cookies. Card-scoped keys remain API-key-only by design (they're for machine-to-machine peer auth).

When a session cookie is present, the authenticated user's ID and username are available via `request.state.user`.

### WebSocket auth

The WebSocket endpoint (`/api/ws`) has its own auth flow in `_authenticate_ws`. It currently supports:
- Query param: `?token=<api_key>` (legacy)
- First message: `{type: "auth", token: "<api_key>"}`

Add a third method: session cookie. Since WebSocket upgrade requests include cookies automatically (same-origin), `_authenticate_ws` checks for a valid `odigos_session` cookie before falling back to the message-based auth. This means the dashboard WebSocket "just works" after login -- no manual token passing needed.

The peer WebSocket (`/ws/peer`) remains API-key-only (machine-to-machine).

## Dashboard Changes

### New: Auth pages

Replace `LoginPrompt.tsx` with a unified auth flow component that handles:
- Setup form (create account) when `setup_required` is true
- Login form when not authenticated
- Change password form when `must_change_password` is true

### Modified: API client

`lib/api.ts` functions stop sending `Authorization` header for browser requests. The browser automatically sends the `odigos_session` cookie. The `lib/auth.ts` module simplifies to:
- `isAuthenticated()` -- calls `/api/auth/status` instead of checking localStorage
- `logout()` -- calls `/api/auth/logout` and redirects
- Remove `getApiKey()` / `setApiKey()` / `clearApiKey()` localStorage functions

### New: Account tab in Settings

First tab in Settings. Shows:
- Username and display name (editable)
- Change password form
- API key display (read-only, for copying to scripts/Telegram)
- Logout button

### Modified: App.tsx

Replace the `isAuthenticated()` check with `/api/auth/status` call. The three states (setup required, not authenticated, authenticated) drive which component renders.

## Install Script Changes

### install.sh and install-bare.sh

After LLM configuration, optionally prompt:
```
Create owner account? [Y/n]:
Username: jacob
Password: ********
```

If yes: write credentials to a temporary file that the server reads on first startup to seed the `users` table.
If no: first-run wizard handles it in the browser.

Also generate `SESSION_SECRET` in `.env`:
```bash
session_secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
echo "SESSION_SECRET=${session_secret}" >> .env
```

### deploy-testers.sh

Changes from printing API keys to printing temporary credentials:
```
Jessica:
  URL: https://jessica.uxrls.com
  Username: jessica
  Temp Password: <generated>
  (You'll be asked to change this on first login)
```

Creates a seed file at `testers/<name>/data/seed_user.json` with format:
```json
{"username": "jessica", "password": "temp-password-here", "must_change_password": true}
```

On startup, the server checks for `data/seed_user.json`. If found and no users exist, it creates the user and deletes the seed file. This is a one-time bootstrap mechanism -- the file is consumed and removed on first startup.

## Files Modified

| File | Change |
|---|---|
| `migrations/025_users.sql` | Create users table |
| `odigos/api/auth.py` | New: auth endpoints (status, setup, login, logout, change-password, me) |
| `odigos/api/deps.py` | Rename require_api_key to require_auth, add cookie validation |
| `odigos/main.py` | Register auth router, generate SESSION_SECRET if missing |
| `dashboard/src/components/LoginPrompt.tsx` | Rewrite: login/setup/change-password flow |
| `dashboard/src/lib/auth.ts` | Simplify: cookie-based, remove localStorage key management |
| `dashboard/src/lib/api.ts` | Remove Authorization header for browser requests |
| `dashboard/src/App.tsx` | Use /api/auth/status for auth state |
| `dashboard/src/pages/SettingsPage.tsx` | Add Account tab |
| `dashboard/src/pages/settings/AccountTab.tsx` | New: account management page |
| `install.sh` | Add optional owner account creation, SESSION_SECRET generation |
| `install-bare.sh` | Same as install.sh |
| `deploy-testers.sh` | Generate temp passwords instead of API keys |
| `pyproject.toml` | Add passlib[bcrypt] and itsdangerous dependencies |
| `odigos/api/ws.py` | Add session cookie validation to _authenticate_ws |

## Out of Scope

- Multi-user / multi-tenant (solved at deployment layer)
- OAuth / OIDC (future service integration)
- Email-based password reset (no email in self-hosted)
- Session storage in DB (signed cookies are stateless)
- Rate limiting on login (defer until needed)
- CSRF tokens -- SameSite=Lax protects POST endpoints from cross-origin form submissions. GET endpoints like `/api/auth/me` are readable cross-origin via navigation timing, but contain no sensitive data beyond username. For a self-hosted single-user tool, this is acceptable risk.

## Security Properties

- Passwords hashed with bcrypt cost factor 12 (~250ms per hash)
- Minimum password length: 8 characters (enforced server-side on setup and change-password)
- Session cookies: HttpOnly (no XSS access), Secure (HTTPS only), SameSite=Lax (no CSRF via cross-origin POST)
- `must_change_password` flag included in signed cookie payload and checked by middleware -- requests other than change-password are blocked until resolved
- Setup endpoint locked after first user created (cannot create second account via API)
- API key remains for machine access (unchanged security model)
- SESSION_SECRET auto-generated per install (no shared secrets)
- WebSocket auth: session cookie validated on upgrade request (same-origin, automatic)
