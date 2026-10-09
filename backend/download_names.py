"""File names for downloads that carry a person's name ("Zoë_Müller_Resume.docx").

HTTP header values must be plain ASCII. A name with an accent or any non-English letter put straight into the
Content-Disposition header made the server answer 500 instead of the file (found in the 2026-10 audit with "Zoë Müller",
"Nguyễn Văn An" and "李明"). This builds the header the standard way (RFC 6266 / 5987): a plain-ASCII filename for old
programs plus a filename* with the full name, percent-encoded. It also removes anything that could break out of the
header (quotes, line breaks, slashes, semicolons). Only the name's letters and digits survive.
"""
import re
import unicodedata
from urllib.parse import quote

MAX_NAME_CHARS = 80


def _clean_unicode(raw) -> str:
    text = unicodedata.normalize("NFC", str(raw or ""))
    kept = []
    for ch in text:
        category = unicodedata.category(ch)
        if ch == " " or ch in "-._":
            kept.append("_" if ch == " " else ch)
        elif category[0] in ("L", "N", "M"):  # letters, digits, accent marks (any language)
            kept.append(ch)
    cleaned = re.sub(r"_+", "_", "".join(kept)).strip("._-")
    return cleaned[:MAX_NAME_CHARS]


def _ascii_only(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in decomposed if ord(ch) < 128 and (ch.isalnum() or ch in "-._"))
    return re.sub(r"_+", "_", ascii_text).strip("._-")


def attachment_headers(person_name, suffix: str, fallback: str = "Resume") -> dict:
    """{"Content-Disposition": ...} for a download named after `person_name` plus `suffix` (e.g. "_Resume.docx")."""
    name = _clean_unicode(person_name) or fallback
    full = name + suffix
    ascii_name = (_ascii_only(name) or fallback) + suffix
    value = f'attachment; filename="{ascii_name}"'
    if full != ascii_name:
        value += f"; filename*=UTF-8''{quote(full, safe='')}"
    return {"Content-Disposition": value}
