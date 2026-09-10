# Photo Booth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local web-based photo booth app that watches a folder for new photos, displays them in a Czech-language Elegant Dark UI, and lets guests print (Canon Selphy CP1500) or email photos; inbound emails to a Seznam.cz inbox also feed the gallery automatically.

**Architecture:** Python/Flask backend with Socket.IO for real-time photo delivery. A `watchdog` folder monitor processes new files (format conversion, crop, thumbnail). A background IMAP poller feeds guest phone photos into the same pipeline. Cross-platform printing via `pywin32` on Windows and `lp` subprocess on Mac.

**Tech Stack:** Python 3.10+, Flask, Flask-SocketIO, eventlet, watchdog, Pillow, pillow-heif, pywin32 (Windows only), python-dotenv, smtplib, imaplib, Vanilla JS + TailwindCSS CDN + Socket.IO client

---

## File Map

```
photobooth/
├── app.py                  # Flask server, Socket.IO, API endpoints
├── watcher.py              # watchdog monitor, image processing pipeline
├── printer.py              # cross-platform print (Win: pywin32, Mac: lp)
├── mailer.py               # outbound SMTP email to guest
├── inbox_poller.py         # IMAP poller, saves attachments to raw/
├── config.py               # loads .env, exposes typed config constants
├── requirements.txt
├── .env                    # secrets (not committed)
├── .env.example            # committed template
├── run.bat                 # Windows startup script
├── run.sh                  # Mac startup script
├── static/
│   ├── index.html          # single-page UI (gallery + lightbox)
│   └── app.js              # all frontend JS
└── photos/
    ├── raw/
    ├── processed/
    ├── printed/
    └── hidden/
```

Tests live in `tests/` and use `pytest`.

---

## Task 1: Project scaffold & config

**Files:**
- Create: `config.py`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `tests/test_config.py`

- [ ] **Step 1: Create `requirements.txt`**

```
Flask
Flask-SocketIO
eventlet
watchdog
Pillow
pillow-heif
pywin32; sys_platform == "win32"
python-dotenv
pytest
```

- [ ] **Step 2: Create `.env.example`**

```
PRINTER_NAME=Canon SELPHY CP1500
SMTP_SERVER=smtp.seznam.cz
SMTP_PORT=465
SMTP_USER=eliskatom2026@seznam.cz
SMTP_PASS=changeme
IMAP_SERVER=imap.seznam.cz
IMAP_USER=eliskatom2026@seznam.cz
IMAP_PASS=changeme
IMAP_POLL_INTERVAL=30
RAW_DIR=./photos/raw
PROCESSED_DIR=./photos/processed
PRINTED_DIR=./photos/printed
HIDDEN_DIR=./photos/hidden
```

- [ ] **Step 3: Write the failing test**

```python
# tests/test_config.py
import os, pytest
from unittest.mock import patch

def test_config_loads_all_keys():
    env = {
        "PRINTER_NAME": "Canon SELPHY CP1500",
        "SMTP_SERVER": "smtp.seznam.cz",
        "SMTP_PORT": "465",
        "SMTP_USER": "a@b.cz",
        "SMTP_PASS": "secret",
        "IMAP_SERVER": "imap.seznam.cz",
        "IMAP_USER": "a@b.cz",
        "IMAP_PASS": "secret",
        "IMAP_POLL_INTERVAL": "30",
        "RAW_DIR": "./photos/raw",
        "PROCESSED_DIR": "./photos/processed",
        "PRINTED_DIR": "./photos/printed",
        "HIDDEN_DIR": "./photos/hidden",
    }
    with patch.dict(os.environ, env):
        import importlib, config
        importlib.reload(config)
        assert config.PRINTER_NAME == "Canon SELPHY CP1500"
        assert config.SMTP_PORT == 465
        assert config.IMAP_POLL_INTERVAL == 30
        assert config.RAW_DIR == "./photos/raw"
```

- [ ] **Step 4: Run test to verify it fails**

```bash
pip install -r requirements.txt
pytest tests/test_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 5: Create `config.py`**

```python
import os
from dotenv import load_dotenv

load_dotenv()

