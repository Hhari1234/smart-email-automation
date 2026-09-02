"""
recipient_parser.py
Smart bulk recipient parser supporting newline, comma, semicolon, and
mixed formats including "Name <email@example.com>".
"""
import re
from typing import Optional

EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)


def parse_recipients(raw_text: str) -> dict:
    """
    Parse raw pasted text into structured recipient data.

    Returns:
        {
            "valid": [ { "email": "...", "name": "..." } ],
            "invalid": [ "raw text" ],
            "duplicates": [ "email" ],
        }
    """
    if not raw_text or not raw_text.strip():
        return {"valid": [], "invalid": [], "duplicates": []}

    candidates = _split_candidates(raw_text)
    seen: dict[str, str] = {}
    valid: list[dict] = []
    invalid: list[str] = []
    duplicates: list[str] = []

    for raw in candidates:
        raw = raw.strip()
        if not raw:
            continue

        email, name = _extract_email_and_name(raw)
        if not email:
            invalid.append(raw)
            continue

        email_lower = email.lower()
        if email_lower in seen:
            duplicates.append(email_lower)
            continue

        seen[email_lower] = email_lower
        valid.append({"email": email_lower, "name": name or "", "hr_name": name or "", "company": "", "job_role": "", "location": ""})

    return {"valid": valid, "invalid": invalid, "duplicates": duplicates}


def _split_candidates(text: str) -> list[str]:
    """
    Split raw text into candidate tokens.
    Supports:
    - newline separated
    - comma separated
    - semicolon separated
    - mixed
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    tokens: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Split by comma or semicolon within the line
        parts = re.split(r"[,;]", line)
        for part in parts:
            part = part.strip()
            if part:
                tokens.append(part)
    return tokens


def _extract_email_and_name(raw: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract email and optional name from a raw string.
    Supports:
    - email@example.com
    - Name <email@example.com>
    """
    raw = raw.strip()
    if not raw:
        return None, None

    # Match "Name <email@example.com>"
    m = re.match(r"^(.*?)\s*<([^>]+@[^>]+)>\s*$", raw, re.DOTALL)
    if m:
        name = m.group(1).strip()
        email = m.group(2).strip()
        if EMAIL_REGEX.search(email):
            return email, name

    # Match bare email
    m = EMAIL_REGEX.search(raw)
    if m:
        return m.group(0), ""

    return None, None
