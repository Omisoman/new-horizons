"""Chat — the analytics agent over the knowledge base and the five databases."""

import streamlit as st

from new_horizons.app import ui_common as U

tr = U.tr
U.page_header(tr("Ask the agent.", "اسأل الوكيل."),
              tr("No synthetic farm data loaded yet.", "لم تُحمَّل بيانات المزرعة التركيبية بعد."),
              [U.chip(tr("Synthetic data", "بيانات تركيبية"))])
st.info(tr("Run `make mock` to generate the five databases.",
           "شغّل `make mock` لإنشاء قواعد البيانات الخمس."))
