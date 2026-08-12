"""
template_engine.py
Simple {{placeholder}} substitution engine for subject/body/signature.
"""
import re

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def render(template: str, context: dict) -> str:
    """Replaces {{key}} tokens with context values. Unknown keys become ''."""
    if not template:
        return ""

    def _sub(match):
        key = match.group(1)
        return str(context.get(key, ""))

    return PLACEHOLDER_RE.sub(_sub, template)


def extract_placeholders(template: str) -> set:
    return set(PLACEHOLDER_RE.findall(template or ""))


def text_to_html(text: str) -> str:
    """Converts plain-text template (with \\n) into basic HTML paragraphs."""
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return escaped.replace("\n", "<br>")
