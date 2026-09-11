import pytest, json, shutil, os, logging
from pathlib import Path
from PIL import Image
from unittest.mock import patch, MagicMock

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTER_NAME", "TestPrinter")
    monkeypatch.setenv("SMTP_SERVER", "smtp.seznam.cz")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "a@b.cz")
    monkeypatch.setenv("SMTP_PASS", "secret")
    monkeypatch.setenv("IMAP_SERVER", "imap.seznam.cz")
    monkeypatch.setenv("IMAP_USER", "a@b.cz")
    monkeypatch.setenv("IMAP_PASS", "secret")
    monkeypatch.setenv("RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("CAMERA_DIR", str(tmp_path / "camera"))
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path / "processed"))
    monkeypatch.setenv("THUMBS_DIR", str(tmp_path / "processed" / "thumbs"))
    monkeypatch.setenv("PRINTED_DIR", str(tmp_path / "printed"))
    monkeypatch.setenv("HIDDEN_DIR", str(tmp_path / "hidden"))
    monkeypatch.setenv("EMAIL_QUEUE_PATH", str(tmp_path / "queue.json"))
    for d in ["raw", "camera", "processed", "processed/thumbs", "printed", "hidden"]:
        (tmp_path / d).mkdir(parents=True)

    import importlib, sys
    from unittest.mock import MagicMock
    with patch("dotenv.load_dotenv", MagicMock()):
        sys.modules.pop("config", None)
        sys.modules.pop("app", None)
        import config
        importlib.reload(config)
        import app as app_module
        importlib.reload(app_module)
    app_module.flask_app.config["TESTING"] = True
    return app_module.flask_app.test_client(), tmp_path

def _make_processed_photo(tmp_path, name="photo1"):
    img = Image.new("RGB", (900, 600))
    img.save(str(tmp_path / "processed" / f"{name}.jpg"), "JPEG")
    img.save(str(tmp_path / "processed" / "thumbs" / f"{name}.jpg"), "JPEG")

def test_get_photos_returns_list(client):
    c, tmp_path = client
    _make_processed_photo(tmp_path, "photo1")
    resp = c.get("/api/photos")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert len(data) == 1
    assert data[0]["filename"] == "photo1.jpg"

def test_hide_moves_file(client):
    c, tmp_path = client
    _make_processed_photo(tmp_path, "photo2")
    resp = c.post("/api/hide", json={"filename": "photo2.jpg"})
    assert resp.status_code == 200
    assert not (tmp_path / "processed" / "photo2.jpg").exists()
    assert (tmp_path / "hidden" / "photo2.jpg").exists()
    assert (tmp_path / "hidden" / "photo2.jpg").is_file()  # must be a file, not dir
    assert not (tmp_path / "processed" / "thumbs" / "photo2.jpg").exists()

def test_print_copies_to_printed_on_success(client):
    c, tmp_path = client
    _make_processed_photo(tmp_path, "photo3")
    with patch("printer.print_image") as mock_print:
        resp = c.post("/api/print", json={"filename": "photo3.jpg", "copies": 2})
        assert resp.status_code == 200
        mock_print.assert_called_once()
        assert (tmp_path / "printed" / "photo3.jpg").exists()

def test_print_does_not_copy_on_failure(client):
    c, tmp_path = client
    _make_processed_photo(tmp_path, "photo4")
    with patch("printer.print_image", side_effect=RuntimeError("offline")):
        resp = c.post("/api/print", json={"filename": "photo4.jpg", "copies": 1})
        assert resp.status_code == 500
        assert not (tmp_path / "printed" / "photo4.jpg").exists()

def test_hide_emits_socket_event(client):
    c, tmp_path = client
    _make_processed_photo(tmp_path, "photo_emit")
    import app as app_module
    with patch.object(app_module.socketio, "emit") as mock_emit:
        resp = c.post("/api/hide", json={"filename": "photo_emit.jpg"})
        assert resp.status_code == 200
        mock_emit.assert_called_once_with("photo_hidden", {"filename": "photo_emit.jpg"})

def test_api_logs_returns_buffer(client):
    c, _ = client
    import app as app_module
    app_module._log_buffer.clear()
    app_module._log_buffer.append({"t": "12:00:00", "level": "INFO", "name": "test", "msg": "hello"})
    resp = c.get("/api/logs")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert data[0]["msg"] == "hello"

def test_api_logs_capped_at_500(client):
    c, _ = client
    import app as app_module
    for i in range(502):
        app_module._log_buffer.append({"t": "12:00:00", "level": "INFO", "name": "x", "msg": f"m{i}"})
    resp = c.get("/api/logs")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 500

def test_api_log_level_valid(client):
    c, _ = client
    resp = c.post("/api/config/log-level", json={"level": "DEBUG"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert logging.getLogger().level == logging.DEBUG
    # restore
    logging.getLogger().setLevel(logging.INFO)

def test_api_log_level_invalid(client):
    c, _ = client
    resp = c.post("/api/config/log-level", json={"level": "NOPE"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False

def test_api_config_get_returns_live_values(client):
    c, _ = client
    import config
    resp = c.get("/api/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["PRINTER_NAME"] == config.PRINTER_NAME
    assert data["SMTP_SERVER"] == config.SMTP_SERVER
    assert "IMAP_PASS" in data

def test_api_email_queue_returns_pending(client):
    c, _ = client
    import app as app_module
    app_module.email_queue._entries.clear()
    app_module.email_queue.enqueue("img.jpg", "a@b.cz")
    resp = c.get("/api/email/queue")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["filename"] == "img.jpg"
