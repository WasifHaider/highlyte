"""Sample a video at a few frames per second and detect faces with
MediaPipe's FaceLandmarker task.

MediaPipe 1.0 removed the old `mediapipe.solutions` API; the Tasks API
needs a model file, downloaded once into data/models/. FaceLandmarker is
used (rather than the lighter FaceDetector) because its `jawOpen`
blendshape is what reframe.speaker_timeline uses to tell who is talking.
"""
from __future__ import annotations

import os
import urllib.request

from .reframe import Detection

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
MAX_FACES = 4


def ensure_model(models_dir: str) -> str:
    path = os.path.join(models_dir, "face_landmarker.task")
    if not os.path.exists(path):
        os.makedirs(models_dir, exist_ok=True)
        tmp = path + ".part"
        urllib.request.urlretrieve(MODEL_URL, tmp)
        os.replace(tmp, path)
    return path


def sample_detections(
    video_path: str, model_path: str, sample_fps: float = 5.0
) -> tuple[list[list[Detection]], list[float]]:
    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(src_fps / sample_fps))

    options = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=MAX_FACES,
        output_face_blendshapes=True,
    )
    frames: list[list[Detection]] = []
    times: list[float] = []
    try:
        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            idx = 0
            while True:
                # grab() skips decoding frames we don't sample, which is most of them.
                if not cap.grab():
                    break
                if idx % step == 0:
                    ok, frame = cap.retrieve()
                    if not ok:
                        break
                    t = idx / src_fps
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    result = landmarker.detect_for_video(image, int(t * 1000))
                    frames.append(_to_detections(result))
                    times.append(round(t, 3))
                idx += 1
    finally:
        cap.release()
    return frames, times


def _to_detections(result) -> list[Detection]:
    dets: list[Detection] = []
    for i, landmarks in enumerate(result.face_landmarks):
        xs = [p.x for p in landmarks]
        ys = [p.y for p in landmarks]
        x0, x1 = max(min(xs), 0.0), min(max(xs), 1.0)
        y0, y1 = max(min(ys), 0.0), min(max(ys), 1.0)
        jaw = 0.0
        if i < len(result.face_blendshapes):
            jaw = next((c.score for c in result.face_blendshapes[i] if c.category_name == "jawOpen"), 0.0)
        dets.append(Detection(cx=(x0 + x1) / 2, cy=(y0 + y1) / 2, w=x1 - x0, h=y1 - y0, jaw=float(jaw)))
    return dets
