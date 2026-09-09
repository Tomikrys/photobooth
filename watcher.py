import os, shutil, logging
import time, threading
from pathlib import Path
from PIL import Image, ImageOps
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import config

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


def process_image(src_path: str, processed_dir: str, hidden_dir: str, thumbs_dir: str | None = None, raw_dir: str | None = None) -> dict | None:
    src = Path(src_path)
    if src.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None
    if thumbs_dir is None:
        thumbs_dir = str(Path(processed_dir) / "thumbs")
    try:
        img = Image.open(src_path)
        img = ImageOps.exif_transpose(img)   # auto-orient from EXIF
        img = img.convert("RGB")
        img = _centre_crop(img)

        stem = src.stem
        fullres_path = Path(processed_dir) / f"{stem}.jpg"
        thumb_path   = Path(thumbs_dir) / f"{stem}.jpg"
        Path(thumbs_dir).mkdir(parents=True, exist_ok=True)

        img.save(str(fullres_path), "JPEG", quality=92)
        tw, th = img.size
        thumb_h = round(400 * th / tw)
        thumb = img.resize((400, thumb_h), Image.LANCZOS)
        thumb.save(str(thumb_path), "JPEG", quality=80)

        if raw_dir:
            Path(raw_dir).mkdir(parents=True, exist_ok=True)
            backup_path = Path(raw_dir) / src.name
            if not backup_path.exists():
                shutil.copy2(src_path, str(backup_path))
        src.unlink()  # remove from camera/ after successful processing (and raw backup)
        return {"fullres": str(fullres_path), "thumb": str(thumb_path), "stem": stem}
    except Exception as exc:
        log.warning("Failed to process %s: %s", src_path, exc)
        if src.exists():
            try:
                dest = Path(hidden_dir) / src.name
                shutil.move(src_path, str(dest))
                log.info("Moved unprocessable file to %s", dest)
            except Exception as move_exc:
                log.error("Failed to move %s to hidden: %s", src_path, move_exc)
        return None


class _Handler(FileSystemEventHandler):
    def __init__(self, on_new_photo):
        self._on_new_photo = on_new_photo
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()

    def on_modified(self, event):
        if event.is_directory:
            return
        name = Path(event.src_path).name
        if name.startswith(".") or name.endswith(".tmp"):
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
            result = process_image(path, config.PROCESSED_DIR, config.HIDDEN_DIR, config.THUMBS_DIR, config.RAW_DIR)
            if result:
                try:
                    self._on_new_photo(result)
                except Exception as exc:
                    log.error("on_new_photo callback failed: %s", exc)


class PhotoWatcher:
    def __init__(self, on_new_photo):
        self._handler = _Handler(on_new_photo)
        self._observer = Observer()
        self._observer.schedule(self._handler, config.CAMERA_DIR, recursive=False)
        self._running = False

    def start(self):
        os.makedirs(config.CAMERA_DIR, exist_ok=True)
        os.makedirs(config.RAW_DIR, exist_ok=True)
        os.makedirs(config.PROCESSED_DIR, exist_ok=True)
        os.makedirs(config.THUMBS_DIR, exist_ok=True)
        os.makedirs(config.PRINTED_DIR, exist_ok=True)
        os.makedirs(config.HIDDEN_DIR, exist_ok=True)
        # Sweep pre-existing files in camera/ — watchdog only reacts to new events
        for p in Path(config.CAMERA_DIR).iterdir():
            if p.is_file() and not p.name.startswith(".") and not p.name.endswith(".tmp"):
                with self._handler._lock:
                    self._handler._pending[str(p)] = time.time()  # ready now
                log.info("Queued pre-existing file: %s", p.name)
        self._observer.start()
        self._running = True
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def _poll_loop(self):
        while self._running:
            try:
                self._handler.flush()
            except Exception as exc:
                log.error("watcher flush failed: %s", exc)
            time.sleep(0.25)

    def stop(self):
        self._running = False
        self._observer.stop()
        self._observer.join()
