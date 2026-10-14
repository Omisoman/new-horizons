"""The metrics layer against live data: periods, aliases, the matcher on
colloquial Arabic and follow-ups, the schema digest, and the graph reading a
record named by its number. Needs Postgres (make db-up mock) and, for the
matcher, Ollama's bge-m3."""

import os

import pytest

from new_horizons.shared.harness import graph as G
from new_horizons.shared.text.lang import script_ok

pytestmark = pytest.mark.domain


def _db_up() -> bool:
    try:
        import psycopg
        psycopg.connect(os.environ.get("DATABASE_URL_RO",
                                       "postgresql://farm_ro:farm-ro@localhost:5432/horizons"),
                        connect_timeout=3).close()
        return True
    except Exception:
        return False


def _embeddings_up() -> bool:
    try:
        from new_horizons.shared.kb.store import embed_texts
        return bool(embed_texts(["ping"]))
    except Exception:
        return False


db = pytest.mark.skipif(not _db_up(), reason="postgres not running")
embeddings = pytest.mark.skipif(not _embeddings_up(), reason="bge-m3 embeddings not reachable")


def _canon(text: str) -> str:
    from new_horizons.app.analytics.metrics import _alias_rules
    rules = _alias_rules({"code": "AQ", "width": 2, "words": {"en": ["unit", "grow unit", "tank"],
                                                             "ar": ["وحدة", "حوض"]}},
                         {"AQ-01", "AQ-02", "AQ-03", "AQ-04"})
    rules += _alias_rules({"code": "TEC", "width": 2, "words": {"en": ["technician", "tech"], "ar": ["فني"]}},
                          {"TEC-06"})
    for rule, sub in rules:
        text = rule.sub(sub, text)
    return text


@pytest.mark.parametrize("typed, read_as", [
    ("How many alerts did unit 3 raise in July?", "How many alerts did unit AQ-03 raise in July?"),
    ("كم تنبيهاً للوحدة 3 في تموز؟", "كم تنبيهاً للوحدة AQ-03 في تموز؟"),
    ("what did tank #4 harvest", "what did tank AQ-04 harvest"),
    ("show AQ3 and AQ 1", "show AQ-03 and AQ-01"),
    ("technician 6 logged what?", "technician TEC-06 logged what?"),
    ("unit 9", "unit 9"),                                # no such unit: left as typed
    ("unit 2026 readings", "unit 2026 readings"),        # a year, not a unit number
    ("aq 3 and WO-2026-0074", "aq 3 and WO-2026-0074"),  # lower-case two letters are not a code
    ("AQ-03", "AQ-03"),
])
def test_a_record_named_by_number_reads_as_its_code(typed, read_as):
    assert _canon(typed) == read_as and _canon(read_as) == read_as


def test_the_graph_matches_and_queries_with_the_code(monkeypatch):
    events = []
    monkeypatch.setattr(G, "audit", lambda actor, kind, payload: events.append((kind, payload)))

    class AliasMetrics:
        calls = []

        def canonical(self, text):
            return _canon(text)

        def match(self, question, guard=None, previous=None):
            self.calls.append(question)
            return {"intent": "pump_failure", "score": 0.95, "second": 0.5, "runner_up": None,
                    "family": "data", "matched": True, "reason": "ok"}

        def resolve(self, intent, question):
            return {"figures": {}, "template_en": "AQ-03's pump failed.", "template_ar": "تعطلت مضخة AQ-03.",
                    "citation": {"source": "pump-maintenance-sop.md", "section": "4"},
                    "citations": [{"source": "pump-maintenance-sop.md", "section": "4"}]}
    fake = AliasMetrics()
    G.register_toolset("t-alias", {}, lambda t, a: {}, system_md="p", kb_dir="/nowhere", metrics=fake)
    res = G.ask(G.build_graph(with_memory=False), "What happened to unit 3's pump?", "qwen3:8b",
                "al", toolset="t-alias")
    assert fake.calls[0] == "What happened to unit AQ-03's pump?"
    assert res["rewritten"] == "What happened to unit AQ-03's pump?"
    assert [p for k, p in events if k == "alias"] == [
        {"from": "What happened to unit 3's pump?", "to": "What happened to unit AQ-03's pump?"}]


