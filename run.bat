@echo off
cd /d "%~dp0"

if not exist venv (
    python -m venv venv
    venv\Scripts\pip install -r requirements.txt
)

if not exist photos\raw       mkdir photos\raw
if not exist photos\processed mkdir photos\processed
if not exist photos\printed   mkdir photos\printed
if not exist photos\hidden    mkdir photos\hidden

venv\Scripts\python app.py