PRINTER_NAME = os.environ["PRINTER_NAME"]
SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
IMAP_SERVER = os.environ["IMAP_SERVER"]
IMAP_USER = os.environ["IMAP_USER"]
IMAP_PASS = os.environ["IMAP_PASS"]
IMAP_POLL_INTERVAL = int(os.environ.get("IMAP_POLL_INTERVAL", "30"))
RAW_DIR = os.environ.get("RAW_DIR", "./photos/raw")
PROCESSED_DIR = os.environ.get("PROCESSED_DIR", "./photos/processed")
PRINTED_DIR = os.environ.get("PRINTED_DIR", "./photos/printed")
HIDDEN_DIR = os.environ.get("HIDDEN_DIR", "./photos/hidden")
```

- [ ] **Step 6: Create `.gitignore`**

```
.env
venv/
__pycache__/
photos/
*.pyc
.superpowers/
```

- [ ] **Step 7: Copy `.env.example` to `.env` and fill in real credentials**

```bash
cp .env.example .env
# edit .env — set SMTP_PASS and IMAP_PASS to your Seznam.cz app password
```

- [ ] **Step 7: Run test to verify it passes**

```bash
pytest tests/test_config.py -v
```
Expected: `PASSED`

- [ ] **Step 9: Commit**

```bash
git init
git add requirements.txt .env.example .gitignore config.py tests/test_config.py
git commit -m "feat: project scaffold and config module"
```

---

## Task 2: Image processing pipeline (watcher core)

**Files:**
- Create: `watcher.py`
- Create: `tests/test_watcher.py`

The watcher processes any image file dropped into `raw/`: converts to JPEG if needed, auto-orients from EXIF, centre-crops to 3:2 (landscape) or 2:3 (portrait), saves full-res and a 400px-wide thumbnail to `processed/`. Corrupt files are moved to `hidden/`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_watcher.py
import os, shutil, tempfile, pytest
from pathlib import Path
from PIL import Image

@pytest.fixture
def dirs(tmp_path):
    raw = tmp_path / "raw";       raw.mkdir()
    processed = tmp_path / "processed"; processed.mkdir()
    hidden = tmp_path / "hidden"; hidden.mkdir()
    return {"raw": str(raw), "processed": str(processed), "hidden": str(hidden)}

def make_jpeg(path, width, height):
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    img.save(path, "JPEG")

def test_process_landscape_jpeg_produces_3x2_crop(dirs):
    src = Path(dirs["raw"]) / "photo.jpg"
    make_jpeg(str(src), 3000, 2000)
    from watcher import process_image
    result = process_image(str(src), dirs["processed"], dirs["hidden"])
    assert result is not None
    img = Image.open(result["fullres"])
    w, h = img.size
    assert abs(w / h - 3 / 2) < 0.01

def test_process_portrait_jpeg_produces_2x3_crop(dirs):
    src = Path(dirs["raw"]) / "portrait.jpg"
    make_jpeg(str(src), 2000, 3000)
    from watcher import process_image
    result = process_image(str(src), dirs["processed"], dirs["hidden"])
    img = Image.open(result["fullres"])
    w, h = img.size
    assert abs(w / h - 2 / 3) < 0.01

def test_thumbnail_width_is_400px(dirs):
    src = Path(dirs["raw"]) / "wide.jpg"
    make_jpeg(str(src), 3000, 2000)
    from watcher import process_image
    result = process_image(str(src), dirs["processed"], dirs["hidden"])
    thumb = Image.open(result["thumb"])
    assert thumb.size[0] == 400

def test_corrupt_file_moved_to_hidden(dirs):
    src = Path(dirs["raw"]) / "bad.jpg"
    src.write_bytes(b"not an image")
    from watcher import process_image
    result = process_image(str(src), dirs["processed"], dirs["hidden"])
    assert result is None
    assert (Path(dirs["hidden"]) / "bad.jpg").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_watcher.py -v
```
Expected: `ModuleNotFoundError: No module named 'watcher'`

- [ ] **Step 3: Create `watcher.py` — `process_image` function**

```python
import os, shutil, logging
from pathlib import Path
from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".tif", ".webp"}


def _centre_crop(img: Image.Image) -> Image.Image:
    w, h = img.size
    if w >= h:  # landscape → 3:2
        target_w, target_h = w, int(w * 2 / 3)
        if target_h > h:
            target_h = h
            target_w = int(h * 3 / 2)
    else:        # portrait → 2:3
        target_h, target_w = h, int(h * 2 / 3)
        if target_w > w:
            target_w = w
            target_h = int(w * 3 / 2)
    left = (w - target_w) // 2
    top = (h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def process_image(src_path: str, processed_dir: str, hidden_dir: str) -> dict | None:
    src = Path(src_path)
    if src.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None
    try:
        img = Image.open(src_path)
        img = ImageOps.exif_transpose(img)   # auto-orient from EXIF
        img = img.convert("RGB")
        img = _centre_crop(img)

        stem = src.stem
        fullres_path = Path(processed_dir) / f"{stem}.jpg"
        thumb_path   = Path(processed_dir) / f"{stem}_thumb.jpg"

        img.save(str(fullres_path), "JPEG", quality=92)
        thumb = img.copy()
        thumb.thumbnail((400, 400))
        thumb.save(str(thumb_path), "JPEG", quality=80)

        return {"fullres": str(fullres_path), "thumb": str(thumb_path), "stem": stem}
    except Exception as exc:
        log.warning("Failed to process %s: %s — moving to hidden", src_path, exc)
        dest = Path(hidden_dir) / src.name
        shutil.move(src_path, str(dest))
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_watcher.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Add `PhotoWatcher` class (watchdog integration) to `watcher.py`**

Append to `watcher.py`:

```python
import time, threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import config


