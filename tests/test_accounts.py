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


def test_signup_rolls_back_team_and_user_on_failure(env, monkeypatch):
    gotrue, teams = env
    monkeypatch.setattr(db, "add_member", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        _signup(api_client())
    # The failed signup must leave no trace: no dangling auth user and no
    # team row that would corrupt which team is "oldest" for later signups.
    assert "admin@x.com" not in gotrue.users
    assert teams.teams == {}


def test_claim_still_works_after_an_earlier_failed_signup(env, monkeypatch):
    gotrue, teams = env
    real_add_member = db.add_member
    monkeypatch.setattr(db, "add_member", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        _signup(api_client())
    monkeypatch.setattr(db, "add_member", real_add_member)
    r = _signup(api_client(), email="second@x.com")
    assert r.status_code == 200
    assert teams.claimed == [r.json()["team"]["id"]]


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
    admin_body = _signup(admin).json()
    password = admin.post("/api/team/users", json={"email": "ali@x.com"}).json()["password"]
    member = api_client()
    member.post("/api/auth/login", json={"email": "ali@x.com", "password": password})
    assert member.get("/api/team/users").status_code == 403
    assert member.post("/api/team/users", json={"email": "b@x.com"}).status_code == 403
    assert member.delete(f"/api/team/users/{admin_body['user']['id']}").status_code == 403


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


def _set_cookie_names(response) -> list[str]:
    return [h.split("=", 1)[0] for h in response.headers.get_list("set-cookie")]


def test_refresh_cookies_survive_a_file_response(env):
    # Endpoints that return their own Response (files, redirects, 204s)
    # must still hand the browser the rotated tokens, or it keeps a spent
    # refresh token and is logged out when the access token next expires.
    import os
    from backend import main

    c = api_client()
    team_id = _signup(c).json()["team"]["id"]
    job_id = "ffff00000001"
    clip_dir = os.path.join(main.CLIPS_DIR, job_id)
    os.makedirs(clip_dir, exist_ok=True)
    with open(os.path.join(clip_dir, "clip_0.mp4"), "wb") as f:
        f.write(b"mp4")
    main.JOBS[job_id] = main.Job(id=job_id, url="u", status="done", team_id=team_id)
    try:
        c.cookies.delete("hl_access")
        r = c.get(f"/api/clips/{job_id}/clip_0.mp4")
        assert r.status_code == 200 and r.content == b"mp4"
        assert {"hl_access", "hl_refresh"} <= set(_set_cookie_names(r))
    finally:
        main.JOBS.pop(job_id, None)
        os.remove(os.path.join(clip_dir, "clip_0.mp4"))
        os.rmdir(clip_dir)


def test_refresh_cookies_survive_a_204(env):
    admin = api_client()
    _signup(admin)
    added = admin.post("/api/team/users", json={"email": "ali@x.com"}).json()
    admin.cookies.delete("hl_access")
    r = admin.delete(f"/api/team/users/{added['user']['id']}")
    assert r.status_code == 204
    assert {"hl_access", "hl_refresh"} <= set(_set_cookie_names(r))
    # The old refresh token was spent by that refresh, so this only works
    # if the browser received the new one.
    assert admin.get("/api/auth/me").status_code == 200


def test_invalid_refresh_clears_cookies(env):
    c = api_client()
    c.cookies.set("hl_refresh", "bogus")
    r = c.get("/api/auth/me")
    assert r.status_code == 401
    cleared = [h.lower() for h in r.headers.get_list("set-cookie") if h.startswith("hl_refresh=")]
    assert cleared and ("max-age=0" in cleared[0] or "expires=thu, 01 jan 1970" in cleared[0])
