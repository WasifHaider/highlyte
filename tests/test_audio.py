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


def test_normalize_produces_16k_mono(tmp_path):
    src = tmp_path / "tone.m4a"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2:sample_rate=44100", "-ac", "2", str(src)], check=True)
    dst = tmp_path / "out.wav"
    audio.normalize(str(src), str(dst))
    with wave.open(str(dst)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
