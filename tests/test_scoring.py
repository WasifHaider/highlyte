import pytest

from backend.pipeline import scoring, segments


def words(start, end, prob=0.9, n=20):
    step = (end - start) / n
    return [segments.SegWord(t="baat", raw="baat", start=start + i * step, end=start + (i + 1) * step,
                             kind="hinglish", prob=prob) for i in range(n)]


def cand(start=0.0, end=20.0, standalone=0.9, hook=0.8, payoff=0.7, total=None, prob=0.9):
    c = scoring.Candidate(start=start, end=end, words=words(start, end, prob),
                          standalone=standalone, hook=hook, payoff=payoff)
    if total is not None:
        c.total = total
    return c


def test_duration_fit():
    assert scoring.duration_fit(20) == 1.0
    assert scoring.duration_fit(10) == 0.5
    assert scoring.duration_fit(8) == 0.0
    assert scoring.duration_fit(47.5) == 0.5
    assert scoring.duration_fit(61) == 0.0


def test_energy_compares_clip_with_episode_median():
    loud = [-20.0] * 200
    for i in range(20, 40):
        loud[i] = -14.0
    assert scoring.energy(loud, 10.0, 20.0) == 1.0
    assert scoring.energy(loud, 50.0, 60.0) == 0.5
    assert scoring.energy([], 0.0, 10.0) == 0.5
    assert scoring.energy([-100.0] * 50, 0.0, 10.0) == 0.5


def test_score_uses_spec_weights():
    c = scoring.score(cand(standalone=0.8, hook=0.6, payoff=0.4), [])
    assert c.energy == 0.5 and c.duration_fit == 1.0
    assert c.total == pytest.approx(0.32 + 0.15 + 0.06 + 0.05 + 0.10)


def test_structural_rejects():
    assert scoring.structural_reject(cand(0, 7)) == "too_short"
    assert scoring.structural_reject(cand(0, 61)) == "too_long"
    late = cand(0, 20)
    late.words = words(1.5, 20)
    assert scoring.structural_reject(late) == "late_speech"
    assert scoring.structural_reject(cand(prob=0.4)) == "low_confidence"
    assert scoring.structural_reject(cand()) is None


def test_qa_flags_low_confidence():
    assert scoring.qa_flags(cand(prob=0.65)) == ["low_confidence"]
    mixed = cand()
    for word in mixed.words[:4]:  # 20% of words under 0.4, mean still high
        word.prob = 0.3
    mixed.words[4].prob = 1.0
    assert scoring.qa_flags(mixed) == ["low_confidence"]
    assert scoring.qa_flags(cand(prob=0.9)) == []


def test_thresholds_and_near_miss():
    assert scoring.passes_thresholds(cand(standalone=0.7, hook=0.55))
    assert not scoring.passes_thresholds(cand(standalone=0.69, hook=0.9))
    assert scoring.near_miss(cand(standalone=0.5, hook=0.35))
    assert not scoring.near_miss(cand(standalone=0.49, hook=0.9))


def test_overlap_ratio_uses_shorter_clip():
    assert scoring.overlap_ratio(cand(0, 20), cand(10, 20)) == 1.0
    assert scoring.overlap_ratio(cand(0, 20), cand(15, 35)) == 0.25
    assert scoring.overlap_ratio(cand(0, 20), cand(30, 50)) == 0.0


def test_span_overlap():
    assert scoring.span_overlap((0, 20), (10, 20)) == 1.0
    assert scoring.span_overlap((0, 20), (15, 35)) == 0.25
    assert scoring.span_overlap((0, 20), (30, 50)) == 0.0
    assert scoring.span_overlap((0, 0), (0, 10)) == 0.0


def test_pack_keeps_best_non_overlapping_up_to_eight():
    cands = [cand(i * 25.0, i * 25.0 + 20, total=0.5 + i / 100) for i in range(10)]
    kept = scoring.pack(cands)
    assert len(kept) == 8
    assert [c.start for c in kept] == sorted(c.start for c in kept)
    assert min(c.total for c in kept) == 0.52


def test_pack_drops_heavy_overlap():
    best, dup, other = cand(0, 20, total=0.9), cand(5, 25, total=0.8), cand(30, 50, total=0.7)
    extra = [cand(60 + i * 25.0, 80 + i * 25.0, total=0.6) for i in range(3)]
    kept = scoring.pack([best, dup, other, *extra])
    assert dup not in kept and best in kept and other in kept


def test_pack_fills_to_five_with_flagged_near_misses():
    strong = [cand(i * 25.0, i * 25.0 + 20, total=0.9) for i in range(3)]
    weak = [cand(100 + i * 25.0, 120 + i * 25.0, standalone=0.6, hook=0.4, total=0.5) for i in range(3)]
    junk = cand(200, 220, standalone=0.3, hook=0.2, total=0.3)
    kept = scoring.pack([*strong, *weak, junk])
    assert len(kept) == 5
    assert sum("weak_pick" in c.flags for c in kept) == 2
    assert all(c.start != 200 for c in kept)
