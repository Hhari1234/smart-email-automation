"""
template_engine.py
Simple {{placeholder}} substitution engine for subject/body/signature.
"""
import re

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)(?:\|([^}]+))?\s*\}\}")


def render(template: str, context: dict) -> str:
    """Replaces {{key}} tokens with context values. Unknown keys become ''.
    Supports {{key|fallback}} syntax."""
    if not template:
        return ""

    def _sub(match):
        key = match.group(1)
        fallback = match.group(2)
        value = context.get(key)
        if value is None or value == "":
            return fallback.strip() if fallback else ""
        return str(value)

    return PLACEHOLDER_RE.sub(_sub, template)


def extract_placeholders(template: str) -> set:
    return {m[0] for m in PLACEHOLDER_RE.findall(template or "") if m[0]}


def text_to_html(text: str) -> str:
    """Converts plain-text template (with \\n) into basic HTML paragraphs."""
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return escaped.replace("\n", "<br>")