class _Handler(FileSystemEventHandler):
    def __init__(self, on_new_photo):
        self._on_new_photo = on_new_photo
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()

    def on_modified(self, event):
        if event.is_directory:
            return
        with self._lock:
            self._pending[event.src_path] = time.time() + 1.0  # 1s debounce

    on_created = on_modified

    def flush(self):
        now = time.time()
        with self._lock:
            ready = [p for p, t in self._pending.items() if now >= t]
            for p in ready:
                del self._pending[p]
        for path in ready:
            result = process_image(path, config.PROCESSED_DIR, config.HIDDEN_DIR)
            if result:
                self._on_new_photo(result)


class PhotoWatcher:
    def __init__(self, on_new_photo):
        self._handler = _Handler(on_new_photo)
        self._observer = Observer()
        self._observer.schedule(self._handler, config.RAW_DIR, recursive=False)
        self._running = False

    def start(self):
        os.makedirs(config.RAW_DIR, exist_ok=True)
        os.makedirs(config.PROCESSED_DIR, exist_ok=True)
        os.makedirs(config.PRINTED_DIR, exist_ok=True)
        os.makedirs(config.HIDDEN_DIR, exist_ok=True)
        self._observer.start()
        self._running = True
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def _poll_loop(self):
        while self._running:
            self._handler.flush()
            time.sleep(0.25)

    def stop(self):
        self._running = False
        self._observer.stop()
        self._observer.join()
```

- [ ] **Step 6: Commit**

```bash
git add watcher.py tests/test_watcher.py
git commit -m "feat: image processing pipeline and folder watcher"
```

---

## Task 3: Printer module

**Files:**
- Create: `printer.py`
- Create: `tests/test_printer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_printer.py
import sys, pytest
from unittest.mock import patch, MagicMock

