"""Arabic text + number normalization (KB index, OCR text, chat questions).

Display text keeps original letters; the search index gets the aggressive
normalization (alef variants, ta-marbuta). Numbers are canonicalized for BOTH:
`(‪)5,991,288` → `-5991288` — Arabic statements mark negatives with parens and
PDF extraction scatters bidi controls and paren halves around the digits.
"""

from __future__ import annotations

import re

# Bidi / directional control characters (same class the pipeline strips).
BIDI = re.compile(r"[‪-‮‎‏⁦-⁩]")

TATWEEL = "ـ"
DIACRITICS = re.compile(r"[ً-ٰٟ]")

EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٬٫", "01234567890123456789,.")

# Negative-number shapes after bidi stripping. RTL rendering scatters the two
# paren halves: "()N", "(N)", ")N(", ")N)" all mean minus N.
_NEG_PATTERNS = [
    re.compile(r"\(\s*\)\s*(\d[\d,]*)"),   # ()5,991,288
    re.compile(r"\)\s*(\d[\d,]*)\s*\("),   # )5,991,288(
    re.compile(r"\)\s*(\d[\d,]*)\s*\)"),   # ) 7,022,634 )
    re.compile(r"\(\s*(\d[\d,]*)\s*\)"),   # (3,223,114)
]
_THOUSANDS = re.compile(r"(?<=\d),(?=\d)")


def strip_bidi(text: str) -> str:
    return BIDI.sub("", text)


def normalize_numbers(text: str) -> str:
    """Eastern digits → ASCII, paren-negatives → -N, thousands commas dropped."""
    t = strip_bidi(text).translate(EASTERN_DIGITS)
    for pat in _NEG_PATTERNS:
        t = pat.sub(lambda m: "-" + m.group(1).replace(",", ""), t)
    return _THOUSANDS.sub("", t)


def clean_arabic(text: str) -> str:
    """Display-safe cleaning: bidi controls, tatweel, diacritics. Letters kept."""
    t = strip_bidi(text)
    t = t.replace(TATWEEL, "")
    return DIACRITICS.sub("", t)


_INDEX_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})


def index_normalize(text: str) -> str:
    """Aggressive form for the search index ONLY (display keeps originals):
    clean + unify alef variants and ta-marbuta + canonical numbers."""
    return normalize_numbers(clean_arabic(text)).translate(_INDEX_MAP)


def parse_amount(token: str) -> int | None:
    """'4,128,996' → 4128996 ; '(3,223,114)' → -3223114 ; junk → None."""
    t = normalize_numbers(token).strip()
    m = re.fullmatch(r"-?\d+", t)
    return int(t) if m else None


def detect_lang(text: str) -> str:
    ar = len(re.findall(r"[؀-ۿ]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if ar and latin and min(ar, latin) / max(ar, latin) > 0.25:
        return "mixed"
    return "ar" if ar >= latin else "en"
