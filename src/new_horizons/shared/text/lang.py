"""Language and figure checks, shared by the harness and the scorecard.

The harness enforces with these (shared/harness/graph.py) and
scripts/question-bank.py measures with them, so a pass in rehearsal means the
same thing as a pass in the room.

- Prose follows the question's language. Identifiers (AQ-03, WO-2026-0042,
  INV-2026-0418), citations (pump-maintenance-sop.md §3), code spans
  (`water_level_cm`), snake_case names and upper-case codes (EUR, DO) are neutral.
- A figure is a number in prose. Digits inside an identifier, a citation, a
  date, a time or a period label are not figures.
"""

from __future__ import annotations

import re
import unicodedata

from new_horizons.shared.text.arabic import EASTERN_DIGITS

# Arabic block plus the presentation forms (U+FB50–FDFF, U+FE70–FEFF) that text
# pasted from PDFs and some chat apps arrives in.
ARABIC = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")
# Latin word edges. Python counts Arabic letters as \w, so \b finds no edge in
# "وGRG-009" — these lookarounds do.
_L, _R = r"(?<![A-Za-z0-9_])", r"(?![A-Za-z0-9_])"

NEUTRAL = re.compile(
    r"`[^`\n]*`"                                                    # `approved_amount`
    rf"|{_L}[a-z0-9_-]+\.md(?:\s*(?:§|section)\s*\d+(?:\.\d+)*)?"   # pump-maintenance-sop.md §3
    r"|§\s*\d+(?:\.\d+)*"                                           # §3.1
    rf"|{_L}[A-Z]{{1,5}}(?:-[A-Z0-9]+)+{_R}"                        # AQ-03, WO-2026-0042, SHP-…
    rf"|{_L}\d{{4}}-\d{{2}}(?:-\d{{2}})?"                           # 2026-09-14, 2024-09
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
    rf"{_R}"
    rf"|{_L}\d{{4}}-Q[1-4]{_R}|{_L}Q[1-4]{_R}|{_L}\d{{4}}/\d{{2}}{_R}"  # 2026-Q3, batch 2026/05
    rf"|{_L}\d{{1,2}}:\d{{2}}{_R}"                                  # 12:34
    rf"|{_L}[a-z]+(?:_[a-z0-9]+)+(?:\.[a-z_]+)?{_R}"                # telemetry.readings, water_level_cm
    rf"|{_L}[a-z]+(?:-[a-z]+)+{_R}"                                 # water-quality-sop
    rf"|{_L}[A-Z]{{2,}}[A-Z0-9]*{_R}"                               # EUR, DO, SOP
)
_LATIN_WORD = re.compile(r"[A-Za-z]{4,}")
IDENT = re.compile(rf"{_L}[A-Z]{{1,5}}(?:-[A-Z0-9]+)+{_R}")


def identifiers(text: str) -> list[str]:
    """Record identifiers in order of appearance: AQ-03, WO-2026-0042, INV-2026-0418."""
    return list(dict.fromkeys(IDENT.findall(text or "")))


def prose(text: str) -> str:
    """The text (NFKC-normalized) with every language-neutral span blanked out."""
    return NEUTRAL.sub(" ", unicodedata.normalize("NFKC", text))


def question_lang(text: str) -> str:
    """'ar' or 'en' — the language an answer to `text` must be written in."""
    t = prose(text)
    ar, latin = len(ARABIC.findall(t)), len(re.findall(r"[A-Za-z]", t))
    return "ar" if ar and ar >= latin else "en"


def script_ok(text: str, lang: str) -> bool:
    """An Arabic answer is Arabic prose only, an English answer English only."""
    t = prose(text)
    if lang == "ar":
        return bool(ARABIC.search(t)) and not _LATIN_WORD.search(t)
    return not ARABIC.search(t)


# ---- figures ------------------------------------------------------------------

_NUM = re.compile(r"(?<![A-Za-z0-9_.,])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:[eE]([-+]?\d+))?"
                  r"(\s?[%٪])?(?![A-Za-z0-9_])")
_EVIDENCE_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?")


def figures(text: str) -> list[dict]:
    """Every figure in prose: {text, span, value, decimals, sci, pct}.
    Spans index the original text (digit normalization keeps lengths)."""
    t = text.translate(EASTERN_DIGITS)
    masked = NEUTRAL.sub(lambda m: " " * len(m.group()), t)
    out = []
    for m in _NUM.finditer(masked):
        whole, frac, exp, pct = m.groups()
        mant = float(whole.replace(",", "") + (frac or ""))
        out.append({"text": text[m.start():m.end()], "span": m.span(),
                    "value": mant * 10 ** int(exp) if exp else mant,
                    "decimals": len(frac) - 1 if frac else 0,
                    "sci": exp is not None, "pct": bool(pct)})
    return out


def evidence(*sources) -> set[float]:
    """Every number a turn's evidence holds: JSON values, numbers inside
    strings (dates included, so '14 September 2026' is supported by
    2026-09-14), and the size of every list and object (a model may count)."""
    vals: set[float] = set()

    def walk(o):
        if o is None or isinstance(o, bool):
            return
        if isinstance(o, (int, float)):
            vals.add(abs(float(o)))
        elif isinstance(o, dict):
            vals.add(float(len(o)))
            for k, v in o.items():
                walk(k)
                walk(v)
        elif isinstance(o, (list, tuple, set)):
            vals.add(float(len(o)))
            for v in o:
                walk(v)
        else:
            for m in _EVIDENCE_NUM.finditer(str(o).translate(EASTERN_DIGITS)):
                try:
                    vals.add(float(m.group().rstrip(",").replace(",", "")))
                except ValueError:
                    pass

    for s in sources:
        walk(s)
    return vals


def _rounds_to(n: float, e: float, decimals: int) -> bool:
    if n == 0:                       # "0" is the classic invented figure: exact only
        return e == 0
    if abs(n - e) <= 0.01:
        return True
    if abs(round(e, decimals) - n) < 1e-9:
        return True
    whole = int(n)
    if decimals == 0 and whole >= 1000:          # 239,000 for 239,424.10
        s = str(whole)
        k = len(s) - len(s.rstrip("0"))          # keeps at least two significant digits
        return 0 < k <= len(s) - 2 and abs(round(e, -k) - n) < 1e-9
    return False


def supported(fig: dict, values: set[float]) -> bool:
    """A figure is supported if some evidence value equals it (±0.01), rounds
    to it at the precision written, or is the ratio it states as a percent."""
    n = fig["value"]
    if fig["sci"]:
        fmt = f"{{:.{fig['decimals']}e}}"
        return any(e and fmt.format(e) == fmt.format(n) for e in values)
    return any(_rounds_to(n, e, fig["decimals"])
               or (e <= 1.5 and _rounds_to(n, e * 100, fig["decimals"]))
               for e in values)


def strip_unsupported(text: str, values: set[float], marker: str) -> tuple[str, list[str]]:
    """Replace every unsupported figure with `marker`; return (text, removed)."""
    out, removed = text, []
    for f in reversed(figures(text)):
        if not supported(f, values):
            s, e = f["span"]
            out = out[:s] + marker + out[e:]
            removed.append(f["text"].strip())
    return out, removed[::-1]


def same_value(a: float, b: float) -> bool:
    return abs(a - b) < 1e-6


def figure_found(needle: str, answer: str) -> bool:
    """Scorecard check, by value not formatting: 61,624.96 == 61624.96, and
    Arabic-Indic digits count."""
    flat = lambda t: re.sub(r"(?<=\d),(?=\d)", "", t.translate(EASTERN_DIGITS))
    return flat(needle) in flat(answer)
