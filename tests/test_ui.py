"""Streamlit design-system guards (Agentization Core): one token file drives
the CSS, the Streamlit theme (config.toml default + runtime themes) and the
chart template; pages compose helpers, hard-code no colours, word every UI
string in both languages, name the farm only through profile.yaml, and
navigation stays one script run per click."""

import inspect
import re
import tomllib
from pathlib import Path

import pytest

from new_horizons.app import ui_common as U

ROOT = Path(__file__).parents[1]
APP = ROOT / "src" / "new_horizons" / "app"

TOKENS = U.TOKENS
THEMES = TOKENS["themes"]
PAGES = sorted(p for p in (APP / "views").glob("*.py") if p.name != "__init__.py")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
ARABIC = re.compile(r"[؀-ۿ]")
THEME_HEX = {v.lower() for t in THEMES.values() for v in t["colors"].values() if HEX.fullmatch(v)}
DOCS = APP / "agents" / "analytics"
# Re-run the dataviz validator before changing these (all six checks pass on every
# theme's card surface: #0a0a0a, #fafafa, #1f1f1f): gold stepped into the band,
# blue, aqua.
VALIDATED_SERIES = ["#b8893a", "#3987e5", "#199e70"]


@pytest.mark.parametrize("lang", sorted(U.LANGS))
@pytest.mark.parametrize("theme", sorted(THEMES))
def test_css_uses_only_token_variables(monkeypatch, theme, lang):
    css = (APP / "design" / "ac.css").read_text()
    assert not HEX.findall(css), "ac.css must use var(--ac-*) only"
    captured = []
    monkeypatch.setattr(U.st, "markdown", lambda body, **kw: captured.append(body))
    U.inject_css(theme, lang)
    used = {h.lower() for h in HEX.findall("".join(captured))}
    assert used and used <= THEME_HEX
    colors = THEMES[theme]["colors"]
    assert all(f"--ac-{var}:{colors[tok]};" in captured[0] for var, tok in U._VARS.items())
    assert f"--ac-dir:{U.LANGS[lang][1]};" in captured[0]
    assert not re.search(r"\bcursor\s*:", captured[0]), "the system pointer, untouched"
    # Arabic is cursive: letter-spacing would pull its joined letters apart
    assert ("letter-spacing:0 !important" in captured[0]) == (lang == "ar")
    # the sidebar sits on the right in Arabic, so it must collapse off the right edge
    assert ("translateX(600px)" in captured[0]) == (lang == "ar")
    # …and its notifications open in the start corner: top-left in Arabic
    assert ("stToastContainer{right:auto;left:0}" in captured[0]) == (lang == "ar")
    for var in set(re.findall(r"var\(--ac-([a-z-]+)\)", css)):
        assert var in U._VARS or var in U._CSS_EXTRA, f"--ac-{var} is not defined"


def test_themes_define_the_same_tokens():
    assert set(THEMES) == {"black", "white", "gray"} and TOKENS["defaultTheme"] == "black"
    keys = set(THEMES["black"]["colors"])
    assert set(U._VARS.values()) <= keys
    for name, t in THEMES.items():
        assert set(t["colors"]) == keys, name
        assert t["base"] in ("dark", "light") and t["label"], name
        assert ARABIC.search(t["labelAr"]), name


def test_white_theme_has_no_black_fills():
    """White carries no black surface: the current square and the tooltip stay white, and
    the nav name tag's glass highlight is light (a dark one read as a spot on White)."""
    c = THEMES["white"]["colors"]
    assert c["navCurrentBg"] == c["tipBg"] == c["bg"]
    assert all(t["colors"]["lensGlow"] == "#ffffff" for t in THEMES.values())


def test_streamlit_config_is_the_default_theme():
    """config.toml is what the browser gets before a saved theme is applied, so
    it must be exactly the default theme (apply_theme is then a no-op for it)."""
    cfg = tomllib.loads((APP / ".streamlit" / "config.toml").read_text())
    th = cfg["theme"]
    flat = {f"theme.{k}": v for k, v in th.items() if isinstance(v, str)}
    flat |= {f"theme.sidebar.{k}": v for k, v in th["sidebar"].items()}
    for key, value in U.streamlit_theme(TOKENS["defaultTheme"]).items():
        assert flat.get(key) == value, key
    assert th["chartCategoricalColors"] == TOKENS["chart"]["series"]
    face = th["fontFaces"][0]
    assert face["family"] == TOKENS["fonts"]["ui"] and th["font"].startswith(face["family"])
    assert (APP / face["url"].removeprefix("app/")).exists()
    assert cfg["server"]["enableStaticServing"] is True
    assert cfg["client"]["showSidebarNavigation"] is False


def test_theme_switch_sets_streamlit_options_once(monkeypatch):
    from streamlit import config
    store: dict = {}
    monkeypatch.setattr(config, "get_option", lambda k: store.get(k))
    monkeypatch.setattr(config, "set_option", lambda k, v, *a: store.__setitem__(k, v))
    assert U.apply_theme("white") is True
    assert store["theme.base"] == "light"
    assert store["theme.backgroundColor"] == THEMES["white"]["colors"]["bg"]
    assert store["theme.sidebar.backgroundColor"] == THEMES["white"]["colors"]["bg"]
    assert U.apply_theme("white") is False        # already applied: no second rerun


