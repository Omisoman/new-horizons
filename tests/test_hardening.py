"""The analytics agent's structural guarantees (docs/brief-agent-hardening.md).

The model is scripted: each test decides what the "LLM" replies, so what is
asserted is the harness — a figure nothing supports is stripped and audited, a
bare figure is sent back then declined, a follow-up never inherits a period, a
metric phrasing that changes a number never reaches the screen. Only the
metric resolvers and the matcher are tested against live data in
tests/test_metrics.py.
"""

import pytest

from new_horizons.shared.harness import graph as G
from new_horizons.shared.harness import tools as toolbox
from new_horizons.shared.text.lang import figures, question_lang, script_ok

KB_HIT = {"source": "pump-maintenance-sop.md", "section": "3", "heading": "", "page": None,
          "synthetic": True,
          "text": "A water-pump failure alert is answered on site within 2 hours."}


class Script:
    """A fake chat model: pops scripted replies, records every prompt."""

    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def __call__(self, model, messages, usage, actor="analytics-agent"):
        self.prompts.append("\n".join(str(m.content) for m in messages))
        usage["ms"] = usage.get("ms", 0) + 1
        return self.replies.pop(0)


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setenv("METRICS_PHRASING", "model")     # exercise the phrasing checks
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(G, "audit", lambda actor, kind, payload: events.append((kind, payload)))
    monkeypatch.setattr(G, "_schema_digest", lambda: "")
    monkeypatch.setattr(toolbox, "kb_search_in", lambda kb_dir, q, k=6: {"hits": [KB_HIT]})
    from langgraph.checkpoint.memory import MemorySaver
    monkeypatch.setattr("new_horizons.shared.harness.memory.checkpointer", lambda: MemorySaver())
    return events


def _toolset(name, results, retrieval=True, metrics=None):
    calls = []

    def run(tool, args):
        calls.append((tool, args))
        return results.pop(0) if results else {"error": "no scripted result"}

    G.register_toolset(name, {"sql_query": toolbox.REGISTRY["sql_query"]}, run,
                       system_md="test prompt", retrieval=retrieval, kb_dir="/nowhere",
                       metrics=metrics)
    return calls


def _ask(graph, q, thread, toolset):
    return G.ask(graph, q, "qwen3:8b", thread, toolset=toolset)


# ---- figure verification and the figure gate ----------------------------------

def test_injected_hallucination_is_stripped_and_audited(harness, monkeypatch):
    _toolset("t-strip", [{"columns": ["count"], "rows": [["34504"]]}])
    hallucinated = '{"final": "There are 34,504 readings and 125,000 EUR is outstanding."}'
    monkeypatch.setattr(G, "_call", Script(
        '{"route": "data"}',
        '{"tool": "sql_query", "args": {"sql": "SELECT count(*) FROM telemetry.readings"}}',
        hallucinated,           # sent back once: 125,000 is in no tool result
        hallucinated))          # insisted: stripped
    res = _ask(G.build_graph(with_memory=False), "How many readings are there?", "t1", "t-strip")
    assert res["answer"] == "There are 34,504 readings and [unverified] EUR is outstanding."
    assert res["unverified_figures"] == ["125,000"]
    gate = [p for kind, p in harness if kind == "figure_gate"]
    assert gate == [{"stage": "sent back", "figures": ["125,000"], "route": "data",
                     "after_tools": True}]
    stripped = [p for kind, p in harness if kind == "unverified_figures"]
    assert stripped and stripped[0]["figures"] == ["125,000"]


def test_an_answer_that_is_only_an_unsupported_figure_is_declined(harness, monkeypatch):
    _toolset("t-zero", [{"columns": ["n"], "rows": [["412"]]}])     # (an empty list would support "0")
    monkeypatch.setattr(G, "_call", Script(
        '{"route": "both"}',
        '{"tool": "sql_query", "args": {"sql": "SELECT 1"}}',
        '{"final": "0"}', '{"final": "0"}'))
    res = _ask(G.build_graph(with_memory=False), "كم عدد التنبيهات المفتوحة؟", "t0", "t-zero")
    assert res["answer"] == G.DECLINE["ar"] and res["unverified_figures"] == ["0"]


