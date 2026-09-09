import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path


def send_email(
    filepath: str,
    recipient: str,
    smtp_server: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
) -> None:
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg["Subject"] = "Vaše fotografie — Eliška & Tom 2026"

    body = MIMEText("Dobrý den,\n\nv příloze najdete Vaši fotografii ze svatby Elišky a Toma.\n\nDěkujeme za účast!", "plain", "utf-8")
    msg.attach(body)

    with open(filepath, "rb") as f:
        part = MIMEBase("image", "jpeg")
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=Path(filepath).name)
        msg.attach(part)

    with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
