import pytest, json, shutil, os
from pathlib import Path
from PIL import Image
from unittest.mock import patch

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
    for d in ["raw", "camera", "processed", "processed/thumbs", "printed", "hidden"]:
        (tmp_path / d).mkdir(parents=True)

    import importlib, config
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
    # Thumb is deleted, not moved to hidden
    assert not (tmp_path / "processed" / "thumbs" / "photo2.jpg").exists()
    assert not (tmp_path / "hidden" / "photo2.jpg").is_dir()
    assert not any((tmp_path / "hidden").glob("*_thumb.jpg"))

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
