#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -f ".env" ]; then
  echo ".env not found — copying .env.example to .env"
  echo "Edit .env with your PRINTER_NAME, SMTP/IMAP credentials before running again."
  echo "Run ./list-printers.sh to see available printer names."
  cp .env.example .env
  exit 1
fi

if [ ! -d "venv" ]; then
  python3 -m venv venv
  venv/bin/pip install --upgrade pip
  venv/bin/pip install -r requirements.txt
fi

mkdir -p photos/camera photos/raw photos/processed photos/processed/thumbs photos/printed photos/hidden

venv/bin/python app.py
