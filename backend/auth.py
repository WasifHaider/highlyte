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
