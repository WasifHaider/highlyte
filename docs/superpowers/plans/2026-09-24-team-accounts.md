# Team Accounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put HighLyte behind login: a team admin signs up, adds users with generated passwords, and everyone in a team shares its projects.

**Architecture:** FastAPI talks to Supabase Auth (GoTrue) over HTTP (`backend/auth.py`) and keeps the session in httpOnly cookies. `backend/accounts.py` holds the login/signup/team endpoints, a CSRF middleware and the `current_member` / `admin_member` dependencies; every existing endpoint takes `current_member` and only sees its team's jobs. The Vue app talks to `/api` on its own origin (Vite proxy), has an auth store with a router guard, login/signup pages, a Team page and an account menu.

**Tech Stack:** Python 3.11, FastAPI, httpx 0.27, Supabase (PostgREST + Auth), pytest; Vue 3, Vue Router, Pinia, axios, Vite.

**Spec:** `docs/superpowers/specs/2026-09-24-team-accounts-design.md`

## Global Constraints

- Cookies: `hl_access` (max-age = token `expires_in`) and `hl_refresh` (max-age 30 days); `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` only when env `COOKIE_SECURE` is `1`/`true`/`yes`.
- CSRF: every non-GET/HEAD/OPTIONS request to `/api/*` needs header `X-Requested-With: highlyte`, else 403.
- Token check cache: 60 s. Generated passwords: 16 characters, letters + digits, from `secrets`.
- Messages (exact): wrong login "Incorrect email or password."; duplicate email "That email already has an account."; Supabase Auth down "Login is unavailable right now. Try again shortly."; no Supabase "Accounts need Supabase".
- Signup validation: team name 1-80 characters after trimming; email; password at least 8 characters.
- Roles: `admin` and `member`. Members can do all video/clip work; only admins use `/api/team/*`. An admin can't remove their own account.
- The first team to sign up claims every job whose `team_id` is null.
- Another team's project, clip, style or render → 404 (never 403).
- Every `/api/*` route except `/api/health` needs Supabase; without it → 503 "Accounts need Supabase".
- The frontend never talks to Supabase; it calls `/api` on its own origin with `withCredentials` and the CSRF header.
- The user does the browser check; tasks verify with pytest and `npm --prefix frontend run build`.
- Comments explain *why*, in full sentences, at the density of the surrounding code.

## Deviations from the spec (decided while planning)

- Admin create/delete user also go through GoTrue HTTP (`POST/DELETE /auth/v1/admin/users`) instead of supabase-py, so every Auth call shares one httpx client and one test fake.
- Member lookups are cached for 60 s alongside token checks, so the 1 s job polling doesn't hit Supabase twice per request; removing a user clears both caches.
- When a media endpoint (clip file, render file, zip) refreshes an expired session, the new cookies can't ride on its redirect/file response; the next JSON request refreshes again. Media still loads.

## File Structure

```
backend/
  auth.py          NEW  Supabase Auth over HTTP: login, refresh, token check (cached), logout, admin create/delete, password generator
  accounts.py      NEW  Member, cookies, CSRF middleware, current_member/admin_member, /api/auth/* and /api/team/* router
  db.py            MOD  team functions; list_jobs/list_clips filtered by team
  main.py          MOD  router + middleware, Job.team_id/created_by, team checks on every endpoint
supabase/schema.sql MOD record the accounts SQL
pytest.ini         MOD  real_auth marker
tests/support.py   NEW  FakeGoTrue, FakeTeamDb, install helpers, api_client, TEST_TEAM_ID
tests/conftest.py  MOD  autouse logged-in member (skipped for real_auth tests)
tests/test_auth.py, tests/test_accounts.py, tests/test_team_scope.py NEW
tests/test_validation.py, test_status.py, test_jobs_api.py, test_render_api.py MOD
frontend/
  vite.config.js                 MOD  /api proxy
  src/services/highlyteApi.js    MOD  same-origin client, CSRF header, 401 redirect, auth + team calls
  src/stores/authStore.js        NEW
  src/utils/authRedirect.js      NEW  safeNext
  src/styles/auth.css            NEW  shared login/signup styles
  src/views/LoginView.vue, SignupView.vue, TeamView.vue NEW
  src/router/index.js            MOD  routes + guard
  src/App.vue                    MOD  hide TopBar on public pages
  src/components/TopBar.vue      MOD  Team tab + account menu
```

---

### Task 1: Supabase Auth client (`backend/auth.py`)

**Files:**
- Create: `backend/auth.py`, `tests/support.py`, `tests/test_auth.py`

**Interfaces:**
- Produces (`backend/auth.py`): exceptions `AuthError`, `InvalidCredentials(AuthError)`, `EmailTaken(AuthError)`, `AuthUnavailable(AuthError)`; dataclasses `AuthUser(id, email)`, `Session(access_token, refresh_token, expires_in, user)`; functions `password_login(email, password) -> Session`, `refresh_session(refresh_token) -> Session`, `user_for_token(access_token) -> AuthUser | None`, `logout(access_token) -> None`, `create_user(email, password) -> AuthUser`, `delete_user(user_id) -> None`, `forget_user(user_id) -> None`, `generate_password() -> str`; module attributes `_client` (httpx.Client) and `_cache` (dict) that tests replace/clear.
- Produces (`tests/support.py`): `FakeGoTrue` (callable httpx MockTransport handler with `add_user(email, password) -> user_id`, `users`, `down`), `install_gotrue(monkeypatch) -> FakeGoTrue`.

- [ ] **Step 1: Test support** — `tests/support.py`:
```python
"""Shared fakes for tests that exercise login and teams without a network."""
from __future__ import annotations

import json

import httpx

from backend import auth, db


class FakeGoTrue:
    """In-memory stand-in for Supabase Auth's HTTP API, mounted as an httpx
    MockTransport handler."""

    def __init__(self) -> None:
        self.users: dict[str, dict] = {}      # email -> {"id", "password"}
        self.access: dict[str, str] = {}      # access token -> email
        self.refresh: dict[str, str] = {}     # refresh token -> email
        self.down = False
        self._n = 0

    def add_user(self, email: str, password: str) -> str:
        user_id = f"00000000-0000-0000-0000-{len(self.users) + 1:012d}"
        self.users[email] = {"id": user_id, "password": password}
        return user_id

    def _issue(self, email: str) -> dict:
        self._n += 1
        access, refresh = f"access-{self._n}", f"refresh-{self._n}"
        self.access[access] = email
        self.refresh[refresh] = email
        return {
            "access_token": access, "refresh_token": refresh, "expires_in": 3600,
            "user": {"id": self.users[email]["id"], "email": email},
        }

    def _email_for_id(self, user_id: str) -> str | None:
        return next((e for e, u in self.users.items() if u["id"] == user_id), None)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("supabase down", request=request)
        path = request.url.path
        grant = request.url.params.get("grant_type")
        body = json.loads(request.content or b"{}")
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")

        if path == "/auth/v1/token" and grant == "password":
            user = self.users.get(body.get("email"))
            if user is None or user["password"] != body.get("password"):
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self._issue(body["email"]))
        if path == "/auth/v1/token" and grant == "refresh_token":
            email = self.refresh.pop(body.get("refresh_token"), None)
            if email is None or email not in self.users:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self._issue(email))
        if path == "/auth/v1/user" and request.method == "GET":
            email = self.access.get(bearer)
            if email is None or email not in self.users:
                return httpx.Response(401, json={"msg": "invalid token"})
            return httpx.Response(200, json={"id": self.users[email]["id"], "email": email})
        if path == "/auth/v1/logout":
            self.access.pop(bearer, None)
            return httpx.Response(204)
        if path == "/auth/v1/admin/users" and request.method == "POST":
            if body["email"] in self.users:
                return httpx.Response(422, json={"error_code": "email_exists", "msg": "A user with this email address has already been registered"})
            user_id = self.add_user(body["email"], body["password"])
            return httpx.Response(200, json={"id": user_id, "email": body["email"]})
        if path.startswith("/auth/v1/admin/users/") and request.method == "DELETE":
            email = self._email_for_id(path.rsplit("/", 1)[-1])
            if email is None:
                return httpx.Response(404, json={"msg": "User not found"})
            del self.users[email]
            self.access = {t: e for t, e in self.access.items() if e != email}
            self.refresh = {t: e for t, e in self.refresh.items() if e != email}
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"msg": f"unexpected {request.method} {path}"})


def install_gotrue(monkeypatch) -> FakeGoTrue:
    fake = FakeGoTrue()
    monkeypatch.setattr(db, "SUPABASE_URL", "https://sb.test")
    monkeypatch.setattr(db, "SUPABASE_KEY", "service-key")
    monkeypatch.setattr(auth, "_client", httpx.Client(transport=httpx.MockTransport(fake)))
    auth._cache.clear()
    return fake
```

