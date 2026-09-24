# Team Accounts: Login, Signup and User Management

Date: 2026-09-24
Status: Draft for review

## Goal

Put HighLyte behind login. A team admin signs up (which creates the team),
adds users by email, and each user gets an auto-generated password the admin
copies and sends them. Users log in with it and share all of the team's
projects. Only admins can sign up; users can only log in.

## Decisions

| Topic | Decision |
|---|---|
| Identity | Supabase Auth (email + password), accessed only by FastAPI |
| Login traffic | Approach B: the frontend never talks to Supabase; FastAPI proxies login/refresh/logout |
| Session storage | httpOnly cookies set by FastAPI |
| Roles | `admin` (the signup account) and `member` (created by the admin) |
| Member permissions | Same as admin for all video/clip work; no user management |
| Admin user management | Add user (generated password shown once) and remove user; no reset, no forced password change |
| Admin signup | No email confirmation; logged in immediately |
| Existing data | The first team to sign up claims every project with no team |
| Team membership | One user belongs to exactly one team |
| Supabase unset | Accounts require Supabase: every API except `/api/health` returns 503 (replaces the earlier "runs without Supabase" rule) |
| Verification | pytest only; the user does the browser check |

## Data (already applied by the user)

```sql
teams(id uuid pk default gen_random_uuid(), name text not null, created_at)
team_members(user_id uuid pk -> auth.users on delete cascade,
             team_id uuid not null -> teams on delete cascade,
             role text check in ('admin','member'), email text not null, created_at)
jobs.team_id uuid -> teams on delete cascade
jobs.created_by uuid -> auth.users on delete set null
index team_members(team_id); index jobs(team_id, created_at desc)
RLS enabled (no policies) on teams, team_members (and recommended on jobs, clips, renders)
```

Clips and renders belong to a team through their job. The SQL is appended to
`supabase/schema.sql` for the record.

## Backend

### Supabase Auth calls (`backend/auth.py`)

All over HTTPS with the service-role key as `apikey`, using `httpx`:

- Password login: `POST {SUPABASE_URL}/auth/v1/token?grant_type=password` `{email, password}`
- Refresh: `POST {SUPABASE_URL}/auth/v1/token?grant_type=refresh_token` `{refresh_token}`
- Who is this token: `GET {SUPABASE_URL}/auth/v1/user` with `Authorization: Bearer <access>`
- Logout: `POST {SUPABASE_URL}/auth/v1/logout` with `Authorization: Bearer <access>`
- Create/delete users: `client.auth.admin.create_user({"email", "password", "email_confirm": True})`
  and `client.auth.admin.delete_user(user_id)` via the existing supabase-py client.

Token checks are cached in memory for 60 s (token → user id, email), so most
requests don't call Supabase. The cache is keyed by the access token and
entries for a deleted user are dropped when that user is removed.

### Cookies

- `hl_access` (access token) and `hl_refresh` (refresh token), both
  `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` when `COOKIE_SECURE=true`
  (env, default false for local http).
- `hl_access` max-age = the token's `expires_in`; `hl_refresh` max-age 30 days.

### Request authentication (FastAPI dependency `current_member`)

1. Read `hl_access`; if valid (cached or `GET /auth/v1/user`), use it.
2. If missing or rejected and `hl_refresh` exists, refresh; on success set
   both new cookies on the response and continue.
3. Otherwise 401.
4. Look up `team_members` for the user id; no row → 401 (account removed or
   never joined a team).
5. Returns `Member(user_id, email, team_id, team_name, role)`.

`admin_member` wraps it and returns 403 for members.

### CSRF

Every non-GET request under `/api/` must carry `X-Requested-With: highlyte`,
else 403. The frontend's axios instance sends it on every request. Combined
with `SameSite=Lax`, other sites can't make authenticated changes.

### Endpoints

| Endpoint | Auth | Behaviour |
|---|---|---|
| `POST /api/auth/signup` `{teamName, email, password}` | none | Validate (team name 1-80 chars, email, password ≥ 8). Create the auth user (confirmed), the team, the admin membership. If this is the only team, set `team_id` on every job where it is null. Log in and set cookies. Returns `/me` shape. |
| `POST /api/auth/login` `{email, password}` | none | Set cookies; returns `/me` shape. Wrong credentials → 401 "Incorrect email or password." A valid login with no team membership → 401 same message. |
| `POST /api/auth/logout` | logged in | Supabase logout (errors ignored), clear cookies, 204 |
| `GET /api/auth/me` | logged in | `{user: {id, email}, team: {id, name}, role}` |
| `GET /api/team/users` | admin | `[{id, email, role, createdAt}]`, admin first then by `createdAt` |
| `POST /api/team/users` `{email}` | admin | Generate a 16-character password (letters + digits, `secrets`), create the auth user (confirmed) and a `member` row. Returns `{user: {id, email, role, createdAt}, password}`. The password is never stored or returned again. |
| `DELETE /api/team/users/{user_id}` | admin | 404 unless the user is in the admin's team; 400 for the admin's own id; delete the auth user (the membership row cascades); drop their cached tokens; 204 |

