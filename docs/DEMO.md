# Demo script — New Horizons, the farm analytics agent (8 min)

One MacBook, 16 GB, offline. Language: Settings → العربية runs the whole app in Arabic
(right to left); the chat answers in the language of the question either way. Never run
this demo and Sojourner's tier stack together.

## Pre-flight (10 min before, in order)

```sh
source scripts/ollama-env.sh && ollama serve        # terminal 1, stays open
make db-up
curl -s localhost:11434/api/version                  # ollama answers
ollama run qwen3:8b "مرحبا" --verbose                # warm the default model
ollama ps                                            # ONLY qwen3:8b resident, VLM unloaded
```

- First time on a machine: `make models`, `uv sync`, `make mock` (five farm systems +
  analytics + the three sample scans), `make kb` (knowledge base, ~5 s).
- Activity Monitor → Memory: pressure **green** before starting.
- `data/kb/stats.json` exists; `data/analytics/` and `data/samples/` are populated.
- Sojourner's stack DOWN (`make demo2-down` there). Postgres alone is shared.
- `ollama serve` MUST run with `scripts/ollama-env.sh` sourced: one 8B model resident,
  `num_ctx` 8192, KV cache q8_0.
- The synthetic farm runs 2026-06-01 … 2026-08-29 — anchor date questions inside it.
- Document intake caches by file hash (`data/intake_cache/`): run the three samples once
  in pre-flight for an instant fallback, or clear the cache for a truly live run.
- Theme (Settings → Black · White · Gray) and language (English · العربية) are app-wide and
  survive restarts — set them before the room fills. Sidebar squares are icon-only; hover
  shows the page name.

## The walk

`make demo1` → http://localhost:8501

| min | screen | say |
|---|---|---|
| 0–1 | Overview | "One aquaponics farm — four grow units (pepper, lettuce, tomato, basil), 97 European perch, five systems: telemetry, the controller, maintenance, harvest, supplies. 34,504 sensor readings at 99.84 % uptime, 16 alerts, none open. Synthetic and generic; one agent sits across all five." |
| 1–2 | Reconcile | "What the controller was told against what happened, harvested against shipped, consumed against bought. 220.89 EUR at risk — ranked by money: six harvests nobody shipped are 171.72 of it, the pump that ran with no level rise 35.28, feed nobody bought 13.89. Each sits next to the rule it breaks." Select a row → **Awaiting · Farm Manager** → **Escalate to owner**. |
| 2–3 | Drift | "The tomato unit's air pump ran 60.4 % of the day in the heatwave against 26.6 % in June. And AQ-04's pH looks like drift — it is the probe: the lab read 6.89 while the probe said 7.28, and the 21 August calibration stepped it back. The two sensor dropouts are gaps, not zeros — they never raise a drift flag." |
| 3–4 | Patterns | "TEC-06 logged six harvests — 31.52 kg — that never left the building, none countersigned. The harvest-shipping procedure requires a second signature at the cold room; that is the control that broke." |
| 4–6 | Documents → **Invoice · held** | "A supplier invoice arrives as a scan. On-device OCR, the vision model extracts every field — and every figure is checked against the OCR text. Then the reconciliation call: INV-2026-0418 bills 2.95 EUR/kg against 2.40 on the purchase order (+22.9 %, outside the 5 % tolerance), and it comes from SUP-007, not the ordered supplier SUP-001. Payment on hold; the actions come from the supplier-invoice controls, cited." Then **Invoice · clean** (INV-2026-0397): "it reconciles — it doesn't cry wolf." Then **Lab report** (LAB-2026-0019): "recalibrate AQ-04." |
| 6–7 | Chat | The alert is already there. Ask the verification question: **How many kilograms did AQ-03 lose in the week after the pump failure, and what does the maintenance SOP say the response time should have been?** → 9.80 kg (6.31 harvested on 20 July against 16.11 usual), the SOP says on site within 2 hours — alert AL-2026-0001 waited 113.2. Cites `pump-maintenance-sop.md §3`; open the trace: one metric call, no free-form SQL. Then the same in Arabic: **كم كيلوغراماً خسرت الوحدة AQ-03 في الأسبوع التالي لتعطل المضخة، وماذا تقول إجراءات الصيانة عن زمن الاستجابة المطلوب؟** |
| 7–8 | Admin center + Changes | "Who escalated that, and what do I hand the auditor?" → **Audit trail** from the finding: time, actor, action, rule, outcome, hash. **Admin center** (shield icon): the **Governance** tab and the full **Audit trail**. In **Settings** press **Pause agent** once — intake and chat refuse and say who paused them — then resume; **Switch model** → Llama 3.1: "one 8B resident, same graph, same tools — in production this endpoint is your inference cluster, one URL change." Last, **Changes** (rocket): "every change to this app shipped by [sojourner](https://github.com/omarsoman/sojourner) — built, tested, evaluated and approved by a person — read from this same chain." |

Every figure above is pinned by `tests/test_validation.py` against
`src/new_horizons/app/ingest/validation/expected-results.json` (written by the
generator), and the 26-question bilingual set (`docs/question-set.md`) rehearses them:
`uv run python scripts/question-bank.py --set docs/question-set.yaml [--model llama3.1:8b]`.

## Recovery

- **Model stalls / slow first token**: `ollama ps` — if two 8B models are loaded,
  `ollama stop <other>`; re-ask. Worst case `pkill ollama` and restart from pre-flight
  (models are cached, warm-up ≈ 20 s).
- **VLM got loaded by a stray intake**: `ollama stop qwen3-vl:4b` (it runs keep_alive 0 —
  it self-unloads within seconds anyway).
- **Streamlit page hangs**: rerun from the browser (R) — data is cached on disk; never
  re-run `make mock` or `make kb` live.
- **Compare mode feels slow**: it is sequential by design (16 GB budget) — say so; qwen3
  answers first.
- **Memory pressure yellow/red**: stop anything else holding a model, wait for `ollama ps`
  to show one model, continue. Sojourner's stack must be down.
