"""The analytics agent as a host tenant (host/registry.yaml).

Same pages, order and titles as the standalone app (`make demo1`): taken from
`U.NAV` (the app's single page list), and page setup from `U.setup()` likewise
— so the two surfaces can't drift. Resources come from ui_common.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from new_horizons.app import ui_common as U
from new_horizons.shared.host.manifest import AppManifest

HERE = Path(__file__).resolve().parent
# U.NAV rows are (key, label, ":material/icon:", "<dir>/<file>.py"); key = url path.
# Page files live in views/, never pages/ (Streamlit's legacy MPA mode triggers on it).
PAGES = [(path, label, icon, key) for key, label, icon, path in U.NAV]


def _sidebar() -> None:
    st.caption("Synthetic data · five farm systems · generic knowledge base")


MANIFEST = AppManifest(
    id=U.TENANT,
    title="Analytics Agent",
    title_ar="وكيل التحليلات",
    pages=[st.Page(str(HERE / p), title=t, icon=i, url_path=u, default=(n == 0))
           for n, (p, t, i, u) in enumerate(PAGES)],
    sidebar=_sidebar,
    setup=U.setup,
    resources=U.RESOURCES,
)
