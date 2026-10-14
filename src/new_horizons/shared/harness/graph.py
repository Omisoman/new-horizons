"""Model-agnostic LangGraph agent.

    prepare → metric                                    → answer   (a known question)
    prepare → route → retrieve → tool_loop → finalize   → answer   (everything else)

One compiled graph serves every chat model — the model comes from
config["configurable"]["model"] and tool calling rides the JSON protocol
(shared/harness/protocol.py), so qwen3:8b, llama3.1:8b and deepseek-r1:8b
produce the same trace shapes. Every model call and tool call is audited.

Toolsets with retrieval (the analytics chat) are hardened in code rather than
in the prompt (docs/brief-agent-hardening.md):
- prepare: a follow-up is rewritten into a standalone question, then matched
  against the metrics layer's known intents.
- metric: a matched intent is answered from computed figures with the
  resolver's template (model phrasing is opt-in and falls back to the template
  whenever it changes a number).
- tool_loop: a figure with nothing behind it this turn is sent back once, then
  declined; figures no tool result or retrieved passage supports are stripped
  and reported.
- finalize: an answer in the wrong script is translated once, figures locked.
Toolsets without retrieval (demo 2's ops agent) keep the original path —
route → tool_loop with thread history, no rewriting, no figure checks.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from new_horizons.paths import APP
from new_horizons.shared.audit.audit import audit
from new_horizons.shared.harness import tools as toolbox
from new_horizons.shared.harness.protocol import (
    Final,
    ProtocolError,
    RETRY_MESSAGE,
    ToolCall,
    parse_decision,
    render_tools,
)
from new_horizons.shared.llm.client import chat_model
from new_horizons.shared.text.arabic import EASTERN_DIGITS
from new_horizons.shared.text.lang import (
    evidence,
    figures,
    identifiers,
    question_lang,
    same_value,
    script_ok,
    strip_unsupported,
    supported,
)

MAX_STEPS = 6
FAMILY_FLOOR = 0.60          # nearest-intent score from which its family steers the router
LANG_NAME = {"en": "English", "ar": "Arabic"}
UNVERIFIED = {"en": "[unverified]", "ar": "[غير موثّق]"}
DECLINE = {"en": "I can't give a figure for that without querying the data.",
           "ar": "لا يمكنني إعطاء رقم لذلك دون الاستعلام من البيانات."}
STUCK = {"en": "I couldn't complete the query for that, so I have no answer to give. "
               "Please rephrase the question.",
         "ar": "تعذّر عليّ إكمال الاستعلام لهذا السؤال، لذلك لا أملك إجابة. يرجى إعادة صياغة السؤال."}
GATE_NUDGE = ("That answer states figures, but no tool ran this turn and the retrieved "
              "context does not contain them. Call the tool that returns them, then reply "
              'with {"final": ...}.')
GATE_NUDGE_AFTER_TOOLS = ("Some figures in that answer are in no TOOL_RESULT above and not in the "
                          "retrieved context. Query the data for them, then reply with "
                          '{"final": ...}.')
GATE_NO_TOOL = ("This question needs the databases, but no tool ran this turn. Call the tool "
                'that answers it, then reply with {"final": ...}.')
GATE_AFTER_ERROR = ("The tool call failed — its TOOL_RESULT error above says what is wrong. Fix "
                    'the call and run it again, then reply with {"final": ...}.')
GUARDS = ("PROTOCOL_FAILURE", "LOOP_GUARD", "STEP_LIMIT")

# Pluggable toolsets — one graph, many personas. The app registers "analytics"
# (default); sojourner's tier-2 registers "ops" with its RBAC-wrapped registry;
# host tenants register a scoped toolset each (build_graph keyword args).
TOOLSETS: dict[str, dict] = {}
# Known-question layers by toolset name. The app registers its metrics factory
# here (app/analytics/agent_tools.py) — the harness never imports the app.
METRICS: dict[str, Any] = {}


def register_metrics(toolset: str, factory) -> None:
    """`factory()` returns the toolset's metrics layer (match / resolve)."""
    METRICS[toolset] = factory


