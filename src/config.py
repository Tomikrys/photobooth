import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Anchor all photo paths to the process CWD at import time. The launcher sets
# CWD = project root before spawning app.py, so relative paths from .env
# resolve there. Freezing to absolute here means later CWD changes (e.g. if a
# subprocess or library calls os.chdir) can't break send_from_directory or
# watcher writes.
_ROOT = Path.cwd().resolve()

def _abs(p: str) -> str:
    path = Path(p)
    if not path.is_absolute():
        path = _ROOT / path
    return str(path.resolve())

PRINTER_NAME = os.environ["PRINTER_NAME"]
SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
IMAP_SERVER = os.environ["IMAP_SERVER"]
IMAP_USER = os.environ["IMAP_USER"]
IMAP_PASS = os.environ["IMAP_PASS"]
IMAP_POLL_INTERVAL = int(os.environ.get("IMAP_POLL_INTERVAL", "30"))
CAMERA_DIR = _abs(os.environ.get("CAMERA_DIR", "./photos/camera"))
RAW_DIR = _abs(os.environ.get("RAW_DIR", "./photos/raw"))
PROCESSED_DIR = _abs(os.environ.get("PROCESSED_DIR", "./photos/processed"))
THUMBS_DIR = _abs(os.environ.get("THUMBS_DIR", "./photos/processed/thumbs"))
PRINTED_DIR = _abs(os.environ.get("PRINTED_DIR", "./photos/printed"))
HIDDEN_DIR = _abs(os.environ.get("HIDDEN_DIR", "./photos/hidden"))
EMAIL_QUEUE_PATH = _abs(os.environ.get("EMAIL_QUEUE_PATH", "./photos/email_queue.json"))
