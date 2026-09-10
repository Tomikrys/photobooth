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
    with patch.dict(os.environ, env):
        import importlib, config
        importlib.reload(config)
        assert config.PRINTER_NAME == "Canon SELPHY CP1500"
        assert config.SMTP_PORT == 465
        assert config.IMAP_POLL_INTERVAL == 30
        assert config.RAW_DIR == "./photos/raw"

def test_missing_required_key_raises():
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
    # PRINTER_NAME is absent; patch load_dotenv to prevent .env file from supplying it
    with patch("dotenv.load_dotenv", MagicMock()), \
         patch.dict(os.environ, env, clear=True):
        sys.modules.pop("config", None)
        with pytest.raises(KeyError):
            import importlib
            importlib.import_module("config")