def test_a_figure_from_the_retrieved_context_needs_no_tool(harness, monkeypatch):
    _toolset("t-kb", [])
    monkeypatch.setattr(G, "_call", Script(
        '{"route": "knowledge"}',
        '{"final": "A water-pump failure is answered on site within 2 hours.",'
        ' "citations": [{"source": "pump-maintenance-sop.md", "section": "3"}]}'))
    res = _ask(G.build_graph(with_memory=False), "How fast must a pump failure be answered?",
               "t2", "t-kb")
    assert "2 hours" in res["answer"] and not res["unverified_figures"]
    assert not [k for k, _ in harness if k == "figure_gate"]


def test_a_bare_figure_is_sent_back_once_then_declined(harness, monkeypatch):
    _toolset("t-gate", [])
    script = Script('{"route": "both"}',
                    '{"final": "412 alerts are open."}',
                    '{"final": "0"}')
    monkeypatch.setattr(G, "_call", script)
    res = _ask(G.build_graph(with_memory=False), "كم عدد التنبيهات المفتوحة؟", "t3", "t-gate")
    assert res["answer"] == G.DECLINE["ar"]
    stages = [p["stage"] for k, p in harness if k == "figure_gate"]
    assert stages == ["sent back", "declined"]
    assert G.GATE_NUDGE in script.prompts[-1]


def test_after_the_nudge_a_real_query_is_accepted(harness, monkeypatch):
    _toolset("t-gate2", [{"columns": ["count"], "rows": [["7"]]}])
    monkeypatch.setattr(G, "_call", Script(
        '{"route": "data"}',
        '{"final": "9 work orders."}',
        '{"tool": "sql_query", "args": {"sql": "SELECT count(*) FROM maintenance.work_orders WHERE closed_ts IS NULL"}}',
        '{"final": "7 work orders are open."}'))
    res = _ask(G.build_graph(with_memory=False), "How many work orders are open?", "t4", "t-gate2")
    assert res["answer"] == "7 work orders are open." and not res["unverified_figures"]


def test_a_data_question_answered_without_any_tool_is_sent_back(harness, monkeypatch):
    _toolset("t-unqueried", [{"columns": ["count"], "rows": [["7"]]}])
    script = Script('{"route": "both"}',
                    '{"final": "لا توجد أوامر عمل مفتوحة حالياً."}',   # no query, no figure
                    '{"tool": "sql_query", "args": {"sql": "SELECT count(*) FROM maintenance.work_orders WHERE closed_ts IS NULL"}}',
                    '{"final": "7 أوامر عمل مفتوحة."}')
    monkeypatch.setattr(G, "_call", script)
    res = _ask(G.build_graph(with_memory=False), "قديش عنا أوامر عمل مفتوحة هلّق؟", "t6", "t-unqueried")
    assert res["answer"] == "7 أوامر عمل مفتوحة." and G.GATE_NO_TOOL in script.prompts[2]
    assert [p["stage"] for k, p in harness if k == "figure_gate"] == ["sent back"]


def test_a_tool_returning_none_is_an_error_not_a_crash(harness, monkeypatch):
    G.register_toolset("t-none", {"sql_query": toolbox.REGISTRY["sql_query"]},
                       lambda tool, args: None, system_md="p", kb_dir="/nowhere")
    cited = ('{"final": "That unit is not in the telemetry system.", '
             '"citations": [{"source": "data-dictionary.md", "section": "2"}]}')
    script = Script('{"route": "data"}', '{"tool": "sql_query", "args": {"sql": "SELECT 1"}}',
                    cited, cited)                       # sent back once after the failure, then kept
    monkeypatch.setattr(G, "_call", script)
    res = _ask(G.build_graph(with_memory=False), "Status of unit AQ-09?", "t5", "t-none")
    assert res["tool_trace"][0]["ok"] is False
    assert res["answer"] == "That unit is not in the telemetry system."
    assert G.GATE_AFTER_ERROR in script.prompts[3]
    assert res["citations"] == []                       # nothing ran, so no section supports it


