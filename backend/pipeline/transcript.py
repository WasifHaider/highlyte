"""Transcript acquisition.

Primary path: YouTube's own captions via youtube-transcript-api (fast, free,
no model download).

Fallback path (in order of preference):
  1. Groq's hosted Whisper API (whisper-large-v3-turbo) — free tier, runs on
     Groq's LPU hardware at 100x+ realtime, vastly faster than local CPU
     inference. Used automatically when GROQ_KEY is set.
  2. Local faster-whisper — fully offline, free, but CPU-only on this
     machine (no CUDA GPU available), so realistically ~1-2x realtime at
     best. Used when GROQ_KEY isn't set, or as a per-chunk fallback if a
     Groq call fails.

Because this app targets podcasts that mix English with Roman-script
Hindi/Urdu (Hindi/Urdu spoken but written in Latin letters, not Devanagari
or the Urdu/Nastaliq script), both paths force `language="en"` and, when the
audio actually contains Urdu/Hindi (see `_detect_needs_roman_urdu_hint`),
seed a prompt with a short Roman-Urdu/Hindi sentence. Whisper treats the
prompt as "text so far" and keeps decoding in the same script family
(Latin), instead of switching to Devanagari/Urdu script or silently
translating the Urdu/Hindi portions into English. This is a well-known
community technique for coaxing Whisper into Roman-Urdu output — see
DeveloperSarim/roman-urdu-speech-to-text on GitHub. Do NOT set
language="ur" or "hi" (that produces native-script output) and do not strip
the prompt on mixed-language audio (without it Whisper tends to translate
instead of transcribe). The prompt is a strong conditioning signal though —
sending it on audio that's actually all-English makes Whisper occasionally
hallucinate a few Urdu-looking words that were never said, so it's only
sent once a quick probe confirms the audio isn't pure English.

Both paths also request word-level timestamps instead of Whisper's own
~15-30s segment timestamps. Whisper's segments are decoding windows, not
sentences — they routinely end mid-sentence, and downstream highlight
selection (`pipeline.highlight`) can only place a clip boundary where a
transcript timestamp exists. Word-level timestamps let it rebuild real
sentence boundaries (punctuation + inter-word pauses) instead of being
stuck with Whisper's coarse window edges, which is what was causing clips
to start/end mid-sentence.
"""
from __future__ import annotations

import os

# Must be set before faster_whisper/huggingface_hub is imported anywhere.
# On this environment the hf_xet accelerated transfer backend silently
# stalls at 0 bytes on large model files (plain HTTPS to the same host
# works fine) — forcing the plain-HTTP downloader avoids the hang.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

# Chunk length for transcription (both Groq and local paths). For local
# faster-whisper: without `torch` installed, it falls back to a pure-numpy
# STFT that materializes one complex128 array covering the *entire* input
# in a single allocation (see feature_extractor.py's stft()) — a multi-hour
# podcast's array alone would be multiple GB and can OOM the process. For
# Groq: the free tier's audio API has a 25MB file-size ceiling per request.
# A 10-minute m4a chunk is comfortably under both limits (~9-10MB) while
# also giving meaningful incremental progress reporting.
WHISPER_CHUNK_S = 600.0  # 10 minutes per chunk

# Seed prompt: natural Roman Urdu/Hindi prose mixed with English, teaching
# Whisper the spelling convention in context (not a word list).
ROMAN_URDU_HINDI_SEED = (
    "Yeh podcast Roman Urdu aur Hindi mein baat karta hai, jaise "
    "'mujhe yeh cheez bohat pasand hai' ya 'hum log kal milenge'. "
    "Kabhi kabhi English words bhi beech mein aa jate hain, jaise "
    "'that's actually a great point' ya 'I totally agree with you'. "
    "Log apni baat normal tareeke se karte hain, bina kisi script ke, "
    "sirf Roman letters mein."
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_WHISPER_MODEL = "whisper-large-v3-turbo"
GROQ_MAX_RETRIES = 2  # per chunk, before falling back to local whisper


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptResult:
    segments: list[TranscriptSegment]
    source: str  # "captions" | "groq" | "whisper"


def fetch_captions(video_id: str) -> TranscriptResult | None:
    try:
        raw = YouTubeTranscriptApi.get_transcript(video_id)
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, Exception):
        return None
    if not raw:
        return None
    segs = [
        TranscriptSegment(
            start=float(r["start"]),
            end=float(r["start"]) + float(r.get("duration", 0.0)),
            text=r["text"].strip(),
        )
        for r in raw
        if r.get("text", "").strip()
    ]
    if not segs:
        return None
    return TranscriptResult(segments=segs, source="captions")


_whisper_model = None


