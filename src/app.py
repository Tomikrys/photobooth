import os, shutil, logging, subprocess, sys, threading
from collections import deque
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO

import config
import printer
import mailer
from email_queue import EmailQueue

log = logging.getLogger(__name__)

# In-memory ring buffer — last 500 log lines, shown in /config
_log_buffer = deque(maxlen=500)

# Loggers that produce high-frequency noise with no actionable signal
_NOISY_LOGGERS = {"werkzeug", "engineio.server", "socketio.server"}
# Message fragments to suppress even from non-noisy loggers
_NOISY_FRAGMENTS = (
    "GET /api/logs",
    "GET /socket.io",
    "POST /socket.io",
    "watcher flush",
)

class _BufferHandler(logging.Handler):
    def emit(self, record):
        if record.name in _NOISY_LOGGERS:
            return
        msg = record.getMessage()
        if any(f in msg for f in _NOISY_FRAGMENTS):
            return
        from datetime import datetime
        _log_buffer.append({
            "t": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
            "level": record.levelname,
            "name": record.name,
            "msg": msg,
        })

_buf_handler = _BufferHandler()
logging.getLogger().addHandler(_buf_handler)

# Demote werkzeug request logs to DEBUG — they're noise at INFO level in the UI
logging.getLogger("werkzeug").setLevel(logging.WARNING)

flask_app = Flask(__name__, static_folder="static", static_url_path="")
flask_app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "photobooth-dev-key-change-in-prod")
socketio = SocketIO(flask_app, async_mode="threading", cors_allowed_origins="*")

email_queue = EmailQueue(
    queue_path=config.EMAIL_QUEUE_PATH,
    smtp_server=config.SMTP_SERVER,
    smtp_port=config.SMTP_PORT,
    smtp_user=config.SMTP_USER,
    smtp_pass=config.SMTP_PASS,
    processed_dir=config.PROCESSED_DIR,
)

# --- NikonMove process management (module-level so /api/config/restart-nikon can reach it) ---
_nikon_proc = None
_nikon_lock = threading.Lock()
_src_dir = Path(__file__).resolve().parent
_root_dir = _src_dir.parent
_poller = None   # InboxPoller — set in __main__, updated by config save
_watcher = None  # PhotoWatcher — set in __main__, updated by config save


def _start_nikon():
    global _nikon_proc
    if os.environ.get("NIKON_MANAGED"):
        log.debug("NIKON_MANAGED set — NikonMove managed by launcher, skipping")
        return
    nikon_script = _src_dir / "NikonMove.ps1"
    if not nikon_script.exists():
        return
    _nikon_proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(nikon_script)],
        cwd=str(_root_dir)
    )
    log.info("NikonMove started (PID %s)", _nikon_proc.pid)


def _stop_nikon():
    global _nikon_proc
    if _nikon_proc and _nikon_proc.poll() is None:
        _nikon_proc.terminate()
        try:
            _nikon_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _nikon_proc.kill()
        log.info("NikonMove stopped")
    _nikon_proc = None


def _photo_list():
    processed = Path(config.PROCESSED_DIR)
    thumbs = Path(config.THUMBS_DIR)
    photos = []
    for f in sorted(processed.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True):
        thumb = thumbs / f.name
        photos.append({
            "filename": f.name,
            "thumb": f"/photos/thumbs/{f.name}" if thumb.exists() else f"/photos/processed/{f.name}",
            "timestamp": f.stat().st_mtime,
        })
    return photos


@flask_app.route("/")
def index():
    return send_from_directory("static", "index.html")


@flask_app.route("/photos/processed/<path:filename>")
def serve_processed_photo(filename):
    full = Path(config.PROCESSED_DIR) / filename
    if not full.exists():
        log.warning("processed 404: %s (looked at %s)", filename, full)
    return send_from_directory(config.PROCESSED_DIR, filename)