def test_a_failed_query_is_retried_not_reported(harness, monkeypatch):
    _toolset("t-retry", [{"error": 'column "eur" does not exist — hint: eur is a column of '
                                   'harvest.shipments — join it on unit_id'},
                         {"columns": ["share"], "rows": [["0.244"]]}])
    script = Script(
        '{"route": "data"}',
        '{"tool": "sql_query", "args": {"sql": "SELECT sum(eur) FROM harvest.harvests"}}',
        '{"final": "It cannot be calculated from the harvests table; use the shipments table."}',
        '{"tool": "sql_query", "args": {"sql": "SELECT 0.244 AS share"}}',
        '{"final": "24.4% of revenue is tomato."}')
    monkeypatch.setattr(G, "_call", script)
    res = _ask(G.build_graph(with_memory=False), "What share of revenue is tomato?", "t7",
               "t-retry")
    assert res["answer"] == "24.4% of revenue is tomato." and G.GATE_AFTER_ERROR in script.prompts[3]
    assert [t["ok"] for t in res["tool_trace"]] == [False, True]


# ---- follow-ups ------------------------------------------------------------------

def test_a_dated_question_followed_by_an_undated_one_does_not_carry_the_date(harness, monkeypatch):
    _toolset("t-carry", [{"columns": ["count"], "rows": [["57"]]},
                         {"columns": ["count"], "rows": [["212"]]}])
    graph = G.build_graph(with_memory=True)
    monkeypatch.setattr(G, "_call", Script(
        '{"route": "data"}',
        '{"tool": "sql_query", "args": {"sql": "SELECT count(*) FROM controller.alerts WHERE opened_ts >= \'2026-01-01\'"}}',
        '{"final": "57 alerts were raised in 2026."}'))
    first = _ask(graph, "How many alerts were raised in 2026?", "carry", "t-carry")
    assert "57" in first["answer"]
    second_turn = Script(
        "How many work orders were opened in 2026?",    # the rewrite tries to carry the year
        '{"route": "data"}',
        '{"tool": "sql_query", "args": {"sql": "SELECT count(*) FROM maintenance.work_orders"}}',
        '{"final": "212 work orders."}')
    monkeypatch.setattr(G, "_call", second_turn)
    res = _ask(graph, "how many work orders?", "carry", "t-carry")
    assert res["rewritten"] is None                   # the carried period was refused
    assert res["answer"] == "212 work orders."
    # nothing after the rewrite call sees the earlier year: no pasted history
    assert all("2026" not in p for p in second_turn.prompts[1:])


def test_a_dependent_follow_up_is_rewritten_before_routing(harness, monkeypatch):
    _toolset("t-follow", [{"ok": 1}, {"kg": 61.4}])
    graph = G.build_graph(with_memory=True)
    monkeypatch.setattr(G, "_call", Script(
        '{"route": "data"}',
        '{"tool": "sql_query", "args": {"sql": "SELECT 1"}}',
        '{"final": "AQ-03 lost its water pump."}'))
    _ask(graph, "Which unit had the pump failure?", "follow", "t-follow")
    script = Script("How many kilograms did the AQ-03 pump failure cost us?",
                    '{"route": "data"}',
                    '{"tool": "sql_query", "args": {"sql": "SELECT 2"}}',
                    '{"final": "61.4 kg of tomato."}')
    monkeypatch.setattr(G, "_call", script)
    res = _ask(graph, "And how much did that cost us?", "follow", "t-follow")
    assert res["rewritten"].startswith("How many kilograms did the AQ-03 pump failure")
    assert "AQ-03 pump failure" in script.prompts[-1]  # the tool loop reads the standalone question
    assert [k for k, _ in harness].count("rewrite") == 1


