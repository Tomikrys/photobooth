import os
import logging
from pathlib import Path
from dotenv import load_dotenv

log = logging.getLogger(__name__)

# Project root = the folder that CONTAINS src/. config.py lives at src/config.py,
# so root is __file__.parent.parent. This is deterministic regardless of the
# process CWD, which the Windows launcher and dev run.sh both set differently.
_ROOT = Path(__file__).resolve().parent.parent

# Load .env from the project root first, then fall back to load_dotenv's default
# search (walks up from CWD). Explicit path avoids surprises when CWD != root.
_env_at_root = _ROOT / ".env"
if _env_at_root.exists():
    load_dotenv(_env_at_root, override=True)
else:
    load_dotenv(override=True)

def _abs(p: str) -> str:
    path = Path(p)
    if not path.is_absolute():
        path = _ROOT / path
    return str(path.resolve())

PRINTER_NAME = os.environ.get("PRINTER_NAME", "")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
IMAP_SERVER = os.environ.get("IMAP_SERVER", "")
IMAP_USER = os.environ.get("IMAP_USER", "")
IMAP_PASS = os.environ.get("IMAP_PASS", "")
IMAP_POLL_INTERVAL = int(os.environ.get("IMAP_POLL_INTERVAL", "30"))
CAMERA_DIR = _abs(os.environ.get("CAMERA_DIR", "./photos/camera"))
RAW_DIR = _abs(os.environ.get("RAW_DIR", "./photos/raw"))
PROCESSED_DIR = _abs(os.environ.get("PROCESSED_DIR", "./photos/processed"))
THUMBS_DIR = _abs(os.environ.get("THUMBS_DIR", "./photos/processed/thumbs"))
PRINTED_DIR = _abs(os.environ.get("PRINTED_DIR", "./photos/printed"))
HIDDEN_DIR = _abs(os.environ.get("HIDDEN_DIR", "./photos/hidden"))
EMAIL_QUEUE_PATH = _abs(os.environ.get("EMAIL_QUEUE_PATH", "./photos/email_queue.json"))

# One-shot log line so the console shows exactly where the app is reading/writing.
log.info(
    "config: root=%s processed=%s thumbs=%s",
    _ROOT, PROCESSED_DIR, THUMBS_DIR,
)
