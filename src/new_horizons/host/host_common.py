"""Host shell helpers: registry loading, tenant switcher, host-level sidebar.

The host knows tenants only through their manifests (shared/host/manifest.py)
— it never imports a tenant's internals itself.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import streamlit as st
import yaml

from new_horizons.shared.host.manifest import AppManifest

from new_horizons.paths import ROOT as REPO

ROOT = Path(__file__).resolve().parents[1]          # the package: tenants live under it
REGISTRY = Path(__file__).with_name("registry.yaml")
LOGO = REPO / "assets" / "brand" / "horizons-mark.svg"


def load_manifest(package: str | Path, tenant_id: str) -> AppManifest:
    """Execute <package>/manifest.py under a tenant-unique module name."""
    path = ROOT / package / "manifest.py"
    name = f"horizons_tenant_{tenant_id}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    manifest = module.MANIFEST
    if manifest.id != tenant_id:
        raise ValueError(f"{path}: MANIFEST.id {manifest.id!r} != registry id {tenant_id!r}")
    return manifest


def load_registry(path: Path = REGISTRY, enable: set[str] | None = None) -> list[AppManifest]:
    """Enabled tenants in registry order. `enable` (or env HOST_ENABLE=a,b)
    switches on entries that are disabled in the file."""
    extra = set(enable or ()) | {x for x in os.environ.get("HOST_ENABLE", "").split(",") if x}
    tenants = [load_manifest(e["package"], e["id"])
               for e in yaml.safe_load(path.read_text(encoding="utf-8")) or []
               if e.get("enabled") or e["id"] in extra]
    ids = [t.id for t in tenants]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate tenant ids in {path.name}: {ids}")
    if sum(p._default for t in tenants for p in t.pages) != 1:
        raise ValueError("exactly one page across all tenants must be default=True")
    # st.Page only resolves url paths inside a Streamlit run (bare-Python
    # imports get a stub), so collisions are checked where they can occur.
    urls = [p.url_path for t in tenants for p in t.pages if hasattr(p, "_url_path")]
    if len(set(urls)) != len(urls):
        raise ValueError(f"page url paths collide across tenants: {urls}")
    return tenants


def navigation_sections(tenants: list[AppManifest]) -> dict[str, list]:
    return {t.title: t.pages for t in tenants}


def owner(tenants: list[AppManifest], page) -> AppManifest:
    """The tenant whose manifest declared the page st.navigation selected."""
    return next(t for t in tenants if any(p is page for p in t.pages))


# ---- sidebar blocks ------------------------------------------------------------

def brand_lockup() -> None:
    """The farm this host serves (the product mark, legible on black)."""
    if LOGO.exists():
        st.image(str(LOGO), width=184)


def platform_wordmark() -> None:
    """Closes the sidebar, as in the design system's standalone app. Served
    from host/static (a link to the app's static folder)."""
    st.markdown("<div class='ac-wordmark'><img src='app/static/ac-wordmark.svg' "
                "alt='agentization-core'></div>", unsafe_allow_html=True)


def tenant_switcher(tenants: list[AppManifest], current: AppManifest) -> None:
    """Pick an app agent; switching jumps to its first page.

    The widget always shows the tenant of the page being viewed (so the nav
    menu and the switcher never fight), and only a user change — seen by
    on_change — triggers a switch. Options are tenant ids: manifests are
    rebuilt every run, so objects would never compare equal across reruns."""
    by_id = {t.id: t for t in tenants}

    def requested() -> None:
        st.session_state["_host_switch_to"] = st.session_state["host_tenant"]

    st.session_state["host_tenant"] = current.id  # follow the page, set before render
    st.selectbox("App agent", list(by_id), key="host_tenant", on_change=requested,
                 format_func=lambda i: f"{by_id[i].title} · {by_id[i].title_ar}",
                 disabled=len(tenants) == 1)
    target = st.session_state.pop("_host_switch_to", None)
    if target in by_id and target != current.id:
        st.switch_page(by_id[target].pages[0])


def tenant_nav(tenant: AppManifest, page) -> None:
    """The current tenant's pages as the design system's square button grid
    (st-key-nav-grid, styled by ac.css) — st.navigation itself is hidden."""
    with st.container(key="nav-grid"):
        for i in range(0, len(tenant.pages), 3):
            row = tenant.pages[i:i + 3]
            for col, p in zip(st.columns(3), row):
                current = p is page
                if col.button(p.title, icon=p.icon or None, width="stretch",
                              key=f"nav-{tenant.id}-{p.url_path or 'home'}",
                              type="primary" if current else "secondary") and not current:
                    st.switch_page(p)


def model_controls() -> None:
    """Model-level, so host-level — and the same switch as the standalone app
    (shared/llm/switch.py): confirming unloads the old 8B model before the
    new one warms. A bare radio would leave two resident (16 GB budget)."""
    from new_horizons.shared.llm import switch
    if st.button("Switch model", icon=":material/swap_horiz:", key="host-model-switch",
                 width="stretch"):
        switch.model_dialog()
    st.session_state.setdefault("model", switch.default_model())
    st.markdown(switch.current_model_html(), unsafe_allow_html=True)
