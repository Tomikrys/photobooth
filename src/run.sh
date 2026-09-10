#!/usr/bin/env bash
# macOS/Linux dev launcher — the Windows equivalent is Photobooth.exe (built from Build.bat).
set -e

# src/run.sh — anchor: this script sits inside src/, root is one level up.
cd "$(dirname "$0")"
SRC_DIR="$(pwd)"
cd ..
ROOT_DIR="$(pwd)"

if [ ! -f ".env" ]; then
  echo ".env not found at project root — copying src/.env.example to ./.env"
  echo "Edit .env with your PRINTER_NAME, SMTP/IMAP credentials, then re-run."
  cp "$SRC_DIR/.env.example" .env
  exit 1
fi

if [ ! -d "$SRC_DIR/venv" ]; then
  python3 -m venv "$SRC_DIR/venv"
  "$SRC_DIR/venv/bin/pip" install --upgrade pip
  "$SRC_DIR/venv/bin/pip" install -r "$SRC_DIR/requirements.txt"
fi

mkdir -p photos/camera photos/raw photos/processed photos/processed/thumbs photos/printed photos/hidden

# CWD stays at project root so ./photos/* resolves correctly.
"$SRC_DIR/venv/bin/python" "$SRC_DIR/app.py"
