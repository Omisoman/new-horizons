"""Document intake pipeline — the flow behind the Documents page and the Chat
attachment button.

    process(path, model, on_step=None, use_cache=True, use_vlm=None) -> dict

Steps: read (text layer / OCR) -> extract (VLM structuring, every figure
verified against the OCR text) -> reconcile (analytics/recon.check_document:
the deterministic cross-check of a supplier invoice against its purchase order,
the supplier master and the approved list — or of a water-lab report against
the probe and the SOP bands) -> terms (the KB sections each failed check cites,
plus one semantic search) -> compose (the chat model writes the alert FROM the
failed checks and the retrieved terms; its citations are validated against what
was retrieved, the hold is decided by the rules not the model, and a
deterministic template stands in whenever its output is unusable).

Detection is code; the model only explains and recommends. Every step is
audited and reported through on_step({"key","label","status","detail","ms"}).
Results are cached by file hash + model + extraction mode under
data/intake_cache/, so repeating a document during a demo is instant.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import yaml

from new_horizons.paths import APP, DATA, ROOT

KB_DIR = ROOT / os.environ.get("KB_DIR", "data/kb")
CACHE = DATA / "intake_cache"
CITATIONS = yaml.safe_load((APP / "ingest" / "kb_synthetic" / "citations.yaml").read_text(encoding="utf-8"))
PROFILE = yaml.safe_load((APP / "profile.yaml").read_text(encoding="utf-8"))
CUR = PROFILE["market"]["currency"]

STEPS = [("read", "Reading document"),
         ("extract", "Extracting fields"),
         ("reconcile", "Reconciling against the farm systems"),
         ("terms", "Retrieving the governing terms"),
         ("compose", "Composing the alert")]
LABEL = dict(STEPS)

# A failed check's own citation plus the terms that decide what happens next.
RELATED = {"invoice_tolerance": ["payment_terms"],
           "supplier_master": ["feed_source"],
           "sensor_vs_chemistry": ["lab_reference"],
           "lab_bands": ["water_ph_band"]}
# Checks whose failure means "does not match the system of record".
MISMATCH = {"order_exists", "item_matches_order", "quantity_matches_receipt", "unit_exists"}
RECON_FIELDS = {"invoice": ("invoice_no", "po_no", "supplier_ref", "item_code", "qty", "unit_price",
                            "total"),
                "lab": ("report_no", "unit_id", "sampled", "ph", "ammonia_mg_l", "nitrite_mg_l",
                        "nitrate_mg_l", "iron_mg_l")}


# ---- helpers -------------------------------------------------------------------------

def _audit(event: str, payload: dict) -> None:
    try:
        from new_horizons.shared.audit.audit import audit
        audit("intake-agent", event, payload)
    except Exception:
        pass  # the audit trail is best-effort here; the demo never fails on it


def money(v) -> str:
    return "—" if v is None else f"{float(v):,.2f} {CUR}"


def cite_of(key: str | None) -> dict | None:
    if not key or key not in CITATIONS:
        return None
    c = CITATIONS[key]
    return {"source": c["source"], "section": str(c["section"])}


_CHUNKS: dict | None = None


def section_text(source: str, section: str) -> tuple[str, str]:
    """(heading, text) of one KB section from data/kb/chunks.jsonl."""
    global _CHUNKS
    if _CHUNKS is None:
        _CHUNKS = {}
        path = KB_DIR / "chunks.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
            c = json.loads(line)
            m = c["meta"]
            key = (m["source"], str(m.get("section", "")))
            head, text = _CHUNKS.get(key, (m.get("heading", ""), ""))
            _CHUNKS[key] = (head, (text + "\n" + c["text"]).strip())
    return _CHUNKS.get((source, str(section)), ("", ""))


# ---- steps ------------------------------------------------------------------------------

def step_terms(recon: dict) -> list[dict]:
    """Every KB section the verdict rests on, in the order actions use them."""
    keys: list[str] = []
    for chk in recon.get("discrepancies", []):
        for k in [chk.get("cite")] + RELATED.get(chk.get("cite") or "", []):
            if k and k not in keys:
                keys.append(k)
    if recon.get("verdict") == "not_found" or any(
            c.get("id") in MISMATCH for c in recon.get("discrepancies", [])):
        keys.append("doc_intake")
    if recon.get("verdict") == "clean":
        keys += ["payment_terms", "doc_intake"] if recon.get("kind") == "invoice" else ["lab_reference"]
    terms, seen = [], set()
    for k in keys:
        c = cite_of(k)
        if c and (c["source"], c["section"]) not in seen:
            head, text = section_text(c["source"], c["section"])
            terms.append({"key": k, **c, "heading": head, "text": text})
            seen.add((c["source"], c["section"]))
    # one semantic pass for anything the registry does not name
    query = "; ".join(c.get("label", c.get("id", "")) for c in recon.get("discrepancies", [])) \
        or ("supplier invoice matches its purchase order" if recon.get("kind") == "invoice"
            else "lab report agrees with the probe")
    try:
        from new_horizons.shared.harness.tools import kb_search_in
        for h in kb_search_in(KB_DIR, query, k=3).get("hits", []):
            src, sec = h.get("source"), str(h.get("section") or "")
            if src and sec and (src, sec) not in seen:
                head, text = section_text(src, sec)
                terms.append({"key": None, "source": src, "section": sec, "heading": head,
                              "text": text or h.get("text", ""), "retrieved": True})
                seen.add((src, sec))
    except Exception:
        pass
    return terms


def _pct(found, expected) -> str:
    try:
        return f"{(float(found) / float(expected) - 1) * 100:+.1f}%"
    except (TypeError, ValueError, ZeroDivisionError):
        return ""


def _check(recon: dict, cid: str) -> dict:
    return next((c for c in recon.get("checks", []) if c.get("id") == cid), {})


def template_alert(recon: dict, fields: dict) -> dict:
    """The always-correct alert, built from the failed checks + registry."""
    if recon.get("kind") == "lab":
        return _lab_template(recon, fields)
    v, rec = recon.get("verdict"), recon.get("record") or {}
    inv, po = fields.get("invoice_no") or "the invoice", recon.get("po_no") or fields.get("po_no") or "—"
    if v == "not_found":
        return {"verdict": v, "headline": "No purchase order behind this invoice",
                "summary": f"{inv} quotes order {po}, which is not in purchasing. The invoice is held as "
                           "an exception; nothing is paid from it.",
                "actions": [{"text": "Hold the invoice and route it to the Farm Manager to identify the "
                                     "order; never create or change a record from the document itself.",
                             "cite": cite_of("doc_intake")}],
                "hold_payment": True}
    if v == "clean":
        return {"verdict": v, "headline": "Invoice matches its order — it can be paid",
                "summary": f"{inv} matches purchase order {po}: supplier {rec.get('supplier_ref')}, "
                           f"{fields.get('qty'):g} {rec.get('item_unit') or ''} of {rec.get('item_code')} at "
                           f"the order price {money(rec.get('unit_price_eur'))}; every check passed.",
                "actions": [{"text": f"Pay {inv} 30 days after matching and mark {po} invoiced.",
                             "cite": cite_of("payment_terms")}],
                "hold_payment": False}
    actions, parts = [], []
    failed = {c.get("id"): c for c in recon.get("discrepancies", [])}
    if "price_within_tolerance" in failed:
        agreed = float(rec.get("unit_price_eur") or 0)
        qty = float(fields.get("qty") or rec.get("qty") or 0)
        billed = float(fields.get("unit_price") or (float(fields["total"]) / qty if fields.get("total") and qty else 0))
        excess = (billed - agreed) * qty
        parts.append(f"it bills {money(billed)} per unit against the order's {money(agreed)} "
                     f"({_pct(billed, agreed)}), {money(excess)} more on {qty:g}")
        actions.append({"text": f"Hold {inv}: the price is outside the 5% tolerance; the Farm Manager "
                                f"decides, and accepting the goods at the order price needs a credit "
                                f"note for {money(excess)}.", "cite": cite_of("invoice_tolerance")})
    if "supplier_matches_order" in failed or "supplier_approved" in failed:
        chk = failed.get("supplier_matches_order") or failed.get("supplier_approved")
        parts.append(f"it comes from {fields.get('supplier_ref') or chk.get('found')}, not "
                     f"{rec.get('supplier_ref')} who took {po}"
                     + (", and that supplier is not on the approved list" if "supplier_approved" in failed else ""))
        actions.append({"text": f"Verify by calling {rec.get('supplier_ref')} on the phone number on file — "
                                "never a number printed on the invoice — before anything is paid.",
                        "cite": cite_of("supplier_master")})
    if "not_already_invoiced" in failed:
        parts.append(f"{po} was already invoiced")
        actions.append({"text": f"Block {inv}: the order is already invoiced and paying it would pay twice.",
                        "cite": cite_of("invoice_tolerance")})
    for cid in ("order_exists", "item_matches_order", "quantity_matches_receipt"):
        if cid in failed:
            chk = failed[cid]
            parts.append(f"{chk.get('label', cid).lower()} failed (document {chk.get('found')}, "
                         f"system {chk.get('expected')})")
            actions.append({"text": f"Return {inv} as an exception with both values; purchasing is "
                                    "never changed from a document.", "cite": cite_of("doc_intake")})
    ids = list(failed)
    head = {"price_within_tolerance": "Price over the order", "supplier_matches_order": "wrong supplier",
            "supplier_approved": "supplier not approved"}
    headline = " · ".join(dict.fromkeys(head.get(i, i.replace("_", " ")) for i in ids[:2]))
    headline = headline[:1].upper() + headline[1:] if headline else "Reconciliation discrepancy"
    n = len(failed)
    summary = (f"{inv} against {po} failed {n} check{'s' if n != 1 else ''}: " + "; ".join(parts)
               + ". It stays on hold until the Farm Manager decides.")
    return {"verdict": v, "headline": headline, "summary": summary, "actions": actions,
            "hold_payment": True}


def _lab_template(recon: dict, fields: dict) -> dict:
    v, unit, rep = recon.get("verdict"), recon.get("unit_id") or fields.get("unit_id"), fields.get("report_no")
    if v == "not_found":
        return {"verdict": v, "headline": "No grow unit matches this report",
                "summary": f"{rep} names {unit}, which is not a grow unit of the Farm.",
                "actions": [{"text": "Return the report to the laboratory to confirm the sample's unit.",
                             "cite": cite_of("lab_reference")}], "hold_payment": False}
    failed = {c.get("id"): c for c in recon.get("discrepancies", [])}
    if v == "clean":
        return {"verdict": v, "headline": "Lab report agrees with the probes",
                "summary": f"{rep} for {unit}: every value is inside its band and the probe agrees "
                           "with the lab within 0.2 pH.",
                "actions": [{"text": "File the report with the unit's records.",
                             "cite": cite_of("lab_reference")}], "hold_payment": False}
    actions, parts = [], []
    if "ph_matches_probe" in failed:
        c = failed["ph_matches_probe"]
        parts.append(f"the probe read {c.get('expected', '').split(' ±')[0].replace('probe ', '')} while the "
                     f"lab measured {fields.get('ph')}")
        actions.append({"text": f"Recalibrate the {unit} pH probe (two-point) and cite {rep} on the work "
                                "order; until then treat its pH readings and the drift built on them as "
                                "suspect.", "cite": cite_of("sensor_vs_chemistry")})
    bands = [c for cid, c in failed.items() if cid != "ph_matches_probe"]
    for c in bands:
        parts.append(f"{c.get('label', c['id']).lower()} failed ({c.get('found')} against {c.get('expected')})")
    if bands:
        actions.append({"text": f"Correct the water in {unit} under the water-quality SOP and re-sample "
                                "within a week.", "cite": cite_of("lab_bands")})
    headline = "Probe disagrees with the lab" if "ph_matches_probe" in failed else "Lab values out of band"
    return {"verdict": v, "headline": headline,
            "summary": f"{rep} for {unit}: " + "; ".join(parts) + ".",
            "actions": actions, "hold_payment": False}


_COMPOSE = """You are the reconciliation agent of an aquaponics farm. An uploaded document
was checked against the farm's systems. The FAILED CHECKS and FACTS are final — do not
re-judge them and do not invent numbers. Write the alert the Farm Manager acts on,
following the TERMS literally: recommend exactly what the terms prescribe for each failed
check, nothing the terms do not say.

