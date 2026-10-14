"""Brand sources of truth: the generated host config and the product marks
never drift from what their scripts render, and the marks keep the
Agentization Core pixel geometry (the AC chevron, a 4.625 px cell)."""

import importlib.util
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "new_horizons" / "app" / "static"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_host_config_matches_a_fresh_render():
    sync = _script("brand-sync")
    for path, text in sync.targets().items():
        assert path.read_text(encoding="utf-8") == text, f"{path.name} drifted — run scripts/brand-sync.py"


def test_marks_match_a_fresh_render():
    marks = _script("brand-marks")
    targets = {
        ROOT / "assets" / "brand" / "horizons-mark.svg": ("new-horizons", marks.WHITE),
        ROOT / "assets" / "brand" / "horizons-mark-for-light.svg": ("new-horizons", marks.INK),
        STATIC / "sojourner-mark.svg": ("sojourner", marks.WHITE),
        STATIC / "sojourner-mark-for-light.svg": ("sojourner", marks.INK),
    }
    for path, (text, ink) in targets.items():
        assert path.read_text() == marks.svg(text, ink, ET.fromstring(path.read_text()).get("aria-label")), \
            f"{path.name} drifted — run make marks"


def test_marks_share_the_ac_chevron_and_grid():
    marks = _script("brand-marks")
    ac = (STATIC / "ac-mark.svg").read_text()
    assert marks.CHEVRON in ac, "the product marks wear the AC mark's own chevron"
    for path in (ROOT / "assets" / "brand").glob("*.svg"):
        svg = path.read_text()
        assert marks.CHEVRON in svg and 'viewBox="0 0 ' in svg
        for x, w in re.findall(r"M([\d.]+) [\d.]+h([\d.]+)", svg):
            assert abs((float(x) - marks.X0) / marks.U - round((float(x) - marks.X0) / marks.U)) < 1e-6
            assert abs(float(w) / marks.U - round(float(w) / marks.U)) < 1e-6


def test_every_glyph_is_seven_cells_wide_on_eight_rows():
    marks = _script("brand-marks")
    for ch, rows in marks.GLYPHS.items():
        assert len(rows) == 8, ch
        assert all(len(r) <= marks.LETTER and set(r) <= {" ", "#"} for r in rows), ch
