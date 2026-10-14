"""What an app agent declares to be hosted by host/app.py.

Each tenant package ships `manifest.py` exposing `MANIFEST = AppManifest(...)`:
its pages, an optional sidebar block, optional per-page setup (CSS, chart
templates) and its `Resources`. Resources are the isolation boundary — every
tenant resolves its own env (`<ID>_DATABASE_URL`-style, `<ID>_KB_DIR`), its own
tool list and system prompt, and gets its own compiled graph, cached under a
key that starts with the tenant id.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, NamedTuple

import streamlit as st
from pydantic import BaseModel, ConfigDict, Field

from new_horizons.paths import data_path


class Resolved(NamedTuple):
    db_url: str | None
    kb_dir: str | None
    system_prompt: str | None  # text, not path
    tools: tuple[str, ...]


class Resources(BaseModel):
    model_config = ConfigDict(frozen=True)

    db_url_env: str                     # e.g. ANALYTICS_DATABASE_URL
    kb_dir: Path | None = None          # default KB; <ID>_KB_DIR overrides
    system_prompt: Path | None = None   # SYSTEM.md for the tenant's agent
    tools: tuple[str, ...] = ()         # names from new_horizons.shared.harness.tools.REGISTRY

    def resolve(self, tenant_id: str) -> Resolved:
        kb = os.environ.get(f"{tenant_id.upper()}_KB_DIR") or (
            str(self.kb_dir) if self.kb_dir else None)
        if kb and not Path(kb).is_absolute():
            kb = str(data_path(kb, "kb"))
        prompt = (self.system_prompt.read_text(encoding="utf-8")
                  if self.system_prompt and self.system_prompt.exists() else None)
        return Resolved(os.environ.get(self.db_url_env), kb, prompt, tuple(self.tools))


class AppManifest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str
    title_ar: str
    pages: list[Any]                         # st.Page objects
    sidebar: Callable[[], None] | None = None
    setup: Callable[[], None] | None = None  # runs before this tenant's page
    resources: Resources


def graph_key(tenant_id: str, resources: Resources) -> str:
    """Cache key for a tenant's graph: tenant id + a digest of what it resolves to."""
    r = resources.resolve(tenant_id)
    digest = hashlib.sha1(json.dumps([r.tools, r.kb_dir, r.system_prompt]).encode()).hexdigest()
    return f"{tenant_id}:{digest[:12]}"


@st.cache_resource(show_spinner="loading agent graph…")
def _graph(key: str, tenant_id: str, tools: tuple[str, ...], kb_dir: str | None,
           system_prompt: str | None):
    from new_horizons.shared.harness.graph import build_graph
    return build_graph(with_memory=True, toolset=tenant_id, tools=tools, kb_dir=kb_dir,
                       system_prompt=system_prompt)


def tenant_graph(tenant_id: str, resources: Resources):
    """The tenant's compiled graph, cached per graph_key()."""
    r = resources.resolve(tenant_id)
    return _graph(graph_key(tenant_id, resources), tenant_id, r.tools, r.kb_dir, r.system_prompt)