Reply with ONE JSON object and nothing else:
{{"headline": "<max 12 words>", "summary": "<2 short sentences with the key figures from FACTS>",
  "actions": [{{"text": "<one concrete action naming the invoice / order / supplier / unit from FACTS>",
               "cite": {{"source": "<file.md>", "section": "<n>"}}}}]}}
One action per rule, each citing the TERMS section it comes from (exact source + section).
Start every action with a verb (Hold, Pay, Call, Verify, Recalibrate, Return, Block, Correct).

FAILED CHECKS:
{failed}

FACTS:
{facts}

TERMS:
{terms}
"""


def _facts(recon: dict, fields: dict) -> list[str]:
    rec = recon.get("record") or {}
    if recon.get("kind") == "lab":
        reading = rec.get("reading") or {}
        return [f"lab report {fields.get('report_no')} for unit {recon.get('unit_id')}, sampled "
                f"{fields.get('sampled')}",
                f"lab pH {fields.get('ph')}; probe pH at that time {reading.get('ph')}"]
    out = [f"invoice {fields.get('invoice_no')} from supplier {fields.get('supplier_ref')} against order "
           f"{recon.get('po_no')} placed with supplier {rec.get('supplier_ref')}",
           f"{fields.get('qty')} of {rec.get('item_code')}; order price {money(rec.get('unit_price_eur'))}; "
           f"invoice total {money(fields.get('total'))}"]
    return out


def compose_llm(model: str, recon: dict, fields: dict, terms: list[dict]) -> dict | None:
    from langchain_core.messages import HumanMessage

    from new_horizons.shared.harness.protocol import _candidates
    from new_horizons.shared.llm.client import chat_model
    cited = {(c["source"], c["section"]) for c in
             (cite_of(k) for chk in recon.get("discrepancies", [])
              for k in [chk.get("cite")] + RELATED.get(chk.get("cite") or "", [])) if c}
    governing = [t for t in terms if (t["source"], str(t["section"])) in cited] or terms[:4]
    prompt = _COMPOSE.format(
        failed="\n".join(f"- {c.get('label', c.get('id'))}: document {c.get('found')} vs "
                         f"system {c.get('expected')}" for c in recon.get("discrepancies", [])),
        facts="\n".join(f"- {f}" for f in _facts(recon, fields)),
        terms="\n\n".join(f"[{t['source']} §{t['section']}]\n{t['text'][:1100]}" for t in governing),
    )
    resp = chat_model(model, temperature=0.0).bind(max_tokens=650).invoke([HumanMessage(prompt)])
    raw = resp.content or (resp.additional_kwargs or {}).get("reasoning_content", "") or ""
    for cand in _candidates(raw):
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("actions"):
            return obj
    return None


# The operative words a model-written action must carry to stand in for the rule it
# cites (each inner tuple: any-of; all tuples must match).
OPERATIVE = {
    "invoice_tolerance": [("hold", "block"), ("credit note", "tolerance", "twice")],
    "supplier_master": [("call", "phone", "verify")],
    "sensor_vs_chemistry": [("calibrat",)],
    "lab_bands": [("correct", "dose", "exchange", "re-sample", "resample")],
    "doc_intake": [("exception", "return", "hold")],
    "payment_terms": [("30 days", "pay")],
}
_KEY_OF = {(c["source"], str(c["section"])): k for k, c in CITATIONS.items()}


def _operative(action: dict) -> bool:
    key = _KEY_OF.get((action["cite"]["source"], action["cite"]["section"]))
    text = action["text"].lower()
    return all(any(w in text for w in group) for group in OPERATIVE.get(key, []))


def validate(alert: dict | None, template: dict, terms: list[dict]) -> tuple[dict, str]:
    """Keep the model's words, never its judgement. A model action survives only if
    it cites a section we retrieved AND carries that rule's operative words;
    otherwise the template action for the same rule takes its place. Uncited advice
    is dropped, every failed check keeps an action, and the hold follows the rules."""
    if not alert or not str(alert.get("headline", "")).strip() or not alert.get("actions"):
        return template, "template"
    allowed = {(t["source"], str(t["section"])) for t in terms}
    model_by_cite: dict[tuple, dict] = {}
    for a in alert.get("actions", []):
        if not isinstance(a, dict) or not str(a.get("text", "")).strip():
            continue
        c = a.get("cite") if isinstance(a.get("cite"), dict) else None
        if not c:
            continue
        c = {"source": str(c.get("source", "")).split("/")[-1],
             "section": str(c.get("section", "")).lstrip("§").strip()}
        if (c["source"], c["section"]) not in allowed:
            continue
        k = (c["source"], c["section"])        # a rule split over lines is one action
        text = str(a["text"]).strip().rstrip(".")
        model_by_cite[k] = ({"text": f"{model_by_cite[k]['text']}; {text[:1].lower()}{text[1:]}",
                             "cite": c} if k in model_by_cite else {"text": text, "cite": c})
    model_by_cite = {k: {**v, "text": v["text"] + "."} for k, v in model_by_cite.items() if _operative(v)}
    actions, used_model = [], 0
    for ta in template["actions"]:
        tc = ta.get("cite")
        m = model_by_cite.pop((tc["source"], tc["section"]), None) if tc else None
        actions.append({**(m or ta), "by": "model" if m else "rule"})
        used_model += bool(m)
    for extra in model_by_cite.values():      # model actions on other retrieved terms
        actions.append({**extra, "by": "model"})
        used_model += 1
    return {"verdict": template["verdict"],
            "headline": str(alert["headline"]).strip()[:140],
            "summary": str(alert.get("summary") or template["summary"]).strip(),
            "actions": actions,
            "hold_payment": template["hold_payment"]}, "llm" if used_model else "llm-summary"


# ---- orchestration -------------------------------------------------------------------------

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _data_version() -> str:
    """Digest of the generated data, the KB build and the code that words the alert,
    so a regenerated database, a rebuilt KB or a reworded alert never serves a stale
    cached verdict."""
    h = hashlib.sha256()
    for f in (DATA / "mock_meta.json", KB_DIR / "stats.json", Path(__file__),
              APP / "analytics" / "recon.py", Path(__file__).with_name("extract.py")):
        h.update(f.read_bytes() if f.exists() else b"-")
    return h.hexdigest()[:8]


def _preview(png: bytes, sha: str) -> str:
    """First-page preview for uploads (samples already ship one)."""
    import io

    from PIL import Image
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{sha[:16]}-p1.png"
    if not out.exists():
        im = Image.open(io.BytesIO(png))
        if im.width > 1000:
            im = im.resize((1000, round(1000 * im.height / im.width)), Image.LANCZOS)
        im.save(out, optimize=True)
    return str(out)


def process(path: str | Path, model: str, on_step=None, use_cache: bool = True,
            use_vlm: bool | None = None) -> dict:
    path = Path(path)
    if use_vlm is None:
        use_vlm = os.environ.get("INTAKE_VLM", "1") != "0"
    sha = _sha(path)
    key = (f"{sha[:16]}-{_data_version()}-{re.sub(r'[^A-Za-z0-9.]+', '_', model)}"
           f"-{'vlm' if use_vlm else 'rx'}")
    cached = CACHE / f"{key}.json"

    def emit(k: str, status: str, detail: str = "", ms: int = 0) -> None:
        if on_step:
            try:
                on_step({"key": k, "label": LABEL[k], "status": status, "detail": detail, "ms": ms})
            except Exception:
                pass

    if use_cache and cached.exists():
        out = json.loads(cached.read_text(encoding="utf-8"))
        for s in out.get("steps", []):
            emit(s["key"], s["status"], s.get("detail", "") + " · cached", 0)
        out["cached"] = True
        _audit("intake_cached", {"doc": path.name, "sha256": sha, "model": model,
                                 "verdict": out["alert"]["verdict"]})
        return out

    t_all = time.time()
    steps, timings = [], {}

    def run(k: str, fn, detail_fn):
        emit(k, "running")
        t0 = time.time()
        try:
            res = fn()
        except Exception as exc:
            ms = int((time.time() - t0) * 1000)
            steps.append({"key": k, "label": LABEL[k], "status": "failed",
                          "detail": f"{type(exc).__name__}: {exc}"[:200], "ms": ms})
            timings[k] = ms
            emit(k, "failed", steps[-1]["detail"], ms)
            _audit("intake_step", {"step": k, "ok": False, "error": steps[-1]["detail"]})
            raise
        ms = int((time.time() - t0) * 1000)
        detail = detail_fn(res)
        steps.append({"key": k, "label": LABEL[k], "status": "done", "detail": detail, "ms": ms})
        timings[k] = ms
        emit(k, "done", detail, ms)
        _audit("intake_step", {"step": k, "ok": True, "ms": ms, "detail": detail})
        return res

    try:
        return _run_steps(path, model, sha, use_vlm, run, steps, timings, t_all, cached)
    except Exception as exc:     # a failed step never crashes the caller
        failed = next((s for s in reversed(steps) if s["status"] == "failed"), None)
        where = failed["label"] if failed else "intake"
        return {"doc": {"name": path.name, "path": str(path), "sha256": sha,
                        "preview_png": _sample_preview(path)},
                "error": {"step": failed["key"] if failed else None,
                          "message": f"{type(exc).__name__}: {exc}"[:300]},
                "alert": {"verdict": "error", "headline": f"Intake stopped at: {where}",
                          "summary": f"{type(exc).__name__}: {exc}"[:300], "actions": [],
                          "hold_payment": True, "composer": "none"},
                "steps": steps, "timings": timings, "model": model,
                "total_ms": int((time.time() - t_all) * 1000), "cached": False}


def _sample_preview(path: Path) -> str | None:
    p = path.with_name(path.stem + "-preview.png")
    return str(p) if p.exists() else None


def _run_steps(path, model, sha, use_vlm, run, steps, timings, t_all, cached) -> dict:
    from new_horizons.app.analytics import recon as R
    from new_horizons.app.intake.extract import extract_fields
    from new_horizons.app.intake.read import read_document

    doc = run("read", lambda: read_document(path),
              lambda r: f"{r['pages']} page{'s' if r['pages'] != 1 else ''} · {r['engine']}")
    preview = _sample_preview(path) or _preview(doc["page_pngs"][0], sha)

    ext = run("extract", lambda: extract_fields(doc["text"], doc["page_pngs"][0], use_vlm),
              lambda e: f"{e['kind']} · {sum(1 for c in e['field_checks'] if c['verified'])} fields "
                        f"verified · {e['engine']}")
    fields, kind = ext["fields"], ext["kind"]
    verified = {c["field"] for c in ext["field_checks"] if c["verified"] is not False}
    recon_in = {k: fields.get(k) for k in RECON_FIELDS[kind]
                if fields.get(k) not in (None, "") and k in verified}

    recon = run("reconcile", lambda: R.check_document(recon_in),
                lambda r: f"{sum(1 for c in r.get('checks', []) if c.get('status') == 'pass')}/"
                          f"{len(r.get('checks', []))} checks passed · {r.get('verdict')}")
    terms = run("terms", lambda: step_terms(recon),
                lambda ts: f"{len(ts)} sections · "
                           + ", ".join(f"{t['source'].removesuffix('.md')} §{t['section']}" for t in ts[:3]))

    def _compose():
        t0 = time.time()
        tmpl = template_alert(recon, fields)
        if recon.get("verdict") != "discrepancy":
            return {**tmpl, "actions": [{**x, "by": "rule"} for x in tmpl["actions"]],
                    "composer": "template", "composer_mode": "template",
                    "ms": int((time.time() - t0) * 1000)}
        try:
            llm = compose_llm(model, recon, fields, terms)
        except Exception as exc:
            llm = None
            _audit("intake_compose_error", {"model": model, "error": f"{type(exc).__name__}: {exc}"[:200]})
        alert, composer = validate(llm, tmpl, terms)
        if composer == "template":
            alert = {**alert, "actions": [{**x, "by": "rule"} for x in alert["actions"]]}
        return {**alert, "composer": model if composer.startswith("llm") else "template",
                "composer_mode": composer, "ms": int((time.time() - t0) * 1000)}

    alert = run("compose", _compose,
                lambda a: f"{a['verdict']} · {len(a['actions'])} actions · {a['composer']}")

    out = {
        "doc": {"name": path.name, "path": str(path), "kind": doc["kind"], "doc_kind": kind,
                "pages": doc["pages"], "sha256": sha, "preview_png": preview},
        "read": {k: v for k, v in doc.items() if k != "page_pngs"},
        "fields": fields,
        "field_checks": ext["field_checks"],
        "extract": {"engine": ext["engine"], "ms": ext["ms"], "kind": kind,
                    **({"vlm_error": ext["vlm_error"]} if ext.get("vlm_error") else {})},
        "recon": recon,
        "terms": terms,
        "alert": alert,
        "steps": steps,
        "timings": timings,
        "model": model,
        "total_ms": int((time.time() - t_all) * 1000),
        "cached": False,
    }
    _audit("intake_alert", {"doc": path.name, "sha256": sha, "model": model, "kind": kind,
                            "verdict": alert["verdict"], "hold": alert["hold_payment"],
                            "ref": recon.get("ref"), "unit_id": recon.get("unit_id"),
                            "failed": [c.get("id") for c in recon.get("discrepancies", [])],
                            "cites": [a["cite"] for a in alert["actions"] if a.get("cite")]})
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(out, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--model", default=os.environ.get("LLM_MODEL_DEFAULT", "qwen3:8b"))
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-vlm", action="store_true")
    a = ap.parse_args()
    r = process(a.path, a.model, on_step=lambda s: print(f"  [{s['status']:7s}] {s['label']}: "
                                                          f"{s['detail']} ({s['ms']} ms)"),
                use_cache=not a.no_cache, use_vlm=False if a.no_vlm else None)
    print(json.dumps(r["alert"], ensure_ascii=False, indent=1))
    print("timings", r["timings"], "total", r["total_ms"])
