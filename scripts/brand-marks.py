"""Product marks in the Agentization Core pixel style (stdlib only).

    uv run python scripts/brand-marks.py

The AC mark is a gray chevron and pixel letters on a 4.625 px grid (x-height
5 cells, one ascender pair above, one descender row below). This draws the
product's pixel wordmark with the same chevron and the same letterforms — nothing
is traced, everything is generated from the bitmaps below. The app shell (host/)
wears it; the analytics app's sidebar wears the flyby mark (scripts/brand-flyby.py).

  assets/brand/horizons-mark.svg            › new-horizons (white ink)
  assets/brand/horizons-mark-for-light.svg  same geometry, gray ink (White theme)
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
U = 4.625                       # one pixel cell
X0, LETTER, ADVANCE = 53.0, 7, 8
ROW_TOP = {r: 11.25 + (r - 2) * U for r in range(8)}   # rows 0-1 ascender, 2-6 x-height, 7 descender
CHEVRON = "M0 42V36H6V30H12V24H18V18H12V12H6V6H0V0H12V6H18V12H24V18H30V24H24V30H18V36H12V42H0Z"
GRAY, WHITE, INK = "#878787", "#f5f5f5", "#525252"

# rows 0..7; "#" = ink. The letters the AC wordmark already draws (a e n o r t i z -)
# are copied cell for cell; m s j u p h l w are drawn to the same rules.
GLYPHS = {
    "a": ["", "", " ##### ", "     ##", " ######", "##   ##", " ######", ""],
    "e": ["", "", " ##### ", "##   ##", "#######", "##     ", " ##### ", ""],
    "n": ["", "", "###### ", "##   ##", "##   ##", "##   ##", "##   ##", ""],
    "o": ["", "", " ##### ", "##   ##", "##   ##", "##   ##", " ##### ", ""],
    "r": ["", "", " ## ###", " ###   ", " ##    ", " ##    ", " ##    ", ""],
    "t": ["   ##  ", "   ##  ", " ######", "   ##  ", "   ##  ", "   ##  ", "   ##  ", ""],
    "i": ["   ##  ", "", "  ###  ", "   ##  ", "   ##  ", "   ##  ", " ######", ""],
    "z": ["", "", "#######", "   ### ", "  ###  ", " ###   ", "#######", ""],
    "-": ["", "", "", " ######", "", "", "", ""],
    "m": ["", "", "###### ", "## # ##", "## # ##", "## # ##", "## # ##", ""],
    "s": ["", "", " ######", "##     ", " ##### ", "     ##", "###### ", ""],
    "u": ["", "", "##   ##", "##   ##", "##   ##", "##   ##", " ######", ""],
    "j": ["     ##", "", "    ###", "     ##", "     ##", "     ##", "     ##", " ##### "],
    "p": ["", "", "###### ", "##   ##", "##   ##", "###### ", "##     ", "##     "],
    "h": ["##     ", "##     ", "###### ", "##   ##", "##   ##", "##   ##", "##   ##", ""],
    "l": ["  ###  ", "   ##  ", "   ##  ", "   ##  ", "   ##  ", "   ##  ", " ######", ""],
    "w": ["", "", "## # ##", "## # ##", "## # ##", "## # ##", " ######", ""],
}


def _runs(text: str) -> list[tuple[float, float, float]]:
    """(x, y, width) of every horizontal run of ink cells."""
    out = []
    for i, ch in enumerate(text):
        rows = GLYPHS[ch]
        left = X0 + i * ADVANCE * U
        for r, line in enumerate(rows):
            c = 0
            while c < len(line):
                if line[c] != "#":
                    c += 1
                    continue
                start = c
                while c < len(line) and line[c] == "#":
                    c += 1
                out.append((left + start * U, ROW_TOP[r], (c - start) * U))
    return out


def _num(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def svg(text: str, ink: str, label: str) -> str:
    width = X0 + (len(text) - 1) * ADVANCE * U + LETTER * U
    d = "".join(f"M{_num(x)} {_num(y)}h{_num(w)}v{_num(U)}h-{_num(w)}Z" for x, y, w in _runs(text))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_num(width)} 42" '
            f'width="{_num(width)}" height="42" fill="none" role="img" aria-label="{label}">\n'
            f'<path d="{CHEVRON}" fill="{GRAY}"/>\n<path d="{d}" fill="{ink}"/>\n</svg>\n')


def main() -> None:
    brand = ROOT / "assets" / "brand"
    brand.mkdir(parents=True, exist_ok=True)
    targets = {
        brand / "horizons-mark.svg": svg("new-horizons", WHITE, "new-horizons"),
        brand / "horizons-mark-for-light.svg": svg("new-horizons", INK, "new-horizons"),
    }
    for path, text in targets.items():
        path.write_text(text)
        print(f"  {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
