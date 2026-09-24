from types import SimpleNamespace

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
    # Only this browser's session ends; the user stays logged in elsewhere.
    assert gotrue.logout_scopes == ["local"]


def test_expired_cache_entries_are_swept(gotrue, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(auth, "time", SimpleNamespace(monotonic=lambda: now[0]))
    auth._remember("old-token", auth.AuthUser(id="u1", email="a@x.com"))
    now[0] += auth.TOKEN_CACHE_TTL_S + 1
    auth._remember("new-token", auth.AuthUser(id="u2", email="b@x.com"))
    assert "old-token" not in auth._cache and "new-token" in auth._cache


def test_generate_password():
    passwords = {auth.generate_password() for _ in range(50)}
    assert len(passwords) == 50
    assert all(len(p) == 16 and p.isalnum() for p in passwords)
