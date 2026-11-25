import io
import os

os.environ.setdefault("DATABASE_PATH", "/tmp/trimiq-live-test.sqlite3")
os.environ.setdefault("UPLOAD_FOLDER", "/tmp/trimiq-live-test-uploads")
os.environ.setdefault("LOG_FOLDER", "/tmp/trimiq-live-test-logs")
os.environ.setdefault("PLAYLIST_FOLDER", "/tmp/trimiq-live-test-playlists")
os.environ.setdefault("KEY_ENCRYPTION_KEY", "test-only-secret")
os.environ.setdefault("STREAMING_MODE", "DEMO")

import app as app_module


def login(client):
    return client.post("/login", data={"username": "admin", "password": "change-this-password"})


def test_login_and_csrf_required(client):
    response = login(client)
    assert response.status_code == 302
    protected = client.post("/api/destinations", json={"name": "Test"})
    assert protected.status_code == 403


def test_system_status(client):
    login(client)
    response = client.get("/api/system")
    assert response.status_code == 200
    data = response.get_json()
    assert data["stream"]["mode"] == "DEMO"
    assert data["stream"]["application_running"] is True


def test_destination_key_not_exposed(client):
    login(client)
    with client.session_transaction() as session:
        token = session["csrf_token"]
    response = client.post(
        "/api/destinations",
        json={"name": "YouTube", "platform": "YouTube Live",
              "server_url": "rtmp://example.com/live", "stream_key": "never-expose"},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 201
    body = response.get_json()
    assert "never-expose" not in str(body)
    listed = client.get("/api/destinations").get_json()
    assert "never-expose" not in str(listed)


def test_demo_stream_does_not_claim_real_broadcast(client):
    login(client)
    with client.session_transaction() as session:
        token = session["csrf_token"]
    headers = {"X-CSRF-Token": token}
    client.post("/api/playlists", json={"name": "Test Playlist"}, headers=headers)
    client.post("/api/destinations",
                json={"name": "Custom", "platform": "Custom RTMP",
                      "server_url": "rtmp://example.com/live", "stream_key": "test"},
                headers=headers)
    playlist_id = client.get("/api/playlists").get_json()[0]["id"]
    destination_id = client.get("/api/destinations").get_json()[0]["id"]
    result = client.post("/api/stream/start",
                         json={"playlist_id": playlist_id, "destination_id": destination_id,
                               "orientation": "landscape_1080"},
                         headers=headers)
    assert result.status_code == 400
    status = client.get("/api/dashboard").get_json()
    assert status["platform_broadcast_live"] is False