def _get_whisper_model(model_size: str = "small"):
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        _whisper_model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            cpu_threads=os.cpu_count() or 4,
        )
    return _whisper_model


def _probe_duration(audio_path: str) -> float:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        raise RuntimeError(f"ffprobe failed to read duration for {audio_path}: {proc.stderr}")


def _split_audio(audio_path: str, chunk_s: float, out_dir: str) -> list[tuple[float, str]]:
    """Split `audio_path` into fixed-length chunks via ffmpeg stream copy
    (fast, no re-encode). Returns [(offset_seconds, chunk_path), ...]."""
    duration = _probe_duration(audio_path)
    if duration <= chunk_s:
        return [(0.0, audio_path)]

    chunks: list[tuple[float, str]] = []
    offset = 0.0
    idx = 0
    while offset < duration:
        out_path = os.path.join(out_dir, f"chunk_{idx:03d}.m4a")
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{offset:.2f}", "-i", audio_path,
            "-t", f"{chunk_s:.2f}",
            "-c", "copy",
            out_path,
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise RuntimeError(f"ffmpeg chunk split failed at offset {offset}: {proc.stderr.decode(errors='ignore')}")
        chunks.append((offset, out_path))
        offset += chunk_s
        idx += 1
    return chunks


def _words_from_segments(segments) -> list[tuple[float, float, str]]:
    """Flatten faster-whisper segments (with word_timestamps=True) into
    word-level (start, end, text) tuples. Falls back to whole-segment
    tuples for any segment that has no word list (shouldn't normally
    happen with word_timestamps=True, but keeps this robust)."""
    out: list[tuple[float, float, str]] = []
    for s in segments:
        words = getattr(s, "words", None)
        if words:
            for w in words:
                text = w.word.strip()
                if text:
                    out.append((w.start, w.end, text))
        elif s.text.strip():
            out.append((s.start, s.end, s.text.strip()))
    return out


def _transcribe_chunk_local(
    chunk_path: str, model_size: str, prompt: str | None
) -> list[tuple[float, float, str]]:
    """Transcribe one chunk with local faster-whisper. beam_size=1 (not 5)
    — measured ~2x throughput on this machine's CPU with a small accuracy
    tradeoff, since this is a fast highlight-scoring pass, not a
    transcript-of-record. Returns word-level (start, end, text) tuples —
    see module docstring for why."""
    model = _get_whisper_model(model_size)
    segments, _info = model.transcribe(
        chunk_path,
        language="en",  # forced: keeps output in Latin script (see module docstring)
        initial_prompt=prompt,
        beam_size=1,
        vad_filter=True,
        word_timestamps=True,
    )
    return _words_from_segments(segments)