def test_print_calls_lp_on_mac(tmp_path):
    jpeg = tmp_path / "photo.jpg"
    from PIL import Image
    Image.new("RGB", (900, 600), (200, 100, 50)).save(str(jpeg), "JPEG")

    with patch("platform.system", return_value="Darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        from printer import print_image
        print_image(str(jpeg), printer_name="TestPrinter", copies=2)
        assert mock_run.call_count == 2
        args = mock_run.call_args_list[0][0][0]
        assert "lp" in args
        assert "-d" in args
        assert "TestPrinter" in args

def test_print_raises_on_lp_failure(tmp_path):
    jpeg = tmp_path / "photo.jpg"
    from PIL import Image
    Image.new("RGB", (900, 600)).save(str(jpeg), "JPEG")

    with patch("platform.system", return_value="Darwin"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        from printer import print_image
        with pytest.raises(RuntimeError, match="Print failed"):
            print_image(str(jpeg), printer_name="TestPrinter", copies=1)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_printer.py -v
```
Expected: `ModuleNotFoundError: No module named 'printer'`

- [ ] **Step 3: Create `printer.py`**

```python
import platform, subprocess, tempfile, os
from pathlib import Path
from PIL import Image


def print_image(filepath: str, printer_name: str, copies: int = 1) -> None:
    if platform.system() == "Windows":
        _print_windows(filepath, printer_name, copies)
    else:
        _print_mac(filepath, printer_name, copies)


def _print_mac(filepath: str, printer_name: str, copies: int) -> None:
    for _ in range(copies):
        result = subprocess.run(
            ["lp", "-d", printer_name, filepath],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Print failed: {result.stderr}")


def _print_windows(filepath: str, printer_name: str, copies: int) -> None:
    import win32print, win32ui
    from PIL import ImageWin

    printer_handle = win32print.OpenPrinter(printer_name)
    try:
        printer_info = win32print.GetPrinter(printer_handle, 2)
        pdevmode = printer_info["pDevMode"]
        dc = win32ui.CreateDC()
        dc.CreatePrinterDC(printer_name)

        img = Image.open(filepath).convert("RGB")
        printable_w = dc.GetDeviceCaps(8)   # HORZRES
        printable_h = dc.GetDeviceCaps(10)  # VERTRES

        img_w, img_h = img.size
        scale = min(printable_w / img_w, printable_h / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        x_offset = (printable_w - new_w) // 2
        y_offset = (printable_h - new_h) // 2

        for _ in range(copies):
            dc.StartDoc(Path(filepath).name)
            dc.StartPage()
            dib = ImageWin.Dib(img)
            dib.draw(dc.GetHandleOutput(), (x_offset, y_offset, x_offset + new_w, y_offset + new_h))
            dc.EndPage()
            dc.EndDoc()
    finally:
        win32print.ClosePrinter(printer_handle)
        dc.DeleteDC()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_printer.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add printer.py tests/test_printer.py
git commit -m "feat: cross-platform printer module (Mac lp + Windows pywin32)"
```

---

## Task 4: Mailer module

**Files:**
- Create: `mailer.py`
- Create: `tests/test_mailer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mailer.py
import pytest
from unittest.mock import patch, MagicMock

def test_send_email_calls_smtp(tmp_path):
    jpeg = tmp_path / "photo.jpg"
    from PIL import Image
    Image.new("RGB", (600, 400)).save(str(jpeg), "JPEG")

    with patch("smtplib.SMTP_SSL") as mock_ssl:
        mock_server = MagicMock()
        mock_ssl.return_value.__enter__ = lambda s: mock_server
        mock_ssl.return_value.__exit__ = MagicMock(return_value=False)

        from mailer import send_email
        send_email(
            filepath=str(jpeg),
            recipient="guest@example.com",
            smtp_server="smtp.seznam.cz",
            smtp_port=465,
            smtp_user="bot@seznam.cz",
            smtp_pass="secret",
        )
        mock_server.login.assert_called_once_with("bot@seznam.cz", "secret")
        mock_server.send_message.assert_called_once()
        msg = mock_server.send_message.call_args[0][0]
        assert msg["To"] == "guest@example.com"
        assert any(p.get_content_type() == "image/jpeg" for p in msg.get_payload())
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_mailer.py -v
```
Expected: `ModuleNotFoundError: No module named 'mailer'`

- [ ] **Step 3: Create `mailer.py`**

```python
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path


def send_email(
    filepath: str,
    recipient: str,
    smtp_server: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
) -> None:
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg["Subject"] = "Vaše fotografie — Eliška & Tom 2026"

    body = MIMEText("Dobrý den,\n\nv příloze najdete Vaši fotografii ze svatby Elišky a Toma.\n\nDěkujeme za účast!", "plain", "utf-8")
    msg.attach(body)

    with open(filepath, "rb") as f:
        part = MIMEBase("image", "jpeg")
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=Path(filepath).name)
        msg.attach(part)

    with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_mailer.py -v
```
Expected: PASSED

- [ ] **Step 5: Commit**

```bash
git add mailer.py tests/test_mailer.py
git commit -m "feat: outbound email module"
```

---

## Task 5: Inbox poller module

**Files:**
- Create: `inbox_poller.py`
- Create: `tests/test_inbox_poller.py`

Polls IMAP inbox every N seconds, downloads image attachments to `raw/`, marks emails as SEEN.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_inbox_poller.py
import pytest
from unittest.mock import patch, MagicMock, call
import email
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

def _make_email_with_jpeg(filename="photo.jpg"):
    msg = MIMEMultipart()
    msg["From"] = "guest@example.com"
    msg["Subject"] = "photo"
    part = MIMEBase("image", "jpeg")
    part.set_payload(b"\xff\xd8\xff" + b"\x00" * 100)  # fake JPEG bytes
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(part)
    return msg.as_bytes()

def test_poll_downloads_jpeg_attachment(tmp_path):
    raw_dir = str(tmp_path / "raw")
    import os; os.makedirs(raw_dir)

    mock_imap = MagicMock()
    mock_imap.search.return_value = ("OK", [b"1"])
    mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {100})", _make_email_with_jpeg())])
    mock_imap.store.return_value = ("OK", [])

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        from inbox_poller import poll_once
        poll_once(
            imap_server="imap.seznam.cz",
            imap_user="a@b.cz",
            imap_pass="secret",
            raw_dir=raw_dir,
        )

    files = list(tmp_path.glob("raw/*"))
    assert len(files) == 1
    assert files[0].suffix.lower() in {".jpg", ".jpeg"}
    mock_imap.store.assert_called_once_with(b"1", "+FLAGS", "\\Seen")

def test_poll_skips_non_image_attachment(tmp_path):
    raw_dir = str(tmp_path / "raw")
    import os; os.makedirs(raw_dir)

    msg = MIMEMultipart()
    part = MIMEBase("application", "pdf")
    part.set_payload(b"%PDF")
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="doc.pdf")
    msg.attach(part)

    mock_imap = MagicMock()
    mock_imap.search.return_value = ("OK", [b"2"])
    mock_imap.fetch.return_value = ("OK", [(b"2 (RFC822 {100})", msg.as_bytes())])
    mock_imap.store.return_value = ("OK", [])

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        from inbox_poller import poll_once
        poll_once("imap.seznam.cz", "a@b.cz", "secret", raw_dir)

    assert list((tmp_path / "raw").iterdir()) == []
    mock_imap.store.assert_called_once()  # still marked SEEN
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_inbox_poller.py -v
```
Expected: `ModuleNotFoundError: No module named 'inbox_poller'`

- [ ] **Step 3: Create `inbox_poller.py`**

```python
import imaplib, email, os, logging, time, threading
from pathlib import Path

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".tif", ".webp"}


def poll_once(imap_server: str, imap_user: str, imap_pass: str, raw_dir: str) -> None:
    try:
        with imaplib.IMAP4_SSL(imap_server) as imap:
            imap.login(imap_user, imap_pass)
            imap.select("INBOX")
            status, data = imap.search(None, "UNSEEN")
            if status != "OK":
                return
            for num in data[0].split():
                _, msg_data = imap.fetch(num, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                _save_attachments(msg, raw_dir)
                imap.store(num, "+FLAGS", "\\Seen")
    except Exception as exc:
        log.warning("IMAP poll failed: %s", exc)


def _save_attachments(msg, raw_dir: str) -> None:
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        cd = part.get("Content-Disposition", "")
        if "attachment" not in cd:
            continue
        filename = part.get_filename()
        if not filename:
            continue
        ext = Path(filename).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        payload = part.get_payload(decode=True)
        dest = Path(raw_dir) / filename
        # avoid overwrite
        counter = 1
        while dest.exists():
            dest = Path(raw_dir) / f"{Path(filename).stem}_{counter}{ext}"
            counter += 1
        dest.write_bytes(payload)
        log.info("Saved inbound photo: %s", dest)


class InboxPoller:
    def __init__(self, imap_server, imap_user, imap_pass, raw_dir, interval=30):
        self._args = (imap_server, imap_user, imap_pass, raw_dir)
        self._interval = interval
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self._running:
            poll_once(*self._args)
            time.sleep(self._interval)

    def stop(self):
        self._running = False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_inbox_poller.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add inbox_poller.py tests/test_inbox_poller.py
git commit -m "feat: IMAP inbox poller for inbound guest photos"
```

---

## Task 6: Flask app & API

**Files:**
- Create: `app.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app.py
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
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path / "processed"))
    monkeypatch.setenv("PRINTED_DIR", str(tmp_path / "printed"))
    monkeypatch.setenv("HIDDEN_DIR", str(tmp_path / "hidden"))
    for d in ["raw", "processed", "printed", "hidden"]:
        (tmp_path / d).mkdir()

    import importlib, config
    importlib.reload(config)
    import app as app_module
    importlib.reload(app_module)
    app_module.flask_app.config["TESTING"] = True
    return app_module.flask_app.test_client(), tmp_path

def _make_processed_photo(tmp_path, name="photo1"):
    img = Image.new("RGB", (900, 600))
    img.save(str(tmp_path / "processed" / f"{name}.jpg"), "JPEG")
    img.save(str(tmp_path / "processed" / f"{name}_thumb.jpg"), "JPEG")

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_app.py -v
```
Expected: `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Create `app.py`**

```python
import os, shutil, logging
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO
import eventlet
eventlet.monkey_patch()

import config
import printer
import mailer

log = logging.getLogger(__name__)

flask_app = Flask(__name__, static_folder="static", static_url_path="")
flask_app.config["SECRET_KEY"] = os.urandom(24)
socketio = SocketIO(flask_app, async_mode="eventlet", cors_allowed_origins="*")


def _photo_list():
    processed = Path(config.PROCESSED_DIR)
    photos = []
    for f in sorted(processed.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.stem.endswith("_thumb"):
            continue
        thumb = processed / f"{f.stem}_thumb.jpg"
        photos.append({
            "filename": f.name,
            "thumb": f"/photos/processed/{thumb.name}" if thumb.exists() else f"/photos/processed/{f.name}",
            "timestamp": f.stat().st_mtime,
        })
    return photos


@flask_app.route("/")
def index():
    return send_from_directory("static", "index.html")


@flask_app.route("/photos/<path:subpath>")
def serve_photo(subpath):
    base = Path(".").resolve()
    return send_from_directory(str(base), f"photos/{subpath}")


@flask_app.route("/api/photos")
def api_photos():
    return jsonify(_photo_list())


@flask_app.route("/api/print", methods=["POST"])
def api_print():
    data = request.json
    filename = data["filename"]
    copies = int(data.get("copies", 1))
    filepath = str(Path(config.PROCESSED_DIR) / filename)
    try:
        printer.print_image(filepath, config.PRINTER_NAME, copies)
        shutil.copy2(filepath, str(Path(config.PRINTED_DIR) / filename))
        return jsonify({"ok": True})
    except Exception as exc:
        log.error("Print error: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@flask_app.route("/api/email", methods=["POST"])
def api_email():
    data = request.json
    filename = data["filename"]
    recipient = data["recipient"]
    filepath = str(Path(config.PROCESSED_DIR) / filename)
    try:
        mailer.send_email(
            filepath=filepath,
            recipient=recipient,
            smtp_server=config.SMTP_SERVER,
            smtp_port=config.SMTP_PORT,
            smtp_user=config.SMTP_USER,
            smtp_pass=config.SMTP_PASS,
        )
        return jsonify({"ok": True})
    except Exception as exc:
        log.error("Email error: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@flask_app.route("/api/hide", methods=["POST"])
def api_hide():
    filename = request.json["filename"]
    src = Path(config.PROCESSED_DIR) / filename
    dst = Path(config.HIDDEN_DIR) / filename
    thumb_src = Path(config.PROCESSED_DIR) / (Path(filename).stem + "_thumb.jpg")
    thumb_dst = Path(config.HIDDEN_DIR) / thumb_src.name
    if src.exists():
        shutil.move(str(src), str(dst))
    if thumb_src.exists():
        shutil.move(str(thumb_src), str(thumb_dst))
    socketio.emit("photo_hidden", {"filename": filename})
    return jsonify({"ok": True})


def on_new_photo(result: dict):
    socketio.emit("new_photo", {
        "filename": Path(result["fullres"]).name,
        "thumb": f"/photos/processed/{Path(result['thumb']).name}",
        "timestamp": Path(result["fullres"]).stat().st_mtime,
    })


if __name__ == "__main__":
    from watcher import PhotoWatcher
    from inbox_poller import InboxPoller

    logging.basicConfig(level=logging.INFO)

    watcher = PhotoWatcher(on_new_photo)
    watcher.start()

    poller = InboxPoller(
        config.IMAP_SERVER, config.IMAP_USER, config.IMAP_PASS,
        config.RAW_DIR, config.IMAP_POLL_INTERVAL
    )
    poller.start()

    socketio.run(flask_app, host="0.0.0.0", port=5000)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_app.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Run the full test suite**

```bash
pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: Flask app with Socket.IO, API endpoints for print/email/hide"
```

---

## Task 7: Frontend UI (static/index.html + static/app.js)

**Files:**
- Create: `static/index.html`
- Create: `static/app.js`

No automated tests for the frontend — manual verification steps are listed at the end.

- [ ] **Step 1: Create `static/index.html`**

```html
<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Eliška & Tom 2026 — Foto Koutek</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
  <style>
    body { background: #1a1a2e; font-family: Georgia, serif; }
    .gold { color: #d4af37; }
    .gold-border { border-color: #d4af37; }
    .gold-bg { background: #d4af37; }
    #lightbox { display: none; }
    #lightbox.open { display: flex; }
    .filmstrip-item.active { outline: 2px solid #d4af37; }
    #toast { transform: translateX(120%); transition: transform 0.3s ease; }
    #toast.show { transform: translateX(0); }
    #photo-main {
      cursor: zoom-in;
      transition: transform 0.2s;
      user-select: none;
    }
    #photo-main.zoomed { transform: scale(2); cursor: zoom-out; }
  </style>
</head>
<body class="min-h-screen text-white">

  <!-- Header -->
  <header class="text-center py-6 border-b border-yellow-700">
    <h1 class="text-3xl tracking-widest gold">ELIŠKA &amp; TOM 2026</h1>
    <p class="text-sm tracking-widest text-gray-400 mt-1">FOTO KOUTEK</p>
    <p class="text-xs text-gray-500 mt-2">Klikněte na fotografii pro tisk nebo odeslání e-mailem</p>
  </header>

  <!-- Gallery grid -->
  <main class="p-4">
    <div id="gallery" class="grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-5"></div>
    <p id="empty-msg" class="text-center text-gray-600 mt-16 text-sm">Zatím žádné fotografie. Pořiďte první snímek!</p>
  </main>

  <!-- Lightbox -->
  <div id="lightbox" class="fixed inset-0 z-50 flex-col" style="background:rgba(10,10,25,0.97)">
    <div class="flex flex-1 overflow-hidden">
      <!-- Photo area -->
      <div class="relative flex-1 flex items-center justify-center overflow-hidden select-none">
        <button id="prev-btn" class="absolute left-2 z-10 text-4xl gold opacity-60 hover:opacity-100 px-2">&#8592;</button>
        <img id="photo-main" class="max-h-full max-w-full object-contain rounded" src="" alt="foto" draggable="false">
        <button id="next-btn" class="absolute right-2 z-10 text-4xl gold opacity-60 hover:opacity-100 px-2">&#8594;</button>
      </div>
      <!-- Right panel -->
      <div class="w-48 flex flex-col gap-4 p-4 border-l border-gray-800 justify-center items-center">
        <button id="close-btn" class="self-end text-gray-500 hover:text-white text-xl">✕</button>

        <!-- Print stepper -->
        <div class="flex flex-col items-center gap-1">
          <span class="text-xs text-gray-500 tracking-widest">POČET KOPIÍ</span>
          <div class="flex items-center gap-3">
            <button id="copies-minus" class="w-8 h-8 rounded-full border gold-border gold text-lg leading-none">−</button>
            <span id="copies-count" class="gold text-2xl font-bold w-6 text-center">1</span>
            <button id="copies-plus" class="w-8 h-8 rounded-full border gold-border gold text-lg leading-none">+</button>
          </div>
        </div>

        <button id="print-btn" class="gold-bg text-gray-900 font-bold rounded-full px-4 py-2 w-full text-sm hover:opacity-90">🖨 TISKNOUT</button>

        <!-- Email section -->
        <div class="w-full flex flex-col gap-2">
          <button id="email-toggle-btn" class="border gold-border gold rounded-full px-4 py-2 w-full text-sm hover:opacity-80">✉ E-MAIL</button>
          <div id="email-form" class="hidden flex-col gap-2">
            <input id="email-input" type="email" value="eliskatom2026@seznam.cz"
              class="bg-gray-900 border border-gray-700 text-white rounded px-2 py-1 text-xs w-full focus:border-yellow-600 outline-none">
            <button id="email-send-btn" class="gold-bg text-gray-900 font-bold rounded px-3 py-1 text-xs w-full">Odeslat</button>
          </div>
        </div>

        <button id="hide-btn" class="border border-red-800 text-red-400 rounded-full px-4 py-2 w-full text-sm hover:border-red-500 hover:text-red-300">🗑 SMAZAT</button>
      </div>
    </div>

    <!-- Filmstrip -->
    <div id="filmstrip" class="flex gap-2 overflow-x-auto px-4 py-2 border-t border-gray-800" style="height:80px"></div>
  </div>

  <!-- Toast -->
  <div id="toast" class="fixed bottom-4 right-4 z-40 flex items-center gap-3 bg-gray-900 border border-yellow-700 rounded-lg px-3 py-2 shadow-xl cursor-pointer max-w-xs">
    <img id="toast-thumb" class="w-12 h-12 object-cover rounded" src="" alt="">
    <div>
      <p class="text-xs gold font-bold">Nová fotografie!</p>
      <p class="text-xs text-gray-400">Klikněte pro zobrazení</p>
    </div>
  </div>

  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `static/app.js`**

```javascript
const socket = io();
let photos = [];       // [{filename, thumb, timestamp}, ...]
let currentIndex = 0;
let copiesCount = 1;
let toastTimer = null;
let toastFilename = null;

// ── Socket.IO ──────────────────────────────────────────────────────────────
socket.on("new_photo", (photo) => {
  photos.unshift(photo);
  renderGallery();
  showToast(photo);
});

socket.on("photo_hidden", ({ filename }) => {
  photos = photos.filter(p => p.filename !== filename);
  renderGallery();
});

// ── Boot ───────────────────────────────────────────────────────────────────
async function loadPhotos() {
  const res = await fetch("/api/photos");
  photos = await res.json();
  renderGallery();
}

// ── Gallery ────────────────────────────────────────────────────────────────
function renderGallery() {
  const gallery = document.getElementById("gallery");
  const empty = document.getElementById("empty-msg");
  empty.style.display = photos.length ? "none" : "block";
  gallery.innerHTML = photos.map((p, i) => `
    <div class="cursor-pointer rounded overflow-hidden border border-gray-800 hover:border-yellow-700 transition"
         onclick="openLightbox(${i})">
      <img src="${p.thumb}" class="w-full aspect-[3/2] object-cover" loading="lazy" alt="">
    </div>`).join("");
}

// ── Lightbox ───────────────────────────────────────────────────────────────
function openLightbox(index) {
  currentIndex = index;
  copiesCount = 1;
  document.getElementById("copies-count").textContent = 1;
  document.getElementById("email-form").classList.add("hidden");
  document.getElementById("lightbox").classList.add("open");
  renderLightbox();
}

function closeLightbox() {
  document.getElementById("lightbox").classList.remove("open");
}

function renderLightbox() {
  const photo = photos[currentIndex];
  document.getElementById("photo-main").src = `/photos/processed/${photo.filename}`;
  renderFilmstrip();
}

function renderFilmstrip() {
  const strip = document.getElementById("filmstrip");
  strip.innerHTML = photos.map((p, i) => `
    <img src="${p.thumb}"
         class="filmstrip-item h-full aspect-[3/2] object-cover rounded cursor-pointer flex-shrink-0 ${i === currentIndex ? "active" : "opacity-50"}"
         onclick="openLightbox(${i})" alt="">`).join("");
  // scroll active into view
  const active = strip.querySelectorAll("img")[currentIndex];
  if (active) active.scrollIntoView({ block: "nearest", inline: "center" });
}

document.getElementById("close-btn").addEventListener("click", closeLightbox);

document.getElementById("prev-btn").addEventListener("click", () => {
  if (currentIndex > 0) { currentIndex--; renderLightbox(); }
});

document.getElementById("next-btn").addEventListener("click", () => {
  if (currentIndex < photos.length - 1) { currentIndex++; renderLightbox(); }
});

document.addEventListener("keydown", (e) => {
  if (!document.getElementById("lightbox").classList.contains("open")) return;
  if (e.key === "ArrowLeft")  document.getElementById("prev-btn").click();
  if (e.key === "ArrowRight") document.getElementById("next-btn").click();
  if (e.key === "Escape")     closeLightbox();
});

// ── Zoom on hold ───────────────────────────────────────────────────────────
const photoEl = document.getElementById("photo-main");
let zoomTimer = null;
photoEl.addEventListener("mousedown", () => { zoomTimer = setTimeout(() => photoEl.classList.add("zoomed"), 200); });
photoEl.addEventListener("mouseup",   () => { clearTimeout(zoomTimer); photoEl.classList.remove("zoomed"); });
photoEl.addEventListener("mouseleave",() => { clearTimeout(zoomTimer); photoEl.classList.remove("zoomed"); });

// ── Copies stepper ─────────────────────────────────────────────────────────
document.getElementById("copies-minus").addEventListener("click", () => {
  if (copiesCount > 1) { copiesCount--; document.getElementById("copies-count").textContent = copiesCount; }
});
document.getElementById("copies-plus").addEventListener("click", () => {
  copiesCount++;
  document.getElementById("copies-count").textContent = copiesCount;
});

// ── Print ──────────────────────────────────────────────────────────────────
document.getElementById("print-btn").addEventListener("click", async () => {
  const photo = photos[currentIndex];
  const res = await fetch("/api/print", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: photo.filename, copies: copiesCount }),
  });
  const data = await res.json();
  showToastMsg(data.ok ? `Tisk zahájen (${copiesCount}×)` : `Chyba tisku: ${data.error}`, data.ok);
});

// ── Email ──────────────────────────────────────────────────────────────────
document.getElementById("email-toggle-btn").addEventListener("click", () => {
  document.getElementById("email-form").classList.toggle("hidden");
});

document.getElementById("email-send-btn").addEventListener("click", async () => {
  const photo = photos[currentIndex];
  const recipient = document.getElementById("email-input").value.trim();
  if (!recipient) return;
  const res = await fetch("/api/email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: photo.filename, recipient }),
  });
  const data = await res.json();
  showToastMsg(data.ok ? "E-mail odeslán!" : `Chyba: ${data.error}`, data.ok);
  if (data.ok) document.getElementById("email-form").classList.add("hidden");
});

// ── Hide / delete ──────────────────────────────────────────────────────────
document.getElementById("hide-btn").addEventListener("click", async () => {
  const photo = photos[currentIndex];
  await fetch("/api/hide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: photo.filename }),
  });
  closeLightbox();
});

// ── Toast ──────────────────────────────────────────────────────────────────
function showToast(photo) {
  toastFilename = photo.filename;
  document.getElementById("toast-thumb").src = photo.thumb;
  const toast = document.getElementById("toast");
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 8000);
}

