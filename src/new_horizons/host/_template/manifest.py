"""Tenant #2 scaffold. Copy this folder, give it an id, point Resources at the
agent's own data source / KB / prompt / tools, list its pages, and add it to
host/registry.yaml. Imports nothing from any other tenant.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from new_horizons.shared.host.manifest import AppManifest, Resources

HERE = Path(__file__).resolve().parent

MANIFEST = AppManifest(
    id="template",
    title="Template Agent",
    title_ar="وكيل نموذجي",
    pages=[st.Page(str(HERE / "pages" / "template_home.py"), title="Setup",
                   icon="🧩", url_path="template")],
    resources=Resources(db_url_env="TEMPLATE_DATABASE_URL"),
)