def _transcribe_chunk_groq(
    chunk_path: str, api_key: str, prompt: str | None
) -> list[tuple[float, float, str]]:
    """Transcribe one chunk via Groq's hosted Whisper API. Raises on
    failure (including rate limits) — caller decides whether to retry or
    fall back to local. Returns word-level (start, end, text) tuples — see
    module docstring for why."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
    kwargs: dict = dict(
        model=GROQ_WHISPER_MODEL,
        language="en",  # forced: keeps output in Latin script (see module docstring)
        response_format="verbose_json",
        timestamp_granularities=["word"],
    )
    if prompt:
        kwargs["prompt"] = prompt
    with open(chunk_path, "rb") as f:
        resp = client.audio.transcriptions.create(file=f, **kwargs)

    words = getattr(resp, "words", None) or []
    out = []
    for w in words:
        start = w["start"] if isinstance(w, dict) else w.start
        end = w["end"] if isinstance(w, dict) else w.end
        text = (w["word"] if isinstance(w, dict) else w.word).strip()
        if text:
            out.append((start, end, text))
    if not out:
        # Fallback: no word timestamps returned (e.g. silent chunk) — use
        # whatever coarser segment/text info is available so the chunk
        # isn't silently dropped.
        segments = getattr(resp, "segments", None) or []
        for s in segments:
            start = s["start"] if isinstance(s, dict) else s.start
            end = s["end"] if isinstance(s, dict) else s.end
            text = (s["text"] if isinstance(s, dict) else s.text).strip()
            if text:
                out.append((start, end, text))
    if not out:
        text = (getattr(resp, "text", "") or "").strip()
        if text:
            out.append((0.0, _probe_duration(chunk_path), text))
    return out


def _detect_needs_roman_urdu_hint(audio_path: str, api_key: str) -> bool:
    """Probe a short sample of the audio (first 30s) with a plain,
    unprompted, language-undetected Groq call, and check what language
    Whisper decides on its own. If it's already confident English, the
    Roman-Urdu seed prompt is skipped for the whole file — sending it on
    English-only audio makes Whisper occasionally hallucinate a few
    Urdu-looking words that were never said (it's a strong conditioning
    signal, not just a spelling hint). Returns True (use the hint, the
    prior always-on behavior) if the probe itself fails for any reason, so
    a Groq hiccup here never breaks mixed-language transcription."""
    from openai import OpenAI

    tmp_dir = tempfile.mkdtemp(prefix="highlyte_langprobe_")
    try:
        sample_path = os.path.join(tmp_dir, "sample.m4a")
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", audio_path, "-t", "30",
            "-c", "copy", sample_path,
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0 or not os.path.exists(sample_path) or os.path.getsize(sample_path) == 0:
            return True
        client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
        with open(sample_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model=GROQ_WHISPER_MODEL,
                file=f,
                response_format="verbose_json",
            )
        lang = (getattr(resp, "language", "") or "").strip().lower()
        return lang not in ("en", "english")
    except Exception:
        return True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


_RETRY_AFTER_RE = re.compile(r"retry.{0,10}?(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


def _extract_retry_after(exc: Exception) -> float:
    match = _RETRY_AFTER_RE.search(str(exc))
    if match:
        return float(match.group(1))
    return 5.0  # sane default backoff if the error message doesn't say


def transcribe_whisper(
    audio_path: str,
    model_size: str = "small",
    on_progress: "callable | None" = None,
) -> TranscriptResult:
    """Transcribe `audio_path`, chunking first (see module-level comment
    for why). Prefers Groq's hosted Whisper API (fast, GROQ_KEY required)
    per chunk, retrying on transient/rate-limit errors, and falling back to
    local faster-whisper for any chunk Groq can't handle — so a Groq outage
    or quota exhaustion degrades to "slow but working" rather than failing
    the whole job. Chunk timestamps are offset back into the original
    audio's timeline before returning, so downstream highlight/cut code
    doesn't need to know chunking or which backend ran.

    If given, `on_progress(current_chunk, total_chunks, latest_text)` is
    called after each chunk finishes transcribing — lets callers surface
    live progress (e.g. "chunk 3/17") instead of a long silent black box.
    """
    groq_key = os.environ.get("GROQ_KEY")
    tmp_dir = tempfile.mkdtemp(prefix="highlyte_whisper_")
    try:
        chunk_list = _split_audio(audio_path, WHISPER_CHUNK_S, tmp_dir)
        total_chunks = len(chunk_list)
        all_segments: list[TranscriptSegment] = []
        used_groq = False
        used_local = False

        # Decide once, up front, whether this file needs the Roman-Urdu
        # hint at all (see `_detect_needs_roman_urdu_hint`). Defaults to
        # on (prior behavior) when there's no Groq key to probe with.
        prompt: str | None = ROMAN_URDU_HINDI_SEED
        if groq_key and not _detect_needs_roman_urdu_hint(audio_path, groq_key):
            prompt = None

        for i, (offset, chunk_path) in enumerate(chunk_list):
            raw_words: list[tuple[float, float, str]] | None = None

            if groq_key:
                for attempt in range(GROQ_MAX_RETRIES + 1):
                    try:
                        raw_words = _transcribe_chunk_groq(chunk_path, groq_key, prompt)
                        used_groq = True
                        break
                    except Exception as e:  # noqa: BLE001
                        is_rate_limit = "rate" in str(e).lower() or "429" in str(e)
                        if is_rate_limit and attempt < GROQ_MAX_RETRIES:
                            time.sleep(_extract_retry_after(e))
                            continue
                        break  # give up on Groq for this chunk, fall back to local

            if raw_words is None:
                raw_words = _transcribe_chunk_local(chunk_path, model_size, prompt)
                used_local = True

            preview_words: list[str] = []
            for start, end, text in raw_words:
                all_segments.append(TranscriptSegment(
                    start=start + offset,
                    end=end + offset,
                    text=text,
                ))
                preview_words.append(text)
            last_text = " ".join(preview_words[-25:])  # word-level now, so preview last ~25 words
            if on_progress is not None:
                try:
                    on_progress(i + 1, total_chunks, last_text)
                except Exception:
                    pass  # progress reporting must never break the pipeline

        source = "groq" if used_groq and not used_local else ("whisper" if used_local else "groq")
        return TranscriptResult(segments=all_segments, source=source)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def get_transcript(
    video_id: str,
    audio_path: str,
    whisper_model_size: str = "small",
    on_progress: "callable | None" = None,
) -> TranscriptResult:
    result = fetch_captions(video_id)
    if result is not None:
        return result
    return transcribe_whisper(audio_path, whisper_model_size, on_progress=on_progress)
