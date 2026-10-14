"""Model switching for every Streamlit surface (standalone app, host).

Model choice is model-level, not tenant-level: one implementation, so every
surface keeps the 16 GB rule — one 8B chat model resident, the old one
released before the new one warms. Session keys `model` / `compare_with`
are what the chat pages read. (Lifted unchanged from the analytics app's
ui_common, which now imports it from here.) The dialog speaks the analytics
app's language when that app has set one (session key `_ac_lang`); the host
never does, so it stays English.
"""

from __future__ import annotations

import os
from html import escape

import streamlit as st


def _tr(en: str, ar: str) -> str:
    try:
        return ar if st.session_state.get("_ac_lang") == "ar" else en
    except Exception:
        return en


def default_model() -> str:
    return os.environ.get("LLM_MODEL_DEFAULT", "qwen3:8b")


def model_label(m: str | None) -> str:
    from new_horizons.shared.llm.client import REGISTRY
    return REGISTRY[m].label if m in REGISTRY else (m or "")


def _ollama(path: str, body: dict, timeout: float) -> None:
    import httpx
    from new_horizons.shared.llm.client import ollama_host
    httpx.post(f"{ollama_host()}{path}", json=body, timeout=timeout).raise_for_status()


def swap_model(old: str, new: str) -> None:
    """One 8B chat model resident (16 GB budget): release the old, warm the new.

    Residency is an Ollama concept. On a rented vLLM endpoint or Claude there
    is nothing to unload and no warm-up to wait for, so the swap is just a
    change of model id.
    """
    from new_horizons.shared.llm.provider import is_local_chat
    if not is_local_chat():
        return
    try:
        _ollama("/api/generate", {"model": old, "keep_alive": 0}, 30)
    except Exception:
        pass  # already unloaded — loading the new one still works
    _ollama("/api/generate", {"model": new}, 240)


def _model_dialog_body() -> None:
    from new_horizons.shared.llm.client import REGISTRY, chat_models
    from new_horizons.shared.llm.provider import is_local_chat, label as lane_label
    models = chat_models()
    cur = st.session_state.get("model", default_model())
    st.markdown(
        "<p class='ac-subtle'>" + (_tr(
            "One 8B chat model stays resident on this laptop. Confirming unloads the current "
            "model and warms the new one (5–15 s). Chat history is kept; the same agent graph "
            "runs on every model.",
            "يبقى نموذج محادثة واحد بحجم 8B في ذاكرة هذا الجهاز. يؤدي التأكيد إلى إخراج النموذج "
            "الحالي وتحميل الجديد (5–15 ثانية). يُحفظ سجل المحادثة، وتعمل بنية الوكيل نفسها على "
            "كل نموذج.") if is_local_chat() else _tr(
            f"Inference runs on {lane_label()} — nothing loads or unloads on this laptop. "
            "Chat history is kept; the same agent graph runs on every model. Embeddings and "
            "document reading stay local.",
            f"يعمل الاستدلال على {lane_label()} — لا يُحمَّل أو يُفرَّغ أي نموذج على هذا الجهاز. "
            "يُحفظ سجل المحادثة، وتعمل بنية الوكيل نفسها على كل نموذج. أما التضمينات وقراءة "
            "المستندات فتبقى محلية.")) + "</p>",
        unsafe_allow_html=True)
    notes = []
    for m in models:
        spec = REGISTRY.get(m)
        notes.append(_tr(
            f"Arabic {spec.arabic} · "
            f"{'native tool template' if spec.native_tools else 'JSON tool protocol only'}",
            f"العربية {'قوية' if spec.arabic == 'strong' else 'ضعيفة'} · "
            f"{'قالب أدوات أصلي' if spec.native_tools else 'بروتوكول أدوات JSON فقط'}")
            if spec else lane_label())
    choice = st.radio(_tr("Model", "النموذج"), models, format_func=model_label,
                      captions=notes, index=models.index(cur) if cur in models else 0,
                      key="model-choice")
    compare = st.toggle(_tr("Compare against a second model", "المقارنة مع نموذج ثانٍ"),
                        value=bool(st.session_state.get("compare_with")),
                        help=_tr("Runs each chat question on both models, one after the other.",
                                 "يُشغّل كل سؤال على النموذجين، واحداً تلو الآخر."))
    other = None
    if compare:
        others = [m for m in models if m != choice]
        prev = st.session_state.get("compare_with")
        other = st.selectbox(_tr("Second model", "النموذج الثاني"), others,
                             format_func=model_label,
                             index=others.index(prev) if prev in others else 0)
    left, right = st.columns(2)
    if left.button(_tr("Cancel", "إلغاء"), width="stretch"):
        st.rerun()
    if right.button(_tr("Confirm switch", "تأكيد التبديل"), type="primary", width="stretch"):
        if choice != cur:
            with st.spinner(_tr(f"Unloading {model_label(cur)} · loading {model_label(choice)}…",
                                f"إخراج {model_label(cur)} · تحميل {model_label(choice)}…")):
                try:
                    swap_model(cur, choice)
                except Exception as exc:
                    st.error(_tr(f"Could not load {choice}: {exc}",
                                 f"تعذّر تحميل {choice}: {exc}"))
                    st.stop()
        st.session_state["model"] = choice
        st.session_state["compare_with"] = other
        st.rerun()


def model_dialog() -> None:
    """The switch dialog — built per call, so its title follows the language."""
    st.dialog(_tr("Switch model", "تبديل النموذج"), width="medium")(_model_dialog_body)()


def current_model_html() -> str:
    """'Model  <label> · <compare>' line for a sidebar (ac-model style)."""
    model = st.session_state.get("model", default_model())
    cmp = st.session_state.get("compare_with")
    return (f"<div class='ac-model'><span class='ac-label'>{_tr('Model', 'النموذج')}</span>"
            f"<b>{escape(model_label(model))}{' · ' + escape(model_label(cmp)) if cmp else ''}"
            f"</b></div>")