def test_ops_toolsets_keep_history_and_skip_the_checks(harness, monkeypatch):
    _toolset("t-ops", [], retrieval=False)
    graph = G.build_graph(with_memory=True)
    monkeypatch.setattr(G, "_call", Script('{"final": "Build 41 queued."}'))
    _ask(graph, "build the service", "ops", "t-ops")
    script = Script('{"final": "Deployed 3 containers."}')
    monkeypatch.setattr(G, "_call", script)
    res = _ask(graph, "deploy it", "ops", "t-ops")
    assert res["answer"] == "Deployed 3 containers." and not res["unverified_figures"]
    assert "(previous user): build the service" in script.prompts[0]
    assert res["route"] == "data" and res["rewritten"] is None


# ---- metrics phrasing --------------------------------------------------------------

PAYLOAD = {"figures": {"lost": "61.40", "share": "0.42"},
           "template_en": "AQ-03 lost 61.40 kg after the pump failure, 0.42× its usual week.",
           "template_ar": "خسرت AQ-03 ما مقداره 61.40 كغ بعد تعطل المضخة، أي 0.42 من أسبوعها المعتاد.",
           "citation": {"source": "pump-maintenance-sop.md", "section": "3"},
           "citations": [{"source": "pump-maintenance-sop.md", "section": "3"}],
           "screen": "Reconcile"}


class FakeMetrics:
    def __init__(self, payload=PAYLOAD):
        self.payload, self.calls = payload, []

    def match(self, question, guard=None, previous=None):
        self.calls.append({"question": question, "previous": previous})
        return {"intent": "pump_failure_loss", "score": 0.93, "second": 0.7,
                "runner_up": "open_alerts", "family": "data", "matched": True, "reason": "ok"}

    def resolve(self, intent, question):
        return dict(self.payload)


@pytest.mark.parametrize("answer, problem", [
    ("AQ-03 lost 61.40 kg, 0.42× its usual week.", None),
    ("AQ-03 lost about 60 kg, 0.42× its usual week.", "dropped"),
    ("AQ-03 lost 61.40 kg, 0.42× its usual week, over 7 days.", "added"),
    ("AQ-03 lost 61.40 kg, 0.42× its usual week at AQ-07.", "invented"),
    ("خسرت الوحدة 61.40 kg, 0.42 of a week.", "wrong language"),
])
def test_metric_phrasing_is_checked_figure_by_figure(answer, problem):
    got = G._phrasing_problem(answer, PAYLOAD, "en", "How much did the pump failure cost us?")
    assert (got is None) if problem is None else (problem in got)


def test_a_phrasing_that_changes_a_number_falls_back_to_the_template(harness, monkeypatch):
    G.register_toolset("t-metric", {}, lambda t, a: {}, system_md="p", kb_dir="/nowhere",
                       metrics=FakeMetrics())
    monkeypatch.setattr(G, "_call", Script("AQ-03 lost roughly 60 kg, 0.42× its usual week."))
    res = _ask(G.build_graph(with_memory=False), "How much did the pump failure cost us?", "m1",
               "t-metric")
    assert res["answer"] == PAYLOAD["template_en"]
    assert res["route"] == "metric" and res["tool_trace"][0]["tool"] == "metric:pump_failure_loss"
    assert res["metric"]["used"] and res["metric"]["phrasing"] == "template"
    assert res["citations"] == PAYLOAD["citations"]


def test_an_arabic_question_gets_the_arabic_answer(harness, monkeypatch):
    G.register_toolset("t-metric-ar", {}, lambda t, a: {}, system_md="p", kb_dir="/nowhere",
                       metrics=FakeMetrics())
    monkeypatch.setattr(G, "_call", Script("AQ-03 lost 61.40 kg, 0.42× its usual week."))
    res = _ask(G.build_graph(with_memory=False), "كم كلّفنا تعطل المضخة؟", "m2", "t-metric-ar")
    assert res["answer"] == PAYLOAD["template_ar"] and script_ok(res["answer"], "ar")


