import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


class StreamingEngine:
    """One-process streaming engine with demo and production modes."""

    def __init__(self, database, upload_folder: Path, playlist_folder: Path,
                 mode: str = "DEMO", log_folder: Path = None):
        self.db = database
        self.upload_folder = upload_folder
        self.playlist_folder = playlist_folder
        self.mode = mode.upper()
        self.log_folder = log_folder or Path("logs")
        self.process = None
        self.demo_thread = None
        self.status = "STOPPED"
        self.started_at = None
        self.current_video = None
        self.current_playlist = None
        self.current_destination = None
        self.orientation = None
        self.last_error = None
        self.retry_count = 0
        self.history_id = None
        self.lock = threading.Lock()

    def is_running(self):
        if self.mode == "DEMO":
            return self.status == "RUNNING"
        return self.process is not None and self.process.poll() is None

    def _log(self, level, message):
        safe = message.replace("\n", " ").replace("\r", " ")
        self.log_folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat()
        with (self.log_folder / "stream.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} [{level}] {safe}\n")
        with self.db.connection() as conn:
            conn.execute("INSERT INTO stream_events(level, message) VALUES (?, ?)", (level, safe))
            conn.commit()

    def build_command(self, playlist_id, destination_url, orientation):
        with self.db.connection() as conn:
            items = conn.execute(
                """SELECT v.stored_name, v.codec, v.audio_codec, v.width, v.height
                   FROM playlist_items p JOIN videos v ON v.id=p.video_id
                   WHERE p.playlist_id=? ORDER BY p.position""",
                (playlist_id,)
            ).fetchall()
        if not items:
            raise RuntimeError("Playlist is empty")
        for item in items:
            source = self.upload_folder / item["stored_name"]
            if not source.is_file():
                raise RuntimeError("A playlist video is missing")
            if not item["codec"] or not item["width"] or not item["height"]:
                raise RuntimeError("Corrupted or unsupported playlist media")

        mode = {"portrait_1080": (1080, 1920), "portrait_720": (720, 1280),
                "landscape_1080": (1920, 1080), "landscape_720": (1280, 720)}
        target = mode.get(orientation)
        if not target:
            raise RuntimeError("Invalid video orientation")
        incompatible = [i["stored_name"] for i in items if (i["width"], i["height"]) != target]
        if incompatible:
            raise RuntimeError(
                "STREAM_COPY_ORIENTATION_MISMATCH: COPY mode cannot change resolution. "
                "Select an orientation matching every source video."
            )

        valid_schemes = ("rtmp://", "rtmps://")
        if not destination_url.lower().startswith(valid_schemes):
            raise RuntimeError("Invalid RTMP/RTMPS destination URL")
        if len(items) == 1:
            inputs = ["-re", "-stream_loop", "-1", "-i", str(self.upload_folder / items[0]["stored_name"])]
        else:
            self.playlist_folder.mkdir(parents=True, exist_ok=True)
            concat = self.playlist_folder / "active_playlist.txt"
            with concat.open("w", encoding="utf-8") as handle:
                for item in items:
                    handle.write("file '" + str((self.upload_folder / item["stored_name"]).resolve()).replace("'", "'\\''") + "'\n")
                    handle.write("duration " + "0\n")
            inputs = ["-re", "-stream_loop", "-1", "-f", "concat", "-safe", "0", "-i", str(concat)]
        return ["ffmpeg", "-hide_banner", "-v", "warning", *inputs,
                "-map", "0:v:0", "-map", "0:a?", "-c:v", "copy", "-c:a", "copy",
                "-f", "flv", destination_url]

    def start(self, playlist_id, destination_id, destination_url, orientation,
              playlist_name=None, destination_name=None):
        with self.lock:
            if self.is_running():
                raise RuntimeError("A streaming process is already active")
            if not shutil.which("ffmpeg") and self.mode == "PRODUCTION":
                raise RuntimeError("FFmpeg is not installed")
            command = self.build_command(playlist_id, destination_url, orientation)
            self.started_at = datetime.now(timezone.utc)
            self.status = "STARTING"
            self.last_error = None
            self.retry_count = 0
            self.current_playlist = playlist_name or str(playlist_id)
            self.current_destination = destination_name or str(destination_id)
            self.orientation = orientation
            with self.db.connection() as conn:
                cursor = conn.execute(
                    """INSERT INTO stream_history(started_at, playlist_id, destination_id, result)
                       VALUES (?, ?, ?, 'RUNNING')""",
                    (self.started_at.isoformat(), playlist_id, destination_id)
                )
                conn.commit()
                self.history_id = cursor.lastrowid
            if self.mode == "DEMO":
                self.status = "RUNNING"
                self._log("INFO", "DEMO stream process started; no real RTMP broadcast is active")
                return {"mode": "DEMO", "status": "DEMO_RUNNING", "process_running": True}
            try:
                log = open(self.log_folder / "ffmpeg.log", "ab", buffering=0)
                self.process = subprocess.Popen(
                    command, stdout=subprocess.DEVNULL, stderr=log,
                    start_new_session=True
                )
                self.status = "RUNNING"
                self._log("INFO", "FFmpeg process started")
            except OSError as exc:
                self.status = "ERROR"
                self.last_error = "Unable to start FFmpeg"
                self._log("ERROR", str(exc))
                raise
        threading.Thread(target=self._watch_process, daemon=True).start()
        return {"mode": "PRODUCTION", "status": "RUNNING", "process_running": True}

    def _watch_process(self):
        while self.process is not None:
            code = self.process.poll()
            if code is not None:
                self.status = "ERROR"
                self.last_error = f"FFmpeg exited unexpectedly (code {code})"
                self._log("ERROR", self.last_error)
                break
            time.sleep(1)

    def stop(self, reason="Stopped by administrator"):
        with self.lock:
            if self.mode == "DEMO":
                self.status = "STOPPED"
                self.started_at = None
                self._finish_history("STOPPED", reason)
                self._log("INFO", "DEMO stream process stopped")
                return
            if self.process is not None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
                self.process = None
            self.status = "STOPPED"
            self.started_at = None
            self._finish_history("STOPPED", reason)
            self._log("INFO", "FFmpeg stream stopped")

    def _finish_history(self, result, error=None):
        if not self.history_id:
            return
        stopped = datetime.now(timezone.utc)
        duration = 0
        if self.started_at:
            duration = int((stopped - self.started_at).total_seconds())
        with self.db.connection() as conn:
            conn.execute(
                """UPDATE stream_history SET stopped_at=?, duration=?, result=?, error=? WHERE id=?""",
                (stopped.isoformat(), duration, result, error, self.history_id)
            )
            conn.commit()
        self.history_id = None

    def snapshot(self):
        process_running = self.is_running()
        uptime = 0
        if self.started_at:
            uptime = int((datetime.now(timezone.utc) - self.started_at).total_seconds())
        return {
            "mode": self.mode,
            "application_running": True,
            "process_running": process_running,
            "status": "DEMO_RUNNING" if self.mode == "DEMO" and process_running else self.status,
            "rtmp_connection_established": "Unknown",
            "platform_stream_detected": False,
            "platform_broadcast_live": False,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "uptime": uptime,
            "current_playlist": self.current_playlist,
            "current_destination": self.current_destination,
            "orientation": self.orientation,
            "last_error": self.last_error,
        }