def register_toolset(name: str, registry: dict, runner, system_md: str | None = None,
                     retrieval: bool = True, kb_dir: str | Path | None = None,
                     metrics=None) -> None:
    """`metrics`: an object with match(question, guard) / resolve(intent, question)
    (app/analytics/metrics.py) — known questions for this toolset. Only toolsets
    with retrieval use it."""
    TOOLSETS[name] = {"registry": registry, "run": runner, "system_md": system_md,
                      "retrieval": retrieval, "kb_dir": str(kb_dir) if kb_dir else None,
                      "metrics": metrics}


def scoped_tools(tools, kb_dir: str | Path | None = None) -> tuple[dict, Any]:
    """A registry subset and its runner: unknown names are rejected up front,
    tools outside the subset are refused at call time, and kb_search reads the
    scope's KB instead of the process-wide KB_DIR."""
    names = list(toolbox.REGISTRY) if tools is None else list(tools)
    unknown = [n for n in names if n not in toolbox.REGISTRY]
    if unknown:
        raise ValueError(f"unknown tools {unknown}; available: {list(toolbox.REGISTRY)}")
    registry = {n: toolbox.REGISTRY[n] for n in names}

    def run(name: str, args: dict) -> dict:
        if name not in registry:
            return {"error": f"unknown tool '{name}'. Available: {list(registry)}"}
        if name == "kb_search" and kb_dir is not None:
            try:
                return toolbox.kb_search_in(kb_dir, **args)
            except TypeError as exc:
                return {"error": f"bad args for kb_search: {exc}"}
            except Exception as exc:
                return {"error": f"{type(exc).__name__}: {exc}"}
        return toolbox.run_tool(name, args)

    return registry, run


def _analytics_metrics():
    """The app's metrics layer, or None when disabled (METRICS_ENABLED=0) or no
    app registered one (register_metrics)."""
    if os.environ.get("METRICS_ENABLED", "1") == "0" or "analytics" not in METRICS:
        return None
    try:
        return METRICS["analytics"]()
    except Exception as exc:
        audit("analytics-agent", "metrics_unavailable", {"error": f"{type(exc).__name__}: {exc}"})
        return None


def _toolset(config) -> dict:
    name = (config.get("configurable", {}) or {}).get("toolset", "analytics")
    return TOOLSETS[name]


def _overwrite(_old, new):
    return new


class AgentState(TypedDict, total=False):
    question: str
    history: Annotated[list[dict], _overwrite]     # prior turns (from checkpointer)
    route: str
    context: list[dict]
    tool_trace: list[dict]
    answer: str
    citations: list[dict]
    latency_ms: int
    tokens: dict
    # hardening — optional, so threads checkpointed before it still resume
    standalone: str                 # the question after follow-up resolution
    rewritten: str | None           # set when the rewrite changed the question
    lang: str | None                # the language the answer must be in
    metric: dict | None             # intent match (and its payload until answered)
    unverified_figures: list[str]   # figures stripped from the answer


def _model_name(config) -> str:
    return (config.get("configurable", {}) or {}).get(
        "model", os.environ.get("LLM_MODEL_DEFAULT", "qwen3:8b"))


def _system_md() -> str:
    p = Path(os.environ.get(
        "SYSTEM_MD", APP / "agents/analytics/SYSTEM.md"))
    return p.read_text() if p.exists() else "You are the Farm's analytics agent."


def _schema_digest() -> str:
    """The generated schema section, or nothing when the database is down."""
    try:
        from new_horizons.shared.db.introspect import schema_digest
        return schema_digest()
    except Exception:
        return ""


def _call(model_name: str, messages: list, usage: dict) -> str:
    llm = chat_model(model_name)
    t0 = time.time()
    resp = llm.invoke(messages)
    ms = int((time.time() - t0) * 1000)
    meta = resp.usage_metadata or {}
    usage["input"] = usage.get("input", 0) + meta.get("input_tokens", 0)
    usage["output"] = usage.get("output", 0) + meta.get("output_tokens", 0)
    usage["ms"] = usage.get("ms", 0) + ms
    audit("analytics-agent", "model_call",
          {"model": model_name, "ms": ms,
           "input_tokens": meta.get("input_tokens"),
           "output_tokens": meta.get("output_tokens")})
    content = resp.content or ""
    if not content.strip():
        # Some Ollama templates route the whole reply into the reasoning
        # channel (observed with qwen3-vl); recover the payload from there.
        ak = resp.additional_kwargs or {}
        content = ak.get("reasoning_content") or ak.get("reasoning") or ""
    return content


