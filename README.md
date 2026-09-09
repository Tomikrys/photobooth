# Foto Koutek — Eliška & Tom 2026

A wedding photo-booth web app. Runs on a laptop connected to a Canon SELPHY dye-sub printer. Guests take photos (either via a camera that syncs a folder, or by emailing them to a mailbox), and a browser gallery on the same laptop shows them live, lets you reprint, resend by email, or delete.

**Stack:** Python 3.11+ · Flask + Flask-SocketIO · watchdog · Pillow · vanilla JS + Tailwind (CDN)

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

### macOS

```bash
git clone https://github.com/Tomikrys/photobooth.git
cd photobooth
cp .env.example .env      # then edit with real credentials — see below
./run.sh
```

### Windows

1. Install **Python 3.11 or 3.12** from https://python.org — during install, check **"Add python.exe to PATH"**. (Avoid 3.14 on Windows for now; `pywin32` wheels lag.)
2. Install **Git for Windows** — https://git-scm.com/download/win
3. Install the **Canon SELPHY CP1500 driver** from Canon's site. After install, open **Settings → Printers & scanners** and note the *exact* printer name — you'll need it in `.env`.
4. Clone and configure:
   ```powershell
   git clone https://github.com/Tomikrys/photobooth.git C:\photobooth
   cd C:\photobooth
   copy .env.example .env
   notepad .env
   ```
5. Double-click **`run.bat`**. On first run it creates the venv, installs dependencies, creates photo folders, and starts the server. Subsequent runs skip the install step.

Open http://localhost:5001 in a browser.

---

## Configuration (`.env`)

Everything is driven by `.env`. This file is git-ignored — never commit it.

```dotenv
# Printer — the name CUPS (macOS) or Windows shows for the SELPHY
PRINTER_NAME=Canon SELPHY CP1500

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

# Photo folder layout (relative to project root)
CAMERA_DIR=./photos/camera
RAW_DIR=./photos/raw
PROCESSED_DIR=./photos/processed
THUMBS_DIR=./photos/processed/thumbs
PRINTED_DIR=./photos/printed
HIDDEN_DIR=./photos/hidden
```

### Seznam.cz app-specific passwords

Seznam's regular login password will **not** work over SMTP/IMAP. Generate an app-specific password in Seznam's account settings → *Nastavení účtu → Zabezpečení → Hesla pro aplikace* and paste that into `SMTP_PASS` / `IMAP_PASS`.

### Printer name

- **macOS**: run `lpstat -p` and copy the exact name (spaces become underscores automatically, e.g. `Canon_SELPHY_CP1500`).
- **Windows**: **Settings → Printers & scanners** → open the printer → the name at the top is what you want (usually just `Canon SELPHY CP1500`).

---

## Running

- **Mac**: `./run.sh`
- **Windows**: double-click `run.bat`

The server listens on `0.0.0.0:5001`. Override with `PORT=8080 ./run.sh` on Mac or set `PORT` in `.env` on Windows.

Any device on the same Wi-Fi can view the gallery at `http://<laptop-ip>:5001`. On Windows, allow Python through the firewall when prompted on first run.

---

## Feeding photos in

Three ways for a photo to reach the gallery — all end up in `photos/camera/` and the watcher handles the rest.

### 1. Camera with Wi-Fi folder sync

Configure your camera (or the Canon Camera Connect app / Sony Imaging Edge / etc.) to save photos into `photos/camera/` on the laptop. Any new JPEG/PNG/HEIC/TIFF/WebP appearing there is picked up within ~1 second.

### 2. Email attachments

Guests email photos to the address in `IMAP_USER`. Every 30 seconds `inbox_poller.py` fetches UNSEEN messages, saves any image attachment into `photos/camera/`, and marks the message SEEN.

### 3. Manual drop

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
  - **✉ E-MAIL** — opens a modal. Enter one or more comma-separated addresses (`jan@example.cz, marie@example.cz`) → busy spinner during send → auto-close on success.
  - **🗑 SMAZAT** — soft delete; moves full-res into `photos/hidden/` and deletes the thumb. The lightbox stays open and navigates to the next-newer photo.
- **Toast** — bottom-right notification when a new photo arrives; click to jump to it in the lightbox.

---

## Development

### Tests

```bash
source venv/bin/activate
pytest -q
```

18 tests cover: config loading, watcher (crop math, thumbs, hidden-on-corrupt, raw backup), mailer (SMTP mock, multi-recipient), inbox poller (attachment save, non-image skip), print (subprocess mock), and the Flask routes.

### Project layout

```
photobooth/
├── app.py              # Flask + Socket.IO routes, wires everything together
├── config.py           # loads .env, exports constants
├── watcher.py          # watchdog observer + process_image (crop, thumb, backup)
├── inbox_poller.py     # IMAP polling loop
├── mailer.py           # send_email with multi-recipient split
├── printer.py          # subprocess `lp` on macOS/Linux, win32print on Windows
├── static/
│   ├── index.html      # single-page UI
│   └── app.js          # gallery, lightbox, socket handlers, email modal
├── tests/              # pytest suite (18 tests)
├── run.sh              # macOS/Linux launcher
├── run.bat             # Windows launcher
├── requirements.txt
└── .env                # (git-ignored) real credentials
```

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
| **No new photos appear** | Check `photos/camera/` — files should vanish within 1–2 seconds. If they stay: check the log for `Failed to process`. Corrupt files go to `photos/hidden/`. |
| **Two pre-existing PNGs weren't picked up** | Fixed — `PhotoWatcher.start()` now sweeps existing files. Restart the server. |
| **Gallery doesn't update in real time** | Socket.IO connection dropped. Check browser console; the CDN URL for socket.io must be reachable (needs internet). If offline, self-host socket.io. |
| **Broken-image icon in error toast** | Fixed — `showToastMsg` now hides the thumbnail slot instead of setting empty `src`. |
| **App can't find `pywin32` on Windows** | Only installs from `requirements.txt` when `sys_platform == "win32"`. Make sure you're on Python 3.11 or 3.12 x64; pywin32 wheels for 3.14 may not exist yet. |

Logs go to stdout; Windows users, keep the `run.bat` console window open to read errors (there's a `pause` at the end so it won't vanish).

---

## Security notes

- `.env` contains real SMTP/IMAP credentials — never commit it. `.gitignore` already excludes it.
- The Flask server is bound to `0.0.0.0` — anyone on the venue Wi-Fi can view the gallery. That's usually desired at a wedding but be aware.
- No authentication on the print/email/delete APIs. If you don't trust your Wi-Fi network, put a `<username>:<password>@` layer in front with e.g. `nginx` or restrict access with a firewall rule.

---

## License

Personal project — no formal license. Use it, fork it, adapt it for your own wedding. 🥂
