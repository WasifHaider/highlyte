"""Shared Groq chat client for clip selection. One place paces calls under
the free tier's per-minute token limit, turns rate-limit errors into
messages a person can act on, and falls back from one model or key to the
next.

Groq limits each organization (account) and each model separately, so
every free key gives two daily buckets, `gpt-oss-120b` and `gpt-oss-20b`.
A member can save a main key and a backup key from a second Groq account;
selection tries main/120b, main/20b, backup/120b, backup/20b, moving on
when one hits its daily limit or fails. Two keys from the same account
share one limit and add nothing."""
from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from . import groq_context

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_BIG_MODEL = "openai/gpt-oss-120b"
# Tried in this order on each key.
GROQ_MODELS = (GROQ_BIG_MODEL, GROQ_MODEL)
# Groq free tier, both models (checked 2026-11-26): 8k tokens/minute,
# 200k tokens/day, 1k requests/day.
TOKENS_PER_MINUTE = 8000
# Transcript tokens per ranker call: what fits under that limit with the
# prompt and answer (ranker.WINDOW_TOKENS is this).
GROQ_WINDOW_TOKENS = 4500
# Roman Hinglish tokenizes worse than plain English.
CHARS_PER_TOKEN = 3.2
# How often a per-minute 429 (or a 503) is waited out and retried.
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
    def __init__(self, wait: str | None, provider: str = "Groq") -> None:
        super().__init__(f"{provider} daily limit reached; try again in {wait or 'a while'}")
        self.wait = wait
        self.provider = provider


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


def is_overloaded(exc: Exception) -> bool:
    """A 503 (capacity) usually clears within seconds."""
    text = str(exc).lower()
    return "503" in text or "over capacity" in text or "overloaded" in text


def is_auth_failure(exc: Exception) -> bool:
    text = str(exc).lower()
    return type(exc).__name__ == "AuthenticationError" or "401" in text or "invalid api key" in text


class GroqChat:
    """One model behind one key."""

    def __init__(
        self, client: Any, *, sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic, tokens_per_minute: int = TOKENS_PER_MINUTE,
        model: str = GROQ_MODEL, label: str | None = None,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._clock = clock
        self._tpm = tokens_per_minute
        self._remaining = tokens_per_minute
        self._reset_at = 0.0
        self.model = model
        self.provider = "Groq"
        # For logs: "main key / openai/gpt-oss-120b".
        self.label = label or model
        # Guards pacing state plus the call itself: two jobs racing here
        # could otherwise both see a full minute's budget and both spend it.
        self._lock = threading.Lock()

    def complete(self, prompt: str, *, max_tokens: int) -> ChatResult:
        need = estimate_tokens(prompt) + max_tokens
        with self._lock:
            for attempt in range(RATE_LIMIT_RETRIES + 1):
                self._wait_for(need)
                try:
                    raw = self._client.chat.completions.with_raw_response.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=max_tokens,
                        # Sent via extra_body because the pinned openai client
                        # predates the field. Without it gpt-oss spends the
                        # whole budget on hidden reasoning.
                        extra_body={"reasoning_effort": "low"},
                    )
                except Exception as e:
                    if is_daily_limit(e):
                        raise DailyLimit(wait_label(e), self.provider) from e
                    if not (is_rate_limit(e) or is_overloaded(e)) or attempt == RATE_LIMIT_RETRIES:
                        raise
                    self._sleep(min(retry_after(e) or DEFAULT_RETRY_S, MAX_RETRY_WAIT_S))
                    self._remaining = self._tpm
                    continue
                self._note_usage(raw.headers, need)
                resp = raw.parse()
                usage = getattr(resp, "usage", None)
                if usage:
                    print(f"[groq] {self.label} prompt_tokens={getattr(usage, 'prompt_tokens', None)} "
                          f"completion_tokens={getattr(usage, 'completion_tokens', None)}")
                choice = resp.choices[0]
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


class FallbackChat:
    """Tries each chat in order. A chat that hits its daily limit is skipped
    for the rest of this object's life (one job); any other failure moves
    this call on to the next chat. Raises only when every chat failed: a
    DailyLimit if all of them were out for the day, else the last error."""

    def __init__(self, chats: list[GroqChat]) -> None:
        self.chats = list(chats)
        self._out_for_day: set[int] = set()
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        return self.chats[0].model

    def complete(self, prompt: str, *, max_tokens: int) -> ChatResult:
        last: Exception | None = None
        waits: list[str] = []
        for i, chat in enumerate(self.chats):
            with self._lock:
                if i in self._out_for_day:
                    continue
            try:
                return chat.complete(prompt, max_tokens=max_tokens)
            except DailyLimit as e:
                with self._lock:
                    self._out_for_day.add(i)
                if e.wait:
                    waits.append(e.wait)
                last = e
                print(f"[llm] {chat.label}: daily limit, trying the next one")
            except Exception as e:  # noqa: BLE001
                last = e
                print(f"[llm] {chat.label} failed ({type(e).__name__}), trying the next one")
        with self._lock:
            all_out = len(self._out_for_day) == len(self.chats)
        if all_out:
            providers = " and ".join(dict.fromkeys(c.provider for c in self.chats))
            raise DailyLimit(waits[-1] if waits else None, providers) from last
        assert last is not None
        raise last


_chats: dict[tuple[str, str], GroqChat] = {}
_chat_lock = threading.Lock()


def _shared(key: str, model: str, label: str | None = None) -> GroqChat:
    """One GroqChat per (key, model), shared by every job using that key so
    they pace calls against the same per-minute budget (spec section 1)."""
    cache_key = (key, model)
    chat = _chats.get(cache_key)
    if chat is None:
        with _chat_lock:
            chat = _chats.get(cache_key)
            if chat is None:
                from openai import OpenAI

                # max_retries=0: GroqChat handles 429s itself, and retrying
                # a daily limit only burns requests.
                chat = GroqChat(OpenAI(api_key=key, base_url=GROQ_BASE_URL, max_retries=0),
                                model=model, label=label)
                _chats[cache_key] = chat
    return chat


# Short names the selection comparison script accepts for --models.
MODEL_NAMES = {"groq": GROQ_MODEL, "gpt-oss-20b": GROQ_MODEL, "gpt-oss-120b": GROQ_BIG_MODEL}


def chat_for_model(name: str) -> GroqChat | None:
    """One model on the main key, no fallback, for the selection comparison
    script. `name` is a key of MODEL_NAMES."""
    key = groq_context.get_groq_key()
    return _shared(key, MODEL_NAMES[name]) if key else None


def keys() -> list[tuple[str, str]]:
    """(label, key) for the caller's main and backup Groq keys, set ones only."""
    out = []
    for label, key in (("main key", groq_context.get_groq_key()),
                       ("backup key", groq_context.get_groq_backup_key())):
        if key and key not in (k for _, k in out):
            out.append((label, key))
    return out


def build_chat() -> GroqChat | FallbackChat | None:
    """The chat clip selection uses: every model on the main key, then every
    model on the backup key (`groq_context`)."""
    chats = [_shared(key, model, f"{label} / {model}") for label, key in keys() for model in GROQ_MODELS]
    if not chats:
        return None
    return FallbackChat(chats)
