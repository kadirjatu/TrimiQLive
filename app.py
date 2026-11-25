import os
import re
import sqlite3
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psutil
from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except ImportError:
    Limiter = None

from backend.config import Config
from backend.database import Database
from backend.security import decrypt_secret, encrypt_secret
from backend.services.video import make_thumbnail, probe_video
from backend.streaming.engine import StreamingEngine


app = Flask(__name__, template_folder="frontend/templates", static_folder="frontend/static")
app.config.from_object(Config)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("COOKIE_SECURE", "0") == "1"

db = Database(app.config["DATABASE_PATH"])
db.init()
for folder in (app.config["UPLOAD_FOLDER"], app.config["LOG_FOLDER"], app.config["PLAYLIST_FOLDER"]):
    Path(folder).mkdir(parents=True, exist_ok=True)


def load_or_create_encryption_key():
    configured = os.getenv("KEY_ENCRYPTION_KEY")
    if configured:
        return configured
    key_file = Path(app.config["DATABASE_PATH"]).parent / ".stream-key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = uuid.uuid4().hex + uuid.uuid4().hex
    key_file.write_text(key, encoding="utf-8")
    os.chmod(key_file, 0o600)
    return key


STREAM_KEY_SECRET = load_or_create_encryption_key()

engine = StreamingEngine(
    db,
    app.config["UPLOAD_FOLDER"],
    app.config["PLAYLIST_FOLDER"],
    app.config["STREAMING_MODE"],
    app.config["LOG_FOLDER"],
)

if Limiter:
    limiter = Limiter(get_remote_address, app=app, default_limits=["300 per minute"])
else:
    limiter = None


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = uuid.uuid4().hex
        session["csrf_token"] = token
    return token


@app.before_request
def protect_mutating_requests():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.endpoint not in ("login", "signup"):
            if not session.get("admin"):
                abort(401)
        submitted_token = (
            request.headers.get("X-CSRF-Token")
            or request.form.get("csrf_token")
        )
        expected_token = session.get("csrf_token")
        if not expected_token or submitted_token != expected_token:
            abort(403)


