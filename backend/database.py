import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def init(self):
        with self.connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY,
                stored_name TEXT UNIQUE NOT NULL,
                original_name TEXT NOT NULL,
                size INTEGER NOT NULL,
                duration REAL,
                width INTEGER,
                height INTEGER,
                codec TEXT,
                audio_codec TEXT,
                thumbnail TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                playback_mode TEXT NOT NULL DEFAULT 'repeat_playlist',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS playlist_items (
                playlist_id INTEGER NOT NULL,
                video_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (playlist_id, video_id),
                FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
                FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS destinations (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                server_url TEXT NOT NULL,
                stream_key_encrypted TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS stream_history (
                id INTEGER PRIMARY KEY,
                started_at TEXT,
                stopped_at TEXT,
                duration INTEGER,
                playlist_id INTEGER,
                destination_id INTEGER,
                result TEXT,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stream_events (
                id INTEGER PRIMARY KEY,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """)
            conn.commit()
