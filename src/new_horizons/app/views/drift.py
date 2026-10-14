"""Drift — water temperature, pH and dissolved oxygen against the reference month."""

import streamlit as st

from new_horizons.app import ui_common as U

tr = U.tr
U.page_header(tr("Water drift.", "انحراف المياه."),
              tr("No synthetic farm data loaded yet.", "لم تُحمَّل بيانات المزرعة التركيبية بعد."),
              [U.chip(tr("Synthetic data", "بيانات تركيبية"))])
st.info(tr("Run `make mock` to generate the five databases.",
           "شغّل `make mock` لإنشاء قواعد البيانات الخمس."))