_THINK = re.compile(r"<think>.*?(?:</think>|\Z)", re.S)
_NOTE = re.compile(r"^\s*(\[[^\n]*\])[ \t]*\n\s*\n")


def _plain(raw: str) -> str:
    """A model's free-text reply without reasoning tags, fences or wrapping quotes."""
    t = _THINK.sub("", raw or "").strip()
    t = re.sub(r"^```\w*\s*|\s*```$", "", t).strip()
    if len(t) > 1 and t[0] in "\"'“«" and t[-1] in "\"'”»":
        t = t[1:-1].strip()
    return t


def _split_note(question: str) -> tuple[str, str]:
    """('[Latest document intake …]', the user's own words). The chat page puts
    the intake note in front of a question; language, rewriting and matching
    read only what the user typed."""
    m = _NOTE.match(question or "")
    return (m.group(1), question[m.end():].strip()) if m else ("", (question or "").strip())


# ---- nodes ------------------------------------------------------------------

_REWRITE_PROMPT = """Rewrite the user's LAST question as a standalone question.
- If it refers back to the conversation ("that", "it", "those", "the same", "ذلك", "هذا", "هذه"), replace the reference with what it points to, taken from the previous question or answer.
- If it can be understood on its own, copy it unchanged.
- Never add a date, period, status, filter or number that the LAST question does not contain.
- Write it in {lang}.
Reply with the question only, no explanation.

Example from another business:
Previous question: Which supplier delivered late most often?
LAST question: And what did that cost us?
Rewritten: What did the supplier that delivered late most often cost us?

Previous question: {prev_q}
Previous answer: {prev_a}
LAST question: {q}
Rewritten:"""

_YEAR_OR_QUARTER = re.compile(r"(?<![0-9])(?:19|20)\d{2}(?![0-9])|(?i:(?<![a-z])q[1-4](?![a-z0-9]))")


def _periods(text: str, metrics) -> set[str]:
    if metrics is not None and hasattr(metrics, "periods"):
        return set(metrics.periods(text))
    blank = text
    for ident in identifiers(text):
        blank = blank.replace(ident, " ")
    return {p.lower() for p in _YEAR_OR_QUARTER.findall(blank)}


def _rewrite(q: str, history: list[dict], lang: str, model_name: str, usage: dict,
             metrics) -> str:
    prev_q = next((t["content"] for t in reversed(history) if t["role"] == "user"), "")
    prev_a = next((t["content"] for t in reversed(history) if t["role"] == "assistant"), "")
    if not prev_q:
        return q
    try:
        raw = _call(model_name, [HumanMessage(_REWRITE_PROMPT.format(
            lang=LANG_NAME[lang], prev_q=_split_note(prev_q)[1][:400], prev_a=prev_a[:600], q=q))],
            usage)
    except Exception:
        return q
    text = _plain(raw)
    out = re.sub(r"^(?:rewritten(?: question)?|question|LAST question)\s*:\s*", "",
                 text.splitlines()[0].strip() if text else "", flags=re.I).strip()
    if not out or len(out) > 3 * len(q) + 200 or question_lang(out) != lang:
        return q
    if _periods(out, metrics) - _periods(q, metrics):
        return q                     # the rewrite carried a period over — the classic miss
    return q if _same_question(out, q) else out


def _same_question(a: str, b: str) -> bool:
    """Equal up to case, a leading 'and'/'و' and end punctuation."""
    norm = lambda t: re.sub(r"^(?:and\s+|so\s+|but\s+|و|ف)", "",  # noqa: E731
                            t.strip().casefold()).strip(" ?؟.!")
    return norm(a) == norm(b)


