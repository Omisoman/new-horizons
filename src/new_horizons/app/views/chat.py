"""Chat — RAG over the knowledge base, SQL over the five farm databases, and
document intake: attach a file and the reconciliation alert lands here.
The agent answers in the language of the question, whatever the app language."""

import uuid
from html import escape

import streamlit as st

from new_horizons.app import intake_view as V
from new_horizons.app import ui_common as U

tr = U.tr
model = st.session_state.get("model", U.default_model())
compare_with = st.session_state.get("compare_with")
st.session_state.setdefault("thread_id", f"ui-{uuid.uuid4().hex[:8]}")
log = st.session_state.setdefault("chat_log", [])

U.page_header(
    tr("Ask the agent.", "اسأل الوكيل."),
    tr("Answers cite the knowledge base or the query they ran. Attach an invoice or a lab "
       "report and the agent reconciles it against the farm systems.",
       "تستشهد الإجابات بقاعدة المعرفة أو بالاستعلام الذي نُفّذ. أرفق فاتورة أو تقرير مختبر "
       "ليطابقه الوكيل مع أنظمة المزرعة."),
    [U.chip(tr("Synthetic data", "بيانات تركيبية"))]
    + [U.chip(U.model_label(m), "strong") for m in (model, compare_with) if m])

SUGGESTIONS = [
    (tr("Pump failure", "تعطل المضخة"),
     tr("How many kilograms did AQ-03 lose in the week after the pump failure, and what does the "
        "maintenance SOP say the response time should have been?",
        "كم كيلوغراماً خسرت الوحدة AQ-03 في الأسبوع التالي لتعطل المضخة، وماذا تقول إجراءات الصيانة "
        "عن زمن الاستجابة المطلوب؟")),
    (tr("Reconciliation", "المطابقة"),
     tr("How much is at risk across the reconciliation exceptions?",
        "كم المبلغ المعرّض للخطر في استثناءات المطابقة؟")),
    (tr("Harvests", "الحصاد"),
     tr("Which harvests were never shipped, and who logged them?",
        "أي عمليات حصاد لم تُشحن أبداً ومن سجّلها؟")),
    (tr("pH probe", "مجس الحموضة"),
     tr("Is the pH drift on AQ-04 a sensor problem or a chemistry problem?",
        "هل انحراف الحموضة في الوحدة AQ-04 مشكلة مجس أم مشكلة كيمياء؟")),
]


def _head(m: str, res: dict | None = None) -> str:
    ms = (res or {}).get("tokens", {}).get("ms")
    return (f"<div style='display:flex;gap:.5rem;align-items:center;margin-bottom:.35rem'>"
            f"{U.chip(U.model_label(m), 'strong')}"
            f"{U.chip(f'{ms / 1000:.1f}s' if ms is not None else '…')}</div>")


def _render_answer(res: dict) -> None:
    st.markdown(res.get("answer", ""))
    stated = res.get("citations") or U.extract_citations(res.get("answer", ""))
    tools_run = [t["tool"] for t in res.get("tool_trace") or []]
    kb, tool_refs, invented = U.check_citations(stated, tools_run)
    cites = [U.cite(c["source"], c["section"]) for c in kb]
    cites += [f"via {t}" for t in dict.fromkeys(tool_refs)]
    if cites:
        st.markdown("<p class='ac-subtle ac-mono'>" + " · ".join(dict.fromkeys(cites)) + "</p>",
                    unsafe_allow_html=True)
    # A narrowed query is the failure mode that looks like a right answer, so the
    # SQL behind a figure sits under it, not only inside the trace.
    for t in res.get("tool_trace") or []:
        if t["tool"] == "sql_query" and t.get("ok"):
            sql = " ".join(str(t["args"].get("sql", "")).split())
            st.markdown(f"<p class='ac-subtle ac-mono' style='opacity:.75'>"
                        f"{escape(sql[:180])}{'…' if len(sql) > 180 else ''}</p>",
                        unsafe_allow_html=True)
    metric, unverified = res.get("metric") or {}, res.get("unverified_figures") or []
    chips = []
    if metric.get("used"):                   # answered by the metrics layer, not the free agent
        chips.append(U.chip(tr("metric", "مؤشر")))
    if unverified:                           # figures nothing this turn supported
        n = len(unverified)
        chips.append(U.chip(tr(f"{n} unverified figure{'s' if n > 1 else ''} removed",
                               f"حُذف {n} رقم غير متحقق منه"), "amber"))
    if invented:
        # Never render a source that is not in the knowledge base.
        n = len(invented)
        chips.append(U.chip(tr(f"{n} unverified citation{'s' if n > 1 else ''} removed",
                               f"حُذف {n} استشهاد غير متحقق منه"), "amber"))
    elif not cites:
        chips.append(U.chip(tr("No citation", "بلا استشهاد"), "amber"))
    if chips:
        st.markdown(" ".join(chips), unsafe_allow_html=True)
    tk, trace = res.get("tokens", {}), res.get("tool_trace", [])
    secs, tok = f"{tk.get('ms', 0) / 1000:.1f}s", f"{tk.get('input', 0)}→{tk.get('output', 0)}"
    with st.expander(tr(f"Trace · {res.get('route')} · {len(trace)} tool calls · {secs} · {tok} tokens",
                        f"التتبع · {res.get('route')} · {len(trace)} استدعاء أداة · {secs} · {tok} رمز")):
        if res.get("rewritten"):
            st.code(f"question read as -> {res['rewritten']}", language="text")
        if metric.get("intent"):
            st.code(f"intent {metric['intent']} · score {metric.get('score')} · "
                    f"{'answered, ' + str(metric.get('phrasing')) + ' phrasing' if metric.get('used') else metric.get('reason')}",
                    language="text")
        if unverified:
            st.code(f"removed unverified figures: {', '.join(unverified)}", language="text")
        for t in trace:
            st.code(f"{t['tool']}({t['args']}) -> {'ok' if t['ok'] else 'ERROR'} in {t['ms']}ms",
                    language="text")


