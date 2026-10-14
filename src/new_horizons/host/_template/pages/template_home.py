"""Placeholder page: shows until the tenant's data source is configured."""

import os

import streamlit as st

ENV = "TEMPLATE_DATABASE_URL"

st.title("Template agent")
if not os.environ.get(ENV):
    st.warning(f"not configured — set {ENV}")
    st.caption("Each app agent owns its data source, knowledge base, prompt and tool "
               "list (its manifest's Resources); nothing is shared with other tenants.")
else:
    st.success(f"{ENV} is set — add this tenant's pages and tools to its manifest.")
