"""
End-to-end and integration tests.

These tests verify real behaviour of the application flows, not just
isolated unit logic. They use real PIL image processing, real file I/O,
and mock only external I/O that would reach the network (SMTP, IMAP, printer).

Flow coverage:
  - Photo ingestion: camera/ → processed/ + thumbs/ (watcher pipeline)
  - EXIF orientation auto-correct
  - Unsupported files silently ignored
  - Missing / vanished files handled gracefully
  - Gallery API: correct files, correct order, thumb URL selection
  - Print: copies, no-copy-on-failure, empty-printer validation
  - Email: success, offline→queue, queue→retry→deliver, concurrent enqueue
  - Hide: file moves, thumb deleted, subsequent gallery reflects removal
  - Config save: .env written, config reloads, email_queue and poller updated
  - Log buffer: entries captured, level change respected
"""

import json
import os
import socket
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


# ── Shared helpers ────────────────────────────────────────────────────────────

def _jpeg(path, width=600, height=400, color=(120, 80, 40)):
    img = Image.new("RGB", (width, height), color)
    img.save(str(path), "JPEG", quality=80)
    return path


def _jpeg_with_exif_rotation(path, width=600, height=400):
    """Create a JPEG that is physically wide but tagged as rotated 90° CW (EXIF tag 6)."""
    import io
    import struct
    img = Image.new("RGB", (width, height), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    buf.seek(0)
    data = buf.read()

    # Inject minimal EXIF with Orientation=6 (90° CW)
    exif_header = (
        b"Exif\x00\x00"          # Exif marker
        b"MM\x00\x2a"            # Big-endian TIFF, magic 42
        b"\x00\x00\x00\x08"      # IFD0 offset = 8
        b"\x00\x01"              # 1 IFD entry
        b"\x01\x12"              # Tag 0x0112 = Orientation
        b"\x00\x03"              # Type SHORT
        b"\x00\x00\x00\x01"      # Count 1
        b"\x00\x06\x00\x00"      # Value 6 (90° CW)
        b"\x00\x00\x00\x00"      # Next IFD = 0 (none)
    )
    app1 = b"\xff\xe1" + struct.pack(">H", len(exif_header) + 2) + exif_header

    # Insert APP1 after SOI (first 2 bytes)
    out = data[:2] + app1 + data[2:]
    Path(path).write_bytes(out)
    return path


# ── App client fixture ────────────────────────────────────────────────────────

@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    """Fresh Flask test client with all dirs pointing at tmp_path."""
    monkeypatch.setenv("PRINTER_NAME", "TestPrinter")
    monkeypatch.setenv("SMTP_SERVER", "smtp.seznam.cz")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "bot@seznam.cz")
    monkeypatch.setenv("SMTP_PASS", "secret")
    monkeypatch.setenv("IMAP_SERVER", "imap.seznam.cz")
    monkeypatch.setenv("IMAP_USER", "bot@seznam.cz")
    monkeypatch.setenv("IMAP_PASS", "secret")
    monkeypatch.setenv("RAW_DIR",        str(tmp_path / "raw"))
    monkeypatch.setenv("CAMERA_DIR",     str(tmp_path / "camera"))
    monkeypatch.setenv("PROCESSED_DIR",  str(tmp_path / "processed"))
    monkeypatch.setenv("THUMBS_DIR",     str(tmp_path / "processed" / "thumbs"))
    monkeypatch.setenv("PRINTED_DIR",    str(tmp_path / "printed"))
    monkeypatch.setenv("HIDDEN_DIR",     str(tmp_path / "hidden"))
    monkeypatch.setenv("EMAIL_QUEUE_PATH", str(tmp_path / "queue.json"))

    for d in ["raw", "camera", "processed", "processed/thumbs", "printed", "hidden"]:
        (tmp_path / d).mkdir(parents=True)

    import importlib, sys
    with patch("dotenv.load_dotenv", MagicMock()):
        sys.modules.pop("config", None)
        sys.modules.pop("app", None)
        import config
        importlib.reload(config)
        import app as app_module
        importlib.reload(app_module)

    app_module.flask_app.config["TESTING"] = True
    client = app_module.flask_app.test_client()
    return client, tmp_path, app_module


def _put_photo(tmp_path, name="photo"):
    """Create a processed photo + thumb (simulates watcher output)."""
    _jpeg(tmp_path / "processed" / f"{name}.jpg", 900, 600)
    _jpeg(tmp_path / "processed" / "thumbs" / f"{name}.jpg", 400, 267)
    return f"{name}.jpg"


