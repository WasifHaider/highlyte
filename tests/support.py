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