Existing email on signup or add user → 409 "That email already has an
account." Supabase Auth unreachable → 503 "Login is unavailable right now.
Try again shortly."

### Team scoping of existing APIs

Every existing endpoint except `/api/health` requires `current_member`:

- `POST /api/generate` stores `team_id` and `created_by` on the in-memory
  `Job` and in the `jobs` row.
- `GET /api/jobs` lists only the member's team (Supabase filter on `team_id`;
  in-memory jobs filtered by `job.team_id`).
- `/api/status/{id}`, `/api/clips/{job}/{file}`, clip style, render, render
  file and zip endpoints load the job (memory or Supabase) and return 404
  when its `team_id` differs from the member's.
- `GET /api/clips` (clip list) filters to the team's jobs.
- The pipeline thread and `RenderService` are unchanged apart from receiving
  already-authorised ids.

### No Supabase

If `SUPABASE_URL`/`SUPABASE_KEY` are unset, every `/api/*` route except
`/api/health` returns 503 "Accounts need Supabase", and `/api/health`
reports `"auth": false`.

## Frontend

### Same-origin API

- `vite.config.js` proxies `/api` to `http://127.0.0.1:8000`.
- `highlyteApi.js` uses a relative base URL (`''`), sends
  `withCredentials: true` and `X-Requested-With: highlyte`, and on a 401
  from anything except `/api/auth/*` redirects to
  `/login?next=<current path>`.
- `VITE_API_BASE_URL` is removed from `frontend/.env` and the code.

### Auth store (`stores/authStore.js`)

State `me` (null or the `/me` shape), `checked` (bool). Actions `load()`
(GET `/me`, 401 → `me = null`), `login`, `signup`, `logout`. Getter
`isAdmin`.

### Router guard

Before each navigation: if the auth store isn't `checked`, `await load()`.
Routes `/login` and `/signup` are public (a logged-in user is sent to
`/`). All others need `me`, else redirect to `/login?next=…`. `/team`
needs `isAdmin`, else redirect to `/`.

### Pages

- `LoginView.vue` (`/login`): email, password, Log in; error text from the
  API; link "Create a team" to `/signup`; note "Users: ask your team admin
  for your login." After login go to `next` or `/`.
- `SignupView.vue` (`/signup`): team name, admin email, password, confirm
  password (client-side check that they match and are ≥ 8 characters);
  Create team; then `/`. Link back to login.
- `TeamView.vue` (`/team`, admin): member list (email, Admin/User badge,
  added date, Remove button for members with a confirmation "Remove
  <email>? They won't be able to log in."). "Add user" form (email). On
  success a panel shows the email and password, a Copy button (copies
  `Email: <email>\nPassword: <password>`) and "This password is shown only
  once. Copy it now and send it to the user." Dismissing the panel clears
  the password from memory.
- The auth pages render without the top bar (`App.vue` hides `TopBar` on
  routes with `meta.public`).

### Top bar

Tabs Home, Projects, and Team (admin only). Right side: an account menu
button showing the team name; its dropdown shows the email and Log out.
Logout calls the API, clears the stores and goes to `/login`.

## Testing

pytest, with Supabase Auth HTTP calls and admin calls faked (no network):

- signup creates team + admin membership, sets both cookies, claims
  unowned jobs only when it's the first team; duplicate email → 409;
  validation errors → 422
- login success/failure (401 message), login with no membership → 401
- `/me` shape; logout clears cookies
- expired access + valid refresh → request succeeds and new cookies are set;
  invalid refresh → 401
- non-GET without `X-Requested-With` → 403
- member calling team endpoints → 403
- add user returns a 16-character password once and creates a member row;
  admin can't delete self (400); deleting a user from another team → 404
- team isolation: another team's project status, clip file, style PATCH,
  render and project list entries → 404 / absent
- no Supabase → 503 on a protected route, `/api/health` reports `auth: false`
- existing API tests updated to authenticate as a test member

The browser check is done by the user.
