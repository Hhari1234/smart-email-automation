"""
mailer.py
Handles the actual delivery of a single email via:
  1. Gmail API (OAuth2) - preferred, higher limits, no app-password needed
  2. SMTP + app password - automatic fallback if Gmail API is unavailable/misconfigured

Both paths build a standard MIME message so attachments/HTML body work identically.
"""
import base64
import smtplib
import ssl
import mimetypes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

import config

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


class SendError(Exception):
    pass


def _build_mime_message(sender, to_addr, subject, html_body, attachments):
    msg = MIMEMultipart("mixed")
    msg["From"] = sender
    msg["To"] = to_addr
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    for path in attachments or []:
        path = Path(path)
        if not path.exists():
            continue
        ctype, encoding = mimetypes.guess_type(str(path))
        if ctype is None or encoding is not None:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        with open(path, "rb") as f:
            part = MIMEBase(maintype, subtype)
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=path.name)
        msg.attach(part)

    return msg


class GmailAPISender:
    """Sends via Gmail API using OAuth2 (credentials.json + cached token.json)."""

    def __init__(self):
        self.service = None
        self._authenticate()

    def _authenticate(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as e:
            raise SendError(
                "Gmail API libraries not installed. Run: pip install -r requirements.txt"
            ) from e

        creds = None
        token_path = Path(config.GMAIL_TOKEN_FILE)
        creds_path = Path(config.GMAIL_CREDENTIALS_FILE)

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not creds_path.exists():
                    raise SendError(
                        f"Gmail API credentials.json not found at {creds_path}. "
                        "Download it from Google Cloud Console (OAuth Client ID, Desktop App) "
                        "or use SMTP fallback instead."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), GMAIL_SCOPES)
                creds = flow.run_local_server(port=0)
            try:
                token_path.parent.mkdir(parents=True, exist_ok=True)
                token_path.write_text(creds.to_json())
            except OSError:
                pass

        self.service = build("gmail", "v1", credentials=creds)

    def send(self, sender, to_addr, subject, html_body, attachments):
        msg = _build_mime_message(sender, to_addr, subject, html_body, attachments)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        try:
            self.service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
        except Exception as e:
            raise SendError(str(e)) from e


class SMTPSender:
    """Sends via SMTP with an app password (works for Gmail and most providers)."""

    def __init__(self, host, port, email_addr, app_password):
        self.host = host
        self.port = port
        self.email_addr = email_addr
        self.app_password = app_password
        if not self.email_addr or not self.app_password:
            raise SendError(
                "SMTP_EMAIL / SMTP_APP_PASSWORD not set in .env. "
                "Create a Gmail App Password and add it to your .env file."
            )

    def send(self, sender, to_addr, subject, html_body, attachments):
        msg = _build_mime_message(sender, to_addr, subject, html_body, attachments)
        context = ssl.create_default_context()
        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.starttls(context=context)
                server.login(self.email_addr, self.app_password)
                server.sendmail(sender, [to_addr], msg.as_string())
        except smtplib.SMTPException as e:
            raise SendError(str(e)) from e


class EmailSender:
    """
    Facade used by the GUI. Tries Gmail API first (if enabled + configured),
    automatically falls back to SMTP on any setup failure.
    """

    def __init__(self, settings):
        self.settings = settings
        self.sender_email = settings.get("sender_email") or config.SMTP_EMAIL
        self.backend = None
        self.backend_name = None
        self._init_backend()

    def _init_backend(self):
        prefer_gmail_api = self.settings.get("use_gmail_api", True)
        if prefer_gmail_api:
            try:
                self.backend = GmailAPISender()
                self.backend_name = "Gmail API"
                return
            except SendError:
                pass  # fall through to SMTP
        self.backend = SMTPSender(
            self.settings.get("smtp_host", "smtp.gmail.com"),
            int(self.settings.get("smtp_port", 587)),
            config.SMTP_EMAIL,
            config.SMTP_APP_PASSWORD,
        )
        self.backend_name = "SMTP"

    def send(self, to_addr, subject, html_body, attachments):
        self.backend.send(self.sender_email, to_addr, subject, html_body, attachments)
