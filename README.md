# Foto Koutek

A wedding photo-booth web app. Runs on a laptop connected to a Canon SELPHY dye-sub printer. Guests take photos (either via a camera that syncs a folder, or by emailing them to a mailbox), and a browser gallery on the same laptop shows them live, lets you reprint, resend by email, or delete.

**Stack:** Python 3.12 · Flask + Flask-SocketIO · watchdog · Pillow · vanilla JS + Tailwind (CDN)

---

## How it works

```
        ┌─── Camera drops photos ──┐
        │       (Wi-Fi folder      │
        │        sync / SD card    │
        │        watched dir)      │
        │                          │
        │      ┌─── Guests email ──┤
        │      │    attachments    │
        ▼      ▼                   │
  ┌───────────────────┐            │
  │  photos/camera/   │  ◄─ inbox_poller.py polls IMAP every 30s
  │  (ingest queue)   │
  └────────┬──────────┘
           │  watcher.py (watchdog + poll loop)
           │  1. copy original → photos/raw/  (backup archive)
           │  2. EXIF-orient + centre-crop 3:2 or 2:3
           │  3. save fullres to photos/processed/
           │  4. save 400px thumb to photos/processed/thumbs/
           │  5. delete from photos/camera/
           │  6. emit Socket.IO "new_photo" → browser toast + gallery
           ▼
  ┌───────────────────┐    ┌────────────────────────┐
  │  photos/processed │───►│  Browser gallery UI    │
  │       /thumbs     │    │  (localhost:5001)      │
  └───────────────────┘    │                        │
                           │  ▸ click → lightbox    │
                           │  ▸ TISKNOUT → lp/win32 │───► photos/printed/
                           │  ▸ E-MAIL   → SMTP     │
                           │  ▸ SMAZAT   → hide     │───► photos/hidden/
                           └────────────────────────┘
```

### Photo folders

| Folder | Purpose | Written by | Cleaned |
|---|---|---|---|
| `photos/camera/` | Ingest queue — files land here from camera or email | camera app / inbox poller | watcher deletes after processing |
| `photos/raw/` | Pristine backup archive of every original | watcher (copies before processing) | never touched |
| `photos/processed/` | Cropped 3:2/2:3 JPEGs shown in the gallery | watcher | on hide → `hidden/` |
| `photos/processed/thumbs/` | 400px thumbnails | watcher | on hide → deleted |
| `photos/printed/` | Copy of every photo sent to the printer | print API | never touched |
| `photos/hidden/` | Soft-deleted photos (guest hit SMAZAT) | hide API | never touched |

---

## Installation

### Windows (operator)

You should end up with a project folder that looks like this:

```
photobooth\
  Photobooth.bat   ← double-click to run
  .env             ← your credentials (created on first run)
  photos\          ← where your pictures live
  README.md
  src\             ← source; you don't need to open it
```

**One-time setup:**

1. Install **Python 3.12** from https://python.org — during install, check **"Add python.exe to PATH"**. (3.11 and 3.13 also work; avoid 3.14 — `pywin32` wheels don't exist for it yet.)
2. Install the **Canon SELPHY CP1500 driver** from Canon's site.
3. Copy the project folder onto the laptop (via git clone, USB stick, or however).

**Every time after that:** double-click **`Photobooth.bat`**. On first run it:

