import os, shutil, logging
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO

import config
import printer
import mailer

log = logging.getLogger(__name__)

flask_app = Flask(__name__, static_folder="static", static_url_path="")
flask_app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "photobooth-dev-key-change-in-prod")
socketio = SocketIO(flask_app, async_mode="threading", cors_allowed_origins="*")


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
    return send_from_directory(config.PROCESSED_DIR, filename)


@flask_app.route("/photos/thumbs/<path:filename>")
def serve_thumb(filename):
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
    except Exception as exc:
        log.error("Email error: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


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


def on_new_photo(result: dict):
    socketio.emit("new_photo", {
        "filename": Path(result["fullres"]).name,
        "thumb": f"/photos/thumbs/{Path(result['thumb']).name}",
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
        config.CAMERA_DIR, config.IMAP_POLL_INTERVAL
    )
    poller.start()

    port = int(os.environ.get("PORT", "5001"))
    socketio.run(flask_app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)
