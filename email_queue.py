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

RETRY_INTERVAL = 60  # seconds between retry sweeps


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
            snapshot = list(self._entries)
        if not snapshot:
            return (0, 0)

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
                # still offline — keep the rest queued and stop trying this round
                idx = snapshot.index(entry)
                still_queued.extend(snapshot[idx:])
                for e in snapshot[idx:]:
                    e["attempts"] = e.get("attempts", 0) + 1
                break
            except Exception as e:  # noqa: BLE001
                # non-connection error (auth, bad address) — drop after logging
                log.error("Dropping queued email %s → %s: %s",
                          entry["filename"], entry["recipient"], e)

        with self._lock:
            self._entries = still_queued
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
        while not self._stop.is_set():
            try:
                self.flush()
            except Exception:  # noqa: BLE001
                log.exception("Email queue flush crashed")
            self._stop.wait(RETRY_INTERVAL)