- Copies `src\.env.example` → `.env`.
- Creates the Python venv (`src\venv\`) and installs dependencies. Takes ~1 minute.
- Creates the `photos\` subfolders.
- Starts the Nikon camera importer and the Flask server.
- Opens `http://localhost:5001/config` — fill in your printer, camera, and email credentials there, then click **Uložit**.

Subsequent runs open the gallery directly at `http://localhost:5001`.

Subsequent runs skip setup and start everything in ~2 seconds. Close the console window (or Ctrl+C) to shut down cleanly.

### macOS (development)

```bash
git clone https://github.com/Tomikrys/photobooth.git
cd photobooth
cp src/.env.example .env      # then edit with real credentials — see below
./src/run.sh
```

There is no `.exe` on macOS — the Nikon-over-MTP importer is Windows-only anyway.

---

## Configuration (`.env`)

Everything is driven by `.env`. This file is git-ignored — never commit it.

```dotenv
# Printer — picked interactively on first run; edit to change
PRINTER_NAME=Canon SELPHY CP1500

# Wedding branding — shown in the UI and email subject
WEDDING_NAMES=Eliška & Tom
WEDDING_YEAR=2026
EMAIL_SUBJECT=Fotočka — Svatba Eliška & Tom 2026
EMAIL_BODY=Ahoj,\n\nvaše fotka z fotokoutku leží v příloze. :)\n\nDěkujeme!

# Outgoing mail (Seznam.cz)
SMTP_SERVER=smtp.seznam.cz
SMTP_PORT=465
SMTP_USER=eliskatom2026@seznam.cz
SMTP_PASS=<app-specific-password>

# Incoming mail — guests can email photos as attachments
IMAP_SERVER=imap.seznam.cz
IMAP_USER=eliskatom2026@seznam.cz
IMAP_PASS=<app-specific-password>
IMAP_POLL_INTERVAL=30

# Camera — picked interactively on first run; edit to change
CAMERA_NAME=D3100
CAMERA_FOLDER_PATTERN=100D3100

# Photo folder layout (relative to project root)
CAMERA_DIR=./photos/camera
RAW_DIR=./photos/raw
PROCESSED_DIR=./photos/processed
THUMBS_DIR=./photos/processed/thumbs
PRINTED_DIR=./photos/printed
HIDDEN_DIR=./photos/hidden
EMAIL_QUEUE_PATH=./photos/email_queue.json
```

### Seznam.cz app-specific passwords

Seznam's regular login password will **not** work over SMTP/IMAP. Generate an app-specific password in Seznam's account settings → *Nastavení účtu → Zabezpečení → Hesla pro aplikace* and paste that into `SMTP_PASS` / `IMAP_PASS`.

### Printer name

Two helper scripts print the list of installed printers so you can copy the exact name into `PRINTER_NAME`:

- **Windows**: double-click **`src\list-printers.bat`**.
- **macOS/Linux**: run **`./src/list-printers.sh`** from the project root.

Or do it by hand:

- **macOS**: `lpstat -p` — spaces become underscores automatically, e.g. `Canon_SELPHY_CP1500`.
- **Windows**: **Settings → Printers & scanners** → open the printer → the name at the top (usually just `Canon SELPHY CP1500`).

---

## Running

- **Windows**: double-click **`Photobooth.bat`** at the project root. It starts the Nikon MTP importer, the Flask server, and opens the browser automatically. Ctrl+C in the console (or closing it) stops everything.
- **macOS**: `./src/run.sh` from the project root. Starts the Flask server only (no Nikon importer on macOS).

The server listens on `0.0.0.0:5001`. Any device on the same Wi-Fi can view the gallery at `http://<laptop-ip>:5001`. On Windows, allow Python through the firewall when prompted on first run.

---

## Feeding photos in

Four ways for a photo to reach the gallery — all end up in `photos/camera/` and the watcher handles the rest.

### 1. Nikon over USB (MTP) — Windows only

Plug the Nikon into the laptop with a USB cable. The MTP importer polls the camera, moves new photos off the SD card into `photos/camera/`, and renames each to a millisecond-precision timestamp (`yyyyMMdd_HHmmss_fff.jpg`) so nothing can ever overwrite an existing photo. The camera model and DCIM folder pattern are set in `.env` (`CAMERA_NAME`, `CAMERA_FOLDER_PATTERN`) and auto-detected on first run. Files that arrive during a crashed run are recovered on next startup (`.mtp_temp/` sweep).

Expected latency: **3–4 seconds** shutter-to-gallery (hardware floor — the D3100 takes ~2s to flush the JPEG and expose it over MTP).

The importer is `src/NikonMove.ps1` — Photobooth.exe spawns it. Runs standalone too:

```powershell
powershell -ExecutionPolicy Bypass -File src\NikonMove.ps1
```

### 2. Camera with Wi-Fi folder sync

Configure your camera (or the Canon Camera Connect app / Sony Imaging Edge / etc.) to save photos into `photos/camera/` on the laptop. Any new JPEG/PNG/HEIC/TIFF/WebP appearing there is picked up within ~1 second.

### 3. Email attachments

Guests email photos to the address in `IMAP_USER`. Every 30 seconds `inbox_poller.py` fetches UNSEEN messages, saves any image attachment into `photos/camera/`, and marks the message SEEN.

### 4. Manual drop

Just drag any supported image file into `photos/camera/`. Supported: `.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`, `.tiff`, `.tif`, `.webp`.

Pre-existing files in `camera/` at startup are also processed (watchdog only fires on *new* events, so we sweep on start).

---

## Using the UI

- **Gallery** — grid of thumbnails, newest first. Click any tile for the lightbox.
- **Lightbox**
  - **← / → keys** or on-screen buttons to navigate; **Esc** closes.
  - **Click-and-hold** a photo to zoom 2.5×; move the mouse to pan.
  - **POČET KOPIÍ** stepper — set number of prints.
  - **🖨 TISKNOUT** — sends N copies to the printer, writes a copy into `photos/printed/`.
  - **✉ E-MAIL** — opens a modal. Enter one or more comma-separated addresses (`jan@example.cz, marie@example.cz`) → busy spinner during send → auto-close on success. **Offline?** If the venue Wi-Fi has no internet, the email is queued to `photos/email_queue.json` and retried every 60 s in the background until it lands — the modal shows "⏳ Bez internetu — odešle se po připojení". The queue survives restarts.
  - **🗑 SMAZAT** — soft delete; moves full-res into `photos/hidden/` and deletes the thumb. The lightbox stays open and navigates to the next-newer photo.
- **Toast** — bottom-right notification when a new photo arrives; click to jump to it in the lightbox.

---

## Development

### Tests

```bash
cd src
source venv/bin/activate
pytest -q
```

18 tests cover: config loading, watcher (crop math, thumbs, hidden-on-corrupt, raw backup), mailer (SMTP mock, multi-recipient), inbox poller (attachment save, non-image skip), print (subprocess mock), Flask routes, and the offline email queue (persistence, restart reload, retry-on-reconnect).

### Project layout

```
photobooth/
├── Photobooth.exe          # built launcher — the ONE file the operator runs
├── Build.bat               # first-time build (calls src/Build.ps1)
├── .env                    # (git-ignored) real credentials, at root
├── photos/                 # all photo folders (ingest, raw, processed, ...)
├── README.md
└── src/                    # everything the operator doesn't need to see
    ├── Photobooth.ps1      # launcher source (run via Photobooth.bat)
    ├── NikonMove.ps1       # Nikon MTP importer (spawned by launcher)
    ├── app.py              # Flask + Socket.IO routes
    ├── config.py           # loads .env, exports constants
    ├── watcher.py          # watchdog observer + process_image
    ├── inbox_poller.py     # IMAP polling loop
    ├── mailer.py           # send_email with multi-recipient split
    ├── printer.py          # subprocess `lp` on macOS/Linux, win32print on Windows
    ├── email_queue.py      # offline email queue
    ├── static/             # single-page UI (index.html, app.js)
    ├── tests/              # pytest suite
    ├── run.sh              # macOS/Linux dev launcher
    ├── list-printers.bat   # Windows: print list of installed printers
    ├── list-printers.sh    # macOS/Linux: same, via CUPS
    ├── conftest.py
    ├── requirements.txt
    ├── .env.example
    └── venv/               # (git-ignored) Python virtual environment
```

**Path convention:** the launcher always sets CWD to the project root before spawning `app.py` / `NikonMove.ps1`, so every relative path in the code (`./photos/camera`, `./.env`, `./photos/email_queue.json`) resolves at the root — even though the Python and PowerShell source lives one level down in `src/`.

### Adding a feature

1. Write the test first (`tests/test_*.py`), see it fail.
2. Implement the smallest change that makes it pass.
3. Re-run `pytest -q` — must stay 18+/18+ green.
4. Commit with a descriptive message.

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| **Print fails: `lp: No such file or directory`** | Printer isn't installed in the OS. Verify with `lpstat -p` (Mac) or `Get-Printer` (Win). Fix `PRINTER_NAME` to match exactly. |
| **Print fails: `client-error-not-possible`** | Wrong paper type or printer offline. Check the SELPHY has a paper cartridge and dye ribbon and is powered on. |
| **Email fails: `Authentication failed`** | You're using the regular Seznam password. Generate an app-specific password (see [Configuration](#seznamcz-app-specific-passwords)). |
| **No new photos appear** | Check `photos/camera/` — files should vanish within a few seconds. If they stay: check the log for `Failed to process`. Corrupt files go to `photos/hidden/`. |
| **NIKON: "resource in use" / retrying** | Normal — the D3100 locks the file while writing to SD. The importer retries up to 10× with 2s gaps; it resolves itself. |
| **NIKON: camera not detected** | USB disconnected or MTP not selected on the camera body. Unplug and re-plug, or go to *Camera menu → USB → MTP*. |
| **Gallery doesn't show new photo** | Socket.IO event was missed (race at startup). The gallery auto-polls every 10s — photo will appear within 10s. |
| **App can't find `pywin32` on Windows** | Only installs from `requirements.txt` when `sys_platform == "win32"`. Make sure you're on Python 3.11 or 3.12 x64; pywin32 wheels for 3.14 may not exist yet. |

Logs go to stdout in the console window `Photobooth.exe` opens; keep it visible during the wedding so you can read errors. Close the window (or Ctrl+C) to stop everything.

---

## Security notes

- `.env` contains real SMTP/IMAP credentials — never commit it. `.gitignore` already excludes it.
- The Flask server is bound to `0.0.0.0` — anyone on the venue Wi-Fi can view the gallery. That's usually desired at a wedding but be aware.
- No authentication on the print/email/delete APIs. If you don't trust your Wi-Fi network, put a `<username>:<password>@` layer in front with e.g. `nginx` or restrict access with a firewall rule.

---

## License

Personal project — no formal license. Use it, fork it, adapt it for your own wedding. 🥂