document.getElementById("toast").addEventListener("click", () => {
  if (toastFilename) {
    const idx = photos.findIndex(p => p.filename === toastFilename);
    if (idx >= 0) openLightbox(idx);
  }
  document.getElementById("toast").classList.remove("show");
});

function showToastMsg(msg, ok) {
  document.getElementById("toast-thumb").src = "";
  document.getElementById("toast").querySelector("p.gold").textContent = ok ? "✓ " + msg : "✗ " + msg;
  document.getElementById("toast").querySelector("p.text-gray-400").textContent = "";
  const toast = document.getElementById("toast");
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 4000);
}

// ── Init ───────────────────────────────────────────────────────────────────
loadPhotos();
```

- [ ] **Step 3: Manual verification**

Start the server and test in a browser:
```bash
cp .env.example .env  # if not already done
python app.py
# open http://localhost:5000
```

Checklist:
- [ ] Gallery loads with "Zatím žádné fotografie" message when empty
- [ ] Copy a JPEG into `photos/raw/` — it appears in gallery within ~2 seconds without refresh
- [ ] Click thumbnail → lightbox opens, photo fills left side, right panel visible
- [ ] Left/right arrows navigate between photos
- [ ] Filmstrip shows all photos, current one highlighted gold
- [ ] Click-and-hold on photo zooms in, release zooms out
- [ ] − / + stepper changes copy count, cannot go below 1
- [ ] TISKNOUT button triggers print (check terminal for lp command on Mac)
- [ ] ✉ E-MAIL reveals input, Odeslat sends (check terminal for SMTP attempt)
- [ ] SMAZAT removes photo from gallery, lightbox closes
- [ ] Drop a second JPEG into `raw/` while lightbox is open → toast appears bottom-right without interrupting lightbox
- [ ] Click toast → jumps to new photo in lightbox

- [ ] **Step 4: Commit**

```bash
git add static/
git commit -m "feat: frontend UI — gallery, lightbox, filmstrip, toast, print/email/hide"
```

---

## Task 8: Startup scripts

**Files:**
- Create: `run.sh`
- Create: `run.bat`

- [ ] **Step 1: Create `run.sh` (Mac)**

```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
  python3 -m venv venv
  venv/bin/pip install -r requirements.txt
