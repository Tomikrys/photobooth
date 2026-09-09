import pytest
from unittest.mock import patch, MagicMock, call
import email
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

def _make_email_with_jpeg(filename="photo.jpg"):
    msg = MIMEMultipart()
    msg["From"] = "guest@example.com"
    msg["Subject"] = "photo"
    part = MIMEBase("image", "jpeg")
    part.set_payload(b"\xff\xd8\xff" + b"\x00" * 100)  # fake JPEG bytes
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(part)
    return msg.as_bytes()

def test_poll_downloads_jpeg_attachment(tmp_path):
    raw_dir = str(tmp_path / "raw")
    import os; os.makedirs(raw_dir)

    mock_imap = MagicMock()
    mock_imap.search.return_value = ("OK", [b"1"])
    mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {100})", _make_email_with_jpeg())])
    mock_imap.store.return_value = ("OK", [])

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        from inbox_poller import poll_once
        poll_once(
            imap_server="imap.seznam.cz",
            imap_user="a@b.cz",
            imap_pass="secret",
            raw_dir=raw_dir,
        )

    files = list(tmp_path.glob("raw/*"))
    assert len(files) == 1
    assert files[0].suffix.lower() in {".jpg", ".jpeg"}
    mock_imap.store.assert_called_once_with(b"1", "+FLAGS", "\\Seen")

def test_poll_skips_non_image_attachment(tmp_path):
    raw_dir = str(tmp_path / "raw")
    import os; os.makedirs(raw_dir)

    msg = MIMEMultipart()
    part = MIMEBase("application", "pdf")
    part.set_payload(b"%PDF")
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="doc.pdf")
    msg.attach(part)

    mock_imap = MagicMock()
    mock_imap.search.return_value = ("OK", [b"2"])
    mock_imap.fetch.return_value = ("OK", [(b"2 (RFC822 {100})", msg.as_bytes())])
    mock_imap.store.return_value = ("OK", [])

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        from inbox_poller import poll_once
        poll_once("imap.seznam.cz", "a@b.cz", "secret", raw_dir)

    assert list((tmp_path / "raw").iterdir()) == []
    mock_imap.store.assert_called_once()  # still marked SEEN
