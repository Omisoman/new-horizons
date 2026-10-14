"""Structure OCR text into document fields — every value verified against the text.

    extract_fields(text, page_png, use_vlm=None) ->
        {"kind": "invoice" | "lab",
         "fields": {...},                       # INVOICE_FIELDS or LAB_FIELDS
         "field_checks": [{field, value, verified, source}],
         "engine": "<vlm model>" | "regex", "ms": int}

Two documents reach the Farm: a supplier invoice (feed, nutrients, parts) and a
water-lab report. The kind is read from the text first; then qwen3-vl:4b
(Ollama /api/chat, JSON schema, think off, keep_alive 0) gets the page image and
the OCR text and STRUCTURES — it never reads a figure from pixels alone: every
identifier and number it returns must occur in the OCR text, else it is
unverified and the deterministic regex value (when verified) wins. Regex is also
the whole fallback when the VLM is off (INTAKE_VLM=0), unreachable or slow.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time

import yaml

from new_horizons.paths import APP

PROFILE = yaml.safe_load((APP / "profile.yaml").read_text(encoding="utf-8"))
CURRENCY = PROFILE["market"]["currency"]
VLM_TIMEOUT = 60.0

INVOICE_FIELDS = ("invoice_no", "po_no", "invoice_date", "supplier_ref", "supplier_name",
                  "item_code", "qty", "unit_price", "total", "currency")
LAB_FIELDS = ("report_no", "unit_id", "sampled", "ph", "ammonia_mg_l", "nitrite_mg_l",
              "nitrate_mg_l", "iron_mg_l", "lab_name")
NUMBERS = {"qty", "unit_price", "total", "ph", "ammonia_mg_l", "nitrite_mg_l", "nitrate_mg_l",
           "iron_mg_l"}
VERIFY = {  # identifiers and figures: must occur in the text
    "invoice": ("invoice_no", "po_no", "invoice_date", "supplier_ref", "item_code", "qty",
                "unit_price", "total"),
    "lab": ("report_no", "unit_id", "sampled", "ph", "ammonia_mg_l", "nitrite_mg_l",
            "nitrate_mg_l", "iron_mg_l"),
}

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_BIDI = re.compile(r"[‎‏‪-‮⁦-⁩؜]")
_DASH = re.compile(r"[‐-―−]")
_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w])")


def normalize(text: str) -> str:
    """Arabic-Indic digits -> ASCII, bidi marks out, dashes unified."""
    return _DASH.sub("-", _BIDI.sub("", text.translate(_DIGITS)))


def _compact(s: str) -> str:
    return re.sub(r"[\s\-_/.:T]", "", s).upper()


def numbers_in(text: str) -> list[float]:
    return [float(a.replace(",", "") + ("." + b if b else "")) for a, b in _NUMBER.findall(normalize(text))]


def verify(field: str, value, text: str) -> bool:
    """Is `value` present in the OCR text? Figures compare numerically,
    identifiers with spaces and separators removed."""
    if value in (None, "", []):
        return False
    if field in NUMBERS:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        return any(abs(v - n) < 0.005 for n in numbers_in(text))
    return _compact(str(value)) in _compact(normalize(text))


def kind_of(text: str) -> str:
    t = normalize(text).upper()
    if re.search(r"\bLAB-\d{4}-\d{4}\b", t) or "LABORATORY" in t or "مختبر" in text:
        return "lab"
    return "invoice"


# ---- deterministic extractor -------------------------------------------------------

def _first(pattern: str, text: str, flags=0, group: int = 1) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(group) if m else None


def _labelled(label: str, pattern: str, text: str) -> str | None:
    """Value on the same line as `label`, else the first anywhere."""
    for line in text.splitlines():
        if re.search(label, line, re.I):
            m = re.search(pattern, line)
            if m:
                return m.group(1)
    return _first(pattern, text)


_AMOUNT = r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?)"


def _after_header(header: str, text: str) -> list[float]:
    """The numbers on the first line under a column header (OCR reads a table
    column by column, so a row's values land on the line after its headers)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.search(header, line, re.I):
            for nxt in lines[i + 1:i + 4]:
                row = re.sub(r"\b[A-Z]{2,5}-\d+\b", " ", nxt)      # item codes are not figures
                row = re.sub(r"(?<=\d):(?=\d{2}\b)", ".", row)    # OCR reads 2.95 as 2:95
                nums = numbers_in(row)
                if nums:
                    return nums
    return []


def regex_invoice(text: str) -> dict:
    t = normalize(text)
    row = _after_header(r"\bQty\b", t)
    # a row ends "qty  unit price  amount"; a description may carry numbers of its own
    # ("3 mm"), and OCR may split the amount onto another line
    tail = row[-3:] if len(row) >= 3 else row
    qty = tail[0] if tail else None
    price = tail[1] if len(tail) > 1 else None
    total = None
    m = re.search(r"(\d{1,3}(?:,\d{3})*\.\d{2})\s*(?:EUR|USD|GBP)\b", t)
    if m:
        total = float(m.group(1).replace(",", ""))
    if total is None:
        line = next((ln for ln in t.splitlines() if re.search(r"TOTAL\s*DUE", ln, re.I)), "")
        vals = [v for v in numbers_in(line) if v]
        total = vals[-1] if vals else None
    if price is not None and qty and total and abs(qty * price - total) > 0.01:
        price = None                      # a misread price (a lost decimal point) is dropped
    name = next((ln.strip() for ln in t.splitlines()[:6]
                 if ln.strip() and not re.search(r"INVOICE|\d{3}", ln, re.I)), None)
    return {
        "invoice_no": _first(r"\b(INV-\d{4}-\d{4})\b", t),
        "po_no": _first(r"\b(PO-\d{4}-\d{4})\b", t),
        "invoice_date": _labelled(r"invoice\s*date", r"(\d{4}-\d{2}-\d{2})", t),
        "supplier_ref": _labelled(r"supplier\s*ref", r"\b(SUP-\d{3})\b", t),
        "supplier_name": name,
        "item_code": _first(r"\b((?:FEED|NUT|PART)-\d{2})\b", t),
        "qty": qty, "unit_price": price, "total": total,
        "currency": _first(r"\b(EUR|USD|GBP)\b", t) or CURRENCY,
    }


def regex_lab(text: str) -> dict:
    t = normalize(text)

    def value(label: str) -> float | None:
        """The first number on a line that names the measure — never a stray number
        elsewhere on the page."""
        for line in t.splitlines():
            if re.search(label, line, re.I):
                rest = re.split(label, line, maxsplit=1, flags=re.I)[-1]
                m = re.search(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w])", rest)
                if m:
                    return float(m.group(1))
        return None

    sampled = _labelled(r"sampled|\d{4}-\d{2}-\d{2} \d{2}:\d{2}", r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})", t)
    return {
        "report_no": _first(r"\b(LAB-\d{4}-\d{4})\b", t),
        "unit_id": _first(r"\b(AQ-\d{2})\b", t),
        "sampled": sampled.replace(" ", "T") if sampled else None,
        "ph": value(r"^\s*pH\b"),
        "ammonia_mg_l": value(r"\bammonia\b"),
        "nitrite_mg_l": value(r"\bnitrite\b"),
        "nitrate_mg_l": value(r"\bnitrate\b"),
        "iron_mg_l": value(r"\b[il1|I]ron\b"),          # OCR reads the I as l, 1 or |
        "lab_name": next((ln.strip() for ln in t.splitlines()[:4] if "lab" in ln.lower()), None),
    }