- [ ] **Step 2: Write the failing tests** — `tests/test_auth.py`:
```python
import pytest

from backend import auth
from tests.support import install_gotrue


@pytest.fixture
def gotrue(monkeypatch):
    return install_gotrue(monkeypatch)


def test_password_login_and_token_check(gotrue):
    user_id = gotrue.add_user("a@x.com", "password1")
    session = auth.password_login("a@x.com", "password1")
    assert session.user == auth.AuthUser(id=user_id, email="a@x.com")
    assert session.expires_in == 3600
    assert auth.user_for_token(session.access_token) == session.user


def test_wrong_password(gotrue):
    gotrue.add_user("a@x.com", "password1")
    with pytest.raises(auth.InvalidCredentials):
        auth.password_login("a@x.com", "nope")


def test_token_check_is_cached(gotrue):
    gotrue.add_user("a@x.com", "password1")
    session = auth.password_login("a@x.com", "password1")
    gotrue.down = True  # a cached token must not need Supabase
    assert auth.user_for_token(session.access_token).email == "a@x.com"


def test_unknown_token_is_none(gotrue):
    assert auth.user_for_token("bogus") is None


def test_refresh(gotrue):
    gotrue.add_user("a@x.com", "password1")
    first = auth.password_login("a@x.com", "password1")
    second = auth.refresh_session(first.refresh_token)
    assert second.access_token != first.access_token
    with pytest.raises(auth.InvalidCredentials):
        auth.refresh_session(first.refresh_token)  # refresh tokens are single-use


def test_supabase_down(gotrue):
    gotrue.down = True
    with pytest.raises(auth.AuthUnavailable):
        auth.password_login("a@x.com", "password1")


def test_create_and_delete_user(gotrue):
    user = auth.create_user("b@x.com", "generated1")
    assert user.email == "b@x.com"
    with pytest.raises(auth.EmailTaken):
        auth.create_user("b@x.com", "other")
    session = auth.password_login("b@x.com", "generated1")
    auth.delete_user(user.id)
    assert auth.user_for_token(session.access_token) is None  # cache dropped too


def test_logout_forgets_token(gotrue):
    gotrue.add_user("a@x.com", "password1")
    session = auth.password_login("a@x.com", "password1")
    auth.logout(session.access_token)
    assert auth.user_for_token(session.access_token) is None


def test_generate_password():
    passwords = {auth.generate_password() for _ in range(50)}
    assert len(passwords) == 50
    assert all(len(p) == 16 and p.isalnum() for p in passwords)
```

- [ ] **Step 3: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_auth.py -v`
Expected: FAIL — `cannot import name 'auth' from 'backend'`.

- [ ] **Step 4: Implement** — `backend/auth.py`:
```python
"""Supabase Auth (GoTrue) over HTTP: password login, token refresh, checking
who a token belongs to, logout, and the admin calls that create and delete
team users. Only the backend talks to Supabase Auth, using the service-role
key it already has, so the browser never holds a Supabase key.
"""
from __future__ import annotations

import secrets
import string
import threading
import time
from dataclasses import dataclass

import httpx

from . import db

HTTP_TIMEOUT_S = 10.0
# How long a token check is trusted before asking Supabase again. Also the
# longest a removed user's open browser keeps working.
TOKEN_CACHE_TTL_S = 60.0
GENERATED_PASSWORD_LENGTH = 16
_PASSWORD_ALPHABET = string.ascii_letters + string.digits


class AuthError(Exception):
    pass


class InvalidCredentials(AuthError):
    pass


class EmailTaken(AuthError):
    pass


class AuthUnavailable(AuthError):
    pass


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str


@dataclass(frozen=True)
class Session:
    access_token: str
    refresh_token: str
    expires_in: int
    user: AuthUser


_client = httpx.Client(timeout=HTTP_TIMEOUT_S)
_cache: dict[str, tuple[float, AuthUser]] = {}
_cache_lock = threading.Lock()


def _url(path: str) -> str:
    return f"{(db.SUPABASE_URL or '').rstrip('/')}/auth/v1{path}"


def _headers(bearer: str | None) -> dict[str, str]:
    key = db.SUPABASE_KEY or ""
    return {"apikey": key, "Authorization": f"Bearer {bearer or key}"}


def _request(method: str, path: str, *, bearer: str | None = None, json: dict | None = None) -> httpx.Response:
    try:
        resp = _client.request(method, _url(path), headers=_headers(bearer), json=json)
    except httpx.HTTPError as e:
        raise AuthUnavailable(str(e)) from e
    if resp.status_code >= 500:
        raise AuthUnavailable(f"Supabase Auth returned {resp.status_code}")
    return resp


def _remember(token: str, user: AuthUser) -> None:
    with _cache_lock:
        _cache[token] = (time.monotonic() + TOKEN_CACHE_TTL_S, user)


def _session(data: dict) -> Session:
    user = AuthUser(id=data["user"]["id"], email=data["user"]["email"])
    session = Session(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_in=int(data.get("expires_in") or 3600),
        user=user,
    )
    _remember(session.access_token, user)
    return session


def password_login(email: str, password: str) -> Session:
    resp = _request("POST", "/token?grant_type=password", json={"email": email, "password": password})
    if resp.status_code != 200:
        raise InvalidCredentials()
    return _session(resp.json())


def refresh_session(refresh_token: str) -> Session:
    resp = _request("POST", "/token?grant_type=refresh_token", json={"refresh_token": refresh_token})
    if resp.status_code != 200:
        raise InvalidCredentials()
    return _session(resp.json())


def user_for_token(access_token: str) -> AuthUser | None:
    with _cache_lock:
        hit = _cache.get(access_token)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]
    resp = _request("GET", "/user", bearer=access_token)
    if resp.status_code != 200:
        with _cache_lock:
            _cache.pop(access_token, None)
        return None
    data = resp.json()
    user = AuthUser(id=data["id"], email=data["email"])
    _remember(access_token, user)
    return user


def logout(access_token: str) -> None:
    with _cache_lock:
        _cache.pop(access_token, None)
    try:
        _request("POST", "/logout", bearer=access_token)
    except AuthUnavailable:
        pass  # the cookies are cleared either way; the token expires on its own


def create_user(email: str, password: str) -> AuthUser:
    """Creates an already-confirmed account (no confirmation email)."""
    resp = _request("POST", "/admin/users", json={"email": email, "password": password, "email_confirm": True})
    if resp.status_code in (400, 409, 422) and any(w in resp.text.lower() for w in ("exist", "already")):
        raise EmailTaken()
    if not resp.is_success:
        raise AuthError(f"create user failed: {resp.status_code} {resp.text[:200]}")
    data = resp.json()
    return AuthUser(id=data["id"], email=data["email"])


def delete_user(user_id: str) -> None:
    resp = _request("DELETE", f"/admin/users/{user_id}")
    if not resp.is_success and resp.status_code != 404:
        raise AuthError(f"delete user failed: {resp.status_code} {resp.text[:200]}")
    forget_user(user_id)


def forget_user(user_id: str) -> None:
    with _cache_lock:
        for token in [t for t, (_, u) in _cache.items() if u.id == user_id]:
            del _cache[token]


def generate_password() -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(GENERATED_PASSWORD_LENGTH))
```

- [ ] **Step 5: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest -v`
Expected: all PASS.

- [ ] **Step 6: Commit**
```bash
git add backend/auth.py tests/support.py tests/test_auth.py
git commit -m "Add Supabase Auth client for login, refresh and team users"
```

---

### Task 2: Accounts API — login, signup, team users, CSRF

**Files:**
- Create: `backend/accounts.py`, `tests/test_accounts.py`
- Modify: `backend/db.py`, `backend/main.py` (router, middleware, health), `pytest.ini`, `tests/support.py`

**Interfaces:**
- Consumes: everything `backend/auth.py` produces (Task 1); `FakeGoTrue`, `install_gotrue` (Task 1).
- Produces (`backend/accounts.py`): `Member(user_id, email, team_id, team_name, role)` with `.to_me() -> dict`; `current_member(request, response) -> Member` and `admin_member(member) -> Member` (FastAPI dependencies); `router` (APIRouter); `csrf_middleware(request, call_next)`; constants `ACCESS_COOKIE = "hl_access"`, `REFRESH_COOKIE = "hl_refresh"`.
- Produces (`backend/db.py`): `create_team(name) -> dict`, `add_member(user_id, team_id, role, email) -> dict`, `get_member(user_id) -> dict | None` (row plus `teams: {name}`), `list_members(team_id) -> list[dict]`, `count_teams() -> int`, `claim_unowned_jobs(team_id) -> None`.
- Produces (`tests/support.py`): `FakeTeamDb`, `install_team_db(monkeypatch) -> FakeTeamDb`, `api_client() -> TestClient` (sends the CSRF header).
- `/api/health` gains `"auth": bool`.

