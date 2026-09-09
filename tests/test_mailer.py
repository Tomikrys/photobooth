from unittest.mock import patch, MagicMock

def test_send_email_calls_smtp(tmp_path):
    jpeg = tmp_path / "photo.jpg"
    from PIL import Image
    Image.new("RGB", (600, 400)).save(str(jpeg), "JPEG")

    with patch("mailer.smtplib.SMTP_SSL") as mock_ssl:
        mock_server = MagicMock()
        mock_ssl.return_value.__enter__ = lambda s: mock_server
        mock_ssl.return_value.__exit__ = MagicMock(return_value=False)

        from mailer import send_email
        send_email(
            filepath=str(jpeg),
            recipient="guest@example.com",
            smtp_server="smtp.seznam.cz",
            smtp_port=465,
            smtp_user="bot@seznam.cz",
            smtp_pass="secret",
        )
        mock_server.login.assert_called_once_with("bot@seznam.cz", "secret")
        mock_server.send_message.assert_called_once()
        msg = mock_server.send_message.call_args[0][0]
        assert msg["To"] == "guest@example.com"
        assert any(p.get_content_type() == "image/jpeg" for p in msg.get_payload())
