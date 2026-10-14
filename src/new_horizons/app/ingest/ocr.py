"""OCR path — only for the pages with no text layer (scans and photos).

Primary: Surya (PyTorch MPS, Arabic). Fallback: Tesseract `ara`.
Never OCR a page that has a text layer.
"""

from __future__ import annotations

import io

from PIL import Image

_predictors = None


def _surya():
    global _predictors
    if _predictors is None:
        from surya.detection import DetectionPredictor
        from surya.foundation import FoundationPredictor
        from surya.recognition import RecognitionPredictor
        foundation = FoundationPredictor()
        _predictors = (RecognitionPredictor(foundation), DetectionPredictor())
    return _predictors


def ocr_images(pngs: list[bytes]) -> list[tuple[str, str]]:
    """[(text, engine)] per page image. Surya first, Tesseract ara fallback."""
    images = [Image.open(io.BytesIO(p)).convert("RGB") for p in pngs]
    try:
        rec, det = _surya()
        results = rec(images, det_predictor=det, sort_lines=True, math_mode=False)
        out = []
        for r in results:
            text = "\n".join(line.text for line in r.text_lines)
            out.append((text, "surya"))
        return out
    except Exception as exc:  # fall back page-by-page
        print(f"  surya failed ({exc}); falling back to tesseract ara")
        import pytesseract
        return [(pytesseract.image_to_string(img, lang="ara"), "tesseract")
                for img in images]
