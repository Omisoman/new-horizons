"""host: registry → manifests → isolated tenants, and the graph kwargs that
keep the standalone app (no kwargs) exactly as it was."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from new_horizons.host import host_common as H
from new_horizons.paths import DATA
from new_horizons.shared.harness import graph as G
from new_horizons.shared.harness import tools as toolbox
from new_horizons.shared.host.manifest import Resources, graph_key

ROOT = Path(__file__).parents[1]
PKG = ROOT / "src" / "new_horizons"
HOST = PKG / "host"
APP = PKG / "app"


def _db_up() -> bool:
    try:
        import psycopg
        psycopg.connect(os.environ.get("DATABASE_URL",
                                       "postgresql://horizons:horizons@localhost:5432/horizons"),
                        connect_timeout=2).close()
        return True
    except Exception:
        return False


def test_registry_ships_analytics_only_template_disabled():
    tenants = H.load_registry()
    assert [t.id for t in tenants] == ["analytics"]


def test_template_enabled_gives_two_sections_and_two_graph_keys():
    tenants = H.load_registry(enable={"template"})
    assert list(H.navigation_sections(tenants)) == ["Analytics Agent", "Template Agent"]
    keys = [graph_key(t.id, t.resources) for t in tenants]
    assert len(set(keys)) == 2
    assert [k.split(":")[0] for k in keys] == ["analytics", "template"]


def test_tenant_two_imports_nothing_from_tenant_one():
    probe = (
        "import sys; from new_horizons.host import host_common as H;"
        "H.load_manifest('host/_template', 'template');"
        "leak = sorted(n for n in sys.modules if n.startswith('new_horizons.app'));"
        "print('LEAK', leak or 'none')"
    )
    out = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True,
                         text=True, timeout=120).stdout
    assert "LEAK none" in out, out


def test_registry_rejects_duplicate_tenants(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text("- {id: analytics, package: app, enabled: true}\n" * 2)
    with pytest.raises(ValueError, match="duplicate tenant ids"):
        H.load_registry(reg)


def test_analytics_manifest_mirrors_the_standalone_app():
    H.load_manifest("app", "analytics")
    manifest = sys.modules["horizons_tenant_analytics"]
    from new_horizons.app import ui_common as U
    expected = [(Path(path).stem, label) for _k, label, _i, path in U.NAV]
    assert [(Path(p).stem, t) for p, t, _i, _u in manifest.PAGES] == expected


def test_resources_resolve_per_tenant_env(monkeypatch):
    res = Resources(db_url_env="ACME_DATABASE_URL", kb_dir=Path("/nope"), tools=("kb_search",))
    monkeypatch.setenv("ACME_DATABASE_URL", "postgresql://acme")
    monkeypatch.setenv("ACME_KB_DIR", "data/acme-kb")
    r = res.resolve("acme")
    assert r.db_url == "postgresql://acme"
    assert r.kb_dir == str(DATA / "acme-kb")  # data/… -> the data home (HORIZONS_DATA)
    assert r.tools == ("kb_search",) and r.system_prompt is None


def test_build_graph_without_kwargs_is_the_original_analytics_graph():
    G.TOOLSETS.clear()
    G.build_graph(with_memory=False)
    assert list(G.TOOLSETS) == ["analytics"]
    ts = G.TOOLSETS["analytics"]
    assert ts["registry"] is toolbox.REGISTRY and ts["run"] is toolbox.run_tool
    assert ts["system_md"] is None and ts["kb_dir"] is None


def test_scoped_toolset_confines_tools_and_kb(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(toolbox, "kb_search_in",
                        lambda kb_dir, **kw: calls.append((str(kb_dir), kw)) or {"hits": []})
    G.build_graph(with_memory=False, toolset="acme", tools=["kb_search"],
                  kb_dir=tmp_path, system_prompt="ACME prompt")
    ts = G.TOOLSETS["acme"]
    assert list(ts["registry"]) == ["kb_search"] and ts["system_md"] == "ACME prompt"
    assert "error" in ts["run"]("sql_query", {"sql": "select 1"})
    ts["run"]("kb_search", {"query": "q"})
    assert calls == [(str(tmp_path), {"query": "q"})]
    with pytest.raises(ValueError, match="unknown tools"):
        G.build_graph(with_memory=False, toolset="bad", tools=["rm_rf"])


@pytest.mark.skipif(not _db_up(), reason="postgres not running")
def test_host_renders_analytics_and_template_pages(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("HOST_ENABLE", "template")
    monkeypatch.delenv("TEMPLATE_DATABASE_URL", raising=False)
    at = AppTest.from_file(str(HOST / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception
    md = " ".join(m.value for m in at.markdown)  # the analytics Overview rendered
    assert "ac-header" in md
    assert at.selectbox(key="host_tenant").value == "analytics"
    # the switcher, not the nav menu: select tenant #2 -> its first page
    at.selectbox(key="host_tenant").set_value("template").run()
    assert not at.exception
    assert "not configured — set TEMPLATE_DATABASE_URL" in at.warning[0].value
    assert at.selectbox(key="host_tenant").value == "template"
    # and back through the nav menu: the switcher follows the page
    from new_horizons.app import ui_common as U
    nav = U.NAV
    drift = next(p for key, _l, _i, p in nav if key == "drift")
    at.switch_page(str(APP / drift)).run()
    assert not at.exception and at.selectbox(key="host_tenant").value == "analytics"
    # the host's own nav grid lists the current tenant's pages and moves between them
    grid = [b.key for b in at.sidebar.button if (b.key or "").startswith("nav-analytics-")]
    assert len(grid) == len(nav)
    at.button(key=grid[0]).click().run()
    assert not at.exception and at.selectbox(key="host_tenant").value == "analytics"


def test_host_config_mirrors_the_design_system():
    host = (HOST / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    app = (APP / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert host.endswith(app), "run scripts/brand-sync.py: the host mirrors the analytics theme"
    static = HOST / "static"
    assert static.is_symlink() and static.resolve() == (APP / "static").resolve()
