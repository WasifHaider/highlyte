"""Speech recognition behind one small interface.

An AsrProvider turns a wav chunk into words with times and a confidence.
Groq's hosted Whisper is the primary provider and local faster-whisper the
fallback; a paid ASR can be added later as another provider without
touching the rest of the pipeline. Whisper always runs with language="en":
the spike (roadmap, "Spike results") showed Hindi mode writes English words
in Devanagari and romanizing them back mangles them.
"""
from __future__ import annotations

import math
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_HINGLISH_MODEL = "whisper-large-v3"  # the model the spike validated
GROQ_ENGLISH_MODEL = "whisper-large-v3-turbo"
GROQ_MAX_RETRIES = 2  # per chunk, on rate limits, before falling back

_RETRY_AFTER_RE = re.compile(r"retry.{0,10}?(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


@dataclass
class AsrWord:
    text: str
    start: float
    end: float
    prob: float


class AsrProvider(Protocol):
    name: str

    def transcribe(self, wav: str, *, prompt: str | None) -> list[AsrWord]: ...


def words_from_verbose(resp: dict[str, Any]) -> list[AsrWord]:
    """Words from a Groq verbose_json response. Groq gives no per-word
    probability, so each word takes exp(avg_logprob) of the segment it
    falls in."""
    segs = [
        (float(s["start"]), float(s["end"]), math.exp(float(s["avg_logprob"])))
        for s in resp.get("segments") or []
    ]
    out: list[AsrWord] = []
    for w in resp.get("words") or []:
        text = w["word"].strip()
        if not text:
            continue
        start, end = float(w["start"]), float(w["end"])
        mid = (start + end) / 2
        prob = next((p for s, e, p in segs if s <= mid <= e), 1.0)
        out.append(AsrWord(text=text, start=start, end=end, prob=round(min(prob, 1.0), 3)))
    return out


class GroqAsr:
    name = "groq"

    def __init__(self, key: str, model: str) -> None:
        self.key, self.model = key, model

    def transcribe(self, wav: str, *, prompt: str | None) -> list[AsrWord]:
        from openai import OpenAI

        client = OpenAI(api_key=self.key, base_url=GROQ_BASE_URL)
        kwargs: dict[str, Any] = dict(
            model=self.model, language="en", response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )
        if prompt:
            kwargs["prompt"] = prompt
        with open(wav, "rb") as f:
            resp = client.audio.transcriptions.create(file=f, **kwargs)
        return words_from_verbose(resp.model_dump())


_local_models: dict[str, Any] = {}


def get_local_model(model_size: str = "small"):
    if model_size not in _local_models:
        from faster_whisper import WhisperModel

        _local_models[model_size] = WhisperModel(
            model_size, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4,
        )
    return _local_models[model_size]


class LocalWhisperAsr:
    name = "whisper"

    def __init__(self, model_size: str = "small") -> None:
        self.model_size = model_size

    def transcribe(self, wav: str, *, prompt: str | None) -> list[AsrWord]:
        # beam_size=1: about twice the CPU throughput for a small accuracy cost.
        segments, _info = get_local_model(self.model_size).transcribe(
            wav, language="en", initial_prompt=prompt, beam_size=1, word_timestamps=True,
        )
        return [
            AsrWord(text=w.word.strip(), start=w.start, end=w.end, prob=round(w.probability, 3))
            for s in segments for w in (s.words or []) if w.word.strip()
        ]


def _retry_after(exc: Exception) -> float:
    match = _RETRY_AFTER_RE.search(str(exc))
    return float(match.group(1)) if match else 5.0


def _is_rate_limit(exc: Exception) -> bool:
    return "rate" in str(exc).lower() or "429" in str(exc)


def transcribe_chunks(
    chunks: list,
    primary: AsrProvider | None,
    fallback: AsrProvider,
    *,
    prompt: str | None,
    on_progress: Callable[[int, int, str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[AsrWord], str]:
    """Transcribe each chunk, primary first. Rate limits are retried with
    the server's retry-after; any other failure, or retries running out,
    sends that chunk to the fallback, so a Groq outage makes a job slow
    rather than failed. Word times come back on the full audio's timeline."""
    words: list[AsrWord] = []
    used: set[str] = set()
    for i, chunk in enumerate(chunks):
        got: list[AsrWord] | None = None
        if primary is not None:
            for attempt in range(GROQ_MAX_RETRIES + 1):
                try:
                    got = primary.transcribe(chunk.path, prompt=prompt)
                    used.add(primary.name)
                    break
                except Exception as e:  # noqa: BLE001
                    if _is_rate_limit(e) and attempt < GROQ_MAX_RETRIES:
                        sleep(_retry_after(e))
                        continue
                    print(f"[asr] {primary.name} failed on chunk {i}, using {fallback.name}: {e}")
                    break
        if got is None:
            got = fallback.transcribe(chunk.path, prompt=prompt)
            used.add(fallback.name)
        for w in got:
            words.append(AsrWord(w.text, round(w.start + chunk.offset, 3), round(w.end + chunk.offset, 3), w.prob))
        if on_progress is not None:
            try:
                on_progress(i + 1, len(chunks), " ".join(w.text for w in got[-25:]))
            except Exception:
                pass  # progress reporting must never break the pipeline
    source = used.pop() if len(used) == 1 else ("mixed" if used else "groq")
    return words, source
