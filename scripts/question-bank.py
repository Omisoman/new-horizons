"""Rehearse the bilingual question set against the live agent — the scorecard.

    uv run python scripts/question-bank.py --set docs/question-set.yaml [--only S04 S09]
    uv run python scripts/question-bank.py --set docs/question-set.yaml --model llama3.1:8b
    uv run python scripts/question-bank.py --render-md docs/question-set.yaml   # no model

Asks each question through the same graph the app uses and grades the answer:
language (shared.text.lang, the same check the harness enforces), every
must-include figure, the expected citation, and whether a known question was
answered by its metric intent. A question passes when its language, figures and
citation are all right. Writes dist/question-set-results-<model>.json (with the
pass rate sojourner' evaluation gate reads) and prints a table.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

_INLINE = re.compile(r"([a-z0-9-]+\.md)\s*(?:§|section\s*)\s*([\d.]+)", re.I)


# ---- the question set -----------------------------------------------------------

def load_set(path: Path, only=None) -> list[dict]:
    """The set in file order. `only` keeps those ids plus the questions they
    follow — a follow-up asked without its parent has no thread to follow."""
    import yaml
    qs = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not only:
        return qs
    by_id, keep = {q["id"]: q for q in qs}, set()
    for qid in only:
        while qid in by_id and qid not in keep:
            keep.add(qid)
            qid = by_id[qid].get("follows")
    return [q for q in qs if q["id"] in keep]


def _cited(r: dict) -> list[str]:
    answer = r.get("answer") or ""
    stated = r.get("citations") or [{"source": s, "section": x} for s, x in _INLINE.findall(answer)]
    return sorted({f"{c.get('source', '')} §{c.get('section') or c.get('page') or ''}"
                   for c in stated})


def run_set(path: Path, model: str, graph, out: Path | None = None, only=None) -> int:
    """Run a question-set YAML: language, figures, citation and intent, per question."""
    from new_horizons.shared.harness.graph import ask
    from new_horizons.shared.text.lang import figure_found, script_ok

    qs = load_set(path, only)
    threads: dict[str, str] = {}
    stamp = int(time.time())
    results = []
    for q in qs:
        thread = threads.get(q.get("follows") or "") or f"set-{q['id']}-{stamp}"
        threads[q["id"]] = thread
        t0 = time.time()
        try:
            r = ask(graph, q["q"], model, thread)
        except Exception as exc:
            r = {"answer": f"ERROR {type(exc).__name__}: {exc}", "citations": [],
                 "tool_trace": [], "route": "error"}
        secs = round(time.time() - t0, 1)
        answer = r.get("answer") or ""
        cited = _cited(r)
        want = q.get("must_include") or []
        found = [f for f in want if figure_found(f, answer)]
        metric = r.get("metric") or {}
        used = bool(metric.get("used"))
        results.append({
            **q, "answer": answer, "seconds": secs, "route": r.get("route"),
            "lang_ok": script_ok(answer, q["lang"]),
            "figures_found": found, "figures_expected": want,
            "figures_ok": len(found) == len(want),
            "citation_ok": not q.get("cite") or q["cite"] in cited, "cited": cited,
            "metric": metric or None, "intent_expected": q.get("intent"),
            "intent_hit": bool(q.get("intent")) and used and metric.get("intent") == q.get("intent"),
            "metric_off_script": not q.get("intent") and used,
            "rewritten": r.get("rewritten"),
            "unverified_figures": r.get("unverified_figures") or [],
            "tools": [t["tool"] for t in r.get("tool_trace") or []]})
        x = results[-1]
        via = f"metric:{metric.get('intent')}" if used else (x["route"] or "-")
        print(f"{q['id']} {q['lang']}  lang={'ok ' if x['lang_ok'] else 'BAD'} "
              f"figures={len(found)}/{len(want)} cite={'ok ' if x['citation_ok'] else '-- '} "
              f"{secs:5.1f}s  {via[:26]:<26} {answer[:50].replace(chr(10), ' ')}", flush=True)

    out = out or ROOT / "dist" / f"question-set-results-{re.sub(r'[:.]', '-', model)}.json"
    passed = sum(1 for x in results if x["lang_ok"] and x["figures_ok"] and x["citation_ok"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": model, "set": str(path), "passed": passed,
                               "total": len(results),
                               "pass_rate": round(passed / len(results), 4) if results else 0.0,
                               "results": results}, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    n = len(results)
    count = lambda key: sum(1 for x in results if x[key])
    known = [x for x in results if x["intent_expected"]]
    used = [x for x in results if (x["metric"] or {}).get("used")]
    print(f"\n{count('lang_ok')}/{n} right language · {count('figures_ok')}/{n} all figures · "
          f"{count('citation_ok')}/{n} citation · {sum(x['intent_hit'] for x in known)}/"
          f"{len(known)} intent hits · {sum(x['seconds'] <= 10 for x in used)}/{len(used)} "
          f"metric answers ≤10 s · {sum(x['seconds'] for x in results):.0f}s")
    misses = {
        "language": [x["id"] for x in results if not x["lang_ok"]],
        "figures": [x["id"] for x in results if not x["figures_ok"]],
        "citation": [x["id"] for x in results if not x["citation_ok"]],
        "intent": [x["id"] for x in known if not x["intent_hit"]],
        "metric on off-script": [x["id"] for x in results if x["metric_off_script"]],
        "metric >10 s": [x["id"] for x in used if x["seconds"] > 10],
    }
    for label, ids in misses.items():
        print(f"  {label} misses: {', '.join(ids) or 'none'}")
    res = out.resolve()
    print(f"pass rate {passed}/{n} (language, every figure and the citation)")
    print(f"-> {res.relative_to(ROOT) if res.is_relative_to(ROOT) else res}")
    return 0


def render_md(path: Path) -> Path:
    """docs/question-set.md from the YAML — the table people read."""
    qs = load_set(path)
    cell = lambda v: str(v).replace("|", "\\|").replace("\n", " ").strip()
    rel = path.resolve().relative_to(ROOT) if path.resolve().is_relative_to(ROOT) else path
    n_en, n_ar = sum(q["lang"] == "en" for q in qs), sum(q["lang"] == "ar" for q in qs)
    lines = [
        "# Demo question set — expected answers", "",
        f"{len(qs)} questions, {n_en} English and {n_ar} Arabic, shuffled. Generated from "
        f"`{rel}`; edit the YAML, then run "
        f"`uv run python scripts/question-bank.py --render-md {rel}`.", "",
        "**An Arabic question is answered in Arabic only, an English question in English "
        "only.** Identifiers (AQ-03, WO-2026-0042, INV-2026-0418), citations "
        "(pump-maintenance-sop.md §3), code spans and EUR are language-neutral. Currency: "
        "EUR in English, يورو in Arabic.", "",
        "Every figure is ground truth. The metric resolvers "
        "(`src/new_horizons/app/analytics/metrics.py`) read the same artifacts as the "
        "screens, and `tests/test_validation.py` pins them. **Intent** is the known "
        "question it should match in `agents/analytics/intents.yaml`; — means off-script "
        "(the free agent answers). **Follows** means it is asked on that question's thread.", "",
        f"Run it: `uv run python scripts/question-bank.py --set {rel} "
        "[--model llama3.1:8b] [--only S04 S09]`", "",
        "| # | Lang | Screen | Intent | Question | Expected answer | Must include | Must cite | Follows |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for q in qs:
        lines.append("| " + " | ".join(cell(v) for v in (
            q["id"], q["lang"].upper(), q["screen"], q.get("intent") or "—", q["q"], q["a"],
            ", ".join(q.get("must_include") or []) or "—", q.get("cite") or "—",
            q.get("follows") or "—")) + " |")
    out = path.with_suffix(".md")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=Path, default=ROOT / "docs" / "question-set.yaml",
                    help="the question-set YAML (default docs/question-set.yaml)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", nargs="*", help="question ids, e.g. S04 S09")
    ap.add_argument("--render-md", type=Path, metavar="YAML",
                    help="regenerate the .md next to a question-set YAML (no model)")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    absolute = lambda p: p if p.is_absolute() else Path.cwd() / p  # noqa: E731

    if a.render_md:
        out = render_md(absolute(a.render_md))
        print(f"-> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
        return 0

    import new_horizons.app.analytics.agent_tools  # noqa: F401  (the farm's tools + metrics)
    from new_horizons.shared.harness.graph import build_graph
    from new_horizons.shared.llm.client import REGISTRY as MODELS

    model = a.model or os.environ.get("LLM_MODEL_DEFAULT", "qwen3:8b")
    if model not in MODELS:
        print(f"unknown model {model}; known: {list(MODELS)}")
        return 2
    graph = build_graph(with_memory=True)     # follow-ups need the thread history
    return run_set(absolute(a.set), model, graph, a.out and absolute(a.out), a.only)


if __name__ == "__main__":
    sys.exit(main())
