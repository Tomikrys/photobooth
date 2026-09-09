import os
from dotenv import load_dotenv

load_dotenv()

PRINTER_NAME = os.environ["PRINTER_NAME"]
SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
IMAP_SERVER = os.environ["IMAP_SERVER"]
IMAP_USER = os.environ["IMAP_USER"]
IMAP_PASS = os.environ["IMAP_PASS"]
IMAP_POLL_INTERVAL = int(os.environ.get("IMAP_POLL_INTERVAL", "30"))
RAW_DIR = os.environ.get("RAW_DIR", "./photos/raw")
PROCESSED_DIR = os.environ.get("PROCESSED_DIR", "./photos/processed")
THUMBS_DIR = os.environ.get("THUMBS_DIR", "./photos/processed/thumbs")
PRINTED_DIR = os.environ.get("PRINTED_DIR", "./photos/printed")
HIDDEN_DIR = os.environ.get("HIDDEN_DIR", "./photos/hidden")