def test_a_faithful_phrasing_is_kept(harness, monkeypatch):
    G.register_toolset("t-metric-ok", {}, lambda t, a: {}, system_md="p", kb_dir="/nowhere",
                       metrics=FakeMetrics())
    monkeypatch.setattr(G, "_call", Script("The pump failure cost AQ-03 61.40 kg — 0.42× its usual week."))
    res = _ask(G.build_graph(with_memory=False), "How much did the pump failure cost us?", "m3",
               "t-metric-ok")
    assert res["answer"].startswith("The pump failure") and res["metric"]["phrasing"] == "model"


def _presentation_forms(text: str) -> str:
    """Arabic as some PDFs and chat apps paste it: isolated presentation forms."""
    import unicodedata

    def form(ch):
        try:
            return unicodedata.lookup(f"{unicodedata.name(ch)} ISOLATED FORM")
        except (KeyError, ValueError):
            return ch
    return "".join(form(c) for c in text)


def test_arabic_pasted_as_presentation_forms_is_still_arabic(harness, monkeypatch):
    fake = FakeMetrics()
    G.register_toolset("t-pf", {}, lambda t, a: {}, system_md="p", kb_dir="/nowhere",
                       metrics=fake)
    monkeypatch.delenv("METRICS_PHRASING")
    pasted = _presentation_forms("أرني الفاتورة التي أُوقفت الأسبوع الماضي ولماذا")
    assert pasted != "أرني الفاتورة التي أُوقفت الأسبوع الماضي ولماذا"
    assert question_lang(pasted) == "ar"
    res = _ask(G.build_graph(with_memory=False), pasted, "pf", "t-pf")
    assert res["lang"] == "ar" and res["answer"] == PAYLOAD["template_ar"]
    seen = fake.calls[0]["question"]
    assert not any("\ufb50" <= c <= "\ufeff" for c in seen)   # the matcher saw plain letters
    assert question_lang(seen) == "ar" and "الأسبوع" in seen


def test_the_next_turn_knows_which_intent_answered_the_last(harness, monkeypatch):
    fake = FakeMetrics()
    G.register_toolset("t-prev", {}, lambda t, a: {}, system_md="p", kb_dir="/nowhere",
                       metrics=fake)
    graph = G.build_graph(with_memory=True)
    monkeypatch.setattr(G, "_call", Script("AQ-03 lost 61.40 kg, 0.42× its usual week."))
    _ask(graph, "How much did the pump failure cost us?", "prev", "t-prev")
    monkeypatch.setattr(G, "_call", Script("And how much did that cost us?",   # rewrite: unchanged
                                           "61.40 kg, 0.42× its usual week."))
    res = _ask(graph, "And how much did that cost us?", "prev", "t-prev")
    assert [c["previous"] for c in fake.calls] == [None, "pump_failure_loss"]
    assert res["rewritten"] is None            # a no-op rewrite is not reported as one


# ---- language ------------------------------------------------------------------------

def test_wrong_script_is_translated_with_figures_locked(harness, monkeypatch):
    _toolset("t-lang", [{"rows": [["55"]]}])
    monkeypatch.setattr(G, "_call", Script(
        '{"route": "data"}',
        '{"tool": "sql_query", "args": {"sql": "SELECT 55"}}',
        '{"final": "55 open alerts."}',
        "55 تنبيهاً مفتوحاً."))
    res = _ask(G.build_graph(with_memory=False), "كم تنبيهاً مفتوحاً لدينا؟", "l1", "t-lang")
    assert res["answer"] == "55 تنبيهاً مفتوحاً."


def test_a_translation_that_moves_a_figure_is_refused(harness, monkeypatch):
    _toolset("t-lang2", [{"rows": [["55"]]}])
    monkeypatch.setattr(G, "_call", Script(
        '{"route": "data"}',
        '{"tool": "sql_query", "args": {"sql": "SELECT 55"}}',
        '{"final": "55 open alerts."}',
        "56 تنبيهاً مفتوحاً."))
    res = _ask(G.build_graph(with_memory=False), "كم تنبيهاً مفتوحاً لدينا؟", "l2", "t-lang2")
    assert "55" in res["answer"] and "56" not in res["answer"] and script_ok(res["answer"], "ar")


