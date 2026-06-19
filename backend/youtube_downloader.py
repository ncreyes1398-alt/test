import os
import uuid
from pathlib import Path
import imageio_ffmpeg
import yt_dlp


# Point yt-dlp at the bundled ffmpeg binary so we don't depend on system ffmpeg
FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()


def download_youtube_audio(url: str, output_dir: Path) -> tuple[str, str]:
    """
    Download the best audio from a YouTube URL.
    Returns (file_path, video_title).
    """
    file_id = str(uuid.uuid4())
    output_template = str(output_dir / f"{file_id}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": str(Path(FFMPEG_BIN).parent),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "YouTube audio")

    # yt-dlp writes <id>.mp3 after post-processing
    output_path = output_dir / f"{file_id}.mp3"
    if not output_path.exists():
        # Fall back: find whatever it wrote
        matches = list(output_dir.glob(f"{file_id}.*"))
        if not matches:
            raise FileNotFoundError("yt-dlp did not produce an output file")
        output_path = matches[0]

    return str(output_path), title, file_id
