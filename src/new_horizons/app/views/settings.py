"""Settings — the application theme and language, the agent's kill switch and
the model it runs on. The agent and model panels are fragments: pausing the
agent or opening the model dialog reruns that panel, not the app."""

import streamlit as st

from new_horizons.app import ui_common as U

tr = U.tr
theme = U.THEMES[U.current_theme()]
model = st.session_state.get("model", U.default_model())

U.page_header(
    tr("Settings.", "الإعدادات."),
    tr("How the application looks and which language it speaks, whether the agent may "
       "act, and the model it runs on.",
       "مظهر التطبيق ولغته، وما إذا كان يُسمح للوكيل بالعمل، والنموذج الذي يعمل عليه."),
    [U.chip(tr(f"Theme · {theme['label']}", f"المظهر · {theme['labelAr']}")),
     U.chip(U.LANGS[U.current_lang()][0]), U.chip(U.lane_label()),
     U.chip(U.model_label(model), "strong")])

left, right = st.columns([1.15, 1], gap="large")
with left:
    U.section(tr("Appearance", "المظهر"), tr("application theme", "سمة التطبيق"))
    with U.card("settings-theme"):
        U.theme_picker()
        st.markdown("<p class='ac-subtle'>" + tr(
            "Charts, tables and dialogs follow the theme. The footer marks keep their own "
            "colours on the dark themes and switch to gray ink on White.",
            "تتبع الرسوم والجداول ونوافذ الحوار السمة المختارة. تحتفظ شعارات التذييل بألوانها "
            "في السمات الداكنة، وتتحول إلى حبر رمادي في السمة البيضاء.") + "</p>",
            unsafe_allow_html=True)
    U.section(tr("Language", "اللغة"), tr("the whole application", "التطبيق بالكامل"))
    with U.card("settings-lang"):
        U.lang_picker()
        st.markdown("<p class='ac-subtle'>" + tr(
            "Arabic runs right to left. The agent answers in the language of the question; "
            "data from the source systems keeps its own language.",
            "تُعرض العربية من اليمين إلى اليسار. يجيب الوكيل بلغة السؤال، وتحتفظ بيانات "
            "أنظمة المصدر بلغتها الأصلية.") + "</p>", unsafe_allow_html=True)
with right:
    U.section(tr("Agent", "الوكيل"),
              tr("every change is written to the audit chain", "كل تغيير يُكتب في سلسلة التدقيق"))
    with U.card("settings-agent"):
        U.kill_switch()
    lane = U.lane_describe()
    U.section(tr("Model", "النموذج"),
              tr("one 8B chat model resident", "نموذج محادثة 8B واحد في الذاكرة")
              if lane["local_chat"] else
              tr(f"inference runs on {lane['label']}", f"يعمل الاستدلال على {lane['label']}"))
    with U.card("settings-model"):
        U.model_panel()
        if not lane["local_chat"]:
            # Never let a screen imply local inference when it is not local.
            st.markdown("<p class='ac-subtle'>" + tr(
                f"Chat endpoint: {lane['chat_base_url']} — embeddings and document reading "
                "stay on this machine.",
                f"نقطة نهاية المحادثة: {lane['chat_base_url']} — تبقى التضمينات وقراءة "
                "المستندات على هذا الجهاز.") + "</p>", unsafe_allow_html=True)