def prepare(state: AgentState, config) -> dict:
    """Reset the per-turn keys; for retrieval toolsets also resolve the
    question's language, rewrite a follow-up and match a known intent."""
    fresh = {"tokens": {}, "rewritten": None, "metric": None, "unverified_figures": [],
             "standalone": state["question"], "lang": None, "context": [],
             "tool_trace": [], "citations": []}
    ts = _toolset(config)
    if not ts["retrieval"]:
        return fresh
    # Arabic pasted as presentation forms (U+FE70–FEFF) read as English and
    # matched nothing (observed live on the S02 question). NFKC restores the
    # letters once, for language, rewriting, matching, periods and the tool loop.
    question = unicodedata.normalize("NFKC", state["question"])
    fresh = {**fresh, "question": question, "standalone": question}
    note, typed = _split_note(question)
    metrics = ts.get("metrics")
    q = typed
    if metrics is not None and hasattr(metrics, "canonical"):
        # "unit 3" → "unit AQ-03": records named by number reach the
        # identifiers, the resolvers and SQL (observed: the agent asked "which
        # database?" until the user typed the code)
        try:
            q = metrics.canonical(typed)
        except Exception:
            q = typed
        if q != typed:
            audit("analytics-agent", "alias", {"from": typed, "to": q})
            question = "\n\n".join(x for x in (note, q) if x)
            fresh = {**fresh, "question": question, "standalone": question}
    lang = question_lang(q)
    usage: dict = {}
    standalone = q
    if state.get("history"):
        standalone = _rewrite(q, state["history"], lang, _model_name(config), usage, metrics)
        if standalone != q:
            audit("analytics-agent", "rewrite", {"from": q, "to": standalone})
    out = {**fresh, "tokens": usage, "lang": lang, "standalone": standalone,
           "rewritten": standalone if standalone != typed else None}
    if metrics is None:
        return out
    previous = next((t.get("intent") for t in reversed(state.get("history") or [])
                     if t["role"] == "assistant"), None)
    try:
        # The user's own words first: an 8B rewrite of a complete question can
        # only blur it. The rewrite is tried when the words alone do not match.
        m = metrics.match(q, previous=previous)
        if not m["matched"] and standalone != q:
            spelled_out = metrics.match(standalone, guard=q, previous=previous)
            if spelled_out["matched"] or spelled_out["score"] > m["score"]:
                m = spelled_out
        if m["matched"]:
            payload = metrics.resolve(m["intent"], standalone)
            if payload is None:
                m = {**m, "matched": False, "reason": "resolver declined the question"}
            else:
                m = {**m, "payload": payload}
    except Exception as exc:        # embeddings or database down: the free agent answers
        m = {"matched": False, "reason": f"metrics unavailable: {type(exc).__name__}: {exc}"}
    audit("analytics-agent", "intent_match",
          {k: m.get(k) for k in ("intent", "score", "second", "runner_up", "follow_up",
                                 "matched", "reason")} | {"previous": previous})
    out["metric"] = m
    return out


_PHRASE_PROMPT = """Answer the question in {lang} using only the facts below. Copy every
number, code and identifier exactly as written and add no other number. At most
three sentences. Reply with the answer only.

Facts:
{facts}

Question: {q}"""


def _phrasing_problem(answer: str, payload: dict, lang: str, question: str) -> str | None:
    """Why a model's phrasing of a metric cannot be shown, or None if it can."""
    template = payload[f"template_{lang}"]
    if not answer:
        return "empty"
    if len(answer) > 2 * len(template) + 200:
        return "too long"
    if not script_ok(answer, lang):
        return "wrong language"
    got = [f["value"] for f in figures(answer)]
    # a payload figure is required in the language whose template writes it as a
    # number ("2 business days" is "يومي عمل" in Arabic)
    written = [f["value"] for f in figures(template)]
    required = [f["value"] for text in payload["figures"].values() for f in figures(str(text))
                if any(same_value(f["value"], w) for w in written)]
    missing = [v for v in required if not any(same_value(v, g) for g in got)]
    if missing:
        return f"dropped figures {missing}"
    sources = (payload["template_en"], payload["template_ar"], question,
               *map(str, payload["figures"].values()))
    allowed = [f["value"] for t in sources for f in figures(t)]
    added = [g for g in got if not any(same_value(g, a) for a in allowed)]
    if added:
        return f"added figures {added}"
    known = set(identifiers(" ".join(sources)))
    invented = [i for i in identifiers(answer) if i not in known]
    return f"invented identifiers {invented}" if invented else None


