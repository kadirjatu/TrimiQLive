import json
import shutil
import subprocess
import uuid
from pathlib import Path


def probe_video(path: Path):
    if not shutil.which("ffprobe"):
        return {"duration": None, "width": None, "height": None, "codec": None, "audio_codec": None,
                "warning": "FFprobe is not installed"}
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=False
        )
        if result.returncode != 0:
            return {"warning": "Unsupported or corrupted media"}
        data = json.loads(result.stdout)
        video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
        audio = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), None)
        if not video:
            return {"warning": "No video stream found"}
        return {
            "duration": float(data.get("format", {}).get("duration") or 0),
            "width": video.get("width"),
            "height": video.get("height"),
            "codec": video.get("codec_name"),
            "audio_codec": audio.get("codec_name") if audio else None,
            "warning": None if audio else "No audio stream found",
        }
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return {"warning": "Unable to inspect media"}


def make_thumbnail(source: Path, destination: Path):
    if not shutil.which("ffmpeg"):
        return None
    destination.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.jpg"
    target = destination / name
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(source), "-frames:v", "1", "-vf", "scale=320:-1",
             "-y", str(target)],
            capture_output=True, text=True, timeout=30, check=False
        )
        return name if result.returncode == 0 and target.exists() else None
    except (subprocess.TimeoutExpired, OSError):
        return None
