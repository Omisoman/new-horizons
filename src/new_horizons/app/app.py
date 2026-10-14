"""Analytics agent — Streamlit entry point (`make demo1`).

Navigation is hidden and re-rendered as the design system's sidebar: farm
logo, a 3×3 grid of icon page links (labels are hover tooltips), the footer
band. Admin center and Settings are pages in that grid. setup(themed=True)
follows the theme and language picked in Settings.
"""

from __future__ import annotations

import streamlit as st

from new_horizons.app import ui_common as U

arabic = U.saved_lang() == "ar"             # the tab title precedes setup(), which sets tr()
st.set_page_config(
    page_title=f"{'وكيل التحليلات' if arabic else 'Analytics Agent'} · "
               f"{U.PROFILE['farm']['name_ar' if arabic else 'name_en']}",
    page_icon=":material/insights:", layout="wide", initial_sidebar_state="expanded")
U.setup(themed=True)

pages = {key: st.Page(str(U.APP / file), title=U.nav_label(key), icon=icon, url_path=key,
                      default=(i == 0))
         for i, (key, _label, icon, file) in enumerate(U.NAV + U.NAV_EXTRA)}
current = st.navigation(list(pages.values()), position="hidden")
current_key = next((k for k, p in pages.items() if p.url_path == current.url_path),
                   U.NAV[0][0])
U.sidebar(pages, current_key)
current.run()
