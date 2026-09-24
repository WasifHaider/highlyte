"""Highlight detection: group the timestamped transcript into natural
sentence/pause-bounded units, then pick self-contained highlight spans from
those units.

Two boundary/selection strategies are supported:
  - heuristic (default, always available, free/offline): sentences are
    grouped into ~45s candidate chunks (never splitting a sentence), scored
    by lexical signals (quote-worthy phrasing, strong opinion markers,
    question density, length) — no external calls, works for any
    language/script since it only looks at punctuation/marker words common
    in both English and Roman Urdu/Hindi conversational speech.
  - llm (optional): if GROQ_KEY is set, a single LLM pass (Groq's free-tier
    API, OpenAI-compatible, model openai/gpt-oss-20b) reads the full
    sentence-indexed transcript and directly picks highlight spans by
    sentence index range — i.e. it chooses the boundaries itself (setup ->
    payoff, question -> answer), it isn't just scoring pre-cut slabs. It also
    returns a hook title, a 0-10 virality score and caption emphasis words per
    span. Long transcripts are split into non-overlapping windows to fit the
    model's context; results from all windows are merged before final selection.
    Purely additive — the app runs fully offline/free without it.

Both paths funnel through a shared final stage: boundary snapping (clip
edges are pulled onto the nearest sentence boundary), leading-filler
trimming, and greedy overlap suppression — so highlight boundaries always
land on sentence edges regardless of which scorer produced the candidate.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, replace

from .transcript import TranscriptSegment

CHUNK_WINDOW_S = 45.0  # heuristic-path candidate window target size
MIN_CLIP_S = 12.0
MAX_CLIP_S = 240.0
MAX_CLIPS = 8
MIN_CLIP_GAP_S = 4.0  # minimum gap enforced between picked clips

HOOK_TITLE_MAX_WORDS = 8
MAX_EMPHASIS_WORDS = 5

# Inter-segment gap above which we treat it as a spoken pause / sentence
# boundary signal, even without terminal punctuation in the transcript text.
PAUSE_GAP_S = 0.5
# Safety valve: force a sentence break after this long even with no
# punctuation or pause (e.g. a run-on caption track with no periods), so a
# single "sentence" can never swallow the whole transcript.
MAX_SENTENCE_S = 20.0
# Snapping tolerance when pulling a candidate clip edge onto the nearest
# sentence boundary. Sentences are now built from word-level timestamps
# (see transcript.py), so real sentence boundaries can sit close together
# (e.g. back-to-back short questions) — kept tight so a clip edge snaps to
# its own boundary rather than jumping onto a neighboring sentence.
SNAP_TOLERANCE_S = 0.4

STRONG_MARKERS = [
    "honestly", "actually", "the truth is", "i think", "i believe",
    "here's the thing", "listen", "wait", "hold on", "crazy", "insane",
    "the point is", "sach yeh hai", "mera khayal hai", "asal mein",
    "sun", "suno", "yaqeen", "hairan", "wahid", "bohat", "bahut",
]

TAGS = ["Strong opinion", "Key insight", "Funny moment", "Actionable advice", "Contrarian take", "Wild claim"]

SENTENCE_END_RE = re.compile(r"[.!?\u2026]+[\"')\]]?\s*$")

FILLER_LEADING_RE = re.compile(
    r"^(um+|uh+|erm+|hmm+|like|okay so|ok so|so yeah|yeah so|well|so,|"
    r"right so|you know|basically|anyway|i mean)\b[,\s]*",
    re.IGNORECASE,
)


@dataclass
class Clip:
    start: float
    end: float
    text: str
    score: float
    tag: str
    # LLM path only: a short hook overlay for the first seconds of the
    # short, and words from the span to highlight in captions.
    hook_title: str | None = None
    emphasis: list[str] = field(default_factory=list)


@dataclass
class Sentence:
    """A natural utterance unit: one or more transcript segments merged up
    to a sentence-ending punctuation mark, a pause boundary, or the
    MAX_SENTENCE_S safety cap. Always built from whole segments, so a
    sentence never splits mid-segment and a chunk built from whole
    sentences never splits mid-sentence."""
    start: float
    end: float
    text: str
    idx: int = -1


# ---------------------------------------------------------------------------
# Step 1: pause/sentence-based segmentation
# ---------------------------------------------------------------------------

def _split_sentences(segments: list[TranscriptSegment]) -> list[Sentence]:
    """Group segments into sentence-like units using (a) sentence-ending
    punctuation in the text and (b) gaps between consecutive segments as
    boundary signals. Only segment-level timestamps exist, so pause
    detection works on inter-segment gaps, not intra-segment."""
    if not segments:
        return []
    sentences: list[Sentence] = []
    buf: list[TranscriptSegment] = []
    n = len(segments)
    for i, seg in enumerate(segments):
        buf.append(seg)
        is_last = i == n - 1
        ends_sentence = bool(SENTENCE_END_RE.search(seg.text.strip()))
        gap_to_next = (segments[i + 1].start - seg.end) if not is_last else None
        pause_boundary = gap_to_next is not None and gap_to_next >= PAUSE_GAP_S
        duration = buf[-1].end - buf[0].start
        force_close = duration >= MAX_SENTENCE_S
        if is_last or ends_sentence or pause_boundary or force_close:
            text = " ".join(s.text for s in buf).strip()
            if text:
                sentences.append(Sentence(
                    start=buf[0].start, end=buf[-1].end, text=text, idx=len(sentences),
                ))
            buf = []
    return sentences


def _group_candidates(sentences: list[Sentence], target_s: float) -> list[list[Sentence]]:
    """Tumbling-window grouping like the old fixed-window `_chunk`, but on
    sentence granularity: a chunk boundary can only fall between two
    sentences, never inside one."""
    if not sentences:
        return []
    chunks: list[list[Sentence]] = []
    current: list[Sentence] = []
    chunk_start = sentences[0].start
    for sent in sentences:
        if current and (sent.end - chunk_start) > target_s:
            chunks.append(current)
            current = []
            chunk_start = sent.start
        current.append(sent)
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Heuristic scoring (offline fallback)
# ---------------------------------------------------------------------------

def _heuristic_score(text: str) -> float:
    lower = text.lower()
    score = 0.0
    score += sum(1.5 for m in STRONG_MARKERS if m in lower)
    score += lower.count("?") * 0.8
    score += lower.count("!") * 0.6
    score += min(len(text) / 120.0, 3.0)
    return score


def _pick_tag(text: str, idx: int) -> str:
    lower = text.lower()
    if "?" in text and any(w in lower for w in ["what", "how", "kya", "kaise"]):
        return "Key insight"
    if any(w in lower for w in ["lol", "funny", "haha", "hilarious"]):
        return "Funny moment"
    if any(w in lower for w in ["should", "you need to", "try this", "karo", "chahiye"]):
        return "Actionable advice"
    if any(w in lower for w in ["everyone says", "actually", "myth", "wrong"]):
        return "Contrarian take"
    if any(w in lower for w in ["insane", "crazy", "wild", "hairan"]):
        return "Wild claim"
    return TAGS[idx % len(TAGS)]


def score_chunks_heuristic(chunks: list[list[Sentence]]) -> list[Clip]:
    """Score sentence-grouped candidate chunks by lexical markers. Returns
    raw (unsorted, unfiltered-for-overlap) candidates — final ranking,
    MAX_CLIPS truncation, snapping and overlap suppression happen in
    `_select_clips`."""
    scored: list[Clip] = []
    for i, chunk in enumerate(chunks):
        text = " ".join(s.text for s in chunk).strip()
        if not text:
            continue
        start, end = chunk[0].start, chunk[-1].end
        if end - start < MIN_CLIP_S:
            continue
        scored.append(Clip(
            start=start,
            end=end,
            text=text,
            score=_heuristic_score(text),
            tag=_pick_tag(text, i),
        ))
    return scored


# ---------------------------------------------------------------------------
# LLM-driven boundary selection (optional, via Groq)
# ---------------------------------------------------------------------------

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-20b"

# Character budget per LLM call (formatted transcript window). Keeps each
# call comfortably inside context even for multi-hour podcasts; long
# transcripts are split into windows and results from every window are
# merged before final selection.
LLM_WINDOW_CHARS = 9000
# Sentences repeated at the start of each window from the tail of the
# previous one, so a highlight whose setup/payoff straddles a window
# boundary is still fully visible (and pickable) in at least one window.
# Overlap suppression in `_select_clips` dedupes any span picked twice.
LLM_WINDOW_OVERLAP_SENTENCES = 8
# Highlight spans requested per window; final MAX_CLIPS truncation and
# overlap suppression happen globally across all windows in `_select_clips`.
LLM_SPANS_PER_WINDOW = 4

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _llm_windows(
    sentences: list[Sentence], max_chars: int, overlap_sentences: int = LLM_WINDOW_OVERLAP_SENTENCES
) -> list[list[Sentence]]:
    windows: list[list[Sentence]] = []
    current: list[Sentence] = []
    current_chars = 0
    for sent in sentences:
        line_chars = len(sent.text) + 40  # rough allowance for "[idx] (s-e) "
        if current and current_chars + line_chars > max_chars:
            windows.append(current)
            # Carry the tail of this window into the next one, so spans
            # that straddle the boundary are still fully contained in a
            # single window somewhere.
            carry = current[-overlap_sentences:] if overlap_sentences else []
            current = list(carry)
            current_chars = sum(len(s.text) + 40 for s in current)
        current.append(sent)
        current_chars += line_chars
    if current:
        windows.append(current)
    return windows


def _format_window(window: list[Sentence]) -> str:
    return "\n".join(f"[{s.idx}] ({s.start:.1f}-{s.end:.1f}) {s.text}" for s in window)


def _llm_score_window(client, window: list[Sentence], sentences_by_idx: dict[int, Sentence]) -> list[Clip]:
    transcript_block = _format_window(window)
    prompt = (
        "You are selecting short-form highlight clips from a podcast transcript "
        "for a faceless content channel. Each line below is one sentence-level "
        "utterance, formatted as [index] (start-end seconds) text. The text may "
        "mix English with Roman-script Urdu/Hindi.\n\n"
        f"{transcript_block}\n\n"
        f"Pick up to {LLM_SPANS_PER_WINDOW} highlight spans from the indices "
        "above. Each span must be a self-contained idea (setup and payoff, or "
        "question and answer) that makes sense with NO outside context, must "
        "start and end exactly on a listed index (never split a sentence), and "
        "should be roughly 15-90 seconds long. end_idx must be the payoff/"
        "answer/punchline sentence, not a filler line before it. Rate each "
        "span's virality_score 0-10: how likely it is to perform as a "
        "standalone short, weighing most heavily how hard its first 2-3 "
        "seconds would grab a scrolling viewer with zero context. Write a "
        "hook_title of at most 8 words, punchy, in the same language mix the "
        "speakers use, that makes someone want to watch. List up to 5 "
        "emphasis words: single words copied from the span's own text that "
        "carry its meaning (they get highlighted in captions).\n\n"
        "Reply with ONLY a JSON array, no prose, in this exact shape:\n"
        '[{"start_idx": <int>, "end_idx": <int>, "virality_score": <0-10 number>, '
        '"hook_title": "<at most 8 words>", "emphasis": ["<word>", ...], '
        '"reason": "<short phrase>", "tag": "<one of: Strong opinion, Key '
        'insight, Funny moment, Actionable advice, Contrarian take, Wild '
        'claim>"}]\n'
        "If nothing in this window is worth clipping, reply with []."
    )
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        # gpt-oss-20b is a reasoning model — needs headroom for hidden
        # reasoning tokens before the JSON answer. Word-level sentence
        # boundaries mean windows now hold many more (shorter) candidate
        # lines than before, so the model reasons over more of them;
        # measured ~850 completion tokens on a 70-line window, so 2200
        # leaves real margin without letting a stuck response run away.
        max_tokens=2200,
    )
    content = resp.choices[0].message.content or ""
    match = _JSON_ARRAY_RE.search(content)
    if not match:
        return []
    try:
        spans = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    clips: list[Clip] = []
    for i, span in enumerate(spans if isinstance(spans, list) else []):
        try:
            start_idx = int(span["start_idx"])
            end_idx = int(span["end_idx"])
            # hook_score was the field name before virality_score existed.
            virality = float(span.get("virality_score", span.get("hook_score", 0)))
        except (KeyError, TypeError, ValueError):
            continue
        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx
        start_sent = sentences_by_idx.get(start_idx)
        end_sent = sentences_by_idx.get(end_idx)
        if start_sent is None or end_sent is None:
            continue
        text = " ".join(
            sentences_by_idx[j].text for j in range(start_idx, end_idx + 1) if j in sentences_by_idx
        ).strip()
        if not text or end_sent.end - start_sent.start < MIN_CLIP_S:
            continue
        tag = span.get("tag") if isinstance(span.get("tag"), str) else None
        if tag not in TAGS:
            tag = _pick_tag(text, i)
        raw_title = span.get("hook_title")
        hook_title = None
        if isinstance(raw_title, str) and raw_title.strip():
            hook_title = " ".join(raw_title.split()[:HOOK_TITLE_MAX_WORDS])
        raw_emphasis = span.get("emphasis") if isinstance(span.get("emphasis"), list) else []
        emphasis = [w for w in raw_emphasis if isinstance(w, str) and w.strip()][:MAX_EMPHASIS_WORDS]
        clips.append(Clip(
            start=start_sent.start,
            end=end_sent.end,
            text=text,
            score=virality,
            tag=tag,
            hook_title=hook_title,
            emphasis=emphasis,
        ))
    return clips


def score_chunks_llm_boundaries(sentences: list[Sentence]) -> list[Clip] | None:
    """Optional LLM-backed boundary selection via Groq's free-tier,
    OpenAI-compatible API. The LLM picks the highlight span boundaries
    itself (by sentence index) instead of just scoring pre-cut slabs.
    Returns None if no API key is configured or the client can't be built
    (caller should fall back to the heuristic path); returns a (possibly
    empty) list of candidate Clips otherwise."""
    api_key = os.environ.get("GROQ_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None

    client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
    sentences_by_idx = {s.idx: s for s in sentences}
    windows = _llm_windows(sentences, LLM_WINDOW_CHARS)

    all_clips: list[Clip] = []
    for window in windows:
        try:
            all_clips.extend(_llm_score_window(client, window, sentences_by_idx))
        except Exception:
            continue  # this window's LLM call failed — skip it, keep going
    return all_clips


# ---------------------------------------------------------------------------
# Shared final stage: snapping, filler trim, overlap suppression
# ---------------------------------------------------------------------------

def _snap_time(t: float, candidates: list[float], tolerance: float) -> float:
    best = t
    best_dist = tolerance
    for c in candidates:
        d = abs(c - t)
        if d <= best_dist:
            best = c
            best_dist = d
    return best


def _snap_clip_bounds(start: float, end: float, sentences: list[Sentence]) -> tuple[float, float]:
    starts = [s.start for s in sentences]
    ends = [s.end for s in sentences]
    snapped_start = _snap_time(start, starts, SNAP_TOLERANCE_S)
    snapped_end = _snap_time(end, ends, SNAP_TOLERANCE_S)
    if snapped_end <= snapped_start:
        snapped_end = end
    return snapped_start, snapped_end


def _trim_leading_filler(clip_sentences: list[Sentence]) -> tuple[float, str]:
    """Drop whole leading sentences that are (almost) nothing but filler —
    advances the clip's start time, since only segment/sentence-level
    timestamps are available, not word-level. Then strips a filler phrase
    prefix from the remaining text (cosmetic only, below sentence
    granularity we can't move the timestamp further)."""
    sentences = list(clip_sentences)
    while len(sentences) > 1:
        first_text = sentences[0].text.strip()
        stripped = FILLER_LEADING_RE.sub("", first_text).strip()
        if len(stripped) <= 2:
            sentences.pop(0)
            continue
        break
    if not sentences:
        sentences = list(clip_sentences)
    start = sentences[0].start
    text = " ".join(s.text for s in sentences).strip()
    text = FILLER_LEADING_RE.sub("", text, count=1).strip()
    return start, text


def _select_clips(candidates: list[Clip], sentences: list[Sentence]) -> list[Clip]:
    """Greedily pick clips by score, snapping each to sentence boundaries,
    trimming leading filler, skipping anything that overlaps an
    already-picked clip (within MIN_CLIP_GAP_S), and enforcing
    MIN_CLIP_S/MAX_CLIP_S/MAX_CLIPS."""
    ordered = sorted(candidates, key=lambda c: c.score, reverse=True)
    sentence_ends = [s.end for s in sentences]
    picked: list[Clip] = []

    for c in ordered:
        start, end = _snap_clip_bounds(c.start, c.end, sentences)
        if end - start > MAX_CLIP_S:
            capped_end = start + MAX_CLIP_S
            end = _snap_time(capped_end, sentence_ends, SNAP_TOLERANCE_S)
            if end > start + MAX_CLIP_S:
                end = capped_end
        if end - start < MIN_CLIP_S:
            continue

        overlaps = any(
            start < p.end + MIN_CLIP_GAP_S and end > p.start - MIN_CLIP_GAP_S
            for p in picked
        )
        if overlaps:
            continue

        clip_sents = [s for s in sentences if s.start >= start - 0.01 and s.end <= end + 0.01]
        text = c.text
        if clip_sents:
            new_start, new_text = _trim_leading_filler(clip_sents)
            if end - new_start >= MIN_CLIP_S:
                start, text = new_start, new_text

        picked.append(replace(c, start=start, end=end, text=text))
        if len(picked) >= MAX_CLIPS:
            break

    picked.sort(key=lambda c: c.start)
    return picked


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def detect_highlights(segments: list[TranscriptSegment]) -> list[Clip]:
    sentences = _split_sentences(segments)
    if not sentences:
        return []

    llm_clips = score_chunks_llm_boundaries(sentences)
    if llm_clips:
        candidates = llm_clips
    else:
        chunks = _group_candidates(sentences, CHUNK_WINDOW_S)
        candidates = score_chunks_heuristic(chunks)

    return _select_clips(candidates, sentences)