def test_settings_round_trip_in_one_file(tmp_path, monkeypatch):
    path = tmp_path / "ui_settings.json"
    monkeypatch.setattr(U, "SETTINGS_FILE", path)
    assert (U.saved_theme(), U.saved_lang()) == (TOKENS["defaultTheme"], U.DEFAULT_LANG)
    U.save_theme("gray")
    U.save_lang("ar")
    assert (U.saved_theme(), U.saved_lang()) == ("gray", "ar")
    path.write_text('{"theme": "neon", "lang": "fr"}')
    assert (U.saved_theme(), U.saved_lang()) == (TOKENS["defaultTheme"], U.DEFAULT_LANG)


def test_tr_follows_the_running_language(monkeypatch):
    monkeypatch.setattr(U, "current_lang", lambda: "ar")
    assert U.tr("Settings", "الإعدادات") == "الإعدادات"
    assert all(ARABIC.search(U.nav_label(k)) for k, *_ in U.NAV + U.NAV_EXTRA)
    monkeypatch.setattr(U, "current_lang", lambda: "en")
    assert U.nav_label("admin") == "Admin center"


@pytest.mark.domain
def test_rule_excerpts_follow_the_language():
    """The KB mirrors each English clause with its Arabic one; an excerpt is one language."""
    if not (U.KB_DIR / "chunks.jsonl").exists():
        pytest.skip("KB not built")
    keys = list(U.citations())
    assert all(not ARABIC.search(U.rule_excerpt(k, lang="en")[1]) for k in keys)
    assert any(ARABIC.search(U.rule_excerpt(k, lang="ar")[1]) for k in keys)
    # a mirrored clause running on into English is cut at the English
    _, ar = U.rule_excerpt("harvest_countersign", 2000, lang="ar")
    assert ARABIC.search(ar) and "technician" not in ar
    # …and the English sentence after an Arabic mirror is not lost in English
    _, en = U.rule_excerpt("stock_unmetered", 2000, lang="en")
    assert "within 2 working days" in en and "stock count" in en


def test_governance_document_has_an_arabic_twin():
    en = (DOCS / "GOVERNANCE.md").read_text(encoding="utf-8")
    ar = (DOCS / "GOVERNANCE.ar.md").read_text(encoding="utf-8")
    assert sorted(re.findall(r"\{\{\w+\}\}", en)) == sorted(re.findall(r"\{\{\w+\}\}", ar))
    assert len(re.findall(r"^## ", en, re.M)) == len(re.findall(r"^## ", ar, re.M))
    assert ARABIC.search(ar) and not ARABIC.search(en)


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_plotly_template_is_token_driven(theme):
    import plotly.io as pio
    U.plotly_template(theme)
    lay = pio.templates["ac"].layout
    border = THEMES[theme]["colors"]["border"]
    assert pio.templates.default == "ac"
    assert pio.templates[f"ac-{theme}"].layout.xaxis.gridcolor == border
    assert list(lay.colorway) == TOKENS["chart"]["series"] == VALIDATED_SERIES
    assert lay.xaxis.gridcolor == lay.yaxis.gridcolor == border
    assert lay.paper_bgcolor == lay.plot_bgcolor == "rgba(0,0,0,0)"
    assert lay.barcornerradius == 4


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_footer_band_geometry_is_the_same_on_every_theme(theme):
    """Only the files follow the theme (gray ink on White) — the marks never move."""
    def no_src(html):
        return re.sub(r"src='[^']*'", "", html)
    html = U.footer_html(theme)
    assert html.count("class='field'") == len(U.FOOTER_MARKS) == 2
    assert no_src(html) == no_src(U.footer_html(TOKENS["defaultTheme"]))
    light = THEMES[theme]["base"] == "light"
    for _alt, dark_file, light_file, _optical in U.FOOTER_MARKS:
        assert (light_file if light else dark_file) in html


@pytest.mark.parametrize("surface", (1, 2), ids=("dark-files", "light-files"))
def test_footer_marks_get_the_same_ink_area(surface):
    """Any mark dropped into static/ is normalised — the same ink area before its
    small optical scale — and fits the box."""
    marks = [(U.footer_mark(m[surface], m[3]), m[3]) for m in U.FOOTER_MARKS]
    sizes = [(g["w"], g["h"]) for g, _ in marks]
    base_areas = [g["w"] * g["h"] / optical ** 2 for g, optical in marks]
    assert max(base_areas) / min(base_areas) < 1.08, sizes
    assert all(.85 <= optical <= 1.15 for _, optical in marks), "optical scales stay small"
    assert all(w <= U.MARK_BOX[0] and h <= U.MARK_BOX[1] for w, h in sizes), sizes


