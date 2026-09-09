# tests/test_config.py
import os, pytest
from unittest.mock import patch

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