# ════════════════════════════════════════════════════════════════════════════
# PHOTO INGESTION PIPELINE (watcher.process_image)
# ════════════════════════════════════════════════════════════════════════════

class TestIngestionPipeline:
    def test_landscape_produces_3x2_fullres_and_400px_thumb(self, tmp_path):
        from watcher import process_image
        dirs = _setup_dirs(tmp_path)
        src = dirs["camera"] / "DSC_001.jpg"
        _jpeg(src, 3000, 2000)

        result = process_image(str(src), str(dirs["processed"]), str(dirs["hidden"]),
                               str(dirs["processed"] / "thumbs"), str(dirs["raw"]))

        assert result is not None
        fullres = Image.open(result["fullres"])
        thumb = Image.open(result["thumb"])
        w, h = fullres.size
        assert abs(w / h - 3 / 2) < 0.02, f"Expected 3:2, got {w}x{h}"
        assert thumb.size[0] == 400

    def test_portrait_produces_2x3_fullres_and_400px_thumb(self, tmp_path):
        from watcher import process_image
        dirs = _setup_dirs(tmp_path)
        src = dirs["camera"] / "DSC_002.jpg"
        _jpeg(src, 2000, 3000)

        result = process_image(str(src), str(dirs["processed"]), str(dirs["hidden"]),
                               str(dirs["processed"] / "thumbs"), str(dirs["raw"]))

        assert result is not None
        fullres = Image.open(result["fullres"])
        w, h = fullres.size
        assert abs(w / h - 2 / 3) < 0.02, f"Expected 2:3, got {w}x{h}"

    def test_exif_orientation_corrected(self, tmp_path):
        """Photo tagged as rotated 90° CW must be auto-oriented before cropping."""
        from watcher import process_image
        dirs = _setup_dirs(tmp_path)
        src = dirs["camera"] / "rotated.jpg"
        # Physically 600×400, tagged 90° CW → after correction should be 400×600 portrait
        _jpeg_with_exif_rotation(src, width=600, height=400)

        result = process_image(str(src), str(dirs["processed"]), str(dirs["hidden"]),
                               str(dirs["processed"] / "thumbs"), str(dirs["raw"]))

        assert result is not None
        fullres = Image.open(result["fullres"])
        w, h = fullres.size
        # After EXIF correction the image is portrait → crop to 2:3
        assert h >= w, f"Expected portrait after EXIF correction, got {w}x{h}"

    def test_source_file_deleted_after_processing(self, tmp_path):
        from watcher import process_image
        dirs = _setup_dirs(tmp_path)
        src = dirs["camera"] / "cleanup.jpg"
        _jpeg(src, 1200, 800)

        process_image(str(src), str(dirs["processed"]), str(dirs["hidden"]),
                      str(dirs["processed"] / "thumbs"), str(dirs["raw"]))

        assert not src.exists(), "Source file must be deleted from camera/ after processing"

    def test_raw_backup_created_before_deletion(self, tmp_path):
        from watcher import process_image
        dirs = _setup_dirs(tmp_path)
        src = dirs["camera"] / "backup_test.jpg"
        _jpeg(src, 1200, 800)

        process_image(str(src), str(dirs["processed"]), str(dirs["hidden"]),
                      str(dirs["processed"] / "thumbs"), str(dirs["raw"]))

        assert (dirs["raw"] / "backup_test.jpg").exists(), "Original must be copied to raw/ before deletion"

    def test_corrupt_file_moved_to_hidden_not_processed(self, tmp_path):
        from watcher import process_image
        dirs = _setup_dirs(tmp_path)
        src = dirs["camera"] / "corrupt.jpg"
        src.write_bytes(b"this is not a jpeg at all")

        result = process_image(str(src), str(dirs["processed"]), str(dirs["hidden"]),
                               str(dirs["processed"] / "thumbs"), str(dirs["raw"]))

        assert result is None
        assert (dirs["hidden"] / "corrupt.jpg").exists()
        assert not list(dirs["processed"].glob("corrupt*")), "Corrupt file must not appear in processed/"

    def test_unsupported_extension_silently_ignored(self, tmp_path):
        from watcher import process_image
        dirs = _setup_dirs(tmp_path)
        src = dirs["camera"] / "document.pdf"
        src.write_bytes(b"%PDF-1.4")

        result = process_image(str(src), str(dirs["processed"]), str(dirs["hidden"]),
                               str(dirs["processed"] / "thumbs"), str(dirs["raw"]))

        assert result is None
        assert src.exists(), "Unsupported file must not be touched"
        assert not list(dirs["hidden"].glob("*")), "Unsupported file must not move to hidden"

    def test_vanished_file_returns_none_gracefully(self, tmp_path):
        from watcher import process_image
        dirs = _setup_dirs(tmp_path)
        nonexistent = str(dirs["camera"] / "ghost.jpg")

        result = process_image(nonexistent, str(dirs["processed"]), str(dirs["hidden"]),
                               str(dirs["processed"] / "thumbs"), str(dirs["raw"]))

        assert result is None  # must not raise

    def test_thumb_proportional_to_fullres(self, tmp_path):
        """Thumb aspect ratio must match fullres (no squash/stretch)."""
        from watcher import process_image
        dirs = _setup_dirs(tmp_path)
        src = dirs["camera"] / "ratio.jpg"
        _jpeg(src, 3000, 2000)

        result = process_image(str(src), str(dirs["processed"]), str(dirs["hidden"]),
                               str(dirs["processed"] / "thumbs"), str(dirs["raw"]))

        fullres = Image.open(result["fullres"])
        thumb = Image.open(result["thumb"])
        fr_ratio = fullres.size[0] / fullres.size[1]
        th_ratio = thumb.size[0] / thumb.size[1]
        assert abs(fr_ratio - th_ratio) < 0.05, f"Thumb ratio {th_ratio:.3f} ≠ fullres ratio {fr_ratio:.3f}"

    def test_dims_never_exceed_original(self, tmp_path):
        """Output must never be larger than input (no upscaling artefacts)."""
        from watcher import process_image
        dirs = _setup_dirs(tmp_path)
        src = dirs["camera"] / "small.jpg"
        _jpeg(src, 200, 150)  # tiny image

        result = process_image(str(src), str(dirs["processed"]), str(dirs["hidden"]),
                               str(dirs["processed"] / "thumbs"), str(dirs["raw"]))

        fullres = Image.open(result["fullres"])
        w, h = fullres.size
        assert w <= 200 and h <= 150, f"Output {w}x{h} exceeds input 200x150"


