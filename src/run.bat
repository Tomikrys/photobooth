@echo off
cd /d "%~dp0"

if not exist .env (
    echo .env not found — copying .env.example to .env
    echo Edit .env with your PRINTER_NAME, SMTP/IMAP credentials before running again.
    echo Run list-printers.bat to see available printer names.
    copy .env.example .env
    pause
    exit /b 1
)

if not exist venv (
    python -m venv venv
    venv\Scripts\pip install --upgrade pip
    venv\Scripts\pip install -r requirements.txt
)

if not exist photos\camera          mkdir photos\camera
if not exist photos\raw             mkdir photos\raw
if not exist photos\processed       mkdir photos\processed
if not exist photos\processed\thumbs mkdir photos\processed\thumbs
if not exist photos\printed         mkdir photos\printed
if not exist photos\hidden          mkdir photos\hidden

venv\Scripts\python app.py
pause
