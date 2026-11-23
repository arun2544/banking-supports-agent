"""PII redaction service: runs BEFORE any text reaches the LLM or the logs."""
import re

_PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("CVV", re.compile(r"(?i)\bcvv\s*[:=]?\s*\d{3,4}\b")),
]
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_AADHAAR = re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+91[ -]?)?[6-9]\d{9}(?!\d)")


def _luhn(num: str) -> bool:
    total, alt = 0, False
    for ch in reversed(num):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def redact(text: str) -> tuple[str, list[str]]:
    """Return (redacted_text, list_of_pii_types_found)."""
    found: list[str] = []

    def card_sub(m):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append("CREDIT_CARD")
            return "[CREDIT_CARD]"
        return m.group()

    text = _CARD.sub(card_sub, text)
    for label, pat in _PATTERNS:
        text, n = pat.subn(f"[{label}]", text)
        found += [label] * n
    text, n = _AADHAAR.subn("[AADHAAR]", text)
    found += ["AADHAAR"] * n
    text, n = _PHONE.subn("[PHONE]", text)
    found += ["PHONE"] * n
    return text, found
