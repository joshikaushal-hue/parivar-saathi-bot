"""
input_parser.py
Deterministic extraction helpers — parse duration, age, treatment from raw text.
These run BEFORE calling OpenAI so the state context is always enriched.
"""

import re
from typing import Optional


# ── S1 REFUSAL DETECTION ─────────────────────────────────────────────────────

def is_s1_refusal(message: str) -> bool:
    refusal_tokens = [
        "no", "nahi", "nahin", "nope",
        "don't", "do not", "not interested",
        "stop", "band karo", "mat karo",
        "baat nahi karni", "call mat karo"
    ]

    msg = message.lower().strip()

    return any(token in msg for token in refusal_tokens)


# ── PHONE EXTRACTION (NEW - CRITICAL FOR S6) ─────────────────────────────────

def extract_phone(message: str) -> Optional[str]:
    digits = re.sub(r"\D", "", message)

    if len(digits) == 10:
        return digits

    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]

    return None


# ── Duration parsing ──────────────────────────────────────────────────────────

_HINDI_NUMS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5,
    "chhe": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "barah": 12, "tera": 13, "chaudah": 14,
    "pandrah": 15, "solah": 16, "satrah": 17, "atharah": 18,
}

_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "half": 0.5,
    **_HINDI_NUMS,
}


def _word_to_num(token: str) -> Optional[float]:
    t = token.lower().strip()
    if t in _WORD_NUMS:
        return float(_WORD_NUMS[t])
    try:
        return float(t)
    except ValueError:
        return None


def parse_duration_months(text: str) -> Optional[float]:
    """
    Extract duration from free text, return months as float or None.
    Handles: "2 years", "18 months", "1.5 years", "do saal", "6 mahine", etc.
    """
    text_l = text.lower()

    # Pattern: <number> year(s)
    m = re.search(r'(\d+\.?\d*|\w+)\s+(?:year|sal|saal|yr)', text_l)
    if m:
        val = _word_to_num(m.group(1))
        if val is not None:
            months = val * 12

            # check additional months
            m2 = re.search(r'(\d+\.?\d*|\w+)\s+(?:month|mahine|mahe)', text_l)
            if m2:
                extra = _word_to_num(m2.group(1))
                if extra:
                    months += extra

            return months

    # Pattern: months only
    m = re.search(r'(\d+\.?\d*|\w+)\s+(?:month|mahine|mahe)', text_l)
    if m:
        val = _word_to_num(m.group(1))
        if val is not None:
            return val

    # "more than 3 years"
    m = re.search(r'(?:over|more than|greater than)\s+(\d+\.?\d*)\s+year', text_l)
    if m:
        return float(m.group(1)) * 12 + 1

    return None


# ── Age parsing ───────────────────────────────────────────────────────────────

def parse_age(text: str) -> Optional[str]:
    """Extract age or age range from text."""
    text_l = text.lower()

    # range: "30-35" or "30 to 35"
    m = re.search(r'(\d{2})\s*(?:-|to)\s*(\d{2})', text_l)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    # single age
    m = re.search(r'(?:am|age|aged|i\'m)?\s*(\d{2})\s*(?:years?\s*old)?', text_l)
    if m:
        age = int(m.group(1))
        if 18 <= age <= 65:
            return str(age)

    return None


# ── Treatment history parsing (UPGRADED WITH TYPOS) ──────────────────────────

_TREATMENT_KEYWORDS = {
    # IVF + failure combinations (MUST come first — longest match wins)
    "ivf failed": "IVF failure",
    "ivf failure": "IVF failure",
    "ivf fail": "IVF failure",
    "failed ivf": "IVF failure",
    "ivf multiple": "IVF multiple failures",
    "multiple ivf": "IVF multiple failures",
    "ivf 2 times": "IVF multiple failures",
    "ivf twice": "IVF multiple failures",
    "ivf 3 times": "IVF multiple failures",

    # IUI + failure combinations
    "iui failed": "IUI failure",
    "iui failure": "IUI failure",
    "failed iui": "IUI failure",

    # IVF variations
    "ivf": "IVF",
    "ivfr": "IVF",
    "ivf treatment": "IVF",
    "test tube": "IVF",
    "testtube": "IVF",
    "test tube baby": "IVF",

    # IUI variations
    "iui": "IUI",
    "iuu": "IUI",
    "iui treatment": "IUI",
    "intrauterine": "IUI",

    # Failure signals (standalone — no treatment prefix)
    "multiple": "Multiple failures",
    "failed": "Multiple failures",
    "failure": "Multiple failures",

    # None / no treatment
    "none": "None",
    "no treatment": "None",
    "nothing": "None",
    "nahi": "None",
    "koi nahi": "None",
    "abhi nahi": "None",
}


def parse_treatment(text: str) -> Optional[str]:
    text_l = text.lower()

    # Check longer phrases first (important)
    for kw in sorted(_TREATMENT_KEYWORDS, key=len, reverse=True):
        if kw in text_l:
            return _TREATMENT_KEYWORDS[kw]

    return None