"""
validators.py
Email address validation utilities.
"""
import re

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def is_valid_email(email: str) -> bool:
    """Basic syntax validation. Returns False for None/empty/malformed."""
    if not email or not isinstance(email, str):
        return False
    email = email.strip()
    if len(email) > 254:
        return False
    return bool(EMAIL_REGEX.match(email))


def clean_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_recipient_row(row: dict) -> tuple[bool, str]:
    """Validates a recipient dict has a usable email + name at minimum."""
    email = clean_email(row.get("email", ""))
    if not is_valid_email(email):
        return False, f"Invalid email address: '{row.get('email', '')}'"
    if not row.get("hr_name", "").strip():
        return False, "Missing HR name"
    return True, ""
