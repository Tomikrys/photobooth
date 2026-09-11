import json
import socket
from pathlib import Path
from unittest.mock import patch, MagicMock

from PIL import Image


def _make_jpeg(path):
    Image.new("RGB", (600, 400)).save(str(path), "JPEG")


def _new_queue(tmp_path, queue_name="queue.json"):
    from email_queue import EmailQueue
    processed = tmp_path / "processed"
    processed.mkdir()
    return EmailQueue(
        queue_path=str(tmp_path / queue_name),
        smtp_server="smtp.seznam.cz",
        smtp_port=465,
        smtp_user="bot@seznam.cz",
        smtp_pass="secret",
        processed_dir=str(processed),
    ), processed


def test_enqueue_persists_to_disk(tmp_path):
    q, _ = _new_queue(tmp_path)
    q.enqueue("photo1.jpg", "guest@example.com")
    saved = json.loads((tmp_path / "queue.json").read_text())
    assert len(saved) == 1
    assert saved[0]["filename"] == "photo1.jpg"
    assert saved[0]["recipient"] == "guest@example.com"


def test_queue_reloads_from_disk_on_restart(tmp_path):
    q1, processed = _new_queue(tmp_path)
    q1.enqueue("a.jpg", "one@example.com")
    q1.enqueue("b.jpg", "two@example.com")
    # simulate restart
    from email_queue import EmailQueue
    q2 = EmailQueue(
        queue_path=str(tmp_path / "queue.json"),
        smtp_server="smtp.seznam.cz", smtp_port=465,
        smtp_user="bot@seznam.cz", smtp_pass="secret",
        processed_dir=str(processed),
    )
    pending = q2.pending()
    assert [e["filename"] for e in pending] == ["a.jpg", "b.jpg"]


def test_flush_sends_and_clears_queue(tmp_path):
    q, processed = _new_queue(tmp_path)
    _make_jpeg(processed / "photo.jpg")
    q.enqueue("photo.jpg", "guest@example.com")

    with patch("mailer.smtplib.SMTP_SSL") as mock_ssl:
        mock_server = MagicMock()
        mock_ssl.return_value.__enter__ = lambda s: mock_server
        mock_ssl.return_value.__exit__ = MagicMock(return_value=False)
        sent, remaining = q.flush()
    assert sent == 1
    assert remaining == 0
    assert q.pending() == []
    # persisted empty
    assert json.loads((tmp_path / "queue.json").read_text()) == []


def test_flush_keeps_entries_when_still_offline(tmp_path):
    q, processed = _new_queue(tmp_path)
    _make_jpeg(processed / "photo.jpg")
    q.enqueue("photo.jpg", "guest@example.com")

    with patch("mailer.smtplib.SMTP_SSL", side_effect=socket.gaierror("no dns")):
        sent, remaining = q.flush()
    assert sent == 0
    assert remaining == 1
    # attempts counter bumped
    assert q.pending()[0]["attempts"] == 1


def test_api_email_queues_on_connection_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTER_NAME", "TestPrinter")
    monkeypatch.setenv("SMTP_SERVER", "smtp.seznam.cz")
    monkeypatch.setenv("SMTP_USER", "bot@seznam.cz")
    monkeypatch.setenv("SMTP_PASS", "secret")
    monkeypatch.setenv("IMAP_SERVER", "imap.seznam.cz")
    monkeypatch.setenv("IMAP_USER", "bot@seznam.cz")
    monkeypatch.setenv("IMAP_PASS", "secret")
    monkeypatch.setenv("CAMERA_DIR", str(tmp_path / "camera"))
    monkeypatch.setenv("RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path / "processed"))
    monkeypatch.setenv("THUMBS_DIR", str(tmp_path / "processed" / "thumbs"))
    monkeypatch.setenv("PRINTED_DIR", str(tmp_path / "printed"))
    monkeypatch.setenv("HIDDEN_DIR", str(tmp_path / "hidden"))
    monkeypatch.setenv("EMAIL_QUEUE_PATH", str(tmp_path / "queue.json"))
    for d in ["camera", "raw", "processed", "processed/thumbs", "printed", "hidden"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    _make_jpeg(tmp_path / "processed" / "photo.jpg")

    # force fresh import so config picks up the env vars
    import importlib, sys
    from unittest.mock import patch, MagicMock
    for mod in ["config", "email_queue", "app"]:
        sys.modules.pop(mod, None)
    with patch("dotenv.load_dotenv", MagicMock()):
        app = importlib.import_module("app")

    with patch("mailer.smtplib.SMTP_SSL", side_effect=socket.gaierror("no internet")):
        client = app.flask_app.test_client()
        resp = client.post("/api/email", json={"filename": "photo.jpg", "recipient": "guest@example.com"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["queued"] is True

    # queue file persisted
    saved = json.loads(Path(tmp_path / "queue.json").read_text())
    assert saved[0]["filename"] == "photo.jpg"
    assert saved[0]["recipient"] == "guest@example.com"