def metric_node(state: AgentState, config) -> dict:
    """Answer a matched intent: computed figures, model phrasing, template fallback."""
    m = dict(state["metric"])
    payload = m.pop("payload")
    lang = state.get("lang") or "en"
    q = state.get("standalone") or state["question"]
    usage = state.get("tokens", {})
    t0 = time.time()
    answer, phrasing = payload[f"template_{lang}"], "template"
    problem = "template phrasing (the default, or the intent's)"
    # Model phrasing is opt-in (METRICS_PHRASING=model). Measured on both 8B
    # models: every phrasing kept its figures, yet 4 of 13 changed the meaning —
    # "not provable" became "the business makes money", an escalation became
    # an approval. Figure checks cannot see that; the template cannot do it.
    if os.environ.get("METRICS_PHRASING", "template") == "model" \
            and payload.get("phrasing", "model") != "template":
        try:
            raw = _call(_model_name(config), [HumanMessage(_PHRASE_PROMPT.format(
                lang=LANG_NAME[lang], facts=payload[f"template_{lang}"], q=q))], usage)
            candidate = _plain(raw).translate(EASTERN_DIGITS)
            problem = _phrasing_problem(candidate, payload, lang, q)
            if problem is None:
                answer, phrasing = candidate, "model"
        except Exception as exc:
            problem = f"{type(exc).__name__}: {exc}"
    step = {"tool": f"metric:{m['intent']}", "args": {"score": m.get("score"), "phrasing": phrasing},
            "ok": True, "ms": int((time.time() - t0) * 1000)}
    usage["ms"] = usage.get("ms", 0) + step["ms"]    # the chat header shows a time, not "…"
    audit("analytics-agent", "tool_call",
          {**step, "figures": payload["figures"], "citations": payload["citations"],
           "template_because": problem if phrasing == "template" else None})
    info = {k: m.get(k) for k in ("intent", "score", "second", "runner_up", "follow_up", "reason")}
    return {"route": "metric", "context": [], "tool_trace": [step], "answer": answer,
            "citations": payload["citations"], "tokens": usage, "unverified_figures": [],
            "metric": {**info, "used": True, "phrasing": phrasing, "screen": payload.get("screen")}}


_ROUTE_PROMPT = """Classify the user question for an aquaponics farm's analytics agent.
Reply with ONE JSON object only: {{"route": "<data|knowledge|both|chat>"}}
- "data": needs the five operational databases — SYNTHETIC sensor readings,
  controller commands and alerts, maintenance work orders and technicians,
  harvests and shipments, supply purchases and consumption (counts, kilograms,
  euros, a grow unit's state, alerts, reconciliation exceptions)
- "knowledge": needs the Farm's documents — water-quality and feeding SOPs,
  maintenance and calibration procedures, harvest and shipping procedure,
  biosecurity rules, alert escalation, invoice controls (what the rule is,
  what to do)
- "both": needs documents and databases (e.g. a finding plus the rule it breaks)
- "chat": ONLY a greeting or a question about the agent itself. Anything asking
  about harvests, yield, money, alerts, pumps, water, fish, technicians or
  documents is never "chat" — including colloquial Arabic (كم صار، شو الوضع)
  and questions that open with مرحبا or hi before the real question.
Question: {q}"""


def route(state: AgentState, config) -> dict:
    if not _toolset(config)["retrieval"]:
        # Ops-style toolsets receive imperative pipeline instructions —
        # classification is meaningless and "chat" would skip the tool loop.
        return {"route": "data", "tokens": state.get("tokens", {})}
    usage = state.get("tokens", {})
    q = state.get("standalone") or state["question"]
    try:
        raw = _call(_model_name(config), [HumanMessage(_ROUTE_PROMPT.format(q=q))], usage)
        r = json.loads(raw[raw.find("{"):raw.rfind("}") + 1]).get("route", "both")
    except Exception:
        r = "both"
    if r not in ("data", "knowledge", "both", "chat"):
        r = "both"
    # The nearest known intent overrules a router that heard small talk or pure
    # documents in a business question — by meaning, so Arabic morphology and
    # colloquial wording do not matter.
    near = state.get("metric") or {}
    if near.get("score", 0.0) >= FAMILY_FLOOR:
        family = near.get("family", "data")
        if r == "chat":
            r = "knowledge" if family == "knowledge" else "both"
        elif r == "knowledge" and family == "data":
            r = "both"
    return {"route": r, "tokens": usage}


