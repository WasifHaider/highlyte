"""Everything that happens to one clip after it's picked: cut its
padded 16:9 segment, time its words, analyse faces, upload the segment,
and describe the result as a ClipSpec. The renderer (Remotion) draws the
final 9:16 short from that spec; no finished video is made here. The
segment carries an 8 s spare window either side of the clip, so a later
nudge or "include the next sentence" edit never needs a re-cut.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from .. import storage
from ..spec import ClipSpec, Source
from . import cut, face_detect, reframe, shots, words
from .selection import Clip
from .transcript import TranscriptSegment

# Spare source video either side of the clip: nudges and "include the
# next sentence" stay inside it, so they never need a re-cut.
SEGMENT_PAD_S = 8.0

# A face must show within this long of the clip start, or the clip gets a
# "No face at start" QA flag.
FACE_START_S = 1.0


@dataclass
class PreparedClip:
    spec: ClipSpec
    storage_key: str | None
    face_at_start: bool | None = None
    filename: str | None = None


def clip_filename(idx: int, revision: int = 0) -> str:
    """The segment's file name (and R2 key suffix). Revision 0 keeps the
    original clip_{idx}.mp4, so clips made before Swap/Regenerate existed
    still resolve; a replacement gets its own name, so preparing it never
    touches the file or object the current clip still points at."""
    return f"clip_{idx}.mp4" if revision <= 0 else f"clip_{idx}_r{revision}.mp4"


def segment_bounds(clip_start: float, clip_end: float, video_duration: float) -> tuple[float, float]:
    seg_start = max(0.0, clip_start - SEGMENT_PAD_S)
    seg_end = clip_end + SEGMENT_PAD_S
    if video_duration:
        seg_end = min(seg_end, video_duration)
    return seg_start, seg_end


def make_poster(segment_path: str, at_s: float) -> str | None:
    """The clip card's still image, next to the segment. Best effort: a
    card without one just shows a plain play button."""
    out = os.path.join(os.path.dirname(segment_path), storage.thumb_filename(os.path.basename(segment_path)))
    try:
        return cut.make_thumbnail(segment_path, at_s, out)
    except Exception as e:  # noqa: BLE001
        print(f"[poster] failed for {segment_path}: {e}")
        return None


def prepare_clip(
    *,
    job_id: str,
    idx: int,
    clip: Clip,
    video_path: str,
    video_duration: float,
    segments: list[TranscriptSegment],
    clips_dir: str,
    models_dir: str,
    on_step: Callable[[str], None],
    revision: int = 0,
) -> PreparedClip:
    clip_id = f"{job_id}-{idx}"
    filename = clip_filename(idx, revision)
    local_path = os.path.join(clips_dir, job_id, filename)
    seg_start, seg_end = segment_bounds(clip.start, clip.end, video_duration)
    offset = clip.start - seg_start
    duration = clip.end - clip.start

    on_step("cutting")
    cut.cut_clip(video_path, seg_start, seg_end, local_path)
    width, height, fps = cut.probe_video(local_path)
    thumb_path = make_poster(local_path, offset)

    on_step("timing captions")
    clip_word_list = words.clip_words(segments, seg_start, seg_end, clip.emphasis)

    on_step("framing")
    face_at_start: bool | None = None
    try:
        frames, times, thumbs = face_detect.sample_detections(local_path, face_detect.ensure_model(models_dir))
        opening = [f for t, f in zip(times, frames) if offset <= t <= offset + FACE_START_S]
        face_at_start = any(len(f) > 0 for f in opening) if opening else None
        cuts = shots.cut_times(thumbs, times)
        reframe_result = reframe.analyze(frames, times, cuts)
    except Exception as e:  # noqa: BLE001
        print(f"[reframe] face analysis failed for {clip_id}, using fit: {e}")
        reframe_result = reframe.fallback()

    on_step("uploading")
    storage_key = None
    if storage.is_enabled():
        try:
            key = storage.clip_key(job_id, filename)
            storage.upload_clip(local_path, key)
            os.remove(local_path)
            storage_key = key
        except Exception as e:  # noqa: BLE001
            print(f"[r2] upload failed for {job_id}/{filename}, keeping local copy: {e}")
        if thumb_path is not None:
            try:
                storage.upload_thumb(thumb_path, storage.clip_key(job_id, os.path.basename(thumb_path)))
                os.remove(thumb_path)
            except Exception as e:  # noqa: BLE001
                print(f"[r2] poster upload failed for {job_id}/{filename}, keeping local copy: {e}")

    spec = ClipSpec(
        version=2,
        clipId=clip_id,
        source=Source(url="", width=width, height=height, fps=fps, duration=round(seg_end - seg_start, 3)),
        start=round(offset, 3),
        end=round(offset + duration, 3),
        words=clip_word_list,
        wordsApprox=False,
        hookTitle=clip.hook_title,
        viralityScore=max(0.0, min(10.0, round(clip.score, 1))),
        reframe=reframe_result,
    )
    return PreparedClip(spec=spec, storage_key=storage_key, face_at_start=face_at_start, filename=filename)
