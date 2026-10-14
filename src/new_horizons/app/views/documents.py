"""Documents — attach a supplier invoice or a water-lab report; the agent reads
it on this machine, reconciles it against the farm systems and raises the alert
in Chat."""

from pathlib import Path

import streamlit as st

from new_horizons.app import intake_view as V
from new_horizons.app import ui_common as U

tr = U.tr
model = st.session_state.get("model", U.default_model())
U.page_header(
    tr("Document intake.", "استلام المستندات."),
    tr("Attach a supplier invoice or a water-lab report. The agent reads it on this machine, "
       "reconciles every field against purchasing, the supplier master, the probes and the "
       "SOP bands, and raises the alert in Chat.",
       "أرفق فاتورة مورد أو تقرير مختبر مياه. يقرأه الوكيل على هذا الجهاز، ويطابق كل حقل مع "
       "المشتريات وسجل الموردين والمجسات ونطاقات الإجراءات، ويرفع التنبيه في المحادثة."),
    [U.chip(tr("Synthetic data", "بيانات تركيبية")),
     U.chip(tr("OCR · on-device", "تعرّف ضوئي · على الجهاز")),
     U.chip(tr("Vision model · qwen3-vl 4B", "نموذج الرؤية · qwen3-vl 4B")),
     U.chip(U.model_label(model), "strong")])

left, right = st.columns([1, 1.15], gap="large")
with left:
    U.section(tr("Attach", "إرفاق"), "PDF · PNG · JPG")
    up = st.file_uploader(tr("Document", "المستند"), type=["pdf", "png", "jpg", "jpeg"],
                          label_visibility="collapsed")
    picked = None
    sample_list = V.samples()
    if sample_list:
        st.markdown(f"<div class='ac-label' style='margin:1rem 0 .5rem'>"
                    f"{tr('Or use a sample', 'أو استخدم نموذجاً')}</div>", unsafe_allow_html=True)
        for col, (key, label, path) in zip(st.columns(len(sample_list)), sample_list):
            if col.button(label, key=f"sample-{key}", width="stretch",
                          icon=":material/receipt_long:"):
                picked = path
    else:
        st.caption(tr("No samples yet — `make mock` prints them to data/samples/.",
                      "لا توجد نماذج بعد — ينشئها `make mock` في data/samples/."))
with right:
    U.section(tr("Pipeline", "المعالجة"), tr("read → reconcile → alert", "قراءة ← مطابقة ← تنبيه"))
    progress = st.empty()

path = None
if up is not None and st.session_state.get("intake_upload") != (up.name, up.size):
    path = V.save_upload(up.name, up.getvalue())
    st.session_state["intake_upload"] = (up.name, up.size)
elif picked is not None:
    path = picked

if path is not None:
    with right:
        result = V.run(path, model, progress)
    if result:
        st.session_state["intake_result"] = result
        V.post_to_chat(result)
        if result.get("alert", {}).get("verdict") != "clean":
            st.session_state["toast"] = tr("Discrepancy alert sent to Chat",
                                           "أُرسل تنبيه التباين إلى المحادثة")
        st.rerun()                           # sidebar picks up the Chat badge

result = st.session_state.get("intake_result")
if not result:
    progress.markdown(V._steps_html({}), unsafe_allow_html=True)
    st.stop()
if path is None:
    progress.markdown(V.steps_done(result), unsafe_allow_html=True)

# ---- result ---------------------------------------------------------------------------
V.alert_card(result)
V.governance_row(result, key_suffix="-doc")
with st.container(key="open-chat"):             # a page link: one run, not a button's two
    st.page_link(str(U.APP / "views" / "chat.py"), label=tr("Open the alert in Chat", "افتح التنبيه في المحادثة"),
                 icon=":material/forum:")

ref = result.get("recon", {}).get("ref") or "—"
U.section(tr("Reconciliation call", "استدعاء المطابقة"),
          tr(f"{ref} · the systems of record", f"{ref} · أنظمة السجل"))
st.markdown(V.checks_table(result), unsafe_allow_html=True)

doc_col, fields_col = st.columns([1, 1.15], gap="large")
with doc_col:
    pages = result["doc"].get("pages", 1)
    U.section(tr("Document", "المستند"),
              f"{result['doc'].get('kind', '')} · {result['read'].get('engine', '')} · "
              + tr(f"{pages} page(s)", f"{pages} صفحة"))
    preview = result["doc"].get("preview_png")
    if preview and Path(preview).exists():
        with U.card("documents-1"):
            st.image(preview, width="stretch")
with fields_col:
    U.section(tr("Extracted fields", "الحقول المستخرجة"), result.get("extract", {}).get("engine", ""))
    st.markdown(V.fields_table(result), unsafe_allow_html=True)

with st.expander(tr("OCR text", "نص التعرف الضوئي")):
    st.text(result.get("read", {}).get("text", "")[:6000])
if result.get("terms"):
    n_terms = len(result["terms"])
    with st.expander(tr(f"Knowledge-base terms used · {n_terms}",
                        f"بنود قاعدة المعرفة المستخدمة · {n_terms}")):
        for t in result["terms"]:
            st.markdown(f"**{U.cite(t['source'], t['section'])}** — "
                        f"{U.in_language(t.get('heading', '')) or t.get('heading', '')}")
            st.caption(" ".join(U.section_bullets(t.get("text", "")))[:700])
