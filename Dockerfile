# HighLyte backend (FastAPI + yt-dlp + ffmpeg + MediaPipe + faster-whisper).
# Built from the repo root because the app is the `backend` package and it
# reads renderer/package.json at startup to check Remotion versions.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg/ffprobe for cutting; libgl1 + libglib2.0-0 are what OpenCV (pulled
# in by MediaPipe) needs to import on a slim image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp needs a JavaScript runtime to solve YouTube's player challenges.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend ./backend
COPY renderer/package.json ./renderer/package.json

EXPOSE 8000
# One worker only: jobs in progress live in this process's memory.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
