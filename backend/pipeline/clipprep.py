"""Everything that happens to one highlight after it's picked: cut its
padded 16:9 segment, time its words, analyse faces, upload the segment,
and describe the result as a ClipSpec. The renderer (Remotion) draws the
final 9:16 short from that spec; no finished video is made here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from .. import storage
from ..spec import ClipSpec, Source
from . import cut, face_detect, reframe, words
from .highlight import Clip
from .transcript import TranscriptSegment

# Extra source video kept either side of the clip, so the renderer and
# any later trim editing have a little room without re-cutting.
SEGMENT_PAD_S = 1.0


@dataclass
class PreparedClip:
    spec: ClipSpec
    storage_key: str | None


def segment_bounds(clip_start: float, clip_end: float, video_duration: float) -> tuple[float, float]:
    seg_start = max(0.0, clip_start - SEGMENT_PAD_S)
    seg_end = clip_end + SEGMENT_PAD_S
    if video_duration:
        seg_end = min(seg_end, video_duration)
    return seg_start, seg_end


def prepare_clip(
    *,
    job_id: str,
    idx: int,
    clip: Clip,
    video_path: str,
    video_duration: float,
    segments: list[TranscriptSegment],
    transcript_source: str,
    audio_path: str,
    clips_dir: str,
    models_dir: str,
    groq_key: str | None,
    prompt: str | None,
    on_step: Callable[[str], None],
) -> PreparedClip:
    clip_id = f"{job_id}-{idx}"
    filename = f"clip_{idx}.mp4"
    local_path = os.path.join(clips_dir, job_id, filename)
    seg_start, seg_end = segment_bounds(clip.start, clip.end, video_duration)
    offset = clip.start - seg_start
    duration = clip.end - clip.start

    on_step("cutting")
    cut.cut_clip(video_path, seg_start, seg_end, local_path)
    width, height, fps = cut.probe_video(local_path)

    on_step("timing captions")
    clip_word_list, approx = words.clip_words(
        segments, transcript_source, audio_path, clip.start, clip.end, clip.emphasis,
        groq_key=groq_key, prompt=prompt,
    )

    on_step("framing")
    try:
        frames, times = face_detect.sample_detections(local_path, face_detect.ensure_model(models_dir))
        # Keep only samples inside the clip itself, re-based to its start.
        kept = [(round(t - offset, 3), f) for t, f in zip(times, frames) if offset <= t <= offset + duration]
        reframe_result = reframe.analyze([f for _, f in kept], [t for t, _ in kept])
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

    spec = ClipSpec(
        clipId=clip_id,
        source=Source(url="", width=width, height=height, fps=fps),
        start=round(offset, 3),
        end=round(offset + duration, 3),
        words=clip_word_list,
        wordsApprox=approx,
        hookTitle=clip.hook_title,
        viralityScore=max(0.0, min(10.0, round(clip.score, 1))),
        reframe=reframe_result,
    )
    return PreparedClip(spec=spec, storage_key=storage_key)