def test_a_translation_may_spell_out_a_small_number(harness, monkeypatch):
    G.register_toolset("t-lang3", {"kb_search": toolbox.REGISTRY["kb_search"]}, lambda t, a: {},
                       system_md="p", kb_dir="/nowhere")
    monkeypatch.setattr(toolbox, "kb_search_in", lambda kb_dir, q, k=6: {"hits": [{
        **KB_HIT, "source": "supplier-invoice-controls.md",
        "text": "If the stock count is not reconciled within 2 working days, refer it to the owner."}]})
    monkeypatch.setattr(G, "_call", Script(
        '{"route": "knowledge"}',
        '{"final": "Refer it to the owner if the stock count is not reconciled within 2 working days."}',
        "تُحال المسألة إلى المالك إذا لم يُطابق جرد المخزون خلال يومي عمل."))
    res = _ask(G.build_graph(with_memory=False), "ما الإجراء إذا لم يطابق الجرد؟", "l3", "t-lang3")
    assert res["answer"].endswith("يومي عمل.")


def test_metric_answers_default_to_the_template(harness, monkeypatch):
    monkeypatch.delenv("METRICS_PHRASING")
    G.register_toolset("t-metric-default", {}, lambda t, a: {}, system_md="p", kb_dir="/nowhere",
                       metrics=FakeMetrics())
    script = Script()
    monkeypatch.setattr(G, "_call", script)
    res = _ask(G.build_graph(with_memory=False), "Is the farm making money?", "m5",
               "t-metric-default")
    assert res["answer"] == PAYLOAD["template_en"] and script.prompts == []
    assert res["metric"]["phrasing"] == "template"


def test_a_stuck_tool_loop_answers_in_the_users_language(harness, monkeypatch):
    _toolset("t-stuck", [{"rows": [["1"]]}])
    same = '{"tool": "sql_query", "args": {"sql": "SELECT 1"}}'
    monkeypatch.setattr(G, "_call", Script('{"route": "data"}', same, same, same))
    res = _ask(G.build_graph(with_memory=False), "كم مضخة متوقفة؟", "g1", "t-stuck")
    assert res["answer"] == G.STUCK["ar"] and "LOOP_GUARD" not in res["answer"]
    assert [p["reason"][:10] for k, p in harness if k == "guard"] == ["LOOP_GUARD"]


def test_knowledge_intents_answer_with_the_template_without_a_model_call(harness, monkeypatch):
    G.register_toolset("t-metric-kb", {}, lambda t, a: {}, system_md="p", kb_dir="/nowhere",
                       metrics=FakeMetrics({**PAYLOAD, "phrasing": "template"}))
    script = Script()
    monkeypatch.setattr(G, "_call", script)
    res = _ask(G.build_graph(with_memory=False), "How much did the pump failure cost us?", "m4",
               "t-metric-kb")
    assert res["answer"] == PAYLOAD["template_en"] and script.prompts == []


def test_language_and_figure_primitives():
    a = "وAQ-03 بـ42 قراءة (715.51 يورو) حسب pump-maintenance-sop.md §3 في 2026-Q3، و`water_level_cm`"
    assert [f["text"] for f in figures(a)] == ["42", "715.51"]
    assert script_ok(a, "ar") and not script_ok("المبلغ is outstanding", "ar")
    assert question_lang("ما معنى dissolved_o2_mg_l؟") == "ar"
    assert question_lang("Why was INV-2026-0418 held?") == "en"
    note, q = G._split_note("[Latest document intake — inv.pdf: supplier SUP-004]\n\nشو لازم أعمل؟")
    assert note.startswith("[Latest") and q == "شو لازم أعمل؟"
