# tests/test_config.py
import os, sys, pytest
from unittest.mock import patch, MagicMock

def test_config_loads_all_keys():
    env = {
        "PRINTER_NAME": "Canon SELPHY CP1500",
        "SMTP_SERVER": "smtp.seznam.cz",
        "SMTP_PORT": "465",
        "SMTP_USER": "a@b.cz",
        "SMTP_PASS": "secret",
        "IMAP_SERVER": "imap.seznam.cz",
        "IMAP_USER": "a@b.cz",
        "IMAP_PASS": "secret",
        "IMAP_POLL_INTERVAL": "30",
        "RAW_DIR": "./photos/raw",
        "PROCESSED_DIR": "./photos/processed",
        "PRINTED_DIR": "./photos/printed",
        "HIDDEN_DIR": "./photos/hidden",
    }
    with patch("dotenv.load_dotenv", MagicMock()), \
         patch.dict(os.environ, env, clear=True):
        import importlib, config
        importlib.reload(config)
        assert config.PRINTER_NAME == "Canon SELPHY CP1500"
        assert config.SMTP_PORT == 465
        assert config.IMAP_POLL_INTERVAL == 30
        assert os.path.isabs(config.RAW_DIR)
        assert config.RAW_DIR.replace(os.sep, "/").endswith("/photos/raw")

def test_missing_required_key_returns_empty_string():
    """Keys are now optional (use .get()) — missing key gives empty string, no crash."""
    env = {
        "SMTP_SERVER": "s", "SMTP_PORT": "465",
        "SMTP_USER": "u", "SMTP_PASS": "p",
        "IMAP_SERVER": "s", "IMAP_USER": "u", "IMAP_PASS": "p",
        "IMAP_POLL_INTERVAL": "30",
        "RAW_DIR": "./photos/raw",
        "PROCESSED_DIR": "./photos/processed",
        "PRINTED_DIR": "./photos/printed",
        "HIDDEN_DIR": "./photos/hidden",
    }
    with patch("dotenv.load_dotenv", MagicMock()), \
         patch.dict(os.environ, env, clear=True):
        sys.modules.pop("config", None)
        import importlib
        cfg = importlib.import_module("config")
        # PRINTER_NAME not in env, should be empty string
        assert cfg.PRINTER_NAME == ""
