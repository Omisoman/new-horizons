"""The question set is well-formed — static checks, no model, no database.

docs/question-set.yaml is what the room hears and what the scorecard (and
sojourner' evaluation gate) grades, so its own expected answers must
pass the rules the agent is held to: the language of the question, the figures
it must carry, citations that exist.
"""

import pytest
import yaml

from new_horizons.paths import APP, ROOT
from new_horizons.shared.text.lang import figure_found, script_ok

SET = ROOT / "docs" / "question-set.yaml"
SPEC = yaml.safe_load((APP / "agents" / "analytics" / "intents.yaml").read_text(encoding="utf-8"))
REG = yaml.safe_load((APP / "ingest" / "kb_synthetic" / "citations.yaml").read_text(encoding="utf-8"))
QS = yaml.safe_load(SET.read_text(encoding="utf-8"))


def test_thirteen_questions_per_language_unique_ids():
    assert len(QS) == 26 and len({q["id"] for q in QS}) == 26
    assert sum(q["lang"] == "en" for q in QS) == 13
    assert sum(q["lang"] == "ar" for q in QS) == 13


def test_languages_are_shuffled_not_grouped_or_alternating():
    langs = [q["lang"] for q in QS]
    run = longest = 1
    for a, b in zip(langs, langs[1:]):
        run = run + 1 if a == b else 1
        longest = max(longest, run)
    assert longest == 2, "no more than two of one language in a row, and not strict alternation"


def test_every_intent_is_covered_and_every_intent_exists():
    ids = {i["id"] for i in SPEC["intents"]}
    used = {q["intent"] for q in QS if q.get("intent")}
    assert used <= ids, sorted(used - ids)
    assert ids <= used, f"uncovered intents: {sorted(ids - used)}"
    assert sum(q.get("intent") is None for q in QS) == 2, "two off-script questions"


def test_follow_ups_share_a_thread_with_an_earlier_question_in_the_same_language():
    order = {q["id"]: i for i, q in enumerate(QS)}
    by_id = {q["id"]: q for q in QS}
    follows = [q for q in QS if q.get("follows")]
    assert len(follows) >= 2 and {q["lang"] for q in follows} == {"en", "ar"}
    for q in follows:
        parent = by_id[q["follows"]]
        assert parent["lang"] == q["lang"] and order[parent["id"]] < order[q["id"]], q["id"]
        intent = next(i for i in SPEC["intents"] if i["id"] == q["intent"])
        assert parent["intent"] in (intent.get("after") or []), q["id"]


def test_colloquial_questions_in_both_languages_are_marked():
    marked = [line.split()[2] for line in SET.read_text(encoding="utf-8").splitlines()
              if line.startswith("- id:") and "# colloquial" in line]
    langs = {q["lang"] for q in QS if q["id"] in marked}
    assert len(marked) >= 4 and langs == {"en", "ar"}


def test_the_verification_question_is_in_both_languages():
    asked = [q for q in QS if q.get("intent") == "pump_failure_loss" and "AQ-03" in q["q"]]
    assert {q["lang"] for q in asked} == {"en", "ar"}
    assert all(q["cite"] == "pump-maintenance-sop.md §3" for q in asked)


@pytest.mark.parametrize("q", QS, ids=[q["id"] for q in QS])
def test_expected_answer_obeys_the_language_rule(q):
    assert script_ok(q["a"], q["lang"]), q["a"]
    assert "$" not in q["a"] and "€" not in q["a"]


@pytest.mark.parametrize("q", QS, ids=[q["id"] for q in QS])
def test_must_include_figures_are_in_the_expected_answer(q):
    for f in q.get("must_include") or []:
        assert figure_found(f, q["a"]), (q["id"], f)


@pytest.mark.parametrize("q", [q for q in QS if q.get("cite")], ids=lambda q: q["id"])
def test_cited_sections_exist(q):
    source, section = q["cite"].split(" §")
    assert any(e["source"] == source and str(e["section"]) == section for e in REG.values()), q["cite"]