@app.context_processor
def inject_csrf():
    return {"csrf_token": csrf_token()}


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    with db.connection() as conn:
        has_account = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
    if not has_account:
        return redirect(url_for("signup"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        with db.connection() as conn:
            user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["admin"] = username
            csrf_token()
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid username or password"), 401
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        with db.connection() as conn:
            has_account = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
        if has_account:
            return redirect(url_for("login"))
        return render_template("signup.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
        return render_template(
            "signup.html",
            error="Username must be 3-32 characters: letters, numbers, dots, dashes or underscores.",
        ), 400
    if len(password) < 12:
        return render_template("signup.html", error="Password must be at least 12 characters."), 400
    if password != confirm_password:
        return render_template("signup.html", error="Passwords do not match."), 400

    try:
        with db.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            has_account = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
            if has_account:
                conn.rollback()
                return render_template(
                    "signup.html", error="Initial account setup is already complete."
                ), 409
            conn.execute(
                "INSERT INTO users(username, password_hash) VALUES (?, ?)",
                (username, generate_password_hash(password)),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        return render_template("signup.html", error="Unable to create the account."), 409

    session.clear()
    session["admin"] = username
    csrf_token()
    return redirect(url_for("dashboard"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html", page="dashboard")


@app.route("/video-library")
@login_required
def video_library():
    return render_template("dashboard.html", page="video_library")


@app.route("/playlists")
@login_required
def playlists_page():
    return render_template("dashboard.html", page="playlists")


@app.route("/streaming")
@login_required
def streaming_page():
    return render_template("dashboard.html", page="streaming")


@app.route("/destinations")
@login_required
def destinations_page():
    return render_template("dashboard.html", page="destinations")


@app.route("/history")
@login_required
def history_page():
    return render_template("dashboard.html", page="history")


@app.route("/settings")
@login_required
def settings_page():
    return render_template("dashboard.html", page="settings")


@app.route("/system")
@login_required
def system_page():
    return render_template("dashboard.html", page="system")


@app.route("/api/system")
@login_required
def api_system():
    disk = shutil.disk_usage(app.config["UPLOAD_FOLDER"])
    return jsonify({
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": psutil.virtual_memory().percent,
        "ram_available_mb": round(psutil.virtual_memory().available / 1024 / 1024),
        "disk_free_mb": round(disk.free / 1024 / 1024),
        "network_status": "Available",
        "stream": engine.snapshot(),
    })


@app.route("/api/dashboard")
@login_required
def api_dashboard():
    with db.connection() as conn:
        video_count = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        playlist_count = conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0]
        last_error = conn.execute(
            "SELECT message FROM stream_events WHERE level='ERROR' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    snapshot = engine.snapshot()
    snapshot.update({
        "video_count": video_count,
        "playlist_count": playlist_count,
        "last_error": snapshot["last_error"] or (last_error["message"] if last_error else None),
    })
    return jsonify(snapshot)


@app.route("/api/videos", methods=["GET"])
@login_required
def api_videos():
    search = request.args.get("search", "").strip()
    sort = request.args.get("sort", "created_at")
    allowed = {"created_at": "created_at DESC", "original_name": "original_name ASC",
               "size": "size DESC", "duration": "duration DESC"}
    order = allowed.get(sort, "created_at DESC")
    with db.connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM videos WHERE original_name LIKE ? OR stored_name LIKE ? ORDER BY {order}",
            (f"%{search}%", f"%{search}%")
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/videos/upload", methods=["POST"])
@login_required
def upload_video():
    uploaded = request.files.get("video")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "No video file provided"}), 400
    original = secure_filename(uploaded.filename)
    if Path(original).suffix.lower() not in (".mp4",):
        return jsonify({"error": "Only MP4 files are accepted"}), 400
    stored = f"{uuid.uuid4().hex}{Path(original).suffix.lower()}"
    target = app.config["UPLOAD_FOLDER"] / stored
    uploaded.save(target)
    if target.stat().st_size == 0:
        target.unlink()
        return jsonify({"error": "The uploaded file is empty"}), 400
    metadata = probe_video(target)
    if metadata.get("warning") in ("Unsupported or corrupted media", "No video stream found", "Unable to inspect media"):
        target.unlink()
        return jsonify({"error": metadata["warning"]}), 400
    thumb = make_thumbnail(target, app.config["UPLOAD_FOLDER"] / "thumbnails")
    with db.connection() as conn:
        cursor = conn.execute(
            """INSERT INTO videos(stored_name, original_name, size, duration, width, height, codec, audio_codec, thumbnail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (stored, original, target.stat().st_size, metadata["duration"], metadata["width"],
             metadata["height"], metadata["codec"], metadata["audio_codec"], thumb)
        )
        conn.commit()
        video_id = cursor.lastrowid
    return jsonify({"id": video_id, "warning": metadata.get("warning")} ), 201


@app.route("/api/videos/<int:video_id>", methods=["DELETE"])
@login_required
def delete_video(video_id):
    with db.connection() as conn:
        video = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        if not video:
            return jsonify({"error": "Video not found"}), 404
        conn.execute("DELETE FROM videos WHERE id=?", (video_id,))
        conn.execute("DELETE FROM playlist_items WHERE video_id=?", (video_id,))
        conn.commit()
    target = app.config["UPLOAD_FOLDER"] / video["stored_name"]
    if target.is_file():
        target.unlink()
    if video["thumbnail"]:
        thumb = app.config["UPLOAD_FOLDER"] / "thumbnails" / video["thumbnail"]
        if thumb.is_file():
            thumb.unlink()
    return jsonify({"success": True})


@app.route("/uploads/thumbnails/<path:name>")
@login_required
def thumbnail(name):
    return send_from_directory(app.config["UPLOAD_FOLDER"] / "thumbnails", name)


@app.route("/api/playlists", methods=["GET", "POST"])
@login_required
def api_playlists():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        if not name:
            return jsonify({"error": "Playlist name is required"}), 400
        mode = str(data.get("playback_mode", "repeat_playlist"))
        if mode not in ("repeat_video", "repeat_playlist", "play_once"):
            return jsonify({"error": "Invalid playback mode"}), 400
        with db.connection() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO playlists(name, playback_mode) VALUES (?, ?)", (name, mode)
                )
                conn.commit()
                return jsonify({"id": cursor.lastrowid, "name": name, "playback_mode": mode}), 201
            except Exception:
                return jsonify({"error": "A playlist with that name already exists"}), 409
    with db.connection() as conn:
        playlists = conn.execute("SELECT * FROM playlists ORDER BY name").fetchall()
        result = []
        for playlist in playlists:
            items = conn.execute(
                """SELECT v.*, p.position FROM playlist_items p JOIN videos v ON v.id=p.video_id
                   WHERE p.playlist_id=? ORDER BY p.position""",
                (playlist["id"],)
            ).fetchall()
            result.append({**dict(playlist), "items": [dict(item) for item in items],
                           "duration": sum(item["duration"] or 0 for item in items)})
    return jsonify(result)


@app.route("/api/playlists/<int:playlist_id>", methods=["PUT", "DELETE"])
@login_required
def playlist_mutation(playlist_id):
    data = request.get_json(silent=True) or {}
    with db.connection() as conn:
        playlist = conn.execute("SELECT * FROM playlists WHERE id=?", (playlist_id,)).fetchone()
        if not playlist:
            return jsonify({"error": "Playlist not found"}), 404
        if request.method == "DELETE":
            conn.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))
            conn.commit()
            return jsonify({"success": True})
        name = str(data.get("name", playlist["name"])).strip()
        mode = str(data.get("playback_mode", playlist["playback_mode"]))
        if not name or mode not in ("repeat_video", "repeat_playlist", "play_once"):
            return jsonify({"error": "Invalid playlist data"}), 400
        conn.execute("UPDATE playlists SET name=?, playback_mode=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (name, mode, playlist_id))
        conn.commit()
        return jsonify({"success": True})


@app.route("/api/playlists/<int:playlist_id>/items", methods=["PUT"])
@login_required
def update_playlist_items(playlist_id):
    data = request.get_json(silent=True) or {}
    video_ids = data.get("video_ids", [])
    if not isinstance(video_ids, list) or len(video_ids) != len(set(video_ids)):
        return jsonify({"error": "video_ids must be a list of unique video IDs"}), 400
    with db.connection() as conn:
        for video_id in video_ids:
            if not conn.execute("SELECT id FROM videos WHERE id=?", (video_id,)).fetchone():
                return jsonify({"error": f"Video {video_id} not found"}), 404
        conn.execute("DELETE FROM playlist_items WHERE playlist_id=?", (playlist_id,))
        conn.executemany(
            "INSERT INTO playlist_items(playlist_id, video_id, position) VALUES (?, ?, ?)",
            [(playlist_id, video_id, position) for position, video_id in enumerate(video_ids)]
        )
        conn.execute("UPDATE playlists SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (playlist_id,))
        conn.commit()
    return jsonify({"success": True})


@app.route("/api/destinations", methods=["GET", "POST"])
@login_required
def api_destinations():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        platform = str(data.get("platform", ""))
        server_url = str(data.get("server_url", "")).strip()
        stream_key = str(data.get("stream_key", "")).strip()
        if not name or platform not in ("YouTube Live", "Facebook Live", "Custom RTMP"):
            return jsonify({"error": "Name and a supported platform are required"}), 400
        if not server_url.lower().startswith(("rtmp://", "rtmps://")) or not stream_key:
            return jsonify({"error": "A valid RTMP/RTMPS URL and stream key are required"}), 400
        encrypted = encrypt_secret(stream_key, STREAM_KEY_SECRET)
        with db.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO destinations(name, platform, server_url, stream_key_encrypted, enabled)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, platform, server_url, encrypted, 1 if data.get("enabled", True) else 0)
            )
            conn.commit()
            return jsonify({"id": cursor.lastrowid, "name": name, "platform": platform,
                            "server_url": server_url, "enabled": True, "stream_key_masked": "********"}), 201
    with db.connection() as conn:
        rows = conn.execute("SELECT id,name,platform,server_url,enabled,created_at FROM destinations ORDER BY name").fetchall()
    result = [{**dict(row), "stream_key_masked": "********"} for row in rows]
    return jsonify(result)


@app.route("/api/destinations/<int:destination_id>", methods=["PUT", "DELETE"])
@login_required
def destination_mutation(destination_id):
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM destinations WHERE id=?", (destination_id,)).fetchone()
        if not row:
            return jsonify({"error": "Destination not found"}), 404
        if request.method == "DELETE":
            conn.execute("DELETE FROM destinations WHERE id=?", (destination_id,))
            conn.commit()
            return jsonify({"success": True})
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", row["name"])).strip()
        server_url = str(data.get("server_url", row["server_url"])).strip()
        platform = str(data.get("platform", row["platform"]))
        enabled = int(data.get("enabled", bool(row["enabled"])))
        if not name or not server_url.lower().startswith(("rtmp://", "rtmps://")):
            return jsonify({"error": "Invalid destination"}), 400
        stream_key = row["stream_key_encrypted"]
        if data.get("stream_key"):
            stream_key = encrypt_secret(str(data["stream_key"]).strip(), STREAM_KEY_SECRET)
        conn.execute(
            "UPDATE destinations SET name=?,platform=?,server_url=?,stream_key_encrypted=?,enabled=? WHERE id=?",
            (name, platform, server_url, stream_key, enabled, destination_id)
        )
        conn.commit()
    return jsonify({"success": True})


@app.route("/api/stream/start", methods=["POST"])
@login_required
def stream_start():
    data = request.get_json(silent=True) or {}
    playlist_id = data.get("playlist_id")
    destination_id = data.get("destination_id")
    orientation = data.get("orientation", "landscape_1080")
    with db.connection() as conn:
        playlist = conn.execute("SELECT * FROM playlists WHERE id=?", (playlist_id,)).fetchone()
        destination = conn.execute("SELECT * FROM destinations WHERE id=? AND enabled=1",
                                   (destination_id,)).fetchone()
    if not playlist:
        return jsonify({"error": "Missing or invalid playlist"}), 400
    if not destination:
        return jsonify({"error": "Missing or disabled destination"}), 400
    stream_key = decrypt_secret(destination["stream_key_encrypted"], STREAM_KEY_SECRET)
    destination_url = destination["server_url"].rstrip("/") + "/" + stream_key
    try:
        result = engine.start(
            playlist_id, destination_id, destination_url, orientation,
            playlist["name"], destination["name"]
        )
        return jsonify(result)
    except RuntimeError as exc:
        with db.connection() as conn:
            conn.execute("INSERT INTO stream_events(level,message) VALUES ('ERROR',?)", (str(exc),))
            conn.commit()
        return jsonify({"error": str(exc)}), 400


@app.route("/api/stream/stop", methods=["POST"])
@login_required
def stream_stop():
    engine.stop()
    return jsonify({"success": True, **engine.snapshot()})


@app.route("/api/stream/restart", methods=["POST"])
@login_required
def stream_restart():
    engine.stop("Restart requested")
    return stream_start()


@app.route("/api/history")
@login_required
def api_history():
    search = request.args.get("search", "").strip()
    with db.connection() as conn:
        rows = conn.execute(
            """SELECT h.*, p.name AS playlist_name, d.name AS destination_name
               FROM stream_history h
               LEFT JOIN playlists p ON p.id=h.playlist_id
               LEFT JOIN destinations d ON d.id=h.destination_id
               WHERE COALESCE(p.name,'') LIKE ? OR COALESCE(d.name,'') LIKE ? OR COALESCE(h.result,'') LIKE ?
               ORDER BY h.id DESC LIMIT 500""",
            (f"%{search}%", f"%{search}%", f"%{search}%")
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/settings", methods=["GET", "PUT"])
@login_required
def api_settings():
    defaults = {
        "application_name": "TRIMIQ LIVE",
        "default_orientation": "landscape_1080",
        "default_playback_mode": "repeat_playlist",
        "default_playlist": "",
        "default_destination": "",
        "automatic_reconnect": "true",
        "maximum_retries": "5",
        "log_retention": "30",
        "upload_size_limit": str(app.config["MAX_UPLOAD_MB"]),
    }
    with db.connection() as conn:
        stored = {row["key"]: row["value"] for row in conn.execute("SELECT * FROM settings").fetchall()}
    values = {**defaults, **stored}
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        with db.connection() as conn:
            for key in defaults:
                if key in data:
                    conn.execute(
                        "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, str(data[key]))
                    )
            conn.commit()
        values = {**values, **{key: str(value) for key, value in data.items() if key in defaults}}
    return jsonify(values)


@app.route("/api/logs")
@login_required
def api_logs():
    with db.connection() as conn:
        rows = conn.execute("SELECT * FROM stream_events ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(row) for row in rows])


@app.errorhandler(413)
def upload_too_large(error):
    return jsonify({"error": f"Upload exceeds the configured {app.config['MAX_UPLOAD_MB']} MB limit"}), 413


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
