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
        tw, th = img.size
        thumb_h = round(400 * th / tw)
        thumb = img.resize((400, thumb_h), Image.LANCZOS)
        thumb.save(str(thumb_path), "JPEG", quality=80)

        src.unlink()  # remove from raw/ after successful processing
        return {"fullres": str(fullres_path), "thumb": str(thumb_path), "stem": stem}
    except Exception as exc:
        log.warning("Failed to process %s: %s — moving to hidden", src_path, exc)
        dest = Path(hidden_dir) / src.name
        shutil.move(src_path, str(dest))
        return None


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
                try:
                    self._on_new_photo(result)
                except Exception as exc:
                    log.error("on_new_photo callback failed: %s", exc)


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