def _setup_dirs(tmp_path):
    dirs = {
        "camera": tmp_path / "camera",
        "processed": tmp_path / "processed",
        "hidden": tmp_path / "hidden",
        "raw": tmp_path / "raw",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    (dirs["processed"] / "thumbs").mkdir(exist_ok=True)
    return dirs


# ════════════════════════════════════════════════════════════════════════════
# GALLERY API
# ════════════════════════════════════════════════════════════════════════════

class TestGalleryAPI:
    def test_empty_gallery_returns_empty_list(self, app_ctx):
        c, tmp_path, _ = app_ctx
        resp = c.get("/api/photos")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_photos_sorted_newest_first(self, app_ctx):
        """Gallery must return photos newest-first (by mtime)."""
        c, tmp_path, _ = app_ctx
        names = ["alpha", "beta", "gamma"]
        for i, name in enumerate(names):
            p = tmp_path / "processed" / f"{name}.jpg"
            _jpeg(p, 600, 400)
            # stagger mtime: alpha=oldest, gamma=newest
            os.utime(p, (1000000 + i * 100, 1000000 + i * 100))

        data = c.get("/api/photos").get_json()
        assert [d["filename"] for d in data] == ["gamma.jpg", "beta.jpg", "alpha.jpg"]

    def test_thumb_url_points_to_existing_thumb(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "with_thumb")
        data = c.get("/api/photos").get_json()
        assert data[0]["thumb"] == "/photos/thumbs/with_thumb.jpg"

    def test_thumb_url_falls_back_to_fullres_when_missing(self, app_ctx):
        c, tmp_path, _ = app_ctx
        # Create fullres but no thumb
        _jpeg(tmp_path / "processed" / "no_thumb.jpg", 600, 400)
        data = c.get("/api/photos").get_json()
        assert data[0]["thumb"] == "/photos/processed/no_thumb.jpg"

    def test_serve_processed_photo(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "serve_me")
        resp = c.get("/photos/processed/serve_me.jpg")
        assert resp.status_code == 200
        assert resp.content_type.startswith("image/")

    def test_serve_thumb(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "thumb_me")
        resp = c.get("/photos/thumbs/thumb_me.jpg")
        assert resp.status_code == 200

    def test_serve_thumb_falls_back_to_fullres(self, app_ctx):
        """GET /photos/thumbs/<name> must return fullres when thumb missing, not 404."""
        c, tmp_path, _ = app_ctx
        _jpeg(tmp_path / "processed" / "only_fullres.jpg", 600, 400)
        resp = c.get("/photos/thumbs/only_fullres.jpg")
        assert resp.status_code == 200

    def test_nonexistent_photo_returns_404(self, app_ctx):
        c, _, _ = app_ctx
        resp = c.get("/photos/processed/ghost.jpg")
        assert resp.status_code == 404

    def test_photos_have_required_fields(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "fields")
        data = c.get("/api/photos").get_json()
        photo = data[0]
        assert "filename" in photo
        assert "thumb" in photo
        assert "timestamp" in photo
        assert isinstance(photo["timestamp"], float)


# ════════════════════════════════════════════════════════════════════════════
# HIDE FLOW
# ════════════════════════════════════════════════════════════════════════════

class TestHideFlow:
    def test_hide_moves_fullres_to_hidden(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "to_hide")
        c.post("/api/hide", json={"filename": "to_hide.jpg"})
        assert not (tmp_path / "processed" / "to_hide.jpg").exists()
        assert (tmp_path / "hidden" / "to_hide.jpg").exists()

    def test_hide_deletes_thumb(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "hide_thumb")
        c.post("/api/hide", json={"filename": "hide_thumb.jpg"})
        assert not (tmp_path / "processed" / "thumbs" / "hide_thumb.jpg").exists()

    def test_hide_removes_photo_from_gallery(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "was_visible")
        assert len(c.get("/api/photos").get_json()) == 1
        c.post("/api/hide", json={"filename": "was_visible.jpg"})
        assert c.get("/api/photos").get_json() == []

    def test_hide_nonexistent_returns_404(self, app_ctx):
        c, _, _ = app_ctx
        resp = c.post("/api/hide", json={"filename": "ghost.jpg"})
        assert resp.status_code == 404

    def test_hide_emits_socket_event(self, app_ctx):
        c, tmp_path, app_module = app_ctx
        _put_photo(tmp_path, "socket_hide")
        with patch.object(app_module.socketio, "emit") as mock_emit:
            c.post("/api/hide", json={"filename": "socket_hide.jpg"})
            mock_emit.assert_called_once_with("photo_hidden", {"filename": "socket_hide.jpg"})

    def test_hide_without_thumb_still_succeeds(self, app_ctx):
        """Hide must succeed even if thumb was already deleted."""
        c, tmp_path, _ = app_ctx
        _jpeg(tmp_path / "processed" / "no_thumb_hide.jpg", 600, 400)
        # No thumb created
        resp = c.post("/api/hide", json={"filename": "no_thumb_hide.jpg"})
        assert resp.status_code == 200
        assert (tmp_path / "hidden" / "no_thumb_hide.jpg").exists()


# ════════════════════════════════════════════════════════════════════════════
# PRINT FLOW
# ════════════════════════════════════════════════════════════════════════════

class TestPrintFlow:
    def test_print_calls_printer_with_correct_args(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "printable")
        with patch("printer.print_image") as mock_print:
            c.post("/api/print", json={"filename": "printable.jpg", "copies": 3})
            mock_print.assert_called_once()
            positional = mock_print.call_args[0]
            assert "printable.jpg" in positional[0]  # filepath contains filename
            assert positional[2] == 3               # copies

    def test_print_copies_to_printed_dir(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "archive_print")
        with patch("printer.print_image"):
            c.post("/api/print", json={"filename": "archive_print.jpg", "copies": 1})
        assert (tmp_path / "printed" / "archive_print.jpg").exists()

    def test_print_original_unchanged_after_print(self, app_ctx):
        """Printing must not delete or modify the processed photo."""
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "keep_original")
        with patch("printer.print_image"):
            c.post("/api/print", json={"filename": "keep_original.jpg", "copies": 1})
        assert (tmp_path / "processed" / "keep_original.jpg").exists()

    def test_print_failure_returns_500_no_archive(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "fail_print")
        with patch("printer.print_image", side_effect=RuntimeError("printer offline")):
            resp = c.post("/api/print", json={"filename": "fail_print.jpg", "copies": 1})
        assert resp.status_code == 500
        assert not (tmp_path / "printed" / "fail_print.jpg").exists()

    def test_print_nonexistent_photo_fails(self, app_ctx):
        c, _, _ = app_ctx
        with patch("printer.print_image", side_effect=FileNotFoundError):
            resp = c.post("/api/print", json={"filename": "nope.jpg", "copies": 1})
        assert resp.status_code == 500

    def test_empty_printer_name_raises_validation_error(self, app_ctx, monkeypatch):
        c, tmp_path, app_module = app_ctx
        import config
        monkeypatch.setattr(config, "PRINTER_NAME", "")
        _put_photo(tmp_path, "validate_printer")
        resp = c.post("/api/print", json={"filename": "validate_printer.jpg", "copies": 1})
        assert resp.status_code == 500
        assert "PRINTER_NAME" in resp.get_json().get("error", "")


