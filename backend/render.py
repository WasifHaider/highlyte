"""Rendering clips to mp4 on AWS Lambda with Remotion.

The Remotion composition lives in renderer/ and is deployed as a "site"
to S3; FastAPI starts renders with Remotion's Python client and polls
their progress. Finished files are copied into R2 (the permanent clip
library, free to download from) and the S3 copy is deleted.

There is no background worker: renders advance whenever someone polls
/api/renders/{id} (the frontend does, every 2 s, while a render is
running). At most MAX_ACTIVE renders run at once — new AWS accounts often
have a 10-concurrent-Lambda limit, and each render uses about 5.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from . import db, storage
from .spec import ClipStyle, style_hash

FPS = 30
MAX_ACTIVE = 2
STUCK_AFTER_S = 30 * 60
THROTTLE_MAX_ATTEMPTS = 5
THROTTLE_BACKOFF_S = 15
THROTTLE_MARKERS = ("TooManyRequests", "Rate Exceeded", "ConcurrentInvocationLimitExceeded", "Throttl")
LIVE_STATUSES = ("queued", "rendering", "done")


@dataclass
class Render:
    id: str
    clip_id: str
    style: dict[str, Any]
    style_hash: str
    status: str = "queued"  # queued|rendering|done|error
    progress: float = 0.0
    lambda_render_id: str | None = None
    lambda_bucket: str | None = None
    storage_key: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    attempts: int = 0
    retry_at: float = 0.0

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "clipId": self.clip_id,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "downloadUrl": f"/api/renders/{self.id}/file" if self.status == "done" else None,
        }

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "clip_id": self.clip_id,
            "style": self.style,
            "style_hash": self.style_hash,
            "status": self.status,
            "progress": self.progress,
            "lambda_render_id": self.lambda_render_id,
            "lambda_bucket": self.lambda_bucket,
            "storage_key": self.storage_key,
            "error": self.error,
            "started_epoch": self.started_at,
            "attempts": self.attempts,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Render":
        return cls(
            id=row["id"],
            clip_id=row["clip_id"],
            style=row["style"],
            style_hash=row["style_hash"],
            status=row["status"],
            progress=float(row.get("progress") or 0),
            lambda_render_id=row.get("lambda_render_id"),
            lambda_bucket=row.get("lambda_bucket"),
            storage_key=row.get("storage_key"),
            error=row.get("error"),
            started_at=row.get("started_epoch"),
            attempts=int(row.get("attempts") or 0),
        )


class RenderStore:
    """In-memory renders, written through to Supabase when configured, so
    the app works without Supabase and survives restarts with it."""

    def __init__(self) -> None:
        self._items: dict[str, Render] = {}

    def put(self, r: Render) -> None:
        self._items[r.id] = r
        db.upsert_render(r.to_row())

    def get(self, render_id: str) -> Render | None:
        r = self._items.get(render_id)
        if r is None:
            row = db.get_render(render_id)
            if row is not None:
                r = Render.from_row(row)
                self._items[r.id] = r
        return r

    def find(self, clip_id: str, hash_value: str) -> Render | None:
        for r in sorted(self._items.values(), key=lambda r: r.created_at, reverse=True):
            if r.clip_id == clip_id and r.style_hash == hash_value and r.status in LIVE_STATUSES:
                return r
        row = db.find_render(clip_id, hash_value)
        if row is None:
            return None
        r = Render.from_row(row)
        self._items[r.id] = r
        return r

    def by_status(self, status: str) -> list[Render]:
        return sorted((r for r in self._items.values() if r.status == status), key=lambda r: r.created_at)


class RenderService:
    def __init__(
        self,
        renderer: Any,
        store: RenderStore,
        build_props: Callable[[str, dict[str, Any]], tuple[dict[str, Any], float]],
        upload_output: Callable[[Any, str, str], None],
        now: Callable[[], float] = time.time,
    ) -> None:
        self.renderer = renderer
        self.store = store
        self.build_props = build_props
        self.upload_output = upload_output
        self.now = now
        self._lock = threading.Lock()

    def request(self, clip_id: str, style: ClipStyle) -> Render:
        hash_value = style_hash(style)
        with self._lock:
            existing = self.store.find(clip_id, hash_value)
            if existing is not None:
                return existing
            r = Render(
                id=uuid.uuid4().hex[:12], clip_id=clip_id, style=style.model_dump(),
                style_hash=hash_value, created_at=self.now(),
            )
            self.store.put(r)
            self._pump()
            return r

    def refresh(self, render_id: str) -> Render | None:
        with self._lock:
            r = self.store.get(render_id)
            if r is None:
                return None
            if r.status == "rendering":
                self._poll(r)
            self._pump()
            return r

    def _pump(self) -> None:
        active = len(self.store.by_status("rendering"))
        for r in self.store.by_status("queued"):
            if active >= MAX_ACTIVE:
                break
            if r.retry_at > self.now():
                continue
            if self._start(r):
                active += 1

    def _start(self, r: Render) -> bool:
        try:
            props, duration_s = self.build_props(r.clip_id, r.style)
            lambda_id, bucket = self.renderer.start(props, duration_s)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if any(m in msg for m in THROTTLE_MARKERS) and r.attempts + 1 < THROTTLE_MAX_ATTEMPTS:
                r.attempts += 1
                r.retry_at = self.now() + THROTTLE_BACKOFF_S * r.attempts
                self.store.put(r)
                return False
            r.status, r.error = "error", msg[:500]
            self.store.put(r)
            return False
        r.status = "rendering"
        r.lambda_render_id, r.lambda_bucket = lambda_id, bucket
        r.started_at = self.now()
        self.store.put(r)
        return True

    def _poll(self, r: Render) -> None:
        # Check actual progress before the stuck-timeout: a render that
        # finished on Lambda while nobody was polling must win the race
        # against the 30-minute check, not be reported as timed out.
        try:
            p = self.renderer.progress(r.lambda_render_id, r.lambda_bucket)
        except Exception as e:  # noqa: BLE001
            print(f"[render] progress check failed for {r.id}, will retry: {e}")
            self._apply_stuck_timeout(r)
            self.store.put(r)
            return
        if p["fatal"]:
            messages = [str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in p["errors"]]
            r.status, r.error = "error", ("; ".join(messages) or "render failed")[:500]
            self.store.put(r)
            return
        r.progress = round(float(p["overallProgress"]) * 100, 1)
        if p["done"]:
            self._finish(r, p)
            return
        self._apply_stuck_timeout(r)
        self.store.put(r)

    def _apply_stuck_timeout(self, r: Render) -> None:
        if r.started_at is not None and self.now() - r.started_at > STUCK_AFTER_S:
            r.status, r.error = "error", "timed out"

    def _finish(self, r: Render, p: dict[str, Any]) -> None:
        key = storage.render_key(r.id)
        try:
            body = self.renderer.fetch_output(r.lambda_bucket, p["outKey"])
            with contextlib.closing(body):
                self.upload_output(body, key, f"highlyte-{r.clip_id}.mp4")
        except Exception as e:  # noqa: BLE001
            # Leave the render "rendering" (with its updated progress) so the
            # next poll retries the copy instead of surfacing a 500.
            print(f"[render] failed to copy output for {r.id}, will retry: {e}")
            self.store.put(r)
            return
        r.status, r.progress, r.storage_key = "done", 100.0, key
        self.store.put(r)
        try:
            # The S3 lifecycle rule is the backstop, so a failed delete here
            # is only worth logging, never worth losing the finished render.
            self.renderer.delete_output(r.lambda_bucket, p["outKey"])
        except Exception as e:  # noqa: BLE001
            print(f"[render] delete_output failed for {r.id}: {e}")


class LambdaRenderer:
    """Thin wrapper over Remotion's Python client plus the S3 calls needed
    to move the output into R2."""

    def __init__(self, region: str, serve_url: str, function_name: str, access_key: str, secret_key: str) -> None:
        import boto3
        from remotion_lambda import RemotionClient

        self.session = boto3.Session(
            aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region,
        )
        self.client = RemotionClient(
            region=region, serve_url=serve_url, function_name=function_name, session=self.session,
        )
        self.s3 = self.session.client("s3")

    def start(self, input_props: dict[str, Any], duration_s: float) -> tuple[str, str]:
        from remotion_lambda import Privacy, RenderMediaParams

        frames = max(1, round(duration_s * FPS))
        params = RenderMediaParams(
            composition="Clip",
            input_props=input_props,
            codec="h264",
            crf=20,
            privacy=Privacy.PRIVATE,
            # About 4 renderer Lambdas per clip (plus the orchestrator), so
            # two concurrent renders fit a new account's 10-Lambda limit.
            frames_per_lambda=max(60, math.ceil(frames / 4)),
            max_retries=1,
        )
        resp = self.client.render_media_on_lambda(params)
        if resp is None:
            raise RuntimeError("Lambda returned no render id")
        return resp.render_id, resp.bucket_name

    def progress(self, render_id: str, bucket: str) -> dict[str, Any]:
        p = self.client.get_render_progress(render_id=render_id, bucket_name=bucket)
        if p is None:
            raise RuntimeError("no progress response")
        return {
            "overallProgress": p.overallProgress,
            "done": p.done,
            "fatal": p.fatalErrorEncountered,
            "errors": p.errors,
            "outKey": p.outKey,
        }

    def fetch_output(self, bucket: str, key: str):
        return self.s3.get_object(Bucket=bucket, Key=key)["Body"]

    def delete_output(self, bucket: str, key: str) -> None:
        self.s3.delete_object(Bucket=bucket, Key=key)


def lambda_config() -> dict[str, str] | None:
    values = {
        "access_key": os.environ.get("REMOTION_AWS_ACCESS_KEY_ID"),
        "secret_key": os.environ.get("REMOTION_AWS_SECRET_ACCESS_KEY"),
        "region": os.environ.get("REMOTION_AWS_REGION"),
        "function_name": os.environ.get("REMOTION_FUNCTION_NAME"),
        "serve_url": os.environ.get("REMOTION_SERVE_URL"),
    }
    if not all(values.values()):
        return None
    return values  # type: ignore[return-value]


def build_service(
    build_props: Callable[[str, dict[str, Any]], tuple[dict[str, Any], float]],
    upload_output: Callable[[Any, str, str], None],
) -> RenderService | None:
    """None unless both Lambda and R2 are configured — renders need R2 for
    their source segment and their output."""
    cfg = lambda_config()
    if cfg is None or not storage.is_enabled():
        return None
    return RenderService(LambdaRenderer(**cfg), RenderStore(), build_props, upload_output)


def check_versions(package_json_path: str, function_name: str | None) -> list[str]:
    """Remotion requires the Python client, the npm packages the site was
    built with, and the deployed function to be the exact same version."""
    from remotion_lambda import VERSION

    problems: list[str] = []
    try:
        with open(package_json_path, encoding="utf-8") as f:
            npm_version = json.load(f).get("dependencies", {}).get("remotion")
    except OSError:
        npm_version = None
    if npm_version != VERSION:
        problems.append(f"renderer/package.json remotion is {npm_version}, Python remotion-lambda is {VERSION}")
    if function_name and VERSION.replace(".", "-") not in function_name:
        problems.append(f"Lambda function {function_name} was not deployed with Remotion {VERSION}")
    return problems
