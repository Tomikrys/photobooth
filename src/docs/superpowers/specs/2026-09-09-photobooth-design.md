# Photo Booth — Design Spec
_Eliška & Tom 2026_

## Overview

A local web-based photo booth application for a Windows PC (event) and Mac (development). A tethering tool (digiCamControl on Windows) drops JPGs into a watched folder. A Python/Flask backend processes them and serves a browser UI. Guests can print photos on a Canon Selphy CP1500, email them to themselves, or submit photos from their own phones via email. The UI is in Czech, Elegant Dark style (navy + gold).

---

## Architecture

```
digiCamControl (Windows) / manual copy (Mac dev)
    │ drops JPGs into
    ▼
photos/raw/              ← never modified, original files
    │ watchdog detects new file
    ▼
watcher.py               ← debounce 1s, format conversion (HEIC/TIFF/PNG→JPEG), EXIF auto-orient, crop to 3:2 (landscape) or 2:3 (portrait) for 10×15cm Selphy output, save full-res + thumbnail
    │ emits Socket.IO "new_photo"
    ▼
app.py (Flask + Socket.IO) ← serves UI at localhost:5000, API endpoints
    ├── printer.py        ← pywin32 (Windows) / lp subprocess (Mac)
    └── mailer.py         ← smtplib outbound to guest email

inbox_poller.py           ← background thread, IMAP polls eliskatom2026@seznam.cz every 30s
    │ downloads image attachments
    ▼
photos/raw/               ← watcher picks them up automatically
```

Browser (same machine or tablet on local Wi-Fi) connects to `http://localhost:5000`.

---

## Folder Structure

```
photos/
  raw/        ← camera input + inbound email attachments (never modified)
  processed/  ← full-res + _thumb.jpg variants (gallery source of truth)
  printed/    ← copy made here when print is confirmed (tracking)
  hidden/     ← "deleted" photos moved here (hidden from UI, preserved on disk)
```

---

## Modules

| Module | Purpose | Key library |
|---|---|---|
| `app.py` | Flask server, Socket.IO, API endpoints | Flask, Flask-SocketIO, eventlet |
| `watcher.py` | Monitors `raw/`, converts formats, processes new files | watchdog, Pillow, pillow-heif |
| `printer.py` | Cross-platform printing | pywin32 (Win), subprocess/lp (Mac) |
| `mailer.py` | Outbound email to guest address | smtplib, email.mime |
| `inbox_poller.py` | Polls IMAP inbox, saves attachments to `raw/` | imaplib |
| `static/index.html` | Single-page UI | Vanilla JS, Socket.IO client, TailwindCSS CDN |

---

## API Endpoints

- `GET /api/photos` — returns list of processed photos (filename, thumbnail path, timestamp)
- `POST /api/print` — `{ filename, copies }` — triggers print; copies file to `printed/` only on success
- `POST /api/email` — `{ filename, recipient }` — sends photo as attachment
- `POST /api/hide` — `{ filename }` — moves file from `processed/` to `hidden/`

Socket.IO events:
- Server → client: `new_photo` `{ filename, thumb_path, timestamp }`

---

## Frontend UI

### Gallery view
- Dark navy background, gold accents, Georgia serif title
- Header: "ELIŠKA & TOM 2026" (gold, large) + "FOTO KOUTEK" (subtitle) + Czech instructions
- Grid of thumbnails, newest first
- Clicking any thumbnail opens the lightbox

### Lightbox
- Photo fills left ~70%, right panel for actions
- **Right panel:**
  - − / count / + stepper (starts at 1, min 1)
  - Gold "🖨 TISKNOUT" button — submits print job with current count
  - "✉ E-MAIL" button — reveals text input pre-filled with `eliskatom2026@seznam.cz`, physical keyboard entry, "Odeslat" confirm
  - Red "🗑 SMAZAT" button — moves photo to hidden, closes lightbox
- **Left/right arrows** on photo edges for carousel navigation
- **Filmstrip** of all thumbnails along the bottom, current one highlighted in gold
- **Click-and-hold** on photo = CSS zoom (pointer-events, no server round-trip); release = normal

### New photo toast
- Bottom-right corner, slides in with small thumbnail + "Nová fotografie!"
- Tapping opens that photo in lightbox
- Auto-dismisses after 8 seconds
- Never interrupts an in-progress action in the lightbox

---

## Email — Two Directions

**Outbound (UI → guest):** Guest taps E-MAIL in lightbox, types address (physical keyboard), taps Odeslat. Photo sent as JPEG attachment via SMTP.

**Inbound (guest phone → gallery):** Guest emails a photo to `eliskatom2026@seznam.cz`. `inbox_poller.py` polls the IMAP inbox every 30 seconds, downloads image attachments (jpg/jpeg/png/heic/tiff accepted), saves to `photos/raw/`, marks email as read (SEEN flag). Watcher picks it up, converts to JPEG if needed, and it appears in the gallery automatically.

---

## Image Format Conversion

`watcher.py` registers `pillow-heif` on startup to enable HEIC support. Any file landing in `raw/` that is not JPEG is converted to JPEG before processing. Supported input formats: JPEG, PNG, HEIC/HEIF (iPhone), TIFF, WebP. The original raw file is preserved unchanged; the converted JPEG is what goes into `processed/`.

---

## Cross-Platform Printing

Canon Selphy CP1500 prints 10×15cm (4×6"). `watcher.py` preserves orientation:
- Landscape photo → cropped to 3:2 ratio
- Portrait photo → cropped to 2:3 ratio

`printer.py` scales the processed image to fill the Selphy's printable area for the detected orientation, with no white borders.

```python
import platform
if platform.system() == "Windows":
    # pywin32: win32print, win32ui, ImageWin
else:
    # subprocess: lp -d <printer_name> <filepath>
```

Printer name configured in `.env` as `PRINTER_NAME`.

---

## Configuration (.env)

```
PRINTER_NAME=Canon SELPHY CP1500
SMTP_SERVER=smtp.seznam.cz
SMTP_PORT=465
SMTP_USER=eliskatom2026@seznam.cz
SMTP_PASS=<app-password>
IMAP_SERVER=imap.seznam.cz
IMAP_USER=eliskatom2026@seznam.cz
IMAP_PASS=<app-password>
IMAP_POLL_INTERVAL=30
RAW_DIR=./photos/raw
PROCESSED_DIR=./photos/processed
PRINTED_DIR=./photos/printed
HIDDEN_DIR=./photos/hidden
```

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Camera disconnect | Watcher idles, resumes automatically when files appear |
| Partial file write | 1s debounce on `on_modified` before Pillow reads the file |
| Printer offline | Toast: "Tiskárna není dostupná. Zkuste znovu." |
| SMTP failure | Toast: "E-mail se nepodařilo odeslat." |
| IMAP poll failure | Silent log, retry on next interval |
| Duplicate inbound email | SEEN flag prevents re-download |
| Non-image attachment | Skipped silently |
| Corrupt photo | Caught by Pillow, file moved to `hidden/`, logged |

---

## Dependencies (requirements.txt)

```
Flask
Flask-SocketIO
eventlet
watchdog
Pillow
pillow-heif
pywin32; sys_platform == "win32"
python-dotenv
```

---

## Startup Scripts

- `run.bat` — Windows: activates venv, starts Flask server
- `run.sh` — Mac: activates venv, starts Flask server

Both create `photos/raw`, `processed`, `printed`, `hidden` directories on first run.