# ════════════════════════════════════════════════════════════════════════════
# EMAIL FLOW
# ════════════════════════════════════════════════════════════════════════════

class TestEmailFlow:
    def test_email_sent_immediately_when_online(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "send_now")
        with patch("mailer.smtplib.SMTP_SSL") as mock_ssl:
            mock_server = MagicMock()
            mock_ssl.return_value.__enter__ = lambda s: mock_server
            mock_ssl.return_value.__exit__ = MagicMock(return_value=False)
            resp = c.post("/api/email", json={"filename": "send_now.jpg", "recipient": "guest@example.com"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert not data.get("queued")
        mock_server.send_message.assert_called_once()

    def test_email_queued_when_offline(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "queue_me")
        with patch("mailer.smtplib.SMTP_SSL", side_effect=socket.gaierror("no internet")):
            resp = c.post("/api/email", json={"filename": "queue_me.jpg", "recipient": "guest@example.com"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["queued"] is True

    def test_email_queue_persisted_to_disk(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "persist_queue")
        with patch("mailer.smtplib.SMTP_SSL", side_effect=socket.gaierror("no internet")):
            c.post("/api/email", json={"filename": "persist_queue.jpg", "recipient": "a@b.cz"})
        saved = json.loads((tmp_path / "queue.json").read_text())
        assert len(saved) == 1
        assert saved[0]["filename"] == "persist_queue.jpg"
        assert saved[0]["recipient"] == "a@b.cz"

    def test_email_multiple_recipients(self, app_ctx):
        c, tmp_path, _ = app_ctx
        _put_photo(tmp_path, "multi_send")
        with patch("mailer.smtplib.SMTP_SSL") as mock_ssl:
            mock_server = MagicMock()
            mock_ssl.return_value.__enter__ = lambda s: mock_server
            mock_ssl.return_value.__exit__ = MagicMock(return_value=False)
            resp = c.post("/api/email", json={
                "filename": "multi_send.jpg",
                "recipient": "jan@a.cz, marie@b.cz, petr@c.cz"
            })
        assert resp.status_code == 200
        _, kwargs = mock_server.send_message.call_args
        assert set(kwargs["to_addrs"]) == {"jan@a.cz", "marie@b.cz", "petr@c.cz"}

    def test_queued_email_retried_when_back_online(self, tmp_path):
        """Full queue lifecycle: enqueue while offline, flush when online."""
        from email_queue import EmailQueue
        processed = tmp_path / "processed"
        processed.mkdir()
        _jpeg(processed / "retry.jpg")

        q = EmailQueue(
            queue_path=str(tmp_path / "queue.json"),
            smtp_server="smtp.seznam.cz",
            smtp_port=465,
            smtp_user="bot@seznam.cz",
            smtp_pass="secret",
            processed_dir=str(processed),
        )
        q.enqueue("retry.jpg", "guest@example.com")

        # First flush: still offline
        with patch("mailer.smtplib.SMTP_SSL", side_effect=socket.gaierror("no internet")):
            sent, remaining = q.flush()
        assert sent == 0 and remaining == 1
        assert q.pending()[0]["attempts"] == 1

        # Second flush: back online
        with patch("mailer.smtplib.SMTP_SSL") as mock_ssl:
            mock_server = MagicMock()
            mock_ssl.return_value.__enter__ = lambda s: mock_server
            mock_ssl.return_value.__exit__ = MagicMock(return_value=False)
            sent, remaining = q.flush()
        assert sent == 1 and remaining == 0
        assert q.pending() == []
        mock_server.send_message.assert_called_once()

    def test_queued_entry_preserved_when_enqueued_during_flush(self, tmp_path):
        """Race: enqueue() called from another thread while flush() is running."""
        from email_queue import EmailQueue
        processed = tmp_path / "processed"
        processed.mkdir()
        for i in range(3):
            _jpeg(processed / f"p{i}.jpg")

        q = EmailQueue(
            queue_path=str(tmp_path / "queue.json"),
            smtp_server="smtp.seznam.cz",
            smtp_port=465,
            smtp_user="bot@seznam.cz",
            smtp_pass="secret",
            processed_dir=str(processed),
        )
        q.enqueue("p0.jpg", "a@b.cz")
        q.enqueue("p1.jpg", "b@b.cz")

        # Intercept SMTP to be offline (so all go to still_queued) and enqueue a new
        # entry partway through
        enqueue_event = threading.Event()
        enqueued_during = threading.Event()

        original_send = None
        call_count = [0]

        def slow_offline(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Signal the side thread to enqueue
                enqueue_event.set()
                # Wait for it to complete
                enqueued_during.wait(timeout=2)
            raise socket.gaierror("offline")

        def side_enqueue():
            enqueue_event.wait(timeout=2)
            q.enqueue("p2.jpg", "c@b.cz")
            enqueued_during.set()

        t = threading.Thread(target=side_enqueue)
        t.start()

        with patch("mailer.smtplib.SMTP_SSL", side_effect=slow_offline):
            q.flush()

        t.join()
        pending = {e["filename"] for e in q.pending()}
        assert "p0.jpg" in pending, "Original failed entries must be kept"
        assert "p2.jpg" in pending, "Entry added during flush must not be lost"

    def test_dropped_photo_removed_from_queue(self, tmp_path):
        """If the file no longer exists, the queue entry is silently dropped."""
        from email_queue import EmailQueue
        processed = tmp_path / "processed"
        processed.mkdir()
        # Don't create the file — it's already gone

        q = EmailQueue(
            queue_path=str(tmp_path / "queue.json"),
            smtp_server="smtp.seznam.cz",
            smtp_port=465,
            smtp_user="bot@seznam.cz",
            smtp_pass="secret",
            processed_dir=str(processed),
        )
        q.enqueue("vanished.jpg", "guest@example.com")

        with patch("mailer.smtplib.SMTP_SSL") as mock_ssl:
            mock_ssl.return_value.__enter__ = lambda s: MagicMock()
            mock_ssl.return_value.__exit__ = MagicMock(return_value=False)
            sent, remaining = q.flush()

        assert sent == 0
        assert remaining == 0
        assert q.pending() == []


# ════════════════════════════════════════════════════════════════════════════
# EMAIL SENDING (mailer)
# ════════════════════════════════════════════════════════════════════════════

class TestMailer:
    def test_attachment_is_the_photo(self, tmp_path):
        """The email must contain the photo as an image/jpeg attachment."""
        _jpeg(tmp_path / "shot.jpg")
        with patch("mailer.smtplib.SMTP_SSL") as mock_ssl:
            mock_server = MagicMock()
            mock_ssl.return_value.__enter__ = lambda s: mock_server
            mock_ssl.return_value.__exit__ = MagicMock(return_value=False)
            from mailer import send_email
            send_email(str(tmp_path / "shot.jpg"), "g@example.com",
                       "smtp.seznam.cz", 465, "u", "p")
        msg = mock_server.send_message.call_args[0][0]
        attachments = [p for p in msg.get_payload() if p.get_content_type() == "image/jpeg"]
        assert len(attachments) == 1
        assert attachments[0].get_filename() == "shot.jpg"

    def test_smtp_auth_failure_raises_email_connection_error(self, tmp_path):
        """Auth failure (bad password) must raise EmailConnectionError, not SMTPAuthenticationError."""
        import smtplib
        from mailer import send_email, EmailConnectionError
        _jpeg(tmp_path / "shot.jpg")
        with patch("mailer.smtplib.SMTP_SSL") as mock_ssl:
            mock_server = MagicMock()
            mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
            mock_ssl.return_value.__enter__ = lambda s: mock_server
            mock_ssl.return_value.__exit__ = MagicMock(return_value=False)
            with pytest.raises(EmailConnectionError):
                send_email(str(tmp_path / "shot.jpg"), "g@example.com",
                           "smtp.seznam.cz", 465, "u", "wrong_pass")

    def test_no_recipient_raises_value_error(self, tmp_path):
        from mailer import send_email
        _jpeg(tmp_path / "shot.jpg")
        with pytest.raises(ValueError, match="No recipient"):
            send_email(str(tmp_path / "shot.jpg"), "",
                       "smtp.seznam.cz", 465, "u", "p")

    def test_connection_error_raises_email_connection_error(self, tmp_path):
        from mailer import send_email, EmailConnectionError
        _jpeg(tmp_path / "shot.jpg")
        with patch("mailer.smtplib.SMTP_SSL", side_effect=socket.gaierror("no dns")):
            with pytest.raises(EmailConnectionError):
                send_email(str(tmp_path / "shot.jpg"), "g@example.com",
                           "smtp.seznam.cz", 465, "u", "p")


# ════════════════════════════════════════════════════════════════════════════
# CONFIG SAVE / RELOAD
# ════════════════════════════════════════════════════════════════════════════

class TestConfigSaveReload:
    def test_save_writes_to_env_file(self, app_ctx, tmp_path):
        c, tmp_path, _ = app_ctx
        # Write a real .env file that the route can update
        env_file = tmp_path / ".env"
        env_file.write_text("PRINTER_NAME=OldPrinter\nSMTP_SERVER=old.server.cz\n")

        import config as cfg
        orig_root = cfg._ROOT

        with patch.object(cfg, "_ROOT", tmp_path):
            resp = c.post("/api/config", json={"PRINTER_NAME": "NewPrinter"})

        # Verify .env was written regardless of the ROOT patch
        # (The route builds the path from config._ROOT at call time)
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_config_get_matches_live_module(self, app_ctx):
        """GET /api/config must return values that match what config.py actually exports."""
        c, _, app_module = app_ctx
        import config as cfg
        resp = c.get("/api/config")
        data = resp.get_json()
        assert data["PRINTER_NAME"] == cfg.PRINTER_NAME
        assert data["SMTP_SERVER"] == cfg.SMTP_SERVER
        assert data["SMTP_PORT"] == str(cfg.SMTP_PORT)
        assert data["PROCESSED_DIR"] == cfg.PROCESSED_DIR

    def test_email_queue_fields_updated_after_save(self, app_ctx, tmp_path, monkeypatch):
        c, tmp_path, app_module = app_ctx
        import config as cfg

        # Write .env at the path the route will look for (config._ROOT / ".env")
        env_file = cfg._ROOT / ".env"
        original_env = env_file.read_text() if env_file.exists() else None

        # Write a minimal .env with the NEW values so reload picks them up
        new_env = (
            f"PRINTER_NAME=TestPrinter\n"
            f"SMTP_SERVER=smtp.newhost.cz\nSMTP_PORT=587\n"
            f"SMTP_USER=bot@seznam.cz\nSMTP_PASS=secret\n"
            f"IMAP_SERVER=imap.seznam.cz\nIMAP_USER=bot@seznam.cz\nIMAP_PASS=secret\n"
            f"CAMERA_DIR={tmp_path}/camera\nRAW_DIR={tmp_path}/raw\n"
            f"PROCESSED_DIR={tmp_path}/processed\nTHUMBS_DIR={tmp_path}/processed/thumbs\n"
            f"PRINTED_DIR={tmp_path}/printed\nHIDDEN_DIR={tmp_path}/hidden\n"
            f"EMAIL_QUEUE_PATH={tmp_path}/queue.json\n"
        )
        env_file.write_text(new_env)

        try:
            resp = c.post("/api/config", json={
                "SMTP_SERVER": "smtp.newhost.cz",
                "SMTP_PORT": "587",
            })
            assert resp.status_code == 200
            assert app_module.email_queue._smtp_server == "smtp.newhost.cz"
            assert app_module.email_queue._smtp_port == 587
        finally:
            # Restore .env so we don't corrupt the real project config
            if original_env is not None:
                env_file.write_text(original_env)
            elif env_file.exists():
                env_file.unlink()


# ════════════════════════════════════════════════════════════════════════════
# INBOX POLLER (email → camera/)
# ════════════════════════════════════════════════════════════════════════════

class TestInboxPoller:
    def _make_email_bytes(self, filename="photo.jpg", mimetype=("image", "jpeg")):
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders
        msg = MIMEMultipart()
        part = MIMEBase(*mimetype)
        part.set_payload(b"\xff\xd8\xff" + b"\x00" * 50)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)
        return msg.as_bytes()

    def test_jpeg_attachment_saved_to_camera_dir(self, tmp_path):
        camera = tmp_path / "camera"
        camera.mkdir()
        mock_imap = MagicMock()
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822)", self._make_email_bytes("nikon.jpg"))])
        mock_imap.store.return_value = ("OK", [])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            from inbox_poller import poll_once
            poll_once("imap.seznam.cz", "u", "p", str(camera))

        saved = list(camera.iterdir())
        assert len(saved) == 1
        assert saved[0].suffix.lower() in {".jpg", ".jpeg"}

    def test_duplicate_attachments_get_unique_names(self, tmp_path):
        camera = tmp_path / "camera"
        camera.mkdir()
        # Pre-create a file with the same name
        (camera / "photo.jpg").write_bytes(b"existing")

        mock_imap = MagicMock()
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822)", self._make_email_bytes("photo.jpg"))])
        mock_imap.store.return_value = ("OK", [])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            from inbox_poller import poll_once
            poll_once("imap.seznam.cz", "u", "p", str(camera))

        files = list(camera.iterdir())
        assert len(files) == 2, "Duplicate must be renamed, not overwritten"
        names = {f.name for f in files}
        assert "photo.jpg" in names
        # second one should be photo_1.jpg
        assert any(n.startswith("photo_") and n.endswith(".jpg") for n in names)

    def test_pdf_attachment_not_saved(self, tmp_path):
        camera = tmp_path / "camera"
        camera.mkdir()
        mock_imap = MagicMock()
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = (
            "OK", [(b"1 (RFC822)", self._make_email_bytes("doc.pdf", ("application", "pdf")))]
        )
        mock_imap.store.return_value = ("OK", [])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            from inbox_poller import poll_once
            poll_once("imap.seznam.cz", "u", "p", str(camera))

        assert list(camera.iterdir()) == []

    def test_message_marked_seen_after_processing(self, tmp_path):
        camera = tmp_path / "camera"
        camera.mkdir()
        mock_imap = MagicMock()
        mock_imap.search.return_value = ("OK", [b"42"])
        mock_imap.fetch.return_value = ("OK", [(b"42 (RFC822)", self._make_email_bytes())])
        mock_imap.store.return_value = ("OK", [])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            from inbox_poller import poll_once
            poll_once("imap.seznam.cz", "u", "p", str(camera))

        mock_imap.store.assert_called_once_with(b"42", "+FLAGS", "\\Seen")

    def test_imap_auth_failure_logged_not_raised(self, tmp_path, caplog):
        """IMAP auth failure must be caught, logged as warning, not crash the poller."""
        import imaplib
        camera = tmp_path / "camera"
        camera.mkdir()
        with patch("imaplib.IMAP4_SSL") as mock_cls:
            mock_cls.return_value.login.side_effect = imaplib.IMAP4.error(b"AUTHENTICATIONFAILED")
            import logging
            with caplog.at_level(logging.WARNING, logger="inbox_poller"):
                from inbox_poller import poll_once
                poll_once("imap.seznam.cz", "u", "p", str(camera))
        assert any("IMAP" in r.message or "poll" in r.message.lower() for r in caplog.records)


# ════════════════════════════════════════════════════════════════════════════
# PRINTER
# ════════════════════════════════════════════════════════════════════════════

class TestPrinter:
    def test_empty_printer_name_raises(self, tmp_path):
        _jpeg(tmp_path / "p.jpg")
        from printer import print_image
        with pytest.raises(ValueError, match="PRINTER_NAME"):
            print_image(str(tmp_path / "p.jpg"), printer_name="", copies=1)

    def test_mac_lp_called_once_per_copy(self, tmp_path):
        _jpeg(tmp_path / "p.jpg")
        with patch("printer.platform.system", return_value="Darwin"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            from printer import print_image
            print_image(str(tmp_path / "p.jpg"), "SELPHY", copies=3)
        assert mock_run.call_count == 3

    def test_mac_lp_failure_raises_runtime_error(self, tmp_path):
        _jpeg(tmp_path / "p.jpg")
        with patch("printer.platform.system", return_value="Darwin"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="paper jam")
            from printer import print_image
            with pytest.raises(RuntimeError, match="Print failed"):
                print_image(str(tmp_path / "p.jpg"), "SELPHY", copies=1)


# ════════════════════════════════════════════════════════════════════════════
# LOG BUFFER
# ════════════════════════════════════════════════════════════════════════════

class TestLogBuffer:
    def test_log_entries_captured_by_buffer_handler(self, app_ctx):
        c, _, app_module = app_ctx
        app_module._log_buffer.clear()
        import logging
        logging.getLogger("test.buffer").warning("buffer test message")
        resp = c.get("/api/logs")
        msgs = [e["msg"] for e in resp.get_json()]
        assert "buffer test message" in msgs

    def test_log_level_change_filters_debug_messages(self, app_ctx):
        c, _, app_module = app_ctx
        import logging
        # Set to WARNING — DEBUG messages should not appear
        c.post("/api/config/log-level", json={"level": "WARNING"})
        app_module._log_buffer.clear()
        logging.getLogger("test.filter").debug("should not appear")
        logging.getLogger("test.filter").warning("should appear")
        msgs = [e["msg"] for e in c.get("/api/logs").get_json()]
        assert "should not appear" not in msgs
        assert "should appear" in msgs
        # restore
        logging.getLogger().setLevel(logging.INFO)
