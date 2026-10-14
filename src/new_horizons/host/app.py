"""new-horizons app-agent host — one Streamlit shell serving every registered app agent.

    make host        → http://localhost:8502

Tenants come from host/registry.yaml; each ships a manifest.py (pages,
sidebar, isolated Resources). Adding one is a registry entry plus a package —
nothing here changes. Standalone `make demo1` is unaffected.
"""

import streamlit as st

from new_horizons.host import host_common as H

st.set_page_config(page_title="new-horizons · App Agents", page_icon=":material/hub:",
                   layout="wide", initial_sidebar_state="expanded")

tenants = H.load_registry()
# sections still define every route; the sidebar draws its own nav (below)
page = st.navigation(H.navigation_sections(tenants), position="hidden")
tenant = H.owner(tenants, page)
if tenant.setup:
    tenant.setup()

with st.sidebar:
    H.brand_lockup()
    H.tenant_switcher(tenants, tenant)
    H.tenant_nav(tenant, page)
    if tenant.sidebar:
        tenant.sidebar()
    H.model_controls()
    H.platform_wordmark()

page.run()
