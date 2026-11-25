import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_path(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")
    STREAMING_MODE = os.getenv("STREAMING_MODE", "DEMO").upper()
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-this-password")
    DATABASE_PATH = env_path("DATABASE_PATH", "data/trimiq.sqlite3")
    UPLOAD_FOLDER = env_path("UPLOAD_FOLDER", "uploads")
    LOG_FOLDER = env_path("LOG_FOLDER", "logs")
    PLAYLIST_FOLDER = env_path("PLAYLIST_FOLDER", "playlists")
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "2048"))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
