"""Shared Groq chat client for clip selection. One place paces calls under
the free tier's per-minute token limit and turns rate-limit errors into
messages a person can act on."""
from __future__ import annotations

import math
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-20b"
# Groq free tier for gpt-oss-20b (checked 2026-09-26): 8k tokens/minute,
# 200k tokens/day.
TOKENS_PER_MINUTE = 8000
# Roman Hinglish tokenizes worse than plain English.
CHARS_PER_TOKEN = 3.2
# How often a per-minute 429 is waited out and retried.
RATE_LIMIT_RETRIES = 2
DEFAULT_RETRY_S = 10.0
MAX_RETRY_WAIT_S = 65.0
# Without rate-limit headers, assume the minute window resets after this.
DEFAULT_WINDOW_S = 60.0

_DURATION_RE = re.compile(r"(?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?(?:([\d.]+)ms)?")
_TRY_AGAIN_RE = re.compile(r"try again in\s+([0-9hms.]+)", re.IGNORECASE)


class SelectionFailed(RuntimeError):
    """Clip selection could not run at all. The message is shown to the
    user as is; the job waits in `selection_failed` for a retry."""


class BadAnswer(Exception):
    """The model answered, but not with usable JSON (cut off or unreadable)."""


class DailyLimit(Exception):
    def __init__(self, wait: str | None) -> None:
        super().__init__(f"Groq daily limit reached; try again in {wait or 'a while'}")
        self.wait = wait


@dataclass
class ChatResult:
    content: str
    finish_reason: str | None


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def parse_duration(text: str) -> float | None:
    """"7.66s", "2m59.5s", "1h", "345ms" -> seconds."""
    match = _DURATION_RE.fullmatch(text.strip())
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds, millis = (float(g) if g else 0.0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def retry_after(exc: Exception) -> float | None:
    match = _TRY_AGAIN_RE.search(str(exc))
    return parse_duration(match.group(1).rstrip(".")) if match else None


def wait_label(exc: Exception) -> str | None:
    """"try again in 21m0.576s" -> "about 21 minutes"."""
    seconds = retry_after(exc)
    if seconds is None:
        return None
    if seconds < 60:
        return "about a minute"
    return f"about {round(seconds / 60)} minutes"


def is_rate_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return type(exc).__name__ == "RateLimitError" or "429" in text or "rate limit" in text


def is_daily_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return is_rate_limit(exc) and ("per day" in text or "(tpd)" in text or "(rpd)" in text)


class GroqChat:
    def __init__(
        self, client: Any, *, sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic, tokens_per_minute: int = TOKENS_PER_MINUTE,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._clock = clock
        self._tpm = tokens_per_minute
        self._remaining = tokens_per_minute
        self._reset_at = 0.0

    def complete(self, prompt: str, *, max_tokens: int) -> ChatResult:
        need = estimate_tokens(prompt) + max_tokens
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            self._wait_for(need)
            try:
                raw = self._client.chat.completions.with_raw_response.create(
                    model=GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    # Sent via extra_body because the pinned openai client
                    # predates the field. Without it gpt-oss-20b spends the
                    # whole budget on hidden reasoning.
                    extra_body={"reasoning_effort": "low"},
                )
            except Exception as e:
                if is_daily_limit(e):
                    raise DailyLimit(wait_label(e)) from e
                if not is_rate_limit(e) or attempt == RATE_LIMIT_RETRIES:
                    raise
                self._sleep(min(retry_after(e) or DEFAULT_RETRY_S, MAX_RETRY_WAIT_S))
                self._remaining = self._tpm
                continue
            self._note_usage(raw.headers, need)
            choice = raw.parse().choices[0]
            return ChatResult(choice.message.content or "", getattr(choice, "finish_reason", None))
        raise AssertionError("unreachable")

    def _wait_for(self, need: int) -> None:
        if self._remaining >= need:
            return
        wait = self._reset_at - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._remaining = self._tpm

    def _note_usage(self, headers: Any, need: int) -> None:
        remaining = headers.get("x-ratelimit-remaining-tokens")
        reset = headers.get("x-ratelimit-reset-tokens")
        try:
            self._remaining = int(float(remaining)) if remaining is not None else self._remaining - need
        except ValueError:
            self._remaining -= need
        wait = parse_duration(reset) if reset else None
        self._reset_at = self._clock() + (wait if wait is not None else DEFAULT_WINDOW_S)


def build_chat() -> GroqChat | None:
    key = os.environ.get("GROQ_KEY")
    if not key:
        return None
    from openai import OpenAI

    # max_retries=0: GroqChat handles 429s itself, and retrying a daily
    # limit only burns requests.
    return GroqChat(OpenAI(api_key=key, base_url=GROQ_BASE_URL, max_retries=0))