- [ ] **Step 1: Marker** — in `pytest.ini` add under `markers =`:
```
    real_auth: uses the real login dependency instead of the default test member
```

- [ ] **Step 2: Test support** — append to `tests/support.py`:
```python
from fastapi.testclient import TestClient


class FakeTeamDb:
    def __init__(self) -> None:
        self.teams: dict[str, dict] = {}
        self.members: dict[str, dict] = {}
        self.claimed: list[str] = []

    def create_team(self, name: str) -> dict:
        team_id = f"team-{len(self.teams) + 1}"
        self.teams[team_id] = {"id": team_id, "name": name}
        return self.teams[team_id]

    def add_member(self, user_id: str, team_id: str, role: str, email: str) -> dict:
        row = {"user_id": user_id, "team_id": team_id, "role": role, "email": email,
               "created_at": f"2026-09-24T00:00:{len(self.members):02d}+00:00"}
        self.members[user_id] = row
        return row

    def get_member(self, user_id: str) -> dict | None:
        row = self.members.get(user_id)
        return None if row is None else {**row, "teams": {"name": self.teams[row["team_id"]]["name"]}}

    def list_members(self, team_id: str) -> list[dict]:
        return [r for r in self.members.values() if r["team_id"] == team_id]

    def count_teams(self) -> int:
        return len(self.teams)

    def claim_unowned_jobs(self, team_id: str) -> None:
        self.claimed.append(team_id)


def install_team_db(monkeypatch) -> FakeTeamDb:
    fake = FakeTeamDb()
    for name in ("create_team", "add_member", "get_member", "list_members", "count_teams", "claim_unowned_jobs"):
        monkeypatch.setattr(db, name, getattr(fake, name))
    monkeypatch.setattr(db, "is_enabled", lambda: True)
    return fake


def api_client() -> TestClient:
    from backend.main import app

    return TestClient(app, headers={"X-Requested-With": "highlyte"})
```

- [ ] **Step 3: Write the failing tests** — `tests/test_accounts.py`:
```python
import pytest

from backend import accounts, db
from tests.support import api_client, install_gotrue, install_team_db

pytestmark = pytest.mark.real_auth


@pytest.fixture
def env(monkeypatch):
    gotrue = install_gotrue(monkeypatch)
    teams = install_team_db(monkeypatch)
    accounts._member_cache.clear()
    return gotrue, teams


def _signup(client, email="admin@x.com", team="Pod team", password="password1"):
    return client.post("/api/auth/signup", json={"teamName": team, "email": email, "password": password})


def test_signup_creates_team_admin_and_logs_in(env):
    gotrue, teams = env
    c = api_client()
    r = _signup(c)
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "admin" and body["team"]["name"] == "Pod team" and body["user"]["email"] == "admin@x.com"
    assert "hl_access" in c.cookies and "hl_refresh" in c.cookies
    set_cookie = r.headers.get_list("set-cookie")
    assert all("httponly" in h.lower() and "samesite=lax" in h.lower() for h in set_cookie)
    assert teams.claimed == [body["team"]["id"]]  # first team claims old projects
    assert c.get("/api/auth/me").json() == body


def test_second_team_does_not_claim(env):
    _, teams = env
    _signup(api_client())
    _signup(api_client(), email="other@x.com", team="Other")
    assert len(teams.claimed) == 1


@pytest.mark.parametrize("payload", [
    {"teamName": "  ", "email": "a@x.com", "password": "password1"},
    {"teamName": "T", "email": "not-an-email", "password": "password1"},
    {"teamName": "T", "email": "a@x.com", "password": "short"},
    {"teamName": "x" * 81, "email": "a@x.com", "password": "password1"},
])
def test_signup_validation(env, payload):
    assert api_client().post("/api/auth/signup", json=payload).status_code == 422


def test_signup_duplicate_email(env):
    _signup(api_client())
    r = _signup(api_client(), team="Again")
    assert r.status_code == 409
    assert r.json()["detail"] == "That email already has an account."


def test_login_and_wrong_password(env):
    _signup(api_client())
    c = api_client()
    assert c.post("/api/auth/login", json={"email": "admin@x.com", "password": "password1"}).status_code == 200
    bad = api_client().post("/api/auth/login", json={"email": "admin@x.com", "password": "wrong"})
    assert bad.status_code == 401 and bad.json()["detail"] == "Incorrect email or password."


def test_login_without_membership(env):
    gotrue, _ = env
    gotrue.add_user("loner@x.com", "password1")
    r = api_client().post("/api/auth/login", json={"email": "loner@x.com", "password": "password1"})
    assert r.status_code == 401 and r.json()["detail"] == "Incorrect email or password."


def test_me_requires_login(env):
    assert api_client().get("/api/auth/me").status_code == 401


def test_expired_access_is_refreshed(env):
    c = api_client()
    _signup(c)
    c.cookies.delete("hl_access")
    r = c.get("/api/auth/me")
    assert r.status_code == 200
    assert any(h.startswith("hl_access=") for h in r.headers.get_list("set-cookie"))


def test_invalid_refresh_is_401(env):
    c = api_client()
    _signup(c)
    c.cookies.clear()  # drop the real cookies so only the bogus one is sent
    c.cookies.set("hl_refresh", "bogus")
    assert c.get("/api/auth/me").status_code == 401


def test_logout_clears_cookies(env):
    c = api_client()
    _signup(c)
    assert c.post("/api/auth/logout").status_code == 204
    assert "hl_access" not in c.cookies
    assert c.get("/api/auth/me").status_code == 401


def test_csrf_header_required(env):
    from fastapi.testclient import TestClient
    from backend.main import app

    r = TestClient(app).post("/api/auth/login", json={"email": "a@x.com", "password": "password1"})
    assert r.status_code == 403


def test_admin_adds_user_who_can_log_in(env):
    admin = api_client()
    _signup(admin)
    r = admin.post("/api/team/users", json={"email": "ali@x.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "ali@x.com" and body["user"]["role"] == "member"
    assert len(body["password"]) == 16
    user = api_client()
    me = user.post("/api/auth/login", json={"email": "ali@x.com", "password": body["password"]}).json()
    assert me["role"] == "member"
    listed = admin.get("/api/team/users").json()
    assert [u["email"] for u in listed] == ["admin@x.com", "ali@x.com"]
    assert "password" not in listed[1]
    assert admin.post("/api/team/users", json={"email": "ali@x.com"}).status_code == 409


def test_member_cannot_manage_team(env):
    admin = api_client()
    _signup(admin)
    password = admin.post("/api/team/users", json={"email": "ali@x.com"}).json()["password"]
    member = api_client()
    member.post("/api/auth/login", json={"email": "ali@x.com", "password": password})
    assert member.get("/api/team/users").status_code == 403
    assert member.post("/api/team/users", json={"email": "b@x.com"}).status_code == 403


def test_remove_user(env):
    admin = api_client()
    me = _signup(admin).json()
    added = admin.post("/api/team/users", json={"email": "ali@x.com"}).json()
    member = api_client()
    member.post("/api/auth/login", json={"email": "ali@x.com", "password": added["password"]})
    assert admin.delete(f"/api/team/users/{me['user']['id']}").status_code == 400  # not yourself
    assert admin.delete(f"/api/team/users/{added['user']['id']}").status_code == 204
    assert member.get("/api/auth/me").status_code == 401


def test_cannot_remove_other_teams_user(env):
    a = api_client()
    _signup(a)
    b = api_client()
    other = _signup(b, email="b@x.com", team="B").json()
    assert a.delete(f"/api/team/users/{other['user']['id']}").status_code == 404


def test_supabase_down_is_503(env):
    gotrue, _ = env
    gotrue.down = True
    r = api_client().post("/api/auth/login", json={"email": "a@x.com", "password": "password1"})
    assert r.status_code == 503
    assert r.json()["detail"] == "Login is unavailable right now. Try again shortly."


def test_without_supabase(monkeypatch):
    monkeypatch.setattr(db, "is_enabled", lambda: False)
    c = api_client()
    assert c.get("/api/auth/me").json()["detail"] == "Accounts need Supabase"
    assert c.get("/api/jobs").status_code == 503
    assert c.get("/api/health").json()["auth"] is False
```
(`/api/jobs` returns 503 here once Task 3 adds `current_member` to it; until then that one assertion fails, so run it with Task 3. In this task, temporarily run the file with `-k "not without_supabase"` and note it in the report.)

