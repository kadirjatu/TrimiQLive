import pytest

import app as app_module
from backend.database import Database
from werkzeug.security import generate_password_hash


@pytest.fixture
def client(tmp_path, monkeypatch):
    database = Database(tmp_path / "test.sqlite3")
    database.init()
    with database.connection() as conn:
        conn.execute(
            "INSERT INTO users(username, password_hash) VALUES (?, ?)",
            ("admin", generate_password_hash("change-this-password")),
        )
        conn.commit()
    monkeypatch.setattr(app_module, "db", database)
    monkeypatch.setattr(app_module.engine, "db", database)
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        yield client
