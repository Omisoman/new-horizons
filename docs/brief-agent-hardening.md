# Agent hardening — correctness in code, not in the prompt

The analytics agent answers questions about a farm's own numbers in front of
people who will act on them. An 8B model will, given the chance, write a number
it never looked up. This document is the design that removes the chance. Every
mechanism below lives in `src/new_horizons/shared/harness/graph.py` or the
metrics layer, is audited, and is pinned by `tests/test_hardening.py` and
`tests/test_metrics.py`.

## The three structural gaps

Measured on two 8B models over a bilingual question set, every wrong figure
traced to one of three gaps in a plain tool loop — not to the prompt:

1. **A figure needs no evidence.** A loop that accepts `{"final": ...}` on the
   first step, with zero tool calls, lets the model answer "0" or copy a number
   from an example.
2. **Numbers are never verified.** Citations are easy to check against the
   index; figures need the same treatment.
3. **Follow-ups are not resolved.** History pasted as flat lines makes the
   model carry the last turn's filter or figure ("how many work orders?" after
   a dated question inherits the date).

Prompt patches — the schema, status values and dates typed into `SYSTEM.md` —
work on the day and drift the day after. The design replaces persuasion with
enforcement.

## A — the metrics layer (known questions)

The questions people ask most are known in advance, with known answers. They
are matched, computed and templated:

- `app/agents/analytics/intents.yaml`: one entry per intent — `id`,
  `paraphrases` (English and Arabic, colloquial included), `resolver`, `cite`
  (a key in `ingest/kb_synthetic/citations.yaml`), `screen`, plus `not:`
  (narrower questions it must not answer), `follow_ups` and `after`.
- Matcher: paraphrases embedded with bge-m3 (already resident for the KB),
  cosine against the question, cached on disk by a hash of `intents.yaml`.
  Above the threshold and the margin → the resolver answers; below → the free
  agent.
- Resolvers (`app/analytics/metrics.py`) are pure reads of what the screens read
  — `data/analytics/*.json`, `data/mock_meta.json`, the read-only DSN, the audit
  chain — so chat, screens and `tests/test_validation.py` cannot disagree.
- Phrasing is the resolver's template by default. Model phrasing is opt-in
  (`METRICS_PHRASING=model`) and is kept only when every payload figure
  survives, no other number appears and the script matches the language.
  Measured: model rewordings kept every figure yet changed the meaning in 4 of
  13 answers — checks on figures cannot see that, a template cannot do it.

## B — the free agent (everything else)

Deterministic, no new prompt prose:

1. **Figure gate.** On a `data` or `both` route, a final answer with a number
   and no successful tool call this turn is sent back once with a nudge; the
   second time it becomes "I can't give a figure for that without querying the
   data", in the question's language. Both are audited.
2. **Figure verification.** Every number in the answer must appear in a tool
   result or the retrieved context of this turn. Unsupported numbers are
   stripped, returned as `unverified_figures`, audited, and shown as an amber
   chip in Chat.
3. **Follow-up resolution.** A dependent question is rewritten into a
   standalone one before routing (one short model call); a rewrite that adds a
   period the user did not say is refused.
4. **Generated schema.** The schema section of the prompt is built from
   `information_schema` plus the values of small categories, code formats and
   date ranges (`shared/db/introspect.py`), cached per process. `SYSTEM.md`
   carries no schema, status value, date or example figure.
5. **Language enforcement.** An answer in the wrong script is translated once
   with its figures locked; if that fails, a template keeps only the verified
   figures.
6. **Router.** The model's route is overruled by the nearest intent's family
   (data / knowledge) when the question is close to a known one, so Arabic
   morphology and colloquial wording do not matter.
7. **SQL hints.** A query that errors or returns rows the schema says cannot be
   empty comes back as an error with a schema-derived hint (a code compared
   with a numeric id, two code columns that never match), so the model retries.

## C — the question set

`docs/question-set.yaml` holds the bilingual scorecard: 13 English and 13
Arabic questions, shuffled, each with `lang`, `screen`, `q`, `a`,
`must_include`, `cite`, `intent` and optional `follows`. An Arabic question's
expected answer is Arabic only; identifiers (AQ-03, WO-2026-0042), citations
(`pump-maintenance-sop.md §3`) and code spans are neutral. Currency: `EUR` in
English, `يورو` in Arabic. Every figure is ground truth from the generator
(`ingest/validation/expected-results.json`).

Run it: `uv run python scripts/question-bank.py --set docs/question-set.yaml
[--model llama3.1:8b]`. sojourner' evaluation gate runs the same set
on `llama3.1:8b` before a deploy may be approved.

## Constraints that held

- One 8B chat model resident; bge-m3 may stay resident.
- Never put an example figure in a prompt; the model copies it.
- Instructions that were tried and made things worse: a "how to answer money
  questions" section (accuracy fell, a figure was invented).
- `shared/harness/` is shared with sojourner's ops agent: `build_graph` keyword
  args, `register_toolset`, `scoped_tools` and the JSON tool protocol stay
  intact.