- [ ] **Step 4: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_accounts.py -v`
Expected: FAIL — `cannot import name 'accounts' from 'backend'`.

- [ ] **Step 5: `backend/db.py`** — append:
```python
# Account and team writes raise instead of logging and carrying on like the
# helpers above: a half-created account is worse than an error the caller
# can clean up after.
def _require_client():
    client = get_client()
    if client is None:
        raise RuntimeError("Supabase is not configured")
    return client


def create_team(name: str) -> dict[str, Any]:
    return _require_client().table("teams").insert({"name": name}).execute().data[0]


def add_member(user_id: str, team_id: str, role: str, email: str) -> dict[str, Any]:
    row = {"user_id": user_id, "team_id": team_id, "role": role, "email": email}
    return _require_client().table("team_members").insert(row).execute().data[0]


def get_member(user_id: str) -> dict[str, Any] | None:
    res = _require_client().table("team_members").select("*, teams(name)").eq("user_id", user_id).limit(1).execute()
    return _first(res)


def list_members(team_id: str) -> list[dict[str, Any]]:
    return _require_client().table("team_members").select("*").eq("team_id", team_id).execute().data or []


def count_teams() -> int:
    return _require_client().table("teams").select("id", count="exact").limit(1).execute().count or 0


def claim_unowned_jobs(team_id: str) -> None:
    _require_client().table("jobs").update({"team_id": team_id}).is_("team_id", "null").execute()
