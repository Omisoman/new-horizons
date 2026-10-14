"""Changes — the deploys Sojourner shipped to this app, read from the
same hash-chained audit log as every decision made here. A change reaches the
app only after a developer agent built it in a sandbox, an operator agent tested
and evaluated it, and a person approved it."""

from datetime import datetime

import pandas as pd
import streamlit as st

from new_horizons.app import ui_common as U

tr = U.tr


@st.cache_data(ttl=5, show_spinner=False)
def _deploys() -> list[dict]:
    from new_horizons.shared.audit.audit import deploys
    return deploys(200)


try:
    rows, error = _deploys(), None
except Exception as exc:                       # the page renders whatever the database does
    rows, error = [], f"{type(exc).__name__}: {exc}"

U.page_header(
    tr("Changes.", "التغييرات."),
    tr("What Sojourner shipped to this app — each deploy built, tested, evaluated and "
       "approved by a person, read from the same audit chain as every decision here.",
       "ما شحنه Sojourner إلى هذا التطبيق — كل نشر بُني واختُبر وقُيّم واعتمده شخص، "
       "ويُقرأ من سلسلة التدقيق نفسها التي تحفظ كل قرار هنا."),
    [U.chip(tr("Synthetic data", "بيانات تركيبية")), U.chip("Sojourner", "strong"),
     U.chip(tr(f"{len(rows)} deploy" + ("" if len(rows) == 1 else "s"), f"عمليات النشر: {len(rows)}"))])

if error:
    U.alert(tr("Audit log unreachable", "تعذّر الوصول إلى سجل التدقيق"), f"<p>{error}</p>",
            pill=tr("Degraded", "أداء منخفض"), kind="amber")

STEPS = [
    (tr("A developer agent changes the app in a sandbox.",
        "يغيّر وكيل تطوير التطبيقَ داخل بيئة معزولة."),
     tr("Sojourner's tier 1: no network, no credentials, a read-only system; it commits and hands "
        "over a patch, nothing else.",
        "المستوى الأول في Sojourner: بلا شبكة ولا بيانات اعتماد، ونظام ملفات للقراءة فقط؛ يحفظ التغيير "
        "ويسلّم رقعة فقط.")),
    (tr("An operator agent builds, tests and evaluates it.",
        "يبني وكيل تشغيل التغيير ويختبره ويقيّمه."),
     tr("Sojourner's tier 2 replays the patch on a clean copy, runs the tests and the architecture "
        "contracts, and scores the question set before anything may ship.",
        "يعيد المستوى الثاني تطبيق الرقعة على نسخة نظيفة، ويشغّل الاختبارات وعقود البنية، ويقيس "
        "مجموعة الأسئلة قبل أن يُسمح بالشحن.")),
    (tr("A person approves it.", "يعتمده شخص."),
     tr("The deploy waits for a human; without an approval nothing reaches staging.",
        "ينتظر النشر قرار إنسان؛ ودون اعتماد لا يصل شيء إلى بيئة الاختبار.")),
    (tr("The deploy is written to this audit chain — and appears here.",
        "يُكتب النشر في سلسلة التدقيق هذه — ويظهر هنا."),
     tr("The same hash-chained log the Admin center verifies: who approved, when, which commit.",
        "السجل المتسلسل بالتجزئة نفسه الذي يتحقق منه مركز الإدارة: من اعتمد، ومتى، وأي التزام.")),
]

if not rows:
    steps = "".join(f"<li><b>{head}</b> {body}</li>" for head, body in STEPS)
    U.alert(tr("No deploys yet", "لا عمليات نشر بعد"),
            "<p>" + tr("Nothing has been shipped to this app since its data was generated. This is "
                       "how a change gets here:",
                       "لم يُشحن أي تغيير إلى هذا التطبيق منذ توليد بياناته. هكذا يصل التغيير إلى هنا:")
            + f"</p><ol>{steps}</ol><p>"
            + tr("Nothing reaches this app without a recorded approval.",
                 "لا يصل شيء إلى هذا التطبيق دون اعتماد مسجّل.") + "</p>",
            pill=tr("How a change gets here", "كيف يصل التغيير"), kind="ok")
    st.stop()


def _when(ts) -> str:
    t = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
    return t.astimezone().strftime("%d %b %Y %H:%M")


last = rows[0]
lp = last["payload"] or {}
evaluation = lp.get("evaluation") or {}
U.stat_cards([
    (tr("Deploys", "عمليات النشر"), f"{len(rows)}", tr("approved and shipped", "معتمدة ومشحونة")),
    (tr("Last deploy", "آخر نشر"), (lp.get("ref") or "—")[:12], _when(last["ts"])),
    (tr("Approved by", "اعتمده"), lp.get("approved_by") or "—",
     tr(f"task {str(lp.get('task_id') or '—')[:8]}", f"المهمة {str(lp.get('task_id') or '—')[:8]}")),
    (tr("Evaluation", "التقييم"),
     f"{evaluation['pass_rate']:.0%}" if evaluation.get("pass_rate") is not None else "—",
     evaluation.get("model") or tr("question set", "مجموعة الأسئلة")),
])

U.section(tr("Deploys", "عمليات النشر"), tr("newest first · from the audit chain", "الأحدث أولاً · من سلسلة التدقيق"))
table = pd.DataFrame([{
    "when": _when(r["ts"]), "ref": ((r["payload"] or {}).get("ref") or "")[:12],
    "summary": (r["payload"] or {}).get("summary") or "",
    "approved_by": (r["payload"] or {}).get("approved_by"),
    "task": str((r["payload"] or {}).get("task_id") or "")[:8],
    "files": len((r["payload"] or {}).get("files") or []),
    "hash": r["hash"][:8]} for r in rows])
event = st.dataframe(
    table, hide_index=True, height=min(420, 38 + 35 * len(table)),
    selection_mode="single-row", on_select="rerun", key="deploys",
    column_config={"when": tr("When", "متى"), "ref": tr("Commit", "الالتزام"),
                   "summary": tr("Change", "التغيير"), "approved_by": tr("Approved by", "اعتمده"),
                   "task": tr("Task", "المهمة"),
                   "files": st.column_config.NumberColumn(tr("Files", "الملفات"), format="%d"),
                   "hash": tr("Hash", "التجزئة")})
chosen = (event.selection.rows or [None])[0] if hasattr(event, "selection") else None
if chosen is None:
    st.caption(tr("Select a deploy to see its files and its audit trail.",
                  "اختر عملية نشر لعرض ملفاتها وسجل تدقيقها."))
else:
    p = rows[chosen]["payload"] or {}
    files = p.get("files") or []
    if files:
        st.markdown("<p class='ac-subtle ac-mono'>" + " · ".join(files[:20]) + "</p>",
                    unsafe_allow_html=True)
    if p.get("staging_url"):
        st.markdown(f"<p class='ac-subtle'>{tr('Staging', 'بيئة الاختبار')}: "
                    f"<span class='ac-mono'>{p['staging_url']}</span></p>", unsafe_allow_html=True)
    if p.get("ref"):
        U.audit_link(p["ref"], tr("Audit trail for this deploy", "سجل التدقيق لهذا النشر"),
                     key_suffix="-changes")
