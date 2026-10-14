"""Text extraction for PDF pages that carry a text layer (document intake).

Text path uses PyMuPDF `rawdict` with the lam-alef ligature fix: the "Arabic
Transparent" font emits every lam-alef ligature reversed (`الأرباح` →
`األرباح`). In `rawdict` the ligature appears as a ZERO-WIDTH alef followed by
`ل` — swap exactly those pairs. Regex on the flat text cannot do this.
"""

from __future__ import annotations

import re

import pymupdf

ALEF = "اأإآ"
BIDI = re.compile(r"[‪-‮‎‏]")

NATIVE_TEXT_MIN = 50  # triage threshold from the brief


def fix_chars(cs: list[dict]) -> list[str]:
    """Ligature fix on one span's rawdict chars: zero-width alef + `ل` → `ل`+alef."""
    out: list[str] = []
    i = 0
    while i < len(cs):
        c = cs[i]
        if (c["c"] in ALEF and c["bbox"][0] == c["bbox"][2]
                and i + 1 < len(cs) and cs[i + 1]["c"] == "ل"):
            out.append("ل" + c["c"])
            i += 2
            continue
        out.append(c["c"])
        i += 1
    return out


def page_text(page: "pymupdf.Page") -> str:
    out: list[str] = []
    for b in page.get_text("rawdict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                out.extend(fix_chars(s["chars"]))
            out.append("\n")
    return BIDI.sub("", "".join(out))


def is_native(page: "pymupdf.Page") -> bool:
    return len(page.get_text().strip()) > NATIVE_TEXT_MIN


def render_png(page: "pymupdf.Page", dpi: int = 150) -> bytes:
    return page.get_pixmap(dpi=dpi).tobytes("png")
