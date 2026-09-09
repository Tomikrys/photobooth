import imaplib, email, os, logging, time, threading
from pathlib import Path

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".tif", ".webp"}


def poll_once(imap_server: str, imap_user: str, imap_pass: str, raw_dir: str) -> None:
    imap = None
    try:
        imap = imaplib.IMAP4_SSL(imap_server)
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
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass


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