# ---- VLM structuring ----------------------------------------------------------------

def _schema(kind: str) -> dict:
    fields = INVOICE_FIELDS if kind == "invoice" else LAB_FIELDS
    props = {f: {"type": ["number", "null"]} if f in NUMBERS else {"type": ["string", "null"]}
             for f in fields}
    return {"type": "object", "properties": props, "required": list(fields)}


_PROMPT = {
    "invoice": """You are structuring one scanned supplier invoice sent to an aquaponics farm.

Below is the OCR TEXT of the page. The image is only for layout orientation. RULES:
- Copy every identifier and number EXACTLY as it appears in the OCR text. Never read
  a number from the image alone; if a value is not in the text, use null.
- invoice_no looks like INV-YYYY-NNNN; po_no (the farm's purchase order) like PO-YYYY-NNNN;
  supplier_ref like SUP-NNN; item_code like FEED-NN, NUT-NN or PART-NN.
- qty and unit_price come from the invoice line; total is the TOTAL DUE.
- invoice_date as YYYY-MM-DD. supplier_name as printed in the letterhead.

OCR TEXT:
{text}
""",
    "lab": """You are structuring one scanned water-laboratory report for an aquaponics farm.

Below is the OCR TEXT of the page. The image is only for layout orientation. RULES:
- Copy every identifier and number EXACTLY as it appears in the OCR text. Never read
  a number from the image alone; if a value is not in the text, use null.
- report_no looks like LAB-YYYY-NNNN; unit_id like AQ-NN; sampled as YYYY-MM-DDTHH:MM.
- ph, ammonia_mg_l, nitrite_mg_l, nitrate_mg_l, iron_mg_l are the measured results (mg/L).

OCR TEXT:
{text}
""",
}


