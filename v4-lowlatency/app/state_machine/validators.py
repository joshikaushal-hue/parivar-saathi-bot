"""
Deterministic speech parsers for Hindi + English inputs.
No LLM. Handles Devanagari digits + basic number words + common phrasing.
"""
import re
from typing import Optional, Dict, Any


# Devanagari → ASCII digits
_DEV_DIGITS = {
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
}

# Hindi number words
_HINDI_WORDS = {
    "शून्य": 0, "एक": 1, "दो": 2, "तीन": 3, "चार": 4,
    "पाँच": 5, "पांच": 5, "छह": 6, "छः": 6, "सात": 7,
    "आठ": 8, "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12,
    "तेरह": 13, "चौदह": 14, "पंद्रह": 15, "सोलह": 16,
    "सत्रह": 17, "अठारह": 18, "उन्नीस": 19, "बीस": 20,
    "पच्चीस": 25, "तीस": 30, "पैंतीस": 35, "चालीस": 40,
    "पैंतालीस": 45, "पचास": 50, "पचपन": 55, "साठ": 60,
}

# English number words (limited — STT usually returns digits)
_EN_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60,
}


def _translate_devanagari_digits(text: str) -> str:
    return "".join(_DEV_DIGITS.get(ch, ch) for ch in text)


def _word_to_number(text: str) -> Optional[int]:
    """Parse a single word or a compound like 'thirty two' / 'तीस दो'."""
    t = text.lower().strip()
    if t in _EN_WORDS:
        return _EN_WORDS[t]
    if t in _HINDI_WORDS:
        return _HINDI_WORDS[t]
    parts = re.split(r"[\s-]+", t)
    total, matched = 0, False
    for p in parts:
        if p in _EN_WORDS:
            total += _EN_WORDS[p]
            matched = True
        elif p in _HINDI_WORDS:
            total += _HINDI_WORDS[p]
            matched = True
    return total if matched else None


# ────────────────────────────────────────────────────────────────
# AGE
# ────────────────────────────────────────────────────────────────

def parse_age(text: str) -> Optional[int]:
    """Returns an age between 18–60 or None."""
    if not text:
        return None
    t = _translate_devanagari_digits(text.lower())

    # Prefer a clean 2-digit number
    for m in re.finditer(r"\b(\d{1,3})\b", t):
        n = int(m.group(1))
        if 18 <= n <= 60:
            return n

    # Fallback: Hindi/English word
    n = _word_to_number(t)
    if n is not None and 18 <= n <= 60:
        return n
    return None


# ────────────────────────────────────────────────────────────────
# DURATION (trying for a baby)
# Returns months
# ────────────────────────────────────────────────────────────────

_YEAR_PAT = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:year|years|yr|yrs|saal|साल|वर्ष|varsh)",
    re.IGNORECASE,
)
_MONTH_PAT = re.compile(
    r"(\d+)\s*(?:month|months|mahina|mahine|mahinon|महीन|महीने|महीनों|माह)",
    re.IGNORECASE,
)


def parse_duration_months(text: str) -> Optional[int]:
    """Return trying-duration in months, or None."""
    if not text:
        return None
    t = _translate_devanagari_digits(text.lower())

    m = _YEAR_PAT.search(t)
    if m:
        return int(round(float(m.group(1)) * 12))

    m = _MONTH_PAT.search(t)
    if m:
        return int(m.group(1))

    # Word + "saal"/"year"
    for w, n in {**_HINDI_WORDS, **_EN_WORDS}.items():
        if re.search(rf"{re.escape(w)}\s*(?:saal|year|साल)", t):
            return n * 12
        if re.search(rf"{re.escape(w)}\s*(?:month|mahina|mahine|महीन)", t):
            return n

    # Bare number: <=20 assume years, else months
    m = re.search(r"\b(\d+)\b", t)
    if m:
        n = int(m.group(1))
        return n * 12 if n <= 20 else n

    n = _word_to_number(t)
    if n is not None:
        return n * 12  # words default to years

    return None


# ────────────────────────────────────────────────────────────────
# TREATMENT HISTORY
# ────────────────────────────────────────────────────────────────

_IVF_PAT = re.compile(r"(\bivf\b|आई\s*वी\s*एफ|आइवीएफ)", re.IGNORECASE)
_IUI_PAT = re.compile(r"(\biui\b|आई\s*यू\s*आई|आइयूआई)", re.IGNORECASE)
_YES_PAT = re.compile(
    r"(\bhaan\b|\byes\b|\byeah\b|\byep\b|\bji\b|हाँ|हां|जी|किया\s*है|done|kiya)",
    re.IGNORECASE,
)
_NO_PAT = re.compile(
    r"(\bnahi\b|\bno\b|\bnope\b|\bnever\b|नहीं|कभी\s*नहीं|never)",
    re.IGNORECASE,
)


def parse_treatment(text: str) -> Optional[Dict[str, Any]]:
    """
    Returns {'prior_ivf': bool, 'treatments': [list of str]}.
    Returns None if the user's intent is unclear.
    """
    if not text:
        return None
    t = text.lower()
    treatments = []
    has_ivf = bool(_IVF_PAT.search(t))
    has_iui = bool(_IUI_PAT.search(t))
    if has_ivf:
        treatments.append("IVF")
    if has_iui:
        treatments.append("IUI")

    if has_ivf or has_iui:
        return {"prior_ivf": has_ivf, "treatments": treatments}

    if _NO_PAT.search(t):
        return {"prior_ivf": False, "treatments": []}
    if _YES_PAT.search(t):
        return {"prior_ivf": True, "treatments": ["unspecified"]}

    return None