def test_period_words_are_canonical_and_identifiers_are_not_years():
    from new_horizons.app.analytics.metrics import periods
    assert periods("how many alerts in 2026?") == {"2026"}
    assert periods("what did we ship in August?") == {"month"}
    assert periods("ماذا حصدنا وبعنا في تموز؟") == {"month"}
    assert periods("قديش حصدنا بحزيران؟") == {"month"}                   # an attached preposition
    assert periods("Which supplier may we use?") == set()
    assert periods("who decided on WO-2026-0074?") == set()
    assert periods("show me the invoice held last week") == {"recent_week"}


@db
def test_every_resolver_answers_in_both_languages():
    from new_horizons.app.analytics import metrics as M
    for name, fn in M.RESOLVERS.items():
        p = fn("")
        assert script_ok(p["template_en"], "en") and script_ok(p["template_ar"], "ar"), name
        assert p["citation"]["source"].endswith(".md"), name


@db
def test_a_month_is_a_slot_of_harvest_and_sales():
    from new_horizons.app.analytics import metrics as M
    july, aug = M.harvest_and_sales("in July")["figures"], M.harvest_and_sales("في آب")["figures"]
    whole = M.harvest_and_sales("")["figures"]
    assert july != aug and float(whole["kg_harvested"]) > float(aug["kg_harvested"].replace(",", ""))


@db
def test_the_held_invoice_answers_only_for_its_own_records():
    from new_horizons.app.analytics import metrics as M
    assert M.held_invoice("Why was INV-2026-0418 held?") is not None
    assert M.held_invoice("Why was INV-2026-0111 held?") is None


@db
def test_aliases_read_the_codes_that_exist():
    from new_horizons.app.analytics.metrics import Metrics
    m = Metrics(cache_dir=None)
    assert m.canonical("How many alerts did unit 3 raise?") == "How many alerts did unit AQ-03 raise?"
    assert m.canonical("unit 7 and technician 12") == "unit 7 and technician 12"
    assert m.canonical("technician 6") == "technician TEC-06"


@db
def test_the_schema_digest_carries_code_formats_keys_and_small_categories():
    from new_horizons.shared.db.introspect import schema_digest
    schema_digest.cache_clear()
    digest = schema_digest()
    assert "unit_id{AQ-01|AQ-02|AQ-03|AQ-04}" in digest            # few values: listed, not a format
    assert "actuator{air_pump|dosing_pump|feeder|water_pump}" in digest
    assert "technician_code<TEC-01..TEC-08>" in digest
    keys = digest.split("business keys:")[1].split("\n")[0]
    for key in ("unit_id", "item_code", "technician_code", "alert_no"):
        assert key in keys, key


@embeddings
@pytest.mark.parametrize("question, intent", [
    ("قديش خسرنا طماطم بسبب عطل المضخة؟", "pump_failure_loss"),
    ("شو في إنذارات مفتوحة هلأ؟", "open_alerts"),
    ("مين سجّل حصاد وما انشحن؟", "ghost_harvests"),
    ("ليش بتطلع الحموضة كل اثنين؟", "dosing_schedule"),
])
def test_matcher_understands_colloquial_arabic(question, intent):
    from new_horizons.app.analytics.metrics import default
    m = default().match(question)
    assert m["matched"] and m["intent"] == intent, m


@embeddings
@pytest.mark.parametrize("question, previous, intent", [
    ("And how many kilograms did that cost us?", "pump_failure", "pump_failure_loss"),
    ("وكم كيلوغراماً كلّفنا ذلك؟", "pump_failure", "pump_failure_loss"),
    ("Is that a biosecurity problem?", "unmetered_feed", "feed_biosecurity"),
    ("And how many kilograms did that cost us?", None, None),   # no conversation: not a known question
])
def test_follow_ups_count_only_after_the_intent_they_follow(question, previous, intent):
    from new_horizons.app.analytics.metrics import default
    m = default().match(question, previous=previous)
    assert (m["matched"] and m["intent"] == intent) if intent else not m["matched"], m


@embeddings
@pytest.mark.parametrize("question", [
    "How many alerts did AQ-03 raise in July?",         # narrower than the farm-wide count
    "What did AQ-03 harvest in July?",                  # a unit the intent does not cover
    "مرحبا",
    "How many fish does AQ-03 have?",
])
def test_matcher_leaves_near_misses_to_the_free_agent(question):
    from new_horizons.app.analytics.metrics import default
    assert not default().match(question)["matched"]