@flask_app.route("/photos/thumbs/<path:filename>")
def serve_thumb(filename):
    # Fall back to the fullres file when the thumbnail is missing for any
    # reason (thumb not generated yet, deleted, older photo that predates the
    # thumbs folder). Better a slightly-larger image than a broken tile.
    thumb_full = Path(config.THUMBS_DIR) / filename
    if not thumb_full.exists():
        processed_full = Path(config.PROCESSED_DIR) / filename
        if processed_full.exists():
            log.info("thumb missing, serving fullres: %s", filename)
            return send_from_directory(config.PROCESSED_DIR, filename)
        log.warning("thumb 404: %s (neither %s nor fullres exists)", filename, thumb_full)
    return send_from_directory(config.THUMBS_DIR, filename)


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
    except mailer.EmailConnectionError as exc:
        log.warning("SMTP unreachable — queuing %s for %s: %s", filename, recipient, exc)
        email_queue.enqueue(filename, recipient)
        return jsonify({"ok": True, "queued": True})
    except Exception as exc:
        log.error("Email error: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@flask_app.route("/api/email/queue")
def api_email_queue():
    return jsonify(email_queue.pending())


@flask_app.route("/api/hide", methods=["POST"])
def api_hide():
    filename = request.json["filename"]
    src = Path(config.PROCESSED_DIR) / filename
    if not src.exists():
        return jsonify({"ok": False, "error": "Photo not found"}), 404
    dst = Path(config.HIDDEN_DIR) / filename
    shutil.move(str(src), str(dst))
    thumb = Path(config.THUMBS_DIR) / filename
    if thumb.exists():
        thumb.unlink()
    socketio.emit("photo_hidden", {"filename": filename})
    return jsonify({"ok": True})


@flask_app.route("/config")
def config_page():
    return send_from_directory("static", "config.html")


@flask_app.route("/api/config", methods=["GET"])
def api_config_get():
    """Return current live config values (what the app actually uses)."""
    return jsonify({
        "PRINTER_NAME": config.PRINTER_NAME,
        "SMTP_SERVER": config.SMTP_SERVER,
        "SMTP_PORT": str(config.SMTP_PORT),
        "SMTP_USER": config.SMTP_USER,
        "SMTP_PASS": config.SMTP_PASS,
        "IMAP_SERVER": config.IMAP_SERVER,
        "IMAP_USER": config.IMAP_USER,
        "IMAP_PASS": config.IMAP_PASS,
        "IMAP_POLL_INTERVAL": str(config.IMAP_POLL_INTERVAL),
        "CAMERA_NAME": os.environ.get("CAMERA_NAME", "D3100"),
        "CAMERA_FOLDER_PATTERN": os.environ.get("CAMERA_FOLDER_PATTERN", "100D3100"),
        "CAMERA_DIR": config.CAMERA_DIR,
        "RAW_DIR": config.RAW_DIR,
        "PROCESSED_DIR": config.PROCESSED_DIR,
        "THUMBS_DIR": config.THUMBS_DIR,
        "PRINTED_DIR": config.PRINTED_DIR,
        "HIDDEN_DIR": config.HIDDEN_DIR,
        "EMAIL_QUEUE_PATH": config.EMAIL_QUEUE_PATH,
    })


@flask_app.route("/api/config", methods=["POST"])
def api_config_save():
    """Write posted key/value pairs into .env and reload config."""
    data = request.json  # {KEY: value, ...}
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"

    # Read existing lines
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    # Update or append each key
    updated = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        k = stripped.partition("=")[0].strip()
        if k in data:
            new_lines.append(f"{k}={data[k]}")
            updated.add(k)
        else:
            new_lines.append(line)
    for k, v in data.items():
        if k not in updated:
            new_lines.append(f"{k}={v}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Reload config module (load_dotenv uses override=True so new values land in os.environ)
    import importlib
    try:
        importlib.reload(config)
        log.info("config reloaded after settings save")
    except Exception as exc:
        log.warning("config reload failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    # Update stateful objects that captured config values at construction time
    email_queue._smtp_server = config.SMTP_SERVER
    email_queue._smtp_port = config.SMTP_PORT
    email_queue._smtp_user = config.SMTP_USER
    email_queue._smtp_pass = config.SMTP_PASS
    email_queue._processed_dir = Path(config.PROCESSED_DIR)

    # Update InboxPoller credentials (it stores them as instance vars, not from config)
    if _poller is not None:
        _poller.update_credentials(config.IMAP_SERVER, config.IMAP_USER, config.IMAP_PASS)
    if _watcher is not None:
        _watcher.reload_watch_dir()

    return jsonify({"ok": True})


@flask_app.route("/api/config/printers")
def api_config_printers():
    """List installed printers (Windows: PowerShell; others: lpstat)."""
    printers = []
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Printer | Select-Object -ExpandProperty Name"],
                text=True, timeout=10
            )
            printers = [l.strip() for l in out.splitlines() if l.strip()]
        except Exception as exc:
            log.warning("printer list failed: %s", exc)
    else:
        try:
            out = subprocess.check_output(["lpstat", "-p"], text=True, timeout=5)
            for line in out.splitlines():
                if line.startswith("printer "):
                    printers.append(line.split()[1])
        except Exception as exc:
            log.warning("printer list failed: %s", exc)
    return jsonify(printers)


@flask_app.route("/api/config/mtp-devices")
def api_config_mtp_devices():
    """List MTP devices visible in Shell namespace (Windows only)."""
    if sys.platform != "win32":
        return jsonify([])
    try:
        script = (
            "$shell = New-Object -ComObject Shell.Application;"
            "$ns = $shell.Namespace(0x11);"
            "if (-not $ns) { exit };"
            "foreach ($item in $ns.Items()) {"
            "  try {"
            "    $f = $item.GetFolder;"
            "    if (-not $f) { continue };"
            "    $children = @($f.Items());"
            "    if ($children.Count -gt 0) { Write-Output $item.Name }"
            "  } catch {}"
            "}"
        )
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True, timeout=15
        )
        devices = [l.strip() for l in out.splitlines() if l.strip()]
        return jsonify(devices)
    except Exception as exc:
        log.warning("MTP device list failed: %s", exc)
        return jsonify([])


@flask_app.route("/api/config/mtp-folders")
def api_config_mtp_folders():
    """List DCIM subfolders for a given MTP device name."""
    device_name = request.args.get("device", "")
    if sys.platform != "win32" or not device_name:
        return jsonify([])
    # Escape PowerShell -like wildcards to prevent injection / unintended matching
    safe_name = device_name.replace("'", "''").replace("[", "`[").replace("]", "`]").replace("*", "`*").replace("?", "`?")
    try:
        script = (
            f"$shell = New-Object -ComObject Shell.Application;"
            f"$ns = $shell.Namespace(0x11);"
            f"$cam = $ns.Items() | Where-Object {{ $_.Name -eq '{safe_name}' }} | Select-Object -First 1;"
            f"if (-not $cam) {{ exit }};"
            f"$storage = $cam.GetFolder.Items() | Select-Object -First 1;"
            f"if (-not $storage) {{ exit }};"
            f"$dcim = $storage.GetFolder.Items() | Where-Object {{ $_.Name -eq 'DCIM' }} | Select-Object -First 1;"
            f"if (-not $dcim) {{ exit }};"
            f"$dcim.GetFolder.Items() | ForEach-Object {{ Write-Output $_.Name }}"
        )
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True, timeout=15
        )
        folders = [l.strip() for l in out.splitlines() if l.strip()]
        return jsonify(folders)
    except Exception as exc:
        log.warning("MTP folder list failed: %s", exc)
        return jsonify([])


