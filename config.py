"""
config.py
Handles environment variables (.env) and persisted user settings (settings.json).
"""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"


def _is_vercel() -> bool:
    return os.environ.get("VERCEL") == "1"


if _is_vercel():
    SETTINGS_PATH = Path(os.environ.get("TMPDIR", "/tmp")) / "settings.json"
else:
    data_dir = os.environ.get("RESUMEMAILER_DATA_DIR")
    if data_dir:
        SETTINGS_PATH = Path(data_dir) / "settings.json"
    else:
        SETTINGS_PATH = BASE_DIR / "settings.json"

load_dotenv(ENV_PATH)

DEFAULT_SETTINGS = {
    "sender_name": "Your Name",
    "sender_email": "",
    "use_gmail_api": True,
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "delay_min_seconds": 5,
    "delay_max_seconds": 15,
    "max_retries": 3,
    "resume_path": "",
    "extra_attachments": [],
    "template_path": str(BASE_DIR / "sample_data" / "email_template.txt"),
    "subject": "Application for {{job_role}} at {{company}}",
    "signature": (
        "<br><br>Best regards,<br>"
        "<b>{{your_name}}</b><br>{{your_phone}} | {{your_email}}<br>"
        "{{your_linkedin}}"
    ),
    "recipients_path": "",
    "last_column_map": {},
}


class Settings:
    """Loads/saves persistent GUI + sending configuration."""

    def __init__(self):
        self.data = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self):
        if SETTINGS_PATH.exists():
            try:
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self.data.update(saved)
            except Exception:
                pass

    def save(self):
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()


def get_env(key, default=""):
    return os.environ.get(key, default)


# Credentials pulled from .env (used by mailer.py)
SMTP_EMAIL = get_env("SMTP_EMAIL")
SMTP_APP_PASSWORD = get_env("SMTP_APP_PASSWORD")
GMAIL_CREDENTIALS_FILE = get_env("GMAIL_CREDENTIALS_FILE", str(BASE_DIR / "credentials" / "credentials.json"))
if _is_vercel():
    _DEFAULT_TOKEN = str(Path(os.environ.get("TMPDIR", "/tmp")) / "token.json")
else:
    _DEFAULT_TOKEN = str(BASE_DIR / "credentials" / "token.json")
GMAIL_TOKEN_FILE = get_env("GMAIL_TOKEN_FILE", _DEFAULT_TOKEN)
