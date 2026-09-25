"""Audio preparation for transcription.

Whisper gets 16kHz mono speech in chunks of at most two minutes, and a
chunk is only ever cut in a silence found by the Silero voice-activity
detector bundled with faster-whisper. The old fixed 10-minute split could
land mid-word; cutting in silence means no word is sliced and chunks never
need overlapping or de-duplicating.
"""
from __future__ import annotations

import os
import subprocess
import wave
from dataclasses import dataclass

import numpy as np

SR = 16000
MAX_CHUNK_S = 120.0
# speech_regions runs Silero VAD over slices of this many seconds instead of
# the whole decoded audio at once: one call over an hour of samples measured
# +1.6 GB on top of decode, enough to OOM the single-worker container on a
# long podcast. A touching pair of regions at a slice boundary (see
# _merge_touching_edges) makes the slicing invisible in the result.
SLICE_S = 600.0
# Regions closer together than this are treated as touching when merging
# across a slice boundary, matching the VAD's own min_silence_duration_ms.
EDGE_MERGE_GAP_S = 0.25
# pack_regions starts a new chunk when the gap since the previous region
# exceeds this many seconds, even if the joined span would still fit under
# max_s: a long gap is likely music or silence, and packing it into a chunk
# anyway gives Whisper (especially with the Hinglish seed prompt) room to
# hallucinate text over it.
MAX_GAP_S = 2.0


@dataclass
class Chunk:
    path: str
    offset: float  # seconds into the full audio where this chunk starts


def normalize(src: str, dst: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", src,
        "-vn", "-ac", "1", "-ar", str(SR), "-af", "loudnorm", "-c:a", "pcm_s16le", dst,
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg normalize failed: {proc.stderr.decode(errors='ignore')}")


def load(path: str) -> np.ndarray:
    from faster_whisper.audio import decode_audio

    return decode_audio(path, sampling_rate=SR)


def write_wav(samples: np.ndarray, path: str) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def pack_regions(regions: list[tuple[float, float]], max_s: float) -> list[tuple[float, float]]:
    """Greedily join consecutive speech regions while the joined span stays
    within max_s. Each boundary between chunks falls in the silence between
    two regions."""
    chunks: list[tuple[float, float]] = []
    for start, end in regions:
        if chunks and end - chunks[-1][0] <= max_s and start - chunks[-1][1] <= MAX_GAP_S:
            chunks[-1] = (chunks[-1][0], end)
        else:
            chunks.append((start, end))
    return chunks


def _merge_touching_edges(regions: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Two regions produced by adjacent slices that touch across the slice
    boundary (gap smaller than the VAD's own min silence) are really one
    region the slicing cut in two; merge them back together."""
    merged: list[tuple[float, float]] = []
    for start, end in regions:
        if merged and start - merged[-1][1] < EDGE_MERGE_GAP_S:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def speech_regions(samples: np.ndarray, max_s: float = MAX_CHUNK_S) -> list[tuple[float, float]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    # max_speech_duration_s makes Silero itself split an unbroken stretch of
    # speech at its last silence, so no single region outgrows a chunk.
    opts = VadOptions(
        min_silence_duration_ms=250, min_speech_duration_ms=400,
        speech_pad_ms=250, max_speech_duration_s=max_s - 1,
    )
    slice_len = int(SLICE_S * SR)
    regions: list[tuple[float, float]] = []
    for slice_start in range(0, len(samples), slice_len):
        chunk = samples[slice_start:slice_start + slice_len]
        offset_s = slice_start / SR
        for t in get_speech_timestamps(chunk, opts):
            regions.append((offset_s + t["start"] / SR, offset_s + t["end"] / SR))
    return _merge_touching_edges(regions)


def speech_chunks(samples: np.ndarray, out_dir: str, max_s: float = MAX_CHUNK_S) -> list[Chunk]:
    chunks: list[Chunk] = []
    for i, (start, end) in enumerate(pack_regions(speech_regions(samples, max_s), max_s)):
        path = os.path.join(out_dir, f"chunk_{i:03d}.wav")
        write_wav(samples[int(start * SR):int(end * SR)], path)
        chunks.append(Chunk(path=path, offset=round(start, 3)))
    return chunks


def language_samples(samples: np.ndarray, out_dir: str, dur_s: float = 20.0) -> list[str]:
    """Short samples at 10%, 50% and 90% of the audio for the language
    check; the whole audio when it is shorter than one sample."""
    total = len(samples) / SR
    if total <= dur_s:
        starts = [0.0]
    else:
        starts = [min(max(total * f - dur_s / 2, 0.0), total - dur_s) for f in (0.1, 0.5, 0.9)]
    paths = []
    for i, start in enumerate(starts):
        path = os.path.join(out_dir, f"langsample_{i}.wav")
        write_wav(samples[int(start * SR):int((start + dur_s) * SR)], path)
        paths.append(path)
    return paths