def test_nav_is_nine_existing_pages_in_a_3x3_grid():
    assert len(U.NAV) == 7                          # the analysis pages (the host tenant's too)
    assert U.NAV[-1][0] == "changes" and [k for k, *_ in U.NAV_EXTRA] == ["admin", "settings"]
    grid = U.NAV + U.NAV_EXTRA
    assert len(grid) == 9 and len({k for k, *_ in grid}) == 9
    css = (APP / "design" / "ac.css").read_text()
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    for key, label, icon, path in grid:
        assert (APP / path).exists(), path
        assert icon.startswith(":material/") and label and ARABIC.search(U.NAV_AR[key])


def test_pointer_is_the_systems_own_and_the_script_only_places_the_nav_tag():
    """The pointer is the system's own. Custom pointers were tried and flickered — an image
    pointer at element edges in Chrome and Safari, a page-drawn disc in Chrome — so no pointer
    style is set anywhere. ac-lens.js only places the nav name tag, which glides between
    squares instead of blinking at the gaps; a newer copy of it replaces an older one."""
    js = (APP / "design" / "ac-lens.js").read_text()
    css = (APP / "design" / "ac.css").read_text()
    assert not re.search(r"\bcursor\s*:", css), "leave the system pointer alone"
    assert "ac-pointer" not in css and "cursor" not in js
    assert ".ac-lens.show.slide" in css and "GRACE" in js
    assert '"mouseleave"' in js and '"mouseout"' not in js
    assert not HEX.findall(js), "the tag takes its colours from the theme CSS"
    # observed: DOMPurify (st.html's sanitiser) silently drops a script whose text holds
    # markup such as "<div", and the script never installs — no tag strings in it
    assert not re.search(r"<[/A-Za-z]", js), "build nodes with createElement"
    assert "AbortController" in js and "installed.stop()" in js
    assert "unsafe_allow_javascript=True" in inspect.getsource(U.sidebar)


def test_navigation_is_one_script_run_per_click():
    """A nav button + st.switch_page is two runs (the click, then the page) —
    the second is what left the old page dimmed. st.page_link is one."""
    src = inspect.getsource(U.sidebar)
    assert "st.page_link" in src and "switch_page" not in src


def test_components_escape_and_validate():
    assert "&lt;b&gt;" in U.chip("<b>")
    assert "&lt;x&gt;" in U.html_table(["h"], [["<x>"]])
    assert "<i>ok</i>" in U.html_table(["h"], [[("html", "<i>ok</i>")]])
    assert U.cite("pump-maintenance-sop.md", "3") == "pump-maintenance-sop.md §3"
    with pytest.raises(KeyError):
        U.alert("t", "", kind="info")


@pytest.mark.domain
def test_citation_registry_resolves_in_the_kb():
    if not (U.KB_DIR / "chunks.jsonl").exists():
        pytest.skip("KB not built")
    for key in U.citations():
        where, excerpt = U.rule_excerpt(key, lang="en")
        assert where and excerpt, key


@pytest.mark.domain
def test_invented_citations_never_render():
    """Observed in a live session: the model cited a database table and a tool as
    if they were documents. Neither is in the KB, so neither may reach the screen."""
    if not (U.KB_DIR / "chunks.jsonl").exists():
        pytest.skip("KB not built")
    kb, tools, invented = U.check_citations([
        {"source": "harvest.shipments.md", "section": "3"},
        {"source": "recon_summary.md", "section": "1"},
        {"source": "pump-maintenance-sop.md", "section": "3"},
        {"source": "drift_report", "section": "flags"},
        {"source": "water_ph_band"},                # a registry key, not a file
    ], tools=["drift_report"])
    assert {(c["source"], c["section"]) for c in kb} == {
        ("pump-maintenance-sop.md", "3"), ("water-quality-sop.md", "2")}
    assert tools == ["drift_report"]
    assert invented == ["harvest.shipments.md §3", "recon_summary.md §1"]


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_pages_follow_the_design_system(page):
    src = page.read_text(encoding="utf-8")
    m = re.search(r'U\.page_header\(\s*(?:U\.)?tr\(\s*"([^"]+)",\s*"([^"]+)"\)', src)
    assert m, "every page opens with a page_header titled in both languages"
    en, ar = m.groups()
    assert en.endswith(".") and ar.endswith(".") and ARABIC.search(ar) and not ARABIC.search(en)
    assert "use_container_width" not in src
    assert not HEX.findall(src), "colours come from tokens"
    assert "st.plotly_chart" not in src, "charts go through U.chart (template + config)"
    assert "switch_page" not in src, "navigate with st.page_link: one run, not two"
    assert not re.search(r"\bar=", src), "no Arabic twin beside English: language is a setting"


@pytest.mark.parametrize("path", [*PAGES, APP / "app.py", DOCS / "SYSTEM.md",
                                  DOCS / "GOVERNANCE.md", DOCS / "GOVERNANCE.ar.md"],
                         ids=lambda p: p.name)
def test_the_farm_is_named_only_through_the_profile(path):
    """Prompt, pages and handoff say "the Farm" or read U.PROFILE['farm']."""
    src = path.read_text(encoding="utf-8")
    for name in (U.PROFILE["farm"]["name_en"], U.PROFILE["farm"]["name_ar"]):
        if name.lower() not in ("the farm", "المزرعة"):
            assert name not in src, f"{path.name} hard-codes the farm's name"