def _queue_question(text: str) -> None:
    """Suggestion cards: a callback, so the question is answered in the same run
    as the click (an st.rerun() here cost a second run)."""
    st.session_state["pending_question"] = text


def _render(entry: dict) -> None:
    kind = entry.get("kind")
    if entry["role"] == "user":
        if kind == "attachment":
            st.markdown(U.chip(f"{tr('Attached', 'مرفق')} · {entry['content']}"),
                        unsafe_allow_html=True)
        else:
            st.markdown(entry["content"])
    elif kind == "intake":
        V.alert_card(entry["result"])
        V.governance_row(entry["result"],
                         key_suffix="-chat-" + str(entry["result"]["doc"].get("sha256", ""))[:6])
        with st.expander(tr("Reconciliation call — every check", "استدعاء المطابقة — كل الفحوص")):
            st.markdown(V.checks_table(entry["result"]), unsafe_allow_html=True)
    else:
        st.markdown(_head(entry.get("model", model), entry["result"]), unsafe_allow_html=True)
        _render_answer(entry["result"])


def _ask(question: str) -> None:
    paused, who, _ = U.agent_paused()
    if paused:                        # the kill switch stops automated actions
        st.warning(tr(f"Agent paused by {who or 'an operator'} — the agent will not answer "
                      "until it is resumed in Settings.",
                      f"أوقف {who or 'أحد المشغّلين'} الوكيل مؤقتاً — لن يجيب الوكيل حتى "
                      "يُستأنف من الإعدادات."), icon=":material/pause:")
        return
    last_intake = next((e["result"] for e in reversed(log) if e.get("kind") == "intake"), None)
    prompt = f"{V.chat_context(last_intake)}\n\n{question}" if last_intake else question
    if compare_with:
        st.caption(tr("Compare mode runs the two models one after the other — "
                      "one 8B model resident at a time.",
                      "وضع المقارنة يشغّل النموذجين واحداً تلو الآخر — نموذج 8B واحد "
                      "في الذاكرة في كل مرة."))
        for col, m in zip(st.columns(2), (model, compare_with)):
            with col, U.card(f"compare-{m.replace(':', '-').replace('.', '-')}", height=560):
                head = st.empty()
                head.markdown(_head(m), unsafe_allow_html=True)
                with st.spinner(tr(f"{U.model_label(m)} is thinking…", f"{U.model_label(m)} يفكّر…")):
                    res = U.ask_agent(prompt, m, f"{st.session_state['thread_id']}-{m}")
                head.markdown(_head(m, res), unsafe_allow_html=True)
                _render_answer(res)
        return
    with st.chat_message("assistant", avatar=":material/smart_toy:"):
        head = st.empty()
        head.markdown(_head(model), unsafe_allow_html=True)
        with st.spinner(tr("thinking…", "جارٍ التفكير…")):
            res = U.ask_agent(prompt, model, st.session_state["thread_id"])
        head.markdown(_head(model, res), unsafe_allow_html=True)
        _render_answer(res)
    log.append({"role": "assistant", "model": model, "result": res})


for entry in log:
    with st.chat_message(entry["role"], avatar=":material/person:" if entry["role"] == "user"
                         else ":material/smart_toy:"):
        _render(entry)

if not log:
    U.section(tr("Try", "جرّب"), tr("or attach a document with the paperclip",
                                    "أو أرفق مستنداً بمشبك الورق"))
    for i, (col, (label, text)) in enumerate(zip(st.columns(4), SUGGESTIONS)):
        with col, U.card(f"suggest-{i}", height=250):
            st.markdown(f"<div class='ac-label'>{label}</div>"
                        f"<p dir='auto' style='margin:.55rem 0 0;font-size:14px;"
                        f"line-height:1.55;color:var(--ac-fg-muted)'>{text}</p>",
                        unsafe_allow_html=True)
            st.button(tr("Ask", "اسأل"), key=f"suggest-btn-{i}", type="primary",
                      on_click=_queue_question, args=(text,))

sub = st.chat_input(tr("Ask about harvests, alerts, water, reconciliation… or attach a document",
                       "اسأل عن الحصاد والتنبيهات والمياه والمطابقة… أو أرفق مستنداً"),
                    accept_file=True, file_type=["pdf", "png", "jpg", "jpeg"])
question = st.session_state.pop("pending_question", None)
files = []
if sub:
    question = (sub.text or "").strip() or None
    files = list(sub.files or [])

for f in files:
    path = V.save_upload(f.name, f.getvalue())
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(U.chip(f"{tr('Attached', 'مرفق')} · {f.name}"), unsafe_allow_html=True)
    with st.chat_message("assistant", avatar=":material/smart_toy:"):
        result = V.run(path, model)
        if result:
            st.session_state["intake_result"] = result
            V.post_to_chat(result)
            st.session_state["unread_alerts"] = []
            V.alert_card(result)

if question:
    log.append({"role": "user", "content": question})
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(question)
    _ask(question)