```

- [ ] **Step 6: `backend/accounts.py`**
```python
"""Login, signup and team-user endpoints, plus the dependencies every other
endpoint uses to learn who is calling and which team they belong to.

Sessions live in two httpOnly cookies set by this backend, so page scripts
can't read them and the browser sends them on every request, including
<video> loads. An expired access token is refreshed transparently inside
`current_member`.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import auth, db

ACCESS_COOKIE = "hl_access"
REFRESH_COOKIE = "hl_refresh"
REFRESH_MAX_AGE_S = 30 * 24 * 3600
MEMBER_CACHE_TTL_S = 60.0
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "highlyte"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

NEEDS_SUPABASE = "Accounts need Supabase"
UNAVAILABLE = "Login is unavailable right now. Try again shortly."
BAD_LOGIN = "Incorrect email or password."
EMAIL_TAKEN = "That email already has an account."

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
_USER_ID_RE = re.compile(r"^[0-9a-fA-F-]{1,64}$")


@dataclass(frozen=True)
class Member:
    user_id: str
    email: str
    team_id: str
    team_name: str
    role: str  # admin | member

    def to_me(self) -> dict[str, Any]:
        return {
            "user": {"id": self.user_id, "email": self.email},
            "team": {"id": self.team_id, "name": self.team_name},
            "role": self.role,
        }


class SignupRequest(BaseModel):
    teamName: str = Field(max_length=80)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)
    password: str = Field(min_length=8, max_length=72)

    @field_validator("teamName")
    @classmethod
    def _team_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("team name is required")
        return value


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class AddUserRequest(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)


_member_cache: dict[str, tuple[float, Member]] = {}
_member_lock = threading.Lock()


def _cookie_secure() -> bool:
    return os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true", "yes")


def set_session_cookies(response: Response, session: auth.Session) -> None:
    common = {"httponly": True, "samesite": "lax", "secure": _cookie_secure(), "path": "/"}
    response.set_cookie(ACCESS_COOKIE, session.access_token, max_age=session.expires_in, **common)
    response.set_cookie(REFRESH_COOKIE, session.refresh_token, max_age=REFRESH_MAX_AGE_S, **common)


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


def _require_supabase() -> None:
    if not db.is_enabled():
        raise HTTPException(503, NEEDS_SUPABASE)


def _load_member(user: auth.AuthUser) -> Member | None:
    with _member_lock:
        hit = _member_cache.get(user.id)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]
    row = db.get_member(user.id)
    if row is None:
        return None
    member = Member(
        user_id=user.id,
        email=user.email,
        team_id=row["team_id"],
        team_name=(row.get("teams") or {}).get("name") or "",
        role=row["role"],
    )
    with _member_lock:
        _member_cache[user.id] = (time.monotonic() + MEMBER_CACHE_TTL_S, member)
    return member


def _forget_member(user_id: str) -> None:
    with _member_lock:
        _member_cache.pop(user_id, None)


def current_member(request: Request, response: Response) -> Member:
    _require_supabase()
    access = request.cookies.get(ACCESS_COOKIE)
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    try:
        user = auth.user_for_token(access) if access else None
        if user is None and refresh_token:
            try:
                session = auth.refresh_session(refresh_token)
            except auth.InvalidCredentials:
                session = None
            if session is not None:
                # The access token expired: hand the browser fresh cookies on
                # this same response so the user never sees a logout.
                set_session_cookies(response, session)
                user = session.user
    except auth.AuthUnavailable:
        raise HTTPException(503, UNAVAILABLE)
    if user is None:
        raise HTTPException(401, "Not logged in")
    member = _load_member(user)
    if member is None:
        raise HTTPException(401, "Not logged in")
    return member


def admin_member(member: Member = Depends(current_member)) -> Member:
    if member.role != "admin":
        raise HTTPException(403, "Only the team admin can do this")
    return member


async def csrf_middleware(request: Request, call_next):
    """Cookie sessions would let another site's form submit changes as the
    logged-in user. Browsers won't let other sites add this custom header,
    and our own frontend sends it on every request."""
    if (
        request.method not in SAFE_METHODS
        and request.url.path.startswith("/api/")
        and request.headers.get(CSRF_HEADER) != CSRF_VALUE
    ):
        return JSONResponse({"detail": f"Missing {CSRF_HEADER} header"}, status_code=403)
    return await call_next(request)


def _member_api(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["user_id"], "email": row["email"], "role": row["role"], "createdAt": row.get("created_at")}


router = APIRouter()


@router.post("/api/auth/signup")
def signup(body: SignupRequest, response: Response) -> dict[str, Any]:
    _require_supabase()
    try:
        user = auth.create_user(body.email, body.password)
    except auth.EmailTaken:
        raise HTTPException(409, EMAIL_TAKEN)
    except auth.AuthUnavailable:
        raise HTTPException(503, UNAVAILABLE)
    try:
        team = db.create_team(body.teamName)
        db.add_member(user.id, team["id"], "admin", user.email)
        if db.count_teams() == 1:
            # The first team is whoever used HighLyte before logins existed,
            # so it inherits the projects made back then.
            db.claim_unowned_jobs(team["id"])
    except Exception:
        auth.delete_user(user.id)  # don't leave a login that belongs to no team
        raise
    try:
        session = auth.password_login(body.email, body.password)
    except auth.AuthUnavailable:
        raise HTTPException(503, UNAVAILABLE)
    set_session_cookies(response, session)
    return Member(user.id, user.email, team["id"], team["name"], "admin").to_me()


@router.post("/api/auth/login")
def login(body: LoginRequest, response: Response) -> dict[str, Any]:
    _require_supabase()
    try:
        session = auth.password_login(body.email, body.password)
    except auth.InvalidCredentials:
        raise HTTPException(401, BAD_LOGIN)
    except auth.AuthUnavailable:
        raise HTTPException(503, UNAVAILABLE)
    member = _load_member(session.user)
    if member is None:
        raise HTTPException(401, BAD_LOGIN)
    set_session_cookies(response, session)
    return member.to_me()


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request) -> Response:
    access = request.cookies.get(ACCESS_COOKIE)
    if access and db.is_enabled():
        auth.logout(access)
    response = Response(status_code=204)
    clear_session_cookies(response)
    return response


@router.get("/api/auth/me")
def me(member: Member = Depends(current_member)) -> dict[str, Any]:
    return member.to_me()


@router.get("/api/team/users")
def team_users(admin: Member = Depends(admin_member)) -> list[dict[str, Any]]:
    rows = sorted(db.list_members(admin.team_id), key=lambda r: (r["role"] != "admin", r.get("created_at") or ""))
    return [_member_api(r) for r in rows]


@router.post("/api/team/users")
def add_team_user(body: AddUserRequest, admin: Member = Depends(admin_member)) -> dict[str, Any]:
    password = auth.generate_password()
    try:
        user = auth.create_user(body.email, password)
    except auth.EmailTaken:
        raise HTTPException(409, EMAIL_TAKEN)
    except auth.AuthUnavailable:
        raise HTTPException(503, UNAVAILABLE)
    try:
        row = db.add_member(user.id, admin.team_id, "member", user.email)
    except Exception:
        auth.delete_user(user.id)
        raise
    # The only time the password leaves the server; it is never stored.
    return {"user": _member_api(row), "password": password}


@router.delete("/api/team/users/{user_id}", status_code=204)
def remove_team_user(user_id: str, admin: Member = Depends(admin_member)) -> Response:
    if user_id == admin.user_id:
        raise HTTPException(400, "You can't remove your own account")
    row = db.get_member(user_id) if _USER_ID_RE.fullmatch(user_id) else None
    if row is None or row["team_id"] != admin.team_id:
        raise HTTPException(404, "user not found")
    try:
        auth.delete_user(user_id)  # the team_members row cascades
    except auth.AuthUnavailable:
        raise HTTPException(503, UNAVAILABLE)
    _forget_member(user_id)
    return Response(status_code=204)
```

- [ ] **Step 7: Wire into `backend/main.py`**

Imports: add `from . import accounts` (next to `from . import db, projects, render, storage`).

After `app.add_middleware(CORSMiddleware, ...)`:
```python
app.middleware("http")(accounts.csrf_middleware)
app.include_router(accounts.router)
```
`health`:
```python
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "supabase": db.is_enabled(),
        "auth": db.is_enabled(),
        "rendering": RENDER_SERVICE is not None,
    }
```

- [ ] **Step 8: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest tests/test_accounts.py -v -k "not without_supabase"` then `./.venv/Scripts/python -m pytest -v`
Expected: accounts tests PASS; the existing suite still passes except tests that POST/PATCH without the CSRF header (`test_validation.py::test_generate_rejects_unknown_whisper_model`, `test_render_api.py` style/render tests). Task 3 updates them; list the failures in the report.

- [ ] **Step 9: Commit**
```bash
git add backend/accounts.py backend/db.py backend/main.py pytest.ini tests/support.py tests/test_accounts.py
git commit -m "Add login, signup and team user endpoints with cookie sessions"
```

---

### Task 3: Team-scope every existing endpoint

**Files:**
- Modify: `backend/main.py`, `backend/db.py` (`list_jobs`, `list_clips`), `supabase/schema.sql`, `tests/conftest.py`, `tests/support.py`, `tests/test_validation.py`, `tests/test_status.py`, `tests/test_jobs_api.py`, `tests/test_render_api.py`
- Create: `tests/test_team_scope.py`

**Interfaces:**
- Consumes: `accounts.Member`, `accounts.current_member` (Task 2); `api_client` (Task 2).
- Produces: `main.Job.team_id: str | None`, `main.Job.created_by: str | None`; `db.list_jobs(team_id, limit=20)`; `db.list_clips(team_id, limit=100)`; `tests/support.TEST_TEAM_ID = "team-test"`; autouse fixture `logged_in_member` in `tests/conftest.py`.

- [ ] **Step 1: Test helpers**

Append to `tests/support.py`:
```python
TEST_TEAM_ID = "team-test"
```
Append to `tests/conftest.py`:
```python
import pytest


@pytest.fixture(autouse=True)
def logged_in_member(request):
    """Most API tests act as a logged-in admin of TEST_TEAM_ID. Tests marked
    `real_auth` exercise the real login dependency instead."""
    if request.node.get_closest_marker("real_auth"):
        yield None
        return
    from backend import accounts, main
    from tests.support import TEST_TEAM_ID

    member = accounts.Member(
        user_id="00000000-0000-0000-0000-00000000test", email="tester@example.com",
        team_id=TEST_TEAM_ID, team_name="Test team", role="admin",
    )
    main.app.dependency_overrides[accounts.current_member] = lambda: member
    yield member
    main.app.dependency_overrides.pop(accounts.current_member, None)
```

- [ ] **Step 2: Write the failing tests** — `tests/test_team_scope.py`:
```python
import pytest

from backend import main
from tests.support import TEST_TEAM_ID, api_client

client = api_client()
OTHER = "team-other"


@pytest.fixture
def jobs():
    main.JOBS["aaaa00000001"] = main.Job(id="aaaa00000001", url="u", status="done", team_id=TEST_TEAM_ID)
    main.JOBS["bbbb00000001"] = main.Job(id="bbbb00000001", url="u", status="done", team_id=OTHER)
    yield
    main.JOBS.pop("aaaa00000001", None)
    main.JOBS.pop("bbbb00000001", None)


def test_project_list_only_shows_own_team(jobs, monkeypatch):
    seen = {}
    monkeypatch.setattr(main.db, "list_jobs", lambda team_id, limit=20: seen.setdefault("team", team_id) and [])
    monkeypatch.setattr(main.db, "count_clips_by_job", lambda ids: {})
    ids = [p["id"] for p in client.get("/api/jobs").json()]
    assert "aaaa00000001" in ids and "bbbb00000001" not in ids
    assert seen["team"] == TEST_TEAM_ID


def test_other_team_status_is_404(jobs):
    assert client.get("/api/status/aaaa00000001").status_code == 200
    assert client.get("/api/status/bbbb00000001").status_code == 404


def test_other_team_db_row_is_404(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: {"id": job_id, "status": "done", "team_id": OTHER})
    assert client.get("/api/status/cccc00000001").status_code == 404


def test_unowned_db_row_is_404(monkeypatch):
    monkeypatch.setattr(main.db, "get_job", lambda job_id: {"id": job_id, "status": "done", "team_id": None})
    assert client.get("/api/status/cccc00000002").status_code == 404


def test_other_team_clip_file_and_style_are_404(jobs):
    assert client.get("/api/clips/bbbb00000001/clip_0.mp4").status_code == 404
    style = {"layout": "fit", "captionPreset": "pop", "showHook": True, "hookTitle": None,
             "accent": "#FFD400", "captionPosition": "lower"}
    assert client.patch("/api/clips/bbbb00000001-0/style", json=style).status_code == 404


def test_generate_records_team_and_creator(monkeypatch):
    started = {}

    class NoThread:
        def __init__(self, target, args, daemon):
            started["job"] = args[0]

        def start(self):
            pass

    monkeypatch.setattr(main.threading, "Thread", NoThread)
    r = client.post("/api/generate", json={"url": "https://youtu.be/qt6YoGmksCc"})
    job = started["job"]
    try:
        assert r.status_code == 200
        assert job.team_id == TEST_TEAM_ID
        assert job.created_by == "00000000-0000-0000-0000-00000000test"
    finally:
        main.JOBS.pop(job.id, None)


def test_clip_list_is_team_filtered(monkeypatch):
    seen = {}
    monkeypatch.setattr(main.db, "list_clips", lambda team_id, limit=100: seen.setdefault("team", team_id) and [])
    assert client.get("/api/clips").status_code == 200
    assert seen["team"] == TEST_TEAM_ID
```

- [ ] **Step 3: Run to verify failure**

Run: `./.venv/Scripts/python -m pytest tests/test_team_scope.py -v`
Expected: FAIL — `Job.__init__() got an unexpected keyword argument 'team_id'`.

- [ ] **Step 4: `backend/db.py`** — change `list_jobs` and `list_clips`:
```python
def list_jobs(team_id: str, limit: int = 20) -> list[dict[str, Any]]:
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("jobs")
            .select("*")
            .eq("team_id", team_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:  # noqa: BLE001
        print(f"[supabase] list_jobs failed: {e}")
        return []
```
In `list_clips`, change the signature to `def list_clips(team_id: str, limit: int = 100)`, the select to `"*, jobs!inner(url, video_title, video_channel, video_duration, team_id)"` and add `.eq("jobs.team_id", team_id)` before `.order(...)`. Update its docstring's first sentence to "All clips across the team's jobs, newest first, ..." (`!inner` makes the join filter the clips, not just the embedded job).

- [ ] **Step 5: `backend/main.py`**

Imports: change `from fastapi import Body, FastAPI, HTTPException, Query` to `from fastapi import Body, Depends, FastAPI, HTTPException, Query` and add `from .accounts import Member, current_member`.

`Job` dataclass — add after `created_at`:
```python
    team_id: str | None = None
    created_by: str | None = None
```

`_persist_job` — add to the `row` dict:
```python
        "team_id": job.team_id,
        "created_by": job.created_by,
```

Add after `JOBS: dict[str, Job] = {}`:
```python
_MISSING = object()


def _require_job(member: Member, job_id: str) -> None:
    """404 unless the job exists and belongs to the caller's team. Another
    team's job gets the same answer as a missing one, so ids can't be probed."""
    job = JOBS.get(job_id)
    if job is not None:
        team_id = job.team_id
    else:
        row = db.get_job(job_id)
        team_id = row.get("team_id") if row is not None else _MISSING
    if team_id != member.team_id:
        raise HTTPException(404, "job not found")


def _job_id_of_clip(clip_id: str) -> str:
    return clip_id.rsplit("-", 1)[0]
```

Endpoint changes (add the `member` parameter exactly as shown; keep the existing bodies otherwise):
- `generate(req: GenerateRequest, member: Member = Depends(current_member))`: build the job with `Job(id=job_id, url=req.url, team_id=member.team_id, created_by=member.user_id)`.
- `status(job_id: str, member: Member = Depends(current_member))`: after `check_id(job_id, "job id")` add `_require_job(member, job_id)`.
- `list_projects(..., member: Member = Depends(current_member))`:
```python
    rows = db.list_jobs(member.team_id, limit=200)
    counts = db.count_clips_by_job([r["id"] for r in rows])
    memory = [projects.from_job(job) for job in list(JOBS.values()) if job.team_id == member.team_id]
    return projects.build_projects(memory, rows, counts, q=q, status=status, limit=limit)
```
- `list_all_clips(limit: int = 100, member: Member = Depends(current_member))`: call `db.list_clips(member.team_id, limit=limit)`.
- `get_clip(job_id: str, filename: str, member: Member = Depends(current_member))`: after `check_clip_filename(filename)` add `_require_job(member, job_id)`.
- `_clip_for_style(clip_id: str, member: Member)`: after `check_id(clip_id, "clip id")` add `_require_job(member, _job_id_of_clip(clip_id))`.
- `update_style(clip_id, style, member: Member = Depends(current_member))` → `_clip_for_style(clip_id, member)`; same for `start_render`.
- `_get_render(render_id: str, member: Member)`:
```python
def _get_render(render_id: str, member: Member) -> render.Render:
    check_id(render_id, "render id")
    if RENDER_SERVICE is None:
        raise HTTPException(503, "Rendering not configured")
    existing = RENDER_SERVICE.store.get(render_id)
    if existing is None:
        raise HTTPException(404, "render not found")
    # Checked before refresh() so another team can't even advance the render.
    _require_job(member, _job_id_of_clip(existing.clip_id))
    return RENDER_SERVICE.refresh(render_id)
```
- `renders_zip(ids, member: Member = Depends(current_member))`, `get_render(render_id, member: Member = Depends(current_member))`, `get_render_file(render_id, member: Member = Depends(current_member))`: pass `member` to `_get_render`.

- [ ] **Step 6: Update existing tests**
- Every module-level `client = TestClient(...)` in `tests/test_validation.py`, `tests/test_status.py`, `tests/test_jobs_api.py`, `tests/test_render_api.py` becomes `client = api_client()` (`from tests.support import TEST_TEAM_ID, api_client`; drop the now-unused `TestClient` import).
- Every `main.Job(...)` in those files gets `team_id=TEST_TEAM_ID`.
- Every fake jobs row dict (`_job_row`, `_row`) gets `"team_id": TEST_TEAM_ID`.
- Fake `list_jobs` lambdas become `lambda team_id, limit=20: [...]`; fake `list_clips` lambdas become `lambda team_id, limit=100: [...]`.
- In `tests/test_status.py::test_status_unknown_job` nothing else changes (a missing row is still 404).

- [ ] **Step 7: Record the SQL** — append to `supabase/schema.sql`:
```sql
-- Team accounts: a team admin signs up and adds users; everyone in a team
-- shares its projects. Only the backend (service-role key) reads these.
create table if not exists teams (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists team_members (
  user_id uuid primary key references auth.users(id) on delete cascade,
  team_id uuid not null references teams(id) on delete cascade,
  role text not null check (role in ('admin', 'member')),
  email text not null,
  created_at timestamptz not null default now()
);
create index if not exists team_members_team_idx on team_members(team_id);

alter table jobs add column if not exists team_id uuid references teams(id) on delete cascade;
alter table jobs add column if not exists created_by uuid references auth.users(id) on delete set null;
create index if not exists jobs_team_created_idx on jobs(team_id, created_at desc);

alter table teams enable row level security;
alter table team_members enable row level security;
alter table jobs enable row level security;
alter table clips enable row level security;
alter table renders enable row level security;
```

- [ ] **Step 8: Run to verify pass**

Run: `./.venv/Scripts/python -m pytest -v`
Expected: all PASS, including `tests/test_accounts.py::test_without_supabase`.

- [ ] **Step 9: Commit**
```bash
git add backend/main.py backend/db.py supabase/schema.sql tests/
git commit -m "Scope projects, clips and renders to the caller's team"
```

---

### Task 4: Frontend — same-origin API, auth store, guard, login and signup

**Files:**
- Create: `frontend/src/stores/authStore.js`, `frontend/src/utils/authRedirect.js`, `frontend/src/styles/auth.css`, `frontend/src/views/LoginView.vue`, `frontend/src/views/SignupView.vue`
- Modify: `frontend/vite.config.js`, `frontend/src/services/highlyteApi.js`, `frontend/src/router/index.js`, `frontend/src/App.vue`, `frontend/.env` (not tracked by git)

**Interfaces:**
- Consumes: `/api/auth/signup|login|logout|me` (Task 2).
- Produces: `highlyteApi.js` exports `getMe()`, `login(email, password)`, `signup(teamName, email, password)`, `logout()`, `listTeamUsers()`, `addTeamUser(email)`, `removeTeamUser(userId)`, `apiErrorMessage(error, fallback)`; `useAuthStore()` with state `me`, `checked`, getters `loggedIn`, `isAdmin`, actions `load()`, `login()`, `signup()`, `logout()`; routes `login`, `signup`, `team` (component added in Task 5 — this task registers the route with `meta: { adminOnly: true }` pointing at a `TeamView.vue` placeholder created here and replaced in Task 5); `safeNext(next)`.

- [ ] **Step 1: Vite proxy** — in `frontend/vite.config.js` add to `server`:
```js
    // The API is served from this same origin in development, so the
    // backend's httpOnly login cookies travel with every request.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
```
Remove the `VITE_API_BASE_URL=...` line from `frontend/.env` (the file is local and not tracked; leave the file empty if that was its only line).

- [ ] **Step 2: `frontend/src/services/highlyteApi.js`** — replace the top of the file (the `baseURL` constant and `api` creation) with:
```js
import axios from 'axios'

// Same origin: Vite proxies /api to the backend in development, and in
// production both are served from one domain. That's what lets the
// backend's httpOnly session cookies go with every request, <video> too.
const baseURL = ''

export const api = axios.create({
  baseURL,
  withCredentials: true,
  // The backend rejects changes without this header (CSRF protection).
  headers: { 'X-Requested-With': 'highlyte' },
})

// A 401 outside the login endpoints means the session is gone (expired,
// logged out elsewhere, or the user was removed), so go log in again.
api.interceptors.response.use(
  response => response,
  (error) => {
    const status = error?.response?.status
    const url = error?.config?.url || ''
    if (status === 401 && !url.startsWith('/api/auth/')) {
      const next = window.location.pathname + window.location.search
      window.location.assign(`/login?next=${encodeURIComponent(next)}`)
    }
    return Promise.reject(error)
  },
)
```
Keep `clipDownloadUrl` and `rendersZipUrl` as they are (they now produce same-origin paths). Append:
```js
export function apiErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

export const getMe = () => api.get('/api/auth/me').then(r => r.data)
export const login = (email, password) => api.post('/api/auth/login', { email, password }).then(r => r.data)
export const signup = (teamName, email, password) =>
  api.post('/api/auth/signup', { teamName, email, password }).then(r => r.data)
export const logout = () => api.post('/api/auth/logout')

export const listTeamUsers = () => api.get('/api/team/users').then(r => r.data)
export const addTeamUser = email => api.post('/api/team/users', { email }).then(r => r.data)
export const removeTeamUser = userId => api.delete(`/api/team/users/${userId}`)
```

- [ ] **Step 3: `frontend/src/utils/authRedirect.js`**
```js
// Only follow ?next= to a path on this site, never to another domain
// (an open redirect a phishing link could use).
export function safeNext(next) {
  return typeof next === 'string' && next.startsWith('/') && !next.startsWith('//') ? next : '/'
}
```

- [ ] **Step 4: `frontend/src/stores/authStore.js`**
```js
import { defineStore } from 'pinia'
import { getMe, login as apiLogin, logout as apiLogout, signup as apiSignup } from '../services/highlyteApi'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    me: null, // { user: {id, email}, team: {id, name}, role } when logged in
    checked: false, // whether we've asked the backend who we are yet
  }),
  getters: {
    loggedIn: state => !!state.me,
    isAdmin: state => state.me?.role === 'admin',
  },
  actions: {
    async load() {
      try {
        this.me = await getMe()
      } catch {
        this.me = null
      } finally {
        this.checked = true
      }
    },
    async login(email, password) {
      this.me = await apiLogin(email, password)
      this.checked = true
    },
    async signup(teamName, email, password) {
      this.me = await apiSignup(teamName, email, password)
      this.checked = true
    },
    async logout() {
      try {
        await apiLogout()
      } finally {
        this.me = null
      }
    },
  },
})
```

- [ ] **Step 5: Router** — `frontend/src/router/index.js`:
```js
import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import JobView from '../views/JobView.vue'
import LoginView from '../views/LoginView.vue'
import ProjectsView from '../views/ProjectsView.vue'
import SignupView from '../views/SignupView.vue'
import TeamView from '../views/TeamView.vue'
import { useAuthStore } from '../stores/authStore'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/signup', name: 'signup', component: SignupView, meta: { public: true } },
    { path: '/', name: 'home', component: HomeView },
    { path: '/projects', name: 'projects', component: ProjectsView },
    { path: '/jobs/:id', name: 'job', component: JobView, props: true },
    { path: '/team', name: 'team', component: TeamView, meta: { adminOnly: true } },
    // Library was replaced by Projects; keep old links working.
    { path: '/library', redirect: '/projects' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.checked) await auth.load()
  if (to.meta.public) return auth.loggedIn ? { path: '/' } : true
  if (!auth.loggedIn) return { path: '/login', query: { next: to.fullPath } }
  if (to.meta.adminOnly && !auth.isAdmin) return { path: '/' }
  return true
})

export default router
```
Placeholder `frontend/src/views/TeamView.vue` (Task 5 replaces it):
```vue
<template>
  <div class="page"><h1>Team</h1></div>
</template>
```

- [ ] **Step 6: `frontend/src/App.vue`**
```vue
<template>
  <TopBar v-if="!route.meta.public" />
  <router-view />
</template>

<script setup>
import { useRoute } from 'vue-router'
import TopBar from './components/TopBar.vue'

const route = useRoute()
</script>
```

- [ ] **Step 7: `frontend/src/styles/auth.css`**
```css
/* Shared by the login and signup pages. */
.auth-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
.auth-card {
  width: 100%; max-width: 380px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; padding: 32px 28px; display: flex; flex-direction: column; gap: 14px;
}
.auth-card .logo { align-self: center; }
.auth-card h1 { font-family: var(--font-serif); font-size: 24px; font-weight: 500; text-align: center; margin: 0 0 6px; }
.auth-card .field { display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; color: var(--ink-soft); }
.auth-card .field input {
  font-family: var(--font-sans); font-size: 14px; color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; background: #fff;
}
.auth-card button[type="submit"] {
  border: none; border-radius: 8px; padding: 11px 16px; font-size: 14px; font-weight: 600;
  font-family: var(--font-sans); color: #fff; background: var(--accent); cursor: pointer; margin-top: 4px;
}
.auth-card button[disabled] { opacity: .6; cursor: default; }
.auth-card .error { background: #FBEAE3; border: 1px solid #E8B79E; color: #9C3B14; border-radius: 8px; padding: 9px 12px; font-size: 13px; }
.auth-card .note { font-size: 12.5px; color: var(--ink-faint); text-align: center; margin: 0; }
.auth-card .switch { font-size: 13px; color: var(--ink-soft); text-align: center; margin: 0; }
.auth-card .switch a { color: var(--accent); font-weight: 600; }
```

- [ ] **Step 8: `frontend/src/views/LoginView.vue`**
```vue
<template>
  <div class="auth-page">
    <form class="auth-card" @submit.prevent="submit">
      <img src="/logo-mark.svg" alt="" width="36" height="36" class="logo" />
      <h1>Log in to Highlyte</h1>
      <label class="field">
        <span>Email</span>
        <input v-model.trim="email" type="email" autocomplete="username" required />
      </label>
      <label class="field">
        <span>Password</span>
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>
      <div v-if="error" class="error" role="alert">{{ error }}</div>
      <button type="submit" :disabled="busy">{{ busy ? 'Logging in…' : 'Log in' }}</button>
      <p class="note">Users: ask your team admin for your login.</p>
      <p class="switch">New team? <router-link to="/signup">Create a team</router-link></p>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import '../styles/auth.css'
import { useAuthStore } from '../stores/authStore'
import { apiErrorMessage } from '../services/highlyteApi'
import { safeNext } from '../utils/authRedirect'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const email = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    await auth.login(email.value, password.value)
    router.replace(safeNext(route.query.next))
  } catch (e) {
    error.value = apiErrorMessage(e, 'Login failed. Please try again.')
  } finally {
    busy.value = false
  }
}
</script>
```

- [ ] **Step 9: `frontend/src/views/SignupView.vue`**
```vue
<template>
  <div class="auth-page">
    <form class="auth-card" @submit.prevent="submit">
      <img src="/logo-mark.svg" alt="" width="36" height="36" class="logo" />
      <h1>Create your team</h1>
      <label class="field">
        <span>Team name</span>
        <input v-model="teamName" type="text" maxlength="80" required />
      </label>
      <label class="field">
        <span>Your email (team admin)</span>
        <input v-model.trim="email" type="email" autocomplete="username" required />
      </label>
      <label class="field">
        <span>Password (at least {{ MIN_PASSWORD }} characters)</span>
        <input v-model="password" type="password" autocomplete="new-password" required />
      </label>
      <label class="field">
        <span>Confirm password</span>
        <input v-model="confirm" type="password" autocomplete="new-password" required />
      </label>
      <div v-if="error" class="error" role="alert">{{ error }}</div>
      <button type="submit" :disabled="busy">{{ busy ? 'Creating…' : 'Create team' }}</button>
      <p class="note">Only the team admin signs up. You'll add your users from the Team page.</p>
      <p class="switch">Already have a login? <router-link to="/login">Log in</router-link></p>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import '../styles/auth.css'
import { useAuthStore } from '../stores/authStore'
import { apiErrorMessage } from '../services/highlyteApi'

const MIN_PASSWORD = 8

const router = useRouter()
const auth = useAuthStore()
const teamName = ref('')
const email = ref('')
const password = ref('')
const confirm = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  if (!teamName.value.trim()) {
    error.value = 'Enter a team name.'
    return
  }
  if (password.value.length < MIN_PASSWORD) {
    error.value = `Password must be at least ${MIN_PASSWORD} characters.`
    return
  }
  if (password.value !== confirm.value) {
    error.value = "Passwords don't match."
    return
  }
  busy.value = true
  try {
    await auth.signup(teamName.value.trim(), email.value, password.value)
    router.replace('/')
  } catch (e) {
    error.value = apiErrorMessage(e, 'Signup failed. Please try again.')
  } finally {
    busy.value = false
  }
}
</script>
```

- [ ] **Step 10: Build**

Run: `npm --prefix frontend run build`
Expected: succeeds; `grep -rn "VITE_API_BASE_URL\|127.0.0.1:8000" frontend/src` prints nothing.

- [ ] **Step 11: Commit**
```bash
git add frontend/vite.config.js frontend/src
git commit -m "Add login and signup pages with an auth store and route guard"
```

---

### Task 5: Frontend — Team page and account menu

**Files:**
- Modify: `frontend/src/views/TeamView.vue` (replace placeholder), `frontend/src/components/TopBar.vue`

**Interfaces:**
- Consumes: `listTeamUsers()`, `addTeamUser(email)` → `{user: {id, email, role, createdAt}, password}`, `removeTeamUser(userId)`, `apiErrorMessage` (Task 4); `useAuthStore()` (`me`, `isAdmin`, `logout()`); `useJobStore().$reset()`; `relativeTime` from `utils/time.js`.

- [ ] **Step 1: `frontend/src/views/TeamView.vue`**
```vue
<template>
  <div class="page">
    <div class="page-head">
      <h1>Team</h1>
      <p class="sub">{{ auth.me?.team.name }} · add the people who should share these projects.</p>
    </div>

    <form class="add-user" @submit.prevent="add">
      <label class="field">
        <span>Add a user by email</span>
        <input v-model.trim="newEmail" type="email" placeholder="name@company.com" required />
      </label>
      <button type="submit" :disabled="adding">{{ adding ? 'Adding…' : 'Add user' }}</button>
    </form>
    <div v-if="addError" class="error" role="alert">{{ addError }}</div>

    <div v-if="created" class="created" role="status">
      <div class="created-title">User added</div>
      <div class="creds">
        <div><span>Email</span><code>{{ created.email }}</code></div>
        <div><span>Password</span><code>{{ created.password }}</code></div>
      </div>
      <div class="created-actions">
        <button class="copy" @click="copyCreds">{{ copied ? 'Copied' : 'Copy login' }}</button>
        <button class="done" @click="closeCreated">Done</button>
      </div>
      <p class="warn">This password is shown only once. Copy it now and send it to the user.</p>
    </div>

    <div v-if="loading" class="state-msg">Loading…</div>
    <div v-else-if="listError" class="state-msg error">{{ listError }}</div>
    <ul v-else class="members">
      <li v-for="u in users" :key="u.id" class="member">
        <div class="who">
          <span class="email">{{ u.email }}</span>
          <span class="badge" :class="u.role">{{ u.role === 'admin' ? 'Admin' : 'User' }}</span>
        </div>
        <span class="added">Added {{ relativeTime(u.createdAt) }}</span>
        <button v-if="u.role !== 'admin'" class="remove" :disabled="removingId === u.id" @click="remove(u)">Remove</button>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useAuthStore } from '../stores/authStore'
import { addTeamUser, apiErrorMessage, listTeamUsers, removeTeamUser } from '../services/highlyteApi'
import { relativeTime } from '../utils/time'

const COPIED_MESSAGE_MS = 2000

const auth = useAuthStore()
const users = ref([])
const loading = ref(true)
const listError = ref('')
const newEmail = ref('')
const adding = ref(false)
const addError = ref('')
const created = ref(null) // { email, password } until the admin dismisses it
const copied = ref(false)
const removingId = ref(null)
let copiedTimer = null

async function load() {
  try {
    users.value = await listTeamUsers()
    listError.value = ''
  } catch (e) {
    listError.value = apiErrorMessage(e, "Couldn't load your team.")
  } finally {
    loading.value = false
  }
}

async function add() {
  addError.value = ''
  adding.value = true
  try {
    const result = await addTeamUser(newEmail.value)
    created.value = { email: result.user.email, password: result.password }
    users.value = [...users.value, result.user]
    newEmail.value = ''
  } catch (e) {
    addError.value = apiErrorMessage(e, "Couldn't add that user.")
  } finally {
    adding.value = false
  }
}

async function copyCreds() {
  await navigator.clipboard.writeText(`Email: ${created.value.email}\nPassword: ${created.value.password}`)
  copied.value = true
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { copied.value = false }, COPIED_MESSAGE_MS)
}

// The password is never retrievable again, so dropping it here is final.
function closeCreated() {
  created.value = null
  copied.value = false
}

async function remove(user) {
  if (!window.confirm(`Remove ${user.email}? They won't be able to log in.`)) return
  removingId.value = user.id
  try {
    await removeTeamUser(user.id)
    users.value = users.value.filter(u => u.id !== user.id)
  } catch (e) {
    listError.value = apiErrorMessage(e, "Couldn't remove that user.")
  } finally {
    removingId.value = null
  }
}

onMounted(load)
onUnmounted(() => clearTimeout(copiedTimer))
</script>

<style scoped>
.page { max-width: 760px; margin: 0 auto; padding: 40px 24px 120px; }
.page-head h1 { font-family: var(--font-serif); font-size: 28px; font-weight: 500; margin: 0; }
.sub { font-size: 13.5px; color: var(--ink-soft); margin: 6px 0 24px; }
.add-user { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
.field { flex: 1; min-width: 240px; display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; color: var(--ink-soft); }
.field input {
  font-family: var(--font-sans); font-size: 14px; color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px; background: #fff;
}
button {
  border: none; border-radius: 8px; padding: 10px 16px; font-size: 13.5px; font-weight: 600;
  font-family: var(--font-sans); color: #fff; background: var(--accent); cursor: pointer;
}
button[disabled] { opacity: .6; cursor: default; }
.error { margin-top: 10px; background: #FBEAE3; border: 1px solid #E8B79E; color: #9C3B14; border-radius: 8px; padding: 9px 12px; font-size: 13px; }
.created { margin-top: 18px; background: var(--surface); border: 1px solid var(--accent); border-radius: 12px; padding: 16px 18px; }
.created-title { font-weight: 600; margin-bottom: 10px; }
.creds { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.creds span { display: inline-block; width: 80px; color: var(--ink-soft); }
.creds code { font-size: 14px; background: var(--accent-soft); padding: 2px 8px; border-radius: 6px; }
.created-actions { display: flex; gap: 8px; margin-top: 12px; }
.created-actions .done { background: #fff; color: var(--ink); border: 1px solid var(--border); }
.warn { margin: 10px 0 0; font-size: 12.5px; color: #8A5A00; }
.members { list-style: none; padding: 0; margin: 28px 0 0; display: flex; flex-direction: column; gap: 8px; }
.member {
  display: flex; align-items: center; gap: 12px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 12px 14px;
}
.who { flex: 1; display: flex; align-items: center; gap: 8px; min-width: 0; }
.email { font-size: 14px; overflow: hidden; text-overflow: ellipsis; }
.badge { font-size: 11.5px; font-weight: 600; padding: 2px 8px; border-radius: 999px; background: var(--accent-soft); color: var(--accent-text); }
.badge.admin { background: #FFF4D6; color: #8A5A00; }
.added { font-size: 12px; color: var(--ink-faint); }
.remove { background: #fff; color: #9C3B14; border: 1px solid #E8B79E; padding: 6px 12px; }
.state-msg { font-size: 13.5px; color: var(--ink-soft); padding: 24px 0; }
.state-msg.error { color: #9C3B14; }
</style>
```

- [ ] **Step 2: `frontend/src/components/TopBar.vue`**

In `<nav class="tabs">`, after the Projects link and its comment, add:
```vue
        <router-link v-if="auth.isAdmin" to="/team" class="tab" active-class="tab-active">Team</router-link>
```
After the Generate `<button>`, add the account menu:
```vue
      <div class="account">
        <button class="account-btn" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen">
          {{ auth.me?.team.name || 'Account' }} ▾
        </button>
        <div v-if="menuOpen" class="account-menu" role="menu">
          <div class="account-email">{{ auth.me?.user.email }}</div>
          <button class="logout" role="menuitem" @click="onLogout">Log out</button>
        </div>
      </div>
```
Script additions:
```js
import { useAuthStore } from '../stores/authStore'

const auth = useAuthStore()
const menuOpen = ref(false)

async function onLogout() {
  menuOpen.value = false
  await auth.logout()
  jobStore.stopPolling()
  jobStore.$reset() // don't show this account's clips to the next person
  router.replace('/login')
}
```
(`ref`, `router` and `jobStore` already exist in this component.) Styles:
```css
.account { position: relative; flex-shrink: 0; }
.account-btn {
  background: var(--surface); color: var(--ink); border: 1px solid var(--border);
  border-radius: 10px; padding: 9px 12px; font-size: 13px; font-weight: 600; cursor: pointer;
}
.account-menu {
  position: absolute; right: 0; top: calc(100% + 6px); min-width: 200px; background: var(--surface);
  border: 1px solid var(--border); border-radius: 10px; padding: 10px; box-shadow: 0 8px 24px rgba(0,0,0,.08); z-index: 30;
}
.account-email { font-size: 12.5px; color: var(--ink-soft); padding: 4px 6px 10px; border-bottom: 1px solid var(--border); margin-bottom: 8px; word-break: break-all; }
.logout { width: 100%; text-align: left; background: none; color: #9C3B14; border: none; padding: 6px; font-size: 13px; font-weight: 600; cursor: pointer; }
```
Check the existing `button` rule in TopBar's styles: if it is an unscoped-looking `button { ... }` rule that would restyle `.account-btn`/`.logout`, scope it to the Generate button (give that button `class="generate"` and change the rule to `.generate`).

- [ ] **Step 3: Build**

Run: `npm --prefix frontend run build`
Expected: succeeds.

- [ ] **Step 4: Commit**
```bash
git add frontend/src
git commit -m "Add the Team page and account menu"
```

---

## After the plan: what the user checks in the browser

1. Restart the backend; start the frontend (`npm --prefix frontend run dev`) and open `http://localhost:6100`. It redirects to `/login`.
2. Create a team on `/signup`; Home shows the old projects (claimed by the first team).
3. Team tab → add a user → copy the login; log in with it in a private window; the user sees the same projects and no Team tab.
4. Remove that user; their next click lands on `/login`.