def retrieve(state: AgentState, config) -> dict:
    # Retrieval is cheap and grounding matters more than routing precision, so
    # EVERY question gets KB context — including one the router called "chat".
    # Toolsets without a KB skip it.
    ts = _toolset(config)
    if not ts["retrieval"]:
        return {"context": []}
    note, _ = _split_note(state["question"])
    query = " ".join(x for x in (note, state.get("standalone") or state["question"]) if x)
    kb_dir = ts.get("kb_dir")
    hits = (toolbox.kb_search_in(kb_dir, query, k=6) if kb_dir
            else toolbox.kb_search(query, k=6)).get("hits", [])
    audit("analytics-agent", "retrieve", {"query": query, "hits": len(hits)})
    return {"context": hits}


def tool_loop(state: AgentState, config) -> dict:
    model_name = _model_name(config)
    ts = _toolset(config)
    registry, run_tool = ts["registry"], ts["run"]
    hardened = ts["retrieval"]
    system_md = ts["system_md"] or _system_md()
    usage = state.get("tokens", {})
    trace: list[dict] = []
    context = "\n\n".join(
        f"[{h['source']} §{h['section']}]\n{h['text']}" if h.get("section")
        else f"[{h['source']} p.{h.get('page')}]\n{h['text']}"
        for h in state.get("context", []))
    schema = _schema_digest() if hardened and "sql_query" in registry else ""
    system = (
        f"{system_md}\n\n" + (f"{schema}\n\n" if schema else "")
        + f"## Tools\n{render_tools(registry)}\n\n"
        "## Protocol\nReply with EXACTLY ONE JSON object per turn:\n"
        '{"tool": "<name>", "args": {...}} to call a tool, or\n'
        '{"final": "<answer>", "citations": [{"source": "...", "section": "..."}]} '
        "when done.\nNo prose outside the JSON object.\n\n"
        f"## Retrieved context\n{context or '(none)'}"
    )
    if hardened:
        note, _ = _split_note(state["question"])
        question = "\n\n".join(x for x in (note, state.get("standalone") or state["question"]) if x)
    else:
        question = state["question"]
    messages: list = [SystemMessage(system)]
    if not hardened:        # hardened toolsets resolve follow-ups in prepare instead
        for turn in state.get("history", [])[-6:]:
            messages.append(HumanMessage(f"(previous {turn['role']}): {turn['content']}"))
    messages.append(HumanMessage(question))

    lang = state.get("lang") or "en"
    grounds: list = [question, context, schema]      # what this turn's figures may rest on
    answer, citations = "", []
    lenient = state.get("route") == "chat"           # small talk may come back as plain text
    retried = nudged = gated = tool_ok = False
    last_call: tuple | None = None
    for _ in range(MAX_STEPS):
        raw = _call(model_name, messages, usage)
        try:
            decision = parse_decision(raw)
        except ProtocolError:
            if lenient and _plain(raw):
                decision = Final(final=_plain(raw))
            elif retried:
                answer = "PROTOCOL_FAILURE: the model did not produce a valid tool/final object."
                break
            else:
                retried = True
                messages.append(HumanMessage(RETRY_MESSAGE))
                continue
        if isinstance(decision, ToolCall):
            this_call = (decision.tool, json.dumps(decision.args, sort_keys=True))
            if this_call == last_call:
                if nudged:
                    answer = ("LOOP_GUARD: the model repeated the same tool "
                              "call; aborting the step budget.")
                    break
                nudged = True
                messages.append(HumanMessage(
                    "You already ran that exact tool call — its TOOL_RESULT is "
                    "above. Move on: either call the NEXT tool or reply with "
                    '{"final": ...}.'))
                continue
            last_call = this_call
            t0 = time.time()
            result = run_tool(decision.tool, decision.args)
            ms = int((time.time() - t0) * 1000)
            if not isinstance(result, dict):    # unit_status on an unknown unit returns None
                result = ({"error": f"{decision.tool} found nothing for {decision.args}"}
                          if result is None else {"result": result})
            ok = "error" not in result
            tool_ok = tool_ok or ok
            if ok:
                grounds.append(result)
            audit("analytics-agent", "tool_call",
                  {"tool": decision.tool, "args": decision.args, "ok": ok, "ms": ms})
            trace.append({"tool": decision.tool, "args": decision.args,
                          "ok": ok, "ms": ms})
            payload = json.dumps(result, ensure_ascii=False, default=str)[:6000]
            messages.append(HumanMessage(f"TOOL_RESULT {decision.tool}:\n{payload}"))
            continue
        if hardened:
            # The figure gate: a number that neither a tool nor the retrieved
            # context gave this turn goes back once. With no successful tool
            # call at all the answer is then declined; otherwise the unsupported
            # figures are stripped below. (Observed: a kb_search, then "0".)
            values = evidence(*grounds)
            bare = [f["text"] for f in figures(decision.final) if not supported(f, values)]
            # a data question answered without trying a single tool — observed:
            # "no units are running", no query, no figure for the gate to see
            unqueried = state.get("route") in ("data", "both") and not trace
            # every tool call failed — observed: one SQL error, then "cannot be
            # calculated" with five steps left
            failed = bool(trace) and not tool_ok
            if (bare or unqueried or failed) and not gated:
                gated = True
                audit("analytics-agent", "figure_gate",
                      {"stage": "sent back", "figures": bare, "route": state.get("route"),
                       "after_tools": tool_ok})
                messages.append(HumanMessage(
                    GATE_NUDGE_AFTER_TOOLS if bare and tool_ok else
                    GATE_AFTER_ERROR if failed else
                    GATE_NUDGE if bare else GATE_NO_TOOL))
                continue
            if bare and not tool_ok:
                audit("analytics-agent", "figure_gate",
                      {"stage": "declined", "figures": bare, "route": state.get("route")})
                answer, citations = DECLINE[lang], []
                break
        answer = decision.final
        citations = [c.model_dump() for c in decision.citations]
        break
    else:
        answer = answer or "STEP_LIMIT: no final answer within the step budget."

    if hardened and trace and not tool_ok:
        citations = []          # nothing ran successfully, so no section supports the answer
    if hardened and answer.startswith(GUARDS):
        # the step budget, the loop guard or the protocol gave out: say so in the
        # user's language; the reason stays in the audit log, not on the screen
        audit("analytics-agent", "guard", {"reason": answer, "route": state.get("route"),
                                           "tools": [t["tool"] for t in trace]})
        answer, citations = STUCK[lang], []
    unverified: list[str] = []
    if hardened and answer and answer not in (DECLINE[lang], STUCK[lang]):
        answer, unverified = strip_unsupported(answer, evidence(*grounds), UNVERIFIED[lang])
        if unverified:
            audit("analytics-agent", "unverified_figures",
                  {"figures": unverified, "question": question[-300:],
                   "tools": [t["tool"] for t in trace]})
            if not re.search(r"[A-Za-z؀-ۿ]{3,}", answer.replace(UNVERIFIED[lang], "")):
                answer = DECLINE[lang]          # nothing left but the markers
    return {"tool_trace": trace, "answer": answer, "citations": citations,
            "tokens": usage, "unverified_figures": unverified}


