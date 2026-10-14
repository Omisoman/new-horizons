"""Lam-alef ligature fix — the zero-width-alef + `ل` swap (Arabic PDFs whose
font emits every lam-alef ligature reversed)."""

from new_horizons.app.ingest.pdf_pipeline import fix_chars


def _char(ch: str, x0: float, x1: float) -> dict:
    return {"c": ch, "bbox": (x0, 0.0, x1, 10.0)}


def test_zero_width_alef_swap():
    # Broken `األرباح` as rawdict emits it: ا + zero-width أ + ل + رباح
    chars = [_char("ا", 0, 2), _char("أ", 2, 2), _char("ل", 2, 5),
             _char("ر", 5, 7), _char("ب", 7, 9), _char("ا", 9, 11),
             _char("ح", 11, 13)]
    assert "".join(fix_chars(chars)) == "الأرباح"


def test_normal_alef_not_swapped():
    # A full-width alef before ل must stay untouched.
    chars = [_char("ا", 0, 2), _char("ل", 2, 4)]
    assert "".join(fix_chars(chars)) == "ال"


def test_all_alef_variants_swap():
    for alef in "اأإآ":
        chars = [_char(alef, 3, 3), _char("ل", 3, 6)]
        assert "".join(fix_chars(chars)) == "ل" + alef
