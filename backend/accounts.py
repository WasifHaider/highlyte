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