_TRANSLATE_PROMPT = """Translate the text below into {lang}. Keep every number,
identifier, code span and file citation exactly as written, and put any database
table, column or value (such as a status) in `backticks`. Reply with the
translation only.

Text:
{text}"""


def _figure_values(text: str) -> list[float]:
    return sorted(f["value"] for f in figures(text))


def finalize(state: AgentState, config) -> dict:
    """Language enforcement: one translation with figures locked, then a
    template that keeps only the verified figures."""
    if not _toolset(config)["retrieval"]:
        return {}
    answer, lang = state.get("answer") or "", state.get("lang") or "en"
    if not answer or answer.startswith(GUARDS) or script_ok(answer, lang):
        return {}
    usage = state.get("tokens", {})
    locked, ids = _figure_values(answer), set(identifiers(answer))
    try:
        candidate = _plain(_call(_model_name(config), [HumanMessage(
            _TRANSLATE_PROMPT.format(lang=LANG_NAME[lang], text=answer))], usage))
    except Exception:
        candidate = ""
    # Figures locked: nothing added or changed. A small whole number may become a
    # word ("2 business days" → "يومي عمل"); any other figure must survive.
    remaining, same = list(locked), True
    for g in _figure_values(candidate):
        hit = next((i for i, v in enumerate(remaining) if same_value(v, g)), None)
        if hit is None:
            same = False
            break
        remaining.pop(hit)
    same = same and all(v <= 10 and float(v).is_integer() for v in remaining)
    if candidate and script_ok(candidate, lang) and same and ids <= set(identifiers(candidate)):
        audit("analytics-agent", "language_fix", {"to": lang, "result": "translated"})
        return {"answer": candidate, "tokens": usage}
    kept = [f["text"].strip() for f in figures(answer)]
    tools = ", ".join(dict.fromkeys(t["tool"] for t in state.get("tool_trace") or [])) or "—"
    if lang == "ar":
        fallback = (f"الأرقام الموثّقة: {'، '.join(kept)} (المصدر: {tools})." if kept
                    else "تعذّرت صياغة الإجابة بالعربية، يرجى إعادة طرح السؤال.")
    else:
        fallback = (f"Verified figures: {', '.join(kept)} (source: {tools})." if kept
                    else "I could not phrase that answer in English; please ask again.")
    audit("analytics-agent", "language_fix", {"to": lang, "result": "template"})
    return {"answer": fallback, "tokens": usage}