@flask_app.route("/api/config/restart-nikon", methods=["POST"])
def api_restart_nikon():
    """Restart the NikonMove.ps1 process."""
    with _nikon_lock:
        _stop_nikon()
        _start_nikon()
    return jsonify({"ok": True})


@flask_app.route("/api/logs")
def api_logs():
    """Return the in-memory log buffer (last 500 lines)."""
    return jsonify(list(_log_buffer))


@flask_app.route("/api/config/log-level", methods=["POST"])
def api_set_log_level():
    """Set the root logger level dynamically."""
    level = request.json.get("level", "INFO").upper()
    numeric = getattr(logging, level, None)
    if not isinstance(numeric, int):
        return jsonify({"ok": False, "error": f"Unknown level: {level}"}), 400
    logging.getLogger().setLevel(numeric)
    log.info("Log level set to %s", level)
    return jsonify({"ok": True})


def on_new_photo(result: dict):
    fullres_name = Path(result["fullres"]).name
    thumb_path = Path(result["thumb"])
    thumb_url = (
        f"/photos/thumbs/{thumb_path.name}"
        if thumb_path.exists()
        else f"/photos/processed/{fullres_name}"
    )
    socketio.emit("new_photo", {
        "filename": fullres_name,
        "thumb": thumb_url,
        "timestamp": Path(result["fullres"]).stat().st_mtime,
    })


if __name__ == "__main__":
    from watcher import PhotoWatcher
    from inbox_poller import InboxPoller

    # basicConfig only installs a StreamHandler when no handlers exist yet.
    # _buf_handler is already on the root logger, so force-add stdout explicitly.
    _stream = logging.StreamHandler()
    _stream.setLevel(logging.INFO)
    _stream.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logging.getLogger().addHandler(_stream)
    logging.getLogger().setLevel(logging.INFO)

    log.info("Serving processed from: %s", config.PROCESSED_DIR)
    log.info("Serving thumbs    from: %s", config.THUMBS_DIR)
    log.info("Watching camera   dir : %s", config.CAMERA_DIR)

    _watcher = PhotoWatcher(on_new_photo)
    _watcher.start()

    _poller = InboxPoller(
        config.IMAP_SERVER, config.IMAP_USER, config.IMAP_PASS,
        config.CAMERA_DIR, config.IMAP_POLL_INTERVAL
    )
    _poller.start()

    email_queue.start()
    # Only spawn NikonMove when running standalone (not via Photobooth.exe launcher,
    # which spawns it separately). Set NIKON_MANAGED=1 in the launcher to skip this.
    if not os.environ.get("NIKON_MANAGED"):
        _start_nikon()

    port = int(os.environ.get("PORT", "5001"))
    socketio.run(flask_app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)
