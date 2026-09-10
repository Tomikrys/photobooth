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

def test_portrait_thumbnail_width_is_400px(dirs):
    src = Path(dirs["raw"]) / "portrait_thumb.jpg"
    make_jpeg(str(src), 2000, 3000)
    from watcher import process_image
    result = process_image(str(src), dirs["processed"], dirs["hidden"])
    thumb = Image.open(result["thumb"])
    assert thumb.size[0] == 400


def test_raw_dir_backs_up_original(dirs, tmp_path):
    # camera/ is the ingest folder; raw/ is the backup archive
    raw_backup = tmp_path / "raw_backup"
    raw_backup.mkdir()
    src = Path(dirs["raw"]) / "archive_me.jpg"  # dirs["raw"] here is just a working folder in the fixture
    make_jpeg(str(src), 3000, 2000)
    from watcher import process_image
    result = process_image(str(src), dirs["processed"], dirs["hidden"], raw_dir=str(raw_backup))
    assert result is not None
    # original backed up under raw/, source (camera/) cleaned up
    assert (raw_backup / "archive_me.jpg").exists()
    assert not src.exists()
