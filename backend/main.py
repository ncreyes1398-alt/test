import os
import uuid
import threading
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

from audio_processor import AudioProcessor
from youtube_downloader import download_youtube_audio
import subprocess
import imageio_ffmpeg

_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def wav_to_mp3(wav_path: str, mp3_path: str, bitrate: str = "192k") -> None:
    subprocess.run(
        [_FFMPEG, "-y", "-i", wav_path, "-codec:a", "libmp3lame",
         "-b:a", bitrate, "-loglevel", "error", mp3_path],
        check=True,
    )

app = FastAPI(title="BeatMixer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
STATIC_DIR = BASE_DIR / "static"

UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

jobs: dict = {}
jobs_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=2)
processor = AudioProcessor()

ALLOWED_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"}


def find_upload(file_id: str) -> Optional[str]:
    for ext in ALLOWED_EXTS:
        p = UPLOADS_DIR / f"{file_id}{ext}"
        if p.exists():
            return str(p)
    return None


# ── Static files & SPA root ────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


# ── API ────────────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_song(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"Unsupported format: {ext}")

    file_id = str(uuid.uuid4())
    upload_path = UPLOADS_DIR / f"{file_id}{ext}"

    content = await file.read()
    upload_path.write_bytes(content)

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            executor, processor.analyze_song, str(upload_path)
        )
        result["file_id"] = file_id
        result["filename"] = file.filename
        return JSONResponse(result)
    except Exception as e:
        upload_path.unlink(missing_ok=True)
        raise HTTPException(500, str(e))


@app.post("/api/yt-upload")
async def upload_from_youtube(url: str = Form(...)):
    """Download audio from a YouTube URL and analyze it."""
    if not url.strip():
        raise HTTPException(400, "URL is required")

    try:
        import asyncio
        loop = asyncio.get_event_loop()

        file_path, title, file_id = await loop.run_in_executor(
            executor, download_youtube_audio, url, UPLOADS_DIR
        )

        result = await loop.run_in_executor(
            executor, processor.analyze_song, file_path
        )
        result["file_id"] = file_id
        result["filename"] = title
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(500, f"YouTube download failed: {e}")


@app.post("/api/process")
async def process_mix(
    song_a_id: str = Form(...),
    song_b_id: str = Form(...),
    vocals_from: str = Form(...),
    target_bpm: float = Form(...),
    vocals_volume: float = Form(1.0),
    instrumental_volume: float = Form(1.0),
    pitch_shift: float = Form(0.0),
):
    song_a = find_upload(song_a_id)
    song_b = find_upload(song_b_id)

    if not song_a or not song_b:
        raise HTTPException(404, "Song file(s) not found")

    if vocals_from not in ("a", "b"):
        raise HTTPException(400, "vocals_from must be 'a' or 'b'")

    job_id = str(uuid.uuid4())
    wav_path = str(OUTPUTS_DIR / f"{job_id}.wav")
    mp3_path = str(OUTPUTS_DIR / f"{job_id}.mp3")

    with jobs_lock:
        jobs[job_id] = {"status": "processing", "progress": 0}

    def run():
        def cb(p):
            # Reserve last 5% for MP3 conversion
            with jobs_lock:
                jobs[job_id]["progress"] = int(p * 0.95)

        try:
            processor.create_mix(
                song_a_path=song_a,
                song_b_path=song_b,
                vocals_from=vocals_from,
                target_bpm=target_bpm,
                vocals_volume=vocals_volume,
                instrumental_volume=instrumental_volume,
                pitch_shift=pitch_shift,
                output_path=wav_path,
                progress_callback=cb,
            )
            # Convert WAV → MP3 then clean up the intermediate WAV
            wav_to_mp3(wav_path, mp3_path)
            Path(wav_path).unlink(missing_ok=True)
            with jobs_lock:
                jobs[job_id] = {"status": "complete", "progress": 100}
        except Exception as e:
            with jobs_lock:
                jobs[job_id] = {"status": "error", "error": str(e), "progress": 0}

    executor.submit(run)
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/download/{job_id}")
async def download_mix(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job or job["status"] != "complete":
        raise HTTPException(404, "Mix not ready")

    mp3_path = OUTPUTS_DIR / f"{job_id}.mp3"
    if not mp3_path.exists():
        raise HTTPException(404, "Output file not found")
    return FileResponse(str(mp3_path), media_type="audio/mpeg", filename="beatmixer_output.mp3")


# Serve static assets
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
