"""Persistent email retry queue.

When SMTP is unreachable (no internet), /api/email calls enqueue(filename, recipient).
A background thread retries every RETRY_INTERVAL seconds until each entry succeeds
or is manually removed. Queue is persisted to JSON so a restart doesn't lose it.
"""
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import mailer

log = logging.getLogger(__name__)

RETRY_INTERVAL = 15  # seconds between retry sweeps


class EmailQueue:
    def __init__(self, queue_path: str, smtp_server: str, smtp_port: int,
                 smtp_user: str, smtp_pass: str, processed_dir: str):
        self._path = Path(queue_path)
        self._smtp_server = smtp_server
        self._smtp_port = smtp_port
        self._smtp_user = smtp_user
        self._smtp_pass = smtp_pass
        self._processed_dir = Path(processed_dir)
        self._lock = threading.Lock()
        self._entries = self._load()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Could not read email queue at %s: %s", self._path, e)
            return []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._entries, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    def enqueue(self, filename: str, recipient: str) -> None:
        with self._lock:
            self._entries.append({
                "filename": filename,
                "recipient": recipient,
                "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "attempts": 0,
            })
            self._save()
        log.info("Queued email for %s → %s (queue size %d)", filename, recipient, len(self._entries))

    def pending(self) -> list[dict]:
        with self._lock:
            return list(self._entries)

    def flush(self) -> tuple[int, int]:
        """Try to send every queued entry. Returns (sent, remaining)."""
        with self._lock:
            if not self._entries:
                return (0, 0)
            snapshot = list(self._entries)

        sent = 0
        still_queued: list[dict] = []
        for entry in snapshot:
            filepath = self._processed_dir / entry["filename"]
            if not filepath.exists():
                log.warning("Queued photo %s no longer exists — dropping entry", entry["filename"])
                continue
            try:
                mailer.send_email(
                    filepath=str(filepath),
                    recipient=entry["recipient"],
                    smtp_server=self._smtp_server,
                    smtp_port=self._smtp_port,
                    smtp_user=self._smtp_user,
                    smtp_pass=self._smtp_pass,
                )
                sent += 1
                log.info("Queued email flushed: %s → %s", entry["filename"], entry["recipient"])
            except mailer.EmailConnectionError:
                # still offline — keep this and all remaining entries, stop trying
                idx = snapshot.index(entry)
                for e in snapshot[idx:]:
                    e["attempts"] = e.get("attempts", 0) + 1
                still_queued.extend(snapshot[idx:])
                break
            except Exception as e:  # noqa: BLE001
                log.error("Dropping queued email %s → %s: %s",
                          entry["filename"], entry["recipient"], e)

        with self._lock:
            # Merge: keep entries added by enqueue() during the flush, plus our still_queued.
            # Entries added during flush are those NOT in snapshot (appended after we copied).
            flushed_names = {id(e) for e in snapshot}
            new_entries = [e for e in self._entries if id(e) not in flushed_names]
            self._entries = still_queued + new_entries
            self._save()
        return (sent, len(still_queued))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="email-queue")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        if self._entries:
            log.info("Email queue loaded %d pending entries — will retry every %ds", len(self._entries), RETRY_INTERVAL)
        while not self._stop.is_set():
            try:
                sent, remaining = self.flush()
                if sent:
                    log.info("Email queue: sent %d, %d remaining", sent, remaining)
                elif remaining:
                    log.debug("Email queue: %d entries still pending (offline?)", remaining)
            except Exception:  # noqa: BLE001
                log.exception("Email queue flush crashed")
            self._stop.wait(RETRY_INTERVAL)