fi

mkdir -p photos/raw photos/processed photos/printed photos/hidden

venv/bin/python app.py
```

- [ ] **Step 2: Create `run.bat` (Windows)**

```bat
@echo off
cd /d "%~dp0"

if not exist venv (
    python -m venv venv
    venv\Scripts\pip install -r requirements.txt
)

if not exist photos\raw       mkdir photos\raw
if not exist photos\processed mkdir photos\processed
if not exist photos\printed   mkdir photos\printed
if not exist photos\hidden    mkdir photos\hidden

venv\Scripts\python app.py
```

- [ ] **Step 3: Make `run.sh` executable**

```bash
chmod +x run.sh
```

- [ ] **Step 4: Commit**

```bash
git add run.sh run.bat
git commit -m "feat: startup scripts for Mac and Windows"
```

---

## Task 9: Final integration smoke test

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 2: Smoke test inbound email pipeline**

Send an email with a JPEG attachment to the configured inbox. Wait up to 60 seconds. Verify:
- Photo appears in gallery
- Toast notification shows
- Photo can be printed and emailed outbound

- [ ] **Step 3: Smoke test HEIC conversion (Mac)**

Copy an iPhone HEIC file into `photos/raw/`. Verify it appears in gallery as JPEG within 2 seconds.

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "chore: final integration verified"
```
