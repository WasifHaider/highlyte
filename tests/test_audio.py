import os
import subprocess
import wave

import numpy as np

from backend.pipeline import audio


def test_pack_regions_joins_until_max():
    regions = [(0.0, 50.0), (51.0, 100.0), (101.0, 130.0), (131.0, 140.0)]
    assert audio.pack_regions(regions, 120.0) == [(0.0, 100.0), (101.0, 140.0)]


def test_pack_regions_never_exceeds_max_for_short_regions():
    regions = [(i * 10.0, i * 10.0 + 8.0) for i in range(40)]
    for start, end in audio.pack_regions(regions, 120.0):
        assert end - start <= 120.0


def test_pack_regions_empty():
    assert audio.pack_regions([], 120.0) == []


def test_pack_regions_starts_new_chunk_on_long_gap():
    """A gap bigger than MAX_GAP_S is likely music/silence; packing it into
    a chunk anyway gives Whisper room to hallucinate text over it."""
    regions = [(0.0, 10.0), (13.0, 20.0)]  # gap 3.0s > MAX_GAP_S
    assert audio.pack_regions(regions, 120.0) == [(0.0, 10.0), (13.0, 20.0)]


def test_pack_regions_joins_short_gap_within_max():
    regions = [(0.0, 10.0), (11.0, 20.0)]  # gap 1.0s <= MAX_GAP_S
    assert audio.pack_regions(regions, 120.0) == [(0.0, 20.0)]


def test_speech_chunks_writes_wavs_with_offsets(tmp_path, monkeypatch):
    samples = np.zeros(audio.SR * 300, dtype=np.float32)
    monkeypatch.setattr(audio, "speech_regions", lambda s, max_s=120.0: [(1.0, 60.0), (62.0, 110.0), (130.0, 200.0)])
    chunks = audio.speech_chunks(samples, str(tmp_path))
    assert [c.offset for c in chunks] == [1.0, 130.0]
    with wave.open(chunks[0].path) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        assert abs(w.getnframes() / 16000 - 109.0) < 0.01


def test_language_samples_positions(tmp_path):
    samples = np.zeros(audio.SR * 200, dtype=np.float32)
    paths = audio.language_samples(samples, str(tmp_path))
    assert len(paths) == 3 and all(os.path.exists(p) for p in paths)


def test_language_samples_short_audio(tmp_path):
    samples = np.zeros(audio.SR * 8, dtype=np.float32)
    assert len(audio.language_samples(samples, str(tmp_path))) == 1


def test_speech_regions_slices_and_shifts_offsets(monkeypatch):
    """speech_regions must run VAD over SLICE_S-second slices of samples
    rather than the whole array at once (memory spike on long audio), and
    shift each slice's timestamps back onto the full-audio timeline."""
    calls = []

    def fake_get_speech_timestamps(chunk, opts):
        calls.append(len(chunk))
        # One region near the start of every slice it's given.
        return [{"start": 0, "end": 1000}]

    monkeypatch.setattr(
        "faster_whisper.vad.get_speech_timestamps", fake_get_speech_timestamps,
    )
    samples = np.zeros(audio.SR * int(audio.SLICE_S * 2.5), dtype=np.float32)
    regions = audio.speech_regions(samples)

    # Three slices: two full SLICE_S ones and a final partial one.
    assert len(calls) == 3
    assert calls[0] == audio.SR * audio.SLICE_S
    assert calls[1] == audio.SR * audio.SLICE_S
    assert calls[2] == audio.SR * int(audio.SLICE_S * 0.5)

    # Each slice's fake region (0..1000 samples = 0..0.0625s) is shifted by
    # that slice's start time.
    assert regions[0] == (0.0, 1000 / audio.SR)
    assert regions[1] == (audio.SLICE_S, audio.SLICE_S + 1000 / audio.SR)
    assert regions[2] == (2 * audio.SLICE_S, 2 * audio.SLICE_S + 1000 / audio.SR)


def test_speech_regions_merges_touching_edge_regions(monkeypatch):
    """A region ending right at a slice boundary and one starting right at
    the next slice's start are really one continuous region split only by
    the slicing, so they must be merged back together (gap < 0.25s)."""
    slice_samples = int(audio.SLICE_S * audio.SR)

    def fake_get_speech_timestamps(chunk, opts):
        if len(chunk) == slice_samples:
            # Region ending at the very end of this slice.
            return [{"start": 0, "end": slice_samples}]
        # Final shorter slice: region starting at its very start.
        return [{"start": 0, "end": 1000}]

    monkeypatch.setattr(
        "faster_whisper.vad.get_speech_timestamps", fake_get_speech_timestamps,
    )
    samples = np.zeros(audio.SR * int(audio.SLICE_S * 1.5), dtype=np.float32)
    regions = audio.speech_regions(samples)
    assert regions == [(0.0, audio.SLICE_S + 1000 / audio.SR)]


def test_speech_regions_pins_vad_options(monkeypatch):
    seen = {}

    def fake_get_speech_timestamps(chunk, opts):
        seen["opts"] = opts
        return []

    monkeypatch.setattr(
        "faster_whisper.vad.get_speech_timestamps", fake_get_speech_timestamps,
    )
    samples = np.zeros(audio.SR * 5, dtype=np.float32)
    audio.speech_regions(samples, max_s=120.0)
    opts = seen["opts"]
    assert opts.min_silence_duration_ms == 250
    assert opts.min_speech_duration_ms == 400
    assert opts.speech_pad_ms == 250
    assert opts.max_speech_duration_s == 119.0


def test_normalize_produces_16k_mono(tmp_path):
    src = tmp_path / "tone.m4a"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2:sample_rate=44100", "-ac", "2", str(src)], check=True)
    dst = tmp_path / "out.wav"
    audio.normalize(str(src), str(dst))
    with wave.open(str(dst)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