def _ollama_host() -> str:
    # qwen3-vl is a local model — it does not follow the chat endpoint.
    from new_horizons.shared.llm.provider import ollama_host
    return ollama_host()


def vlm_extract(kind: str, text: str, page_png: bytes | None, timeout: float = VLM_TIMEOUT) -> dict:
    import httpx
    msg = {"role": "user", "content": _PROMPT[kind].format(text=text[:6000])}
    if page_png:
        msg["images"] = [base64.b64encode(page_png).decode()]
    body = {"model": os.environ.get("VLM_MODEL", "qwen3-vl:4b"), "messages": [msg],
            "format": _schema(kind), "stream": False, "think": False, "keep_alive": 0,
            "options": {"temperature": 0, "num_predict": 768}}
    r = httpx.post(f"{_ollama_host()}/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    m = r.json()["message"]
    for key in ("content", "thinking"):        # qwen3-vl may answer in `thinking`
        raw = (m.get(key) or "").strip()
        a, b = raw.find("{"), raw.rfind("}")
        if a >= 0 and b > a:
            try:
                return json.loads(raw[a:b + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("VLM returned no JSON object")


# ---- merge + verify ------------------------------------------------------------------

def _clean(field: str, v):
    if v in (None, "", "null"):
        return None
    if field in NUMBERS:
        try:
            return round(float(str(v).replace(",", "")), 3)
        except ValueError:
            return None
    if field in ("invoice_no", "po_no", "supplier_ref", "item_code", "report_no", "unit_id"):
        return re.sub(r"\s", "", str(v)).upper()
    return str(v).strip()


def merge(kind: str, text: str, vlm: dict | None, rx: dict) -> tuple[dict, list[dict]]:
    """Pick per field: a verified VLM value, else a verified regex value, else
    whatever exists (unverified). Returns (fields, field_checks)."""
    fields, checks = {}, []
    for f in (INVOICE_FIELDS if kind == "invoice" else LAB_FIELDS):
        v_vlm, v_rx = _clean(f, (vlm or {}).get(f)), _clean(f, rx.get(f))
        if f not in VERIFY[kind]:
            fields[f] = v_vlm if v_vlm is not None else v_rx
            checks.append({"field": f, "value": fields[f], "verified": None,
                           "source": "vlm" if v_vlm is not None else ("regex" if v_rx is not None else None)})
            continue
        ok_vlm, ok_rx = verify(f, v_vlm, text), verify(f, v_rx, text)
        if ok_vlm and (not ok_rx or _same(f, v_vlm, v_rx)):
            val, ok, src = v_vlm, True, "vlm+regex" if ok_rx else "vlm"
        elif ok_rx:
            val, ok, src = v_rx, True, "regex"
        else:
            val = v_vlm if v_vlm is not None else v_rx
            ok, src = False, ("vlm" if v_vlm is not None else ("regex" if v_rx is not None else None))
        fields[f] = val
        checks.append({"field": f, "value": val, "verified": ok, "source": src})
    return fields, checks


def _same(field: str, a, b) -> bool:
    if field in NUMBERS:
        return a is not None and b is not None and abs(float(a) - float(b)) < 0.005
    return _compact(str(a)) == _compact(str(b))


def extract_fields(text: str, page_png: bytes | None = None, use_vlm: bool | None = None) -> dict:
    t0 = time.time()
    if use_vlm is None:
        use_vlm = os.environ.get("INTAKE_VLM", "1") != "0"
    kind = kind_of(text)
    rx = regex_invoice(text) if kind == "invoice" else regex_lab(text)
    vlm, engine, error = None, "regex", None
    if use_vlm:
        try:
            vlm = vlm_extract(kind, text, page_png)
            engine = os.environ.get("VLM_MODEL", "qwen3-vl:4b")
        except Exception as exc:          # the demo never fails here — regex carries it
            error = f"{type(exc).__name__}: {exc}"[:200]
    fields, checks = merge(kind, text, vlm, rx)
    out = {"kind": kind, "fields": fields, "field_checks": checks, "engine": engine,
           "ms": int((time.time() - t0) * 1000)}
    if error:
        out["vlm_error"] = error
    return out
