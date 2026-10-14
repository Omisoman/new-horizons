"""Read an attached document into text — text layer first, OCR otherwise.

    read_document(path) -> {"kind": "pdf"|"image", "pages": n,
                            "engine": "native"|"tesseract"|"surya",
                            "text": str, "page_pngs": [png bytes], "ms": int}

PDF pages with a text layer are read with the ligature-fixed extractor
(ingest/pdf_pipeline.page_text). Scanned pages and photos go to OCR:
Tesseract (CPU, ~4 s a page for two passes: `eng` for identifiers and
amounts, `ara+eng` for the Arabic lines) is the default — on the demo
invoices it recovers every identifier and amount; Surya (ingest/ocr.py,
PyTorch/MPS) is the fallback when Tesseract's text misses the key patterns
and INTAKE_SURYA=1 allows loading it (it competes with the chat model for
unified memory, so it is opt-in).
"""

from __future__ import annotations

import io
import os
import re
import time
from pathlib import Path

OCR_DPI = 200          # the demo scans are 200 dpi; 300 adds 2.5 s, no accuracy
MAX_PAGES = 4
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
TESS_CONFIG = "--oem 1 --psm 4"
# What a readable farm document must yield; missing -> try the fallback engine.
KEY_PATTERNS = (re.compile(r"\b(?:INV|LAB)-\d{4}-\d{4}\b"), re.compile(r"\bAQ-0\d\b"),
                re.compile(r"\d[\d,]*\.\d{2}"))


_ARABIC = re.compile(r"[؀-ۿ]")
_AR_RUN = re.compile(r"[؀-ۿ](?:[؀-ۿ\s]*[؀-ۿ])?")


def _tesseract(png: bytes) -> str:
    """Two passes. `eng` reads every identifier and amount cleanly; a mixed
    `ara+eng` pass bidi-reorders Latin runs (codes, dates) on mixed
    lines, so it only contributes its Arabic runs (names, labels), one line
    per source line, after the English text."""
    import pytesseract
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert("L")
    latin = pytesseract.image_to_string(img, lang="eng", config=TESS_CONFIG)
    mixed = pytesseract.image_to_string(img, lang="ara+eng", config=TESS_CONFIG)
    arabic = []
    for ln in mixed.splitlines():
        runs = [r.strip() for r in _AR_RUN.findall(ln) if len(_ARABIC.findall(r)) >= 3]
        if runs:
            arabic.append(" · ".join(runs))
    return latin.rstrip() + ("\n\n" + "\n".join(arabic) if arabic else "")


def _surya(png: bytes) -> str:
    from new_horizons.app.ingest.ocr import ocr_images   # Surya, Tesseract fallback
    text, _engine = ocr_images([png])[0]
    return text


def ocr_png(png: bytes, engine: str | None = None) -> tuple[str, str]:
    """(text, engine). Tesseract first; Surya only when allowed and needed."""
    engine = engine or os.environ.get("INTAKE_OCR", "tesseract")
    if engine == "surya":
        return _surya(png), "surya"
    text = _tesseract(png)
    if not all(p.search(text) for p in KEY_PATTERNS) and os.environ.get("INTAKE_SURYA") == "1":
        try:
            alt = _surya(png)
            if sum(bool(p.search(alt)) for p in KEY_PATTERNS) > \
                    sum(bool(p.search(text)) for p in KEY_PATTERNS):
                return alt, "surya"
        except Exception:
            pass
    return text, "tesseract"


def read_document(path: str | Path, engine: str | None = None) -> dict:
    import pymupdf
    from new_horizons.app.ingest.pdf_pipeline import is_native, page_text

    p = Path(path)
    t0 = time.time()
    if p.suffix.lower() in IMAGE_EXT:
        from PIL import Image
        img = Image.open(p).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        png = buf.getvalue()
        text, eng = ocr_png(png, engine)
        return {"kind": "image", "pages": 1, "engine": eng, "text": text,
                "page_pngs": [png], "ms": int((time.time() - t0) * 1000)}

    doc = pymupdf.open(p)
    texts, pngs, engines = [], [], []
    for i in range(min(len(doc), MAX_PAGES)):
        page = doc[i]
        png = page.get_pixmap(dpi=OCR_DPI).tobytes("png")
        pngs.append(png)
        if is_native(page):
            texts.append(page_text(page))
            engines.append("native")
        else:
            text, eng = ocr_png(png, engine)
            texts.append(text)
            engines.append(eng)
    eng = "native" if set(engines) == {"native"} else next(e for e in engines if e != "native")
    return {"kind": "pdf", "pages": len(doc), "engine": eng,
            "text": "\n\f\n".join(texts), "page_pngs": pngs,
            "ms": int((time.time() - t0) * 1000)}