def answer_node(state: AgentState, config) -> dict:
    hardened = _toolset(config)["retrieval"]
    asked = (state.get("standalone") or state["question"]) if hardened else state["question"]
    metric = state.get("metric") or {}
    history = state.get("history", []) + [
        {"role": "user", "content": asked},
        {"role": "assistant", "content": state.get("answer", ""),
         "intent": metric.get("intent") if metric.get("used") else None},
    ]
    audit("analytics-agent", "answer",
          {"model": _model_name(config), "route": state.get("route"),
           "citations": state.get("citations", []),
           "tools_used": [t["tool"] for t in state.get("tool_trace", [])],
           "rewritten": state.get("rewritten"),
           "unverified_figures": state.get("unverified_figures") or []})
    return {"history": history[-12:],
            "latency_ms": state.get("tokens", {}).get("ms", 0)}


def _after_prepare(state: AgentState) -> str:
    return "metric" if (state.get("metric") or {}).get("payload") else "route"


def build_graph(with_memory: bool = True, *, toolset: str = "analytics",
                tools=None, kb_dir: str | Path | None = None,
                system_prompt: str | None = None):
    """Compile the graph. With no keyword args this is the original
    single-tenant analytics graph. `tools` (names), `kb_dir` and
    `system_prompt` (text) scope a tenant: they register `toolset` with its
    own registry subset, KB and prompt — callers pass the same `toolset` to
    ask()."""
    if "analytics" not in TOOLSETS:
        register_toolset("analytics", toolbox.REGISTRY, toolbox.run_tool,
                         metrics=_analytics_metrics())
    if tools is not None or kb_dir is not None or system_prompt is not None:
        registry, runner = scoped_tools(tools, kb_dir)
        register_toolset(toolset, registry, runner, system_md=system_prompt, kb_dir=kb_dir,
                         metrics=_analytics_metrics() if toolset == "analytics" else None)
    g = StateGraph(AgentState)
    g.add_node("prepare", prepare)
    g.add_node("metric", metric_node)
    g.add_node("route", route)
    g.add_node("retrieve", retrieve)
    g.add_node("tool_loop", tool_loop)
    g.add_node("finalize", finalize)
    g.add_node("answer", answer_node)
    g.set_entry_point("prepare")
    g.add_conditional_edges("prepare", _after_prepare, {"metric": "metric", "route": "route"})
    g.add_edge("metric", "answer")
    g.add_edge("route", "retrieve")
    g.add_edge("retrieve", "tool_loop")
    g.add_edge("tool_loop", "finalize")
    g.add_edge("finalize", "answer")
    g.add_edge("answer", END)
    saver = None
    if with_memory:
        try:
            from new_horizons.shared.harness.memory import checkpointer
            saver = checkpointer()
        except Exception:
            saver = None
    return g.compile(checkpointer=saver)


def ask(graph, question: str, model: str, thread_id: str = "default",
        toolset: str = "analytics") -> dict[str, Any]:
    """One turn; returns the final state slice the UI needs."""
    cfg = {"configurable": {"model": model, "thread_id": thread_id,
                            "toolset": toolset}}
    out = graph.invoke({"question": question}, cfg)
    res = {k: out.get(k) for k in
           ("answer", "citations", "tool_trace", "route", "tokens", "rewritten",
            "unverified_figures", "lang")}
    metric = out.get("metric") or None
    res["metric"] = {k: v for k, v in metric.items() if k != "payload"} if metric else None
    return res
