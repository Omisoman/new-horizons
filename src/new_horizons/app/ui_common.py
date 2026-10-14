"""Shared UI for the Streamlit app — Agentization Core design system.

Colours come only from design/tokens.json, which defines three application
themes (black, white, gray). inject_css() turns the active theme into the
--ac-* variables that design/ac.css consumes, plotly_template() builds its
`ac` chart template, and apply_theme() points Streamlit's own theme config at
it (.streamlit/config.toml holds the default; tests/test_ui.py keeps them in
agreement). Pages compose the helpers below and hard-code no colours.

Language: the whole application runs in English or Arabic (Settings; right to
left in Arabic). A UI string is written where it is used, as tr("English",
"العربية"). Data keeps the language it was produced in: analytics JSON, database
rows, the intake pipeline's composed alert and the model's answers.

Smoothness: navigation is st.page_link (one script run per click, where a
button + st.switch_page took two), and a click that changes one panel is a
callback inside a fragment, never an st.rerun() of the whole app.

The farm (logo, name) comes from profile.yaml and appears in chrome only.
The app is also a host tenant (manifest.py): TENANT / RESOURCES scope its
graph, KB and database there.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from html import escape
from pathlib import Path

import streamlit as st
import yaml
from dotenv import load_dotenv

from new_horizons.paths import ROOT
from new_horizons.shared.host.manifest import Resources, tenant_graph
from new_horizons.shared.llm.switch import (  # noqa: F401  (model-level; shared with apps-host)
    current_model_html, default_model, model_dialog, model_label, swap_model)
from new_horizons.shared.llm.provider import (  # noqa: F401  (where inference runs — say it on screen)
    describe as lane_describe, label as lane_label)

load_dotenv(ROOT / ".env")

APP = Path(__file__).parent
DESIGN = APP / "design"
TOKENS = json.loads((DESIGN / "tokens.json").read_text())
THEMES: dict = TOKENS["themes"]
DEFAULT_THEME: str = TOKENS["defaultTheme"]
LANGS = {"en": ("English", "ltr"), "ar": ("العربية", "rtl")}  # code -> (own name, direction)
DEFAULT_LANG = "en"
SERIES = TOKENS["chart"]["series"]
PROFILE = yaml.safe_load((APP / "profile.yaml").read_text())
CURRENCY = PROFILE["market"]["currency"]

# This app agent's isolated resources (host tenant "analytics"). Env
# ANALYTICS_DATABASE_URL / ANALYTICS_KB_DIR win; otherwise DATABASE_URL and
# KB_DIR as before, so standalone `make demo1` needs nothing new.
TENANT = "analytics"
RESOURCES = Resources(
    db_url_env="ANALYTICS_DATABASE_URL",
    kb_dir=ROOT / os.environ.get("KB_DIR", "data/kb"),
    system_prompt=APP / "agents" / "analytics" / "SYSTEM.md",
    tools=("sql_query", "kb_search", "unit_status", "recon_summary", "reconcile_document",
           "audit_trail", "ocr_document", "drift_report", "pattern_scan"),
)
KB_DIR = Path(RESOURCES.resolve(TENANT).kb_dir)
AN_DIR = ROOT / "data" / "analytics"
SAMPLES = ROOT / "data" / "samples"
UPLOADS = ROOT / "data" / "uploads"
SETTINGS_FILE = ROOT / "data" / "ui_settings.json"   # application-wide UI settings: theme, lang

_VARS = {  # css variable -> colour token (every theme defines every token)
    "bg": "bg", "card": "card", "muted": "muted", "border": "border",
    "border-strong": "borderStrong", "fg": "fg", "fg-muted": "fgMuted",
    "fg-subtle": "fgSubtle", "red": "red", "amber": "amber", "green": "green",
    "nav-current-bg": "navCurrentBg", "nav-current-fg": "navCurrentFg",
    "nav-current-border": "navCurrentBorder", "nav-hover": "navHover",
    "tip-bg": "tipBg", "tip-fg": "tipFg", "tip-border": "tipBorder", "logo-rule": "logoRule",
    "lens-glow": "lensGlow", "lens-shadow": "lensShadow",
}
_CSS_EXTRA = ("font", "mono", "scheme", "dir")  # the non-colour variables inject_css() defines


# ---- settings: theme and language ------------------------------------------------------

def _settings() -> dict:
    return load_json(SETTINGS_FILE, {}) or {}


def _save_setting(key: str, value: str) -> None:
    settings = dict(_settings(), **{key: value})
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=1, ensure_ascii=False))


def saved_theme() -> str:
    """The application theme chosen in Settings (data/ui_settings.json), else the default."""
    name = _settings().get("theme")
    return name if name in THEMES else DEFAULT_THEME


def save_theme(name: str) -> None:
    _save_setting("theme", name)


def saved_lang() -> str:
    """The application language chosen in Settings, else English."""
    code = _settings().get("lang")
    return code if code in LANGS else DEFAULT_LANG


def save_lang(code: str) -> None:
    _save_setting("lang", code)


def _session(key: str, default: str) -> str:
    try:
        return st.session_state.get(key, default)
    except Exception:                        # no Streamlit session (tests, scripts)
        return default


def current_theme() -> str:
    """The theme this run renders in (set by setup())."""
    return _session("_ac_theme", DEFAULT_THEME)


def current_lang() -> str:
    """The language this run renders in (set by setup())."""
    return _session("_ac_lang", DEFAULT_LANG)


def tr(en: str, ar: str) -> str:
    """A UI string in the running language, written where it is used."""
    return ar if current_lang() == "ar" else en


class _Palette(Mapping):
    """U.C — the active theme's colours, looked up at use, so a chart mark
    coloured U.C["red"] follows the theme the way the CSS does."""

    def __getitem__(self, key: str) -> str:
        return THEMES[current_theme()]["colors"][key]

    def __iter__(self):
        return iter(THEMES[DEFAULT_THEME]["colors"])

    def __len__(self) -> int:
        return len(THEMES[DEFAULT_THEME]["colors"])


C = _Palette()


def streamlit_theme(name: str) -> dict[str, str]:
    """Streamlit's own theme options for a token theme: what config.toml holds
    for the default, and what apply_theme() sets at runtime for the others."""
    t, c = THEMES[name], THEMES[name]["colors"]
    return {
        "theme.base": t["base"], "theme.primaryColor": c["fg"],
        "theme.backgroundColor": c["bg"], "theme.secondaryBackgroundColor": c["card"],
        "theme.textColor": c["fg"], "theme.borderColor": c["border"], "theme.linkColor": c["fg"],
        "theme.dataframeBorderColor": c["border"],
        "theme.dataframeHeaderBackgroundColor": c["card"],
        "theme.redColor": c["red"], "theme.greenColor": c["green"],
        "theme.sidebar.backgroundColor": c["bg"],
        "theme.sidebar.secondaryBackgroundColor": c["card"],
        "theme.sidebar.borderColor": c["border"],
    }


def apply_theme(name: str) -> bool:
    """Point Streamlit's theme config at `name`; True if anything changed.

    Streamlit's theme is server config, sent to the browser as each run starts,
    so its widgets (dataframes, dialogs, toasts) recolour on the run after the
    change — setup() restarts the run once for that. It is server-wide, which is
    what an application theme is."""
    from streamlit import config
    changed = False
    for key, value in streamlit_theme(name).items():
        if config.get_option(key) != value:
            config.set_option(key, value)
            changed = True
    return changed


@lru_cache(maxsize=4)
def _css_at(_mtime_ns: int) -> str:
    return (DESIGN / "ac.css").read_text()


@lru_cache(maxsize=4)
def _lens_js_at(_mtime_ns: int) -> str:
    return (DESIGN / "ac-lens.js").read_text()


def inject_css(theme: str | None = None, lang: str | None = None) -> None:
    """The app's only CSS: the theme's token variables and reading direction,
    each theme option's preview colours (Settings), design/ac.css, and the
    Arabic-only rules: no letter-spacing anywhere (tracking breaks Arabic's joined
    letters), and the sidebar — on the right in Arabic — collapses off the right
    edge. Streamlit collapses it with translateX(-width), which assumes a left
    sidebar and would slide it across the page; 600px is Streamlit's widest sidebar."""
    t = THEMES[theme or current_theme()]
    code = lang or current_lang()
    c = t["colors"]
    root = "".join(f"--ac-{var}:{c[token]};" for var, token in _VARS.items())
    root += (f"--ac-font:{TOKENS['fonts']['uiStack']};--ac-mono:{TOKENS['fonts']['mono']};"
             f"--ac-scheme:{t['base']};--ac-dir:{LANGS[code][1]};")
    swatches = "".join(
        f'[class*="st-key-theme-{n}"]{{--sw-bg:{o["colors"]["bg"]};--sw-card:{o["colors"]["card"]};'
        f'--sw-fg:{o["colors"]["fg"]};--sw-subtle:{o["colors"]["fgSubtle"]}}}'
        for n, o in THEMES.items())
    # Streamlit pins toasts top-right; in Arabic they open top-left, the start corner
    arabic = ('[data-testid="stApp"] *,.ac-lens{letter-spacing:0 !important}'
              '[data-testid="stSidebar"][aria-expanded="false"]{transform:translateX(600px)}'
              '[data-testid="stToastContainer"].stToastContainer{right:auto;left:0}'
              if code == "ar" else "")
    css = _css_at((DESIGN / "ac.css").stat().st_mtime_ns)
    st.markdown(f"<style>:root{{{root}}}\n{swatches}\n{css}\n{arabic}</style>",
                unsafe_allow_html=True)


_TEMPLATES: dict[str, object] = {}


def plotly_template(theme: str | None = None) -> None:
    """Register the theme's `ac` Plotly template (also as `ac-<theme>`) and make
    it the default: transparent surfaces (charts sit on cards), hairline grid in
    the theme's border tone, muted axes, the validated series order, 4px rounded
    bar ends."""
    import plotly.io as pio
    name = theme or current_theme()
    if name not in _TEMPLATES:
        _TEMPLATES[name] = _build_template(name)
    pio.templates[f"ac-{name}"] = _TEMPLATES[name]
    pio.templates["ac"] = _TEMPLATES[name]
    pio.templates.default = "ac"


def _build_template(name: str):
    import plotly.graph_objects as go
    import plotly.io as pio
    t, c = THEMES[name], THEMES[name]["colors"]
    font = TOKENS["fonts"]["uiStack"]
    axis = dict(gridcolor=c["border"], zerolinecolor=c["border"], linecolor=c["border"],
                tickfont=dict(color=c["fgSubtle"], size=12),
                title=dict(font=dict(color=c["fgSubtle"], size=12)))
    tpl = go.layout.Template(pio.templates["plotly_white" if t["base"] == "light" else "plotly_dark"])
    tpl.layout.update(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=font, color=c["fgMuted"], size=13),
        colorway=SERIES, piecolorway=SERIES, xaxis=axis, yaxis=axis,
        barcornerradius=4, bargap=0.28,
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", x=0, y=1.12,
                    font=dict(color=c["fgMuted"], size=12)),
        hoverlabel=dict(bgcolor=c["card"], bordercolor=c["borderStrong"],
                        font=dict(family=font, color=c["fg"], size=12)),
        margin=dict(t=40, r=12, b=36, l=52),
        title=dict(font=dict(size=14, color=c["fg"]), x=0, xanchor="left"),
    )
    return tpl


def setup(themed: bool = False) -> None:
    """Per-run page setup. The standalone app passes themed=True and follows the
    theme and language saved in Settings; the apps-host tenant keeps the
    defaults, since the host shell owns its own theme."""
    name = saved_theme() if themed else DEFAULT_THEME
    lang = saved_lang() if themed else DEFAULT_LANG
    if themed and apply_theme(name):
        st.rerun()                           # this run's browser theme predates the change
    st.session_state["_ac_theme"] = name
    st.session_state["_ac_lang"] = lang
    inject_css(name, lang)
    plotly_template(name)


def card(key: str, **kw):
    """A bordered container styled as an AC card (2px border, card tone) —
    the keyed class `st-key-card-*` is what design/ac.css targets."""
    return st.container(border=True, key=f"card-{key}", **kw)


def chart(fig, height: int = 340) -> None:
    # Streamlit fills UNSET layout backgrounds with its theme colours even with
    # theme=None — set them on the figure itself so charts sit on their card.
    fig.update_layout(height=height, template=f"ac-{current_theme()}",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, theme=None, config={"displayModeBar": False})


def flush_toast() -> None:
    """Show the toast a callback queued: the sidebar does it on full runs, a
    fragment on its own reruns."""
    if msg := st.session_state.pop("toast", None):
        st.toast(msg, icon=":material/notifications_active:")


# ---- components -----------------------------------------------------------------------

def chip(text: str, kind: str = "") -> str:
    """Uppercase pill. kind: '' | strong | solid | red | amber."""
    return f"<span class='ac-chip {kind}'>{escape(text)}</span>"


def page_header(title: str, subtitle: str = "", chips: Sequence[str] = ()) -> None:
    """Title (house style ends in a full stop), muted subtitle, chips at the end."""
    sub = f"<p class='sub'>{escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        f"<div class='ac-header'><div><h1>{escape(title)}</h1>{sub}</div>"
        f"<div class='chips'>{''.join(chips)}</div></div>", unsafe_allow_html=True)


def section(title: str, right: str = "") -> None:
    st.markdown(f"<div class='ac-section'><h3>{escape(title)}</h3>"
                f"<span class='ac-label'>{escape(right)}</span></div>",
                unsafe_allow_html=True)


def stat_cards(items: Sequence[tuple], cols: int | None = None) -> None:
    """[(label, value, sub[, flag])] -> one row of AC cards. flag=True paints
    the value red — reserved for discrepancy counts, never a plain KPI."""
    cells = []
    for it in items:
        label, value = it[0], it[1]
        sub = it[2] if len(it) > 2 else ""
        flag = len(it) > 3 and it[3]
        cells.append(
            f"<div class='ac-card{' flag' if flag else ''}'><div class='ac-label'>"
            f"{escape(label)}</div><div class='v'>{escape(str(value))}</div>"
            + (f"<div class='s'>{escape(sub)}</div>" if sub else "") + "</div>")
    n = cols or len(items)
    st.markdown(f"<div class='ac-grid' style='grid-template-columns:repeat({n},minmax(0,1fr))'>"
                f"{''.join(cells)}</div>", unsafe_allow_html=True)


def alert(title: str, body_html: str, pill: str = "", kind: str = "red") -> None:
    """Bordered alert card. kind: red (discrepancy) | amber (warning) | ok."""
    pill_kind = {"red": "red", "amber": "amber", "ok": "strong"}[kind]
    st.markdown(
        f"<div class='ac-alert {'' if kind == 'red' else kind}'><div class='head'>"
        f"{chip(pill or tr('Discrepancy', 'تباين'), pill_kind)}<b>{escape(title)}</b></div>"
        f"{body_html}</div>", unsafe_allow_html=True)


def check_icon(status: str) -> str:
    glyph = {"pass": "✓", "fail": "✕", "warn": "!", "skip": "–"}.get(status, "–")
    return f"<span class='ac-check {status}'>{glyph}</span>"


def html_table(headers: Sequence[str], rows: Sequence[Sequence], ar_cols: Sequence[int] = (),
               row_class: Sequence[str] | None = None) -> str:
    """Cells are escaped unless given as ("html", markup)."""
    def cell(v, i):
        body = v[1] if isinstance(v, tuple) and len(v) == 2 and v[0] == "html" else escape(str(v))
        return f"<td{' class=ar' if i in ar_cols else ''}>{body}</td>"
    body = "".join(
        f"<tr class='{row_class[r] if row_class else ''}'>"
        + "".join(cell(v, i) for i, v in enumerate(row)) + "</tr>"
        for r, row in enumerate(rows))
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    return f"<table class='ac-table'><tr>{head}</tr>{body}</table>"


def money(v: float | None, decimals: int = 0) -> str:
    return "—" if v is None else f"{float(v):,.{decimals}f} {CURRENCY}"


def money_short(v: float | None) -> str:
    """6.01M EUR / 842K EUR — for cards where a full figure would wrap."""
    if v is None:
        return "—"
    v = float(v)
    for div, suffix in ((1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{v / div:,.{2 if div == 1e6 else 0}f}{suffix} {CURRENCY}"
    return money(v)


_INLINE_CITE = re.compile(r"([a-z0-9-]+\.md)\s*(?:§|section\s*)\s*([\d.]+)", re.I)


def extract_citations(text: str) -> list[dict]:
    """Citations the model wrote into the prose (e.g. "[payment-controls.md §3]")
    instead of the citations field. Small models do this often enough that the
    answer would otherwise render with no citation line at all."""
    seen, out = set(), []
    for source, section in _INLINE_CITE.findall(text or ""):
        key = (source.lower(), section.rstrip("."))
        if key not in seen:
            seen.add(key)
            out.append({"source": key[0], "section": key[1]})
    return out


def check_citations(cites: list[dict], tools: list[str] | None = None) -> tuple[list, list, list]:
    """Split what the model cited into (kb, tool, invented).

    A citation only counts if its (source, section) is actually in the indexed
    knowledge base; a tool name counts as provenance if that tool really ran
    this turn. Everything else the model made up — and it does: observed
    "finance.gl_accounts.md §3" (a database table) and "recon_summary.md §1"
    (a tool). Rendering those as sources is the one thing the governance
    document promises never happens.
    """
    sections, reg = _kb_sections(), citations()
    kb, tool, invented = [], [], []
    for c in cites or []:
        src = str(c.get("source") or "").strip()
        sec = str(c.get("section") or c.get("page") or "").strip().lstrip("§ ")
        if src in reg:                                   # a registry key, not a file
            src, sec = reg[src]["source"], str(reg[src]["section"])
        base = src.split(" ")[0]
        if (src, sec) in sections or (src, "") in sections:
            kb.append({"source": src, "section": sec})
        elif base.removesuffix(".md") in (tools or []):
            tool.append(base.removesuffix(".md"))
        else:
            invented.append(f"{src} §{sec}" if sec else src)
    return kb, tool, invented


def cite(source: str, section: str | int | None = None) -> str:
    """Display form of a KB citation: `payment-controls.md §3`."""
    return f"{source} §{section}" if section not in (None, "") else source


@st.cache_data
def citations() -> dict:
    """The citation registry (ingest/kb_synthetic/citations.yaml): key -> source/section."""
    return yaml.safe_load((APP / "ingest" / "kb_synthetic" / "citations.yaml").read_text())


@st.cache_data
def _kb_sections() -> dict:
    out: dict = {}
    path = KB_DIR / "chunks.jsonl"
    if path.exists():
        for line in path.read_text().splitlines():
            c = json.loads(line)
            m = c["meta"]
            key = (m.get("source"), str(m.get("section", "")))
            prev = out.get(key)
            out[key] = {"heading": m.get("heading", ""), "title": m.get("title", ""),
                        "text": (prev["text"] + "\n" if prev else "") + c["text"]}
    return out


def kb_section(source: str, section: str) -> dict | None:
    """{heading, title, text} of one KB section, straight from the index."""
    return _kb_sections().get((source, str(section)))


_ARABIC = re.compile(r"[؀-ۿ]")
_SENTENCE = re.compile(r"(?<=[.:;!?؟])\s+")


def in_language(text: str, lang: str | None = None) -> str:
    """One language out of a bilingual KB line. The corpus mirrors an English clause
    with its Arabic one after " — ", but a mirror can run straight on into the next
    English sentence ("… غير طبيعية: one technician logging …"), so each " — " part
    is filtered sentence by sentence and only the running language's are kept."""
    arabic = (lang or current_lang()) == "ar"
    parts = []
    for part in text.split(" — "):
        kept = [s for s in _SENTENCE.split(part) if s and bool(_ARABIC.search(s)) == arabic]
        if kept:
            parts.append(" ".join(kept))
    return " — ".join(parts).strip(" —:")


def section_bullets(text: str, english_only: bool = True, lang: str | None = None) -> list[str]:
    """A KB section's bullets/paragraphs, wrapped lines joined, markdown
    stripped. With english_only (the default; the name predates Arabic) only one
    language's clauses are kept — the running language, or `lang`."""
    items: list[str] = []
    for line in text.splitlines()[1:]:          # line 0 = "title › heading"
        s = line.strip()
        if not s or s.startswith("|") or s.startswith("#"):
            continue
        if s[:2] in ("- ", "* ") or s[:3].rstrip(".").isdigit() or not items:
            items.append(s.lstrip("-* ").strip())
        else:
            items[-1] += " " + s
    out = []
    for it in items:
        it = it.replace("**", "").replace("`", "")
        if english_only:
            it = in_language(it, lang)
        if it:
            out.append(it)
    return out


def rule_excerpt(key: str, chars: int = 320, lang: str | None = None) -> tuple[str, str]:
    """(citation, excerpt) for a citations.yaml key — the governing rule text, in
    the running language (English where a section has no Arabic mirror)."""
    c = citations().get(key)
    if not c:
        return "", ""
    sec = kb_section(c["source"], c["section"])
    text = sec["text"] if sec else ""
    bullets = section_bullets(text, lang=lang) or section_bullets(text, lang="en")
    body = " ".join(b if b[-1:] in ".:;!?…؟" else b + "." for b in bullets)
    if len(body) > chars:
        body = body[:chars].rsplit(" ", 1)[0] + "…"
    return cite(c["source"], c["section"]), body


# ---- governance ---------------------------------------------------------------------------
# Decisions and pause/resume are audit events (shared/audit/audit.py), never UI
# state: what the drawer shows is the chain itself, and nothing can be changed
# without breaking it.

DECISION_CHIP = {"approve": ("Approved", "strong"), "escalate": ("Escalated to the owner", "amber"),
                 "reject": ("Rejected", "red")}
_DECISION_AR = {"approve": "معتمد", "escalate": "مُصعَّد إلى المالك", "reject": "مرفوض"}


def decision_chip(decision: str) -> tuple[str, str]:
    """(label, chip kind) of a recorded decision, in the running language."""
    text, kind = DECISION_CHIP.get(decision, (decision, "strong"))
    return tr(text, _DECISION_AR.get(decision, text)), kind


def operator() -> str:
    """Who is acting. The demo has no sign-in: HORIZONS_OPERATOR, else the OS user."""
    return os.environ.get("HORIZONS_OPERATOR") or os.environ.get("USER") or "demo operator"


@st.cache_data(ttl=5, show_spinner=False)
def _decisions() -> dict:
    from new_horizons.shared.audit.audit import decisions
    try:
        return decisions()
    except Exception:
        return {}


@st.cache_data(ttl=5, show_spinner=False)
def agent_paused() -> tuple[bool, str | None, object]:
    """(paused, who, when) from the latest kill-switch event."""
    from new_horizons.shared.audit.audit import agent_state
    try:
        s = agent_state()
        return (not s["active"], s["actor"], s["ts"])
    except Exception:
        return (False, None, None)


def _decide(subject: str, decision: str, label: str, rule: str | None,
            detail: str | None) -> None:
    from new_horizons.shared.audit.audit import record_decision
    record_decision(subject, decision, operator(), rule=rule, detail=detail,
                    subject_label=label)
    _decisions.clear()
    st.session_state["toast"] = (f"{decision_chip(decision)[0]} · {subject} · "
                                 f"{tr('written to audit', 'سُجّل في سجل التدقيق')}")


@st.fragment
def approval_bar(subject: str, label: str, rule: str | None = None,
                 detail: str | None = None, key_suffix: str = "") -> None:
    """Awaiting · Farm Manager → Approve / Escalate to the owner / Reject.
    Every click writes one audit line (who, when, which rule) from a callback,
    and reruns this bar only."""
    flush_toast()
    decided = _decisions().get(subject)
    if decided:
        text, kind = decision_chip(decided["decision"])
        when = decided["ts"].strftime("%d %b %Y %H:%M") if decided.get("ts") else ""
        st.markdown(
            f"<div class='ac-approval'>{chip(text, kind)}"
            f"<span class='ac-subtle'>{escape(decided['approver'] or '')} · {when}"
            f"{' · ' + escape(decided['rule']) if decided.get('rule') else ''}</span>"
            f"</div>", unsafe_allow_html=True)
        return
    wkey = f"{subject}{key_suffix}"
    with st.container(key=f"approval-{wkey}"):
        head, c1, c2, c3 = st.columns([2.2, 1, 1.25, 1], vertical_alignment="center")
        head.markdown(f"<div class='ac-approval'>"
                      f"{chip(tr('Awaiting · Farm Manager', 'بانتظار · مدير المزرعة'))}"
                      f"<span class='ac-subtle'>{escape(label)}</span></div>",
                      unsafe_allow_html=True)
        for col, (decision, text, prefix) in zip(
                (c1, c2, c3), (("approve", tr("Approve", "اعتماد"), "ap"),
                               ("escalate", tr("Escalate to owner", "تصعيد للمالك"), "es"),
                               ("reject", tr("Reject", "رفض"), "rj"))):
            col.button(text, key=f"{prefix}-{wkey}", width="stretch", on_click=_decide,
                       args=(subject, decision, label, rule, detail))


_EVENT_LABEL = {"model_call": "model call", "tool_call": "tool call", "retrieve": "retrieval",
                "answer": "answer", "intake_step": "intake step", "decision": "decision",
                "agent_state": "agent state"}
_EVENT_LABEL_AR = {"model_call": "استدعاء نموذج", "tool_call": "استدعاء أداة",
                   "retrieve": "استرجاع", "answer": "إجابة", "intake_step": "خطوة استلام",
                   "decision": "قرار", "agent_state": "حالة الوكيل"}


def _event_row(e: dict) -> tuple:
    p = e.get("payload") or {}
    etype = e["event_type"]
    subject = (p.get("subject") or p.get("unit_id") or p.get("ref") or p.get("tool")
               or p.get("model") or "")
    if etype == "decision":
        outcome = decision_chip(p.get("decision", ""))[0]
    elif etype == "agent_state":
        outcome = tr("resumed", "استؤنف") if p.get("active") else tr("paused", "أُوقف")
    elif etype == "chain_carried":
        # a rotation's checkpoint (shared/audit/rotate.py): state carried from the archive
        n = int((p.get("counts") or {}).get("decision", 0))
        states = [e for e in p.get("carried") or [] if e.get("event_type") == "agent_state"]
        running = (states[-1].get("payload") or {}).get("active", True) if states else True
        src = p.get("from_table", "")
        subject = tr("state carried forward", "حالة مُرحّلة")
        outcome = tr(f"{n} decisions · agent {'running' if running else 'paused'} · from {src}",
                     f"{n} قرارات · الوكيل {'يعمل' if running else 'متوقف'} · من {src}")
    elif "ok" in p:
        outcome = tr("ok", "نجح") if p["ok"] else tr("error", "خطأ")
    else:
        hits = p.get("hits")
        outcome = p.get("route") or (tr(f"{hits} hits", f"{hits} نتيجة") if "hits" in p else "")
    return (e["ts"].strftime("%d %b %H:%M:%S"), e["actor"],
            tr(_EVENT_LABEL.get(etype, etype), _EVENT_LABEL_AR.get(etype, etype)), str(subject),
            str(p.get("rule") or ""), outcome, e["hash"][:8])


def _audit_body(contains: str | None) -> None:
    from new_horizons.shared.audit.audit import events
    st.markdown("<p class='ac-subtle'>" + tr(
        "Hash-chained, append-only. Each row carries the head of its own hash; changing "
        "any row breaks every row after it.",
        "سجل متسلسل بالتجزئة وقابل للإضافة فقط. يحمل كل صف تجزئته، وأي تغيير في صف يكسر "
        "كل الصفوف التي تليه.") + "</p>", unsafe_allow_html=True)
    q = st.text_input(tr("Filter", "تصفية"), value=contains or "",
                      placeholder=tr("unit, work order, shipment, rule, tool…",
                                     "وحدة، أمر عمل، شحنة، قاعدة، أداة…"))
    rows = [_event_row(e) for e in events(limit=300, contains=q.strip() or None)]
    st.markdown(f"<div class='ac-label'>{tr(f'{len(rows)} events', f'{len(rows)} حدث')}</div>",
                unsafe_allow_html=True)
    st.markdown(html_table([tr("Time", "الوقت"), tr("Actor", "الجهة"), tr("Action", "الإجراء"),
                            tr("Subject", "الموضوع"), tr("Rule", "القاعدة"),
                            tr("Outcome", "النتيجة"), tr("Hash", "التجزئة")], rows[:120]),
                unsafe_allow_html=True)


def _verify_chain_button(col, key: str) -> None:
    from new_horizons.shared.audit.audit import verify_chain
    if col.button(tr("Verify chain", "التحقق من السلسلة"), key=key, width="stretch"):
        v = verify_chain()
        if v["ok"]:
            st.success(tr(f"{v['rows']} rows · chain verified", f"{v['rows']} صف · السلسلة سليمة"))
        else:
            st.error(tr(f"{v['rows']} rows · chain BROKEN at row {v['break_at']}",
                        f"{v['rows']} صف · السلسلة مكسورة عند الصف {v['break_at']}"))


def _audit_dialog_body(contains: str | None) -> None:
    _audit_body(contains)
    left, right = st.columns([1, 1])
    _verify_chain_button(left, "audit-dialog-verify")
    if right.button(tr("Close", "إغلاق"), type="primary", width="stretch",
                    key="audit-dialog-close"):
        st.rerun()


def audit_dialog(contains: str | None = None) -> None:
    """Every model call, tool call, decision and pause — the screen an examiner
    opens first. Filter is a plain match anywhere in the event payload. The
    dialog is built per call so its title follows the language."""
    st.dialog(tr("Audit trail", "سجل التدقيق"), width="large")(_audit_dialog_body)(contains)


@st.fragment
def audit_trail(contains: str | None = None, key: str = "audit") -> None:
    """The same trail inline (Admin center): filtering and verifying rerun this
    panel only."""
    _audit_body(contains)
    left, _ = st.columns([1, 2])
    _verify_chain_button(left, f"{key}-verify")


def audit_link(contains: str, label: str | None = None, key_suffix: str = "") -> None:
    """One click from any finding into the drawer, pre-filtered to it."""
    if st.button(label or tr("Audit trail", "سجل التدقيق"), icon=":material/history:",
                 key=f"audit-{contains}{key_suffix}"):
        audit_dialog(contains)


def _toggle_agent(paused: bool) -> None:
    from new_horizons.shared.audit.audit import set_agent_state
    set_agent_state(paused, operator())            # paused -> resume, active -> pause
    agent_paused.clear()
    st.session_state["toast"] = (tr("Agent resumed", "استؤنف عمل الوكيل") if paused else
                                 tr("Agent paused — automated actions stopped",
                                    "أُوقف الوكيل مؤقتاً — توقفت الإجراءات الآلية"))


@st.fragment
def kill_switch() -> None:
    """Agent · Active / Paused. Pausing stops every automated action (document
    intake, chat answers) and is written to the audit chain with who and when."""
    flush_toast()
    paused, who, ts = agent_paused()
    label, kind = (tr("Paused", "متوقف"), "red") if paused else (tr("Active", "نشط"), "strong")
    when = ts.strftime("%d %b %H:%M") if ts is not None else ""
    st.markdown(f"<div class='ac-agent'><span class='ac-label'>{tr('Agent', 'الوكيل')}</span>"
                f"{chip(label, kind)}</div>"
                + (f"<div class='ac-subtle' style='margin:-.2rem .1rem .4rem'>"
                   f"{escape(who or '')} · {when}</div>" if who else ""),
                unsafe_allow_html=True)
    st.button(tr("Resume agent", "استئناف الوكيل") if paused
              else tr("Pause agent", "إيقاف الوكيل مؤقتاً"),
              icon=":material/play_arrow:" if paused else ":material/pause:",
              key="kill-switch", width="stretch", on_click=_toggle_agent, args=(paused,))


@st.fragment
def model_panel() -> None:
    """The model switch (shared/llm/switch.py). Opening the dialog reruns this
    panel only; confirming a switch reruns the app, so every chip follows."""
    if st.button(tr("Switch model", "تبديل النموذج"), icon=":material/swap_horiz:",
                 key="model-switch", width="stretch"):
        model_dialog()
    st.markdown(current_model_html(), unsafe_allow_html=True)


def _pick_theme(name: str) -> None:
    if name != saved_theme():
        save_theme(name)
        t = THEMES[name]
        st.session_state["toast"] = tr(f"Theme · {t['label']}", f"المظهر · {t['labelAr']}")


def theme_picker() -> None:
    """Black · White · Gray, each option previewing its own theme. The choice is
    application-wide (data/ui_settings.json) and survives restarts."""
    current = current_theme()
    with st.container(key="theme-picker"):
        for name, t in THEMES.items():
            with st.container(key=f"theme-{name}{'--current' if name == current else ''}"):
                st.button(tr(t["label"], t["labelAr"]), key=f"theme-btn-{name}",
                          width="stretch", on_click=_pick_theme, args=(name,))


def _pick_lang(code: str) -> None:
    if code != saved_lang():
        save_lang(code)
        st.session_state["toast"] = LANGS[code][0]


def lang_picker() -> None:
    """English · العربية — the whole application, each language named in its own
    script. Saved beside the theme; takes effect on the run the click starts."""
    current = current_lang()
    with st.container(key="lang-picker"):
        for code, (name, _direction) in LANGS.items():
            with st.container(key=f"lang-{code}{'--current' if code == current else ''}"):
                st.button(name, key=f"lang-btn-{code}", width="stretch",
                          on_click=_pick_lang, args=(code,))


# ---- sidebar ---------------------------------------------------------------------------

NAV = [  # key, label, material icon, page file — the analysis pages (also the host tenant's)
    ("overview", "Overview", ":material/space_dashboard:", "views/overview.py"),
    ("reconcile", "Reconcile", ":material/rule:", "views/reconcile.py"),
    ("drift", "Drift", ":material/monitoring:", "views/drift.py"),
    ("patterns", "Patterns", ":material/hub:", "views/patterns.py"),
    ("documents", "Documents", ":material/document_scanner:", "views/documents.py"),
    ("chat", "Chat", ":material/forum:", "views/chat.py"),
    ("changes", "Changes", ":material/rocket_launch:", "views/changes.py"),
]
NAV_EXTRA = [  # the last row of the same grid: administration, not analysis
    ("admin", "Admin center", ":material/admin_panel_settings:", "views/admin.py"),
    ("settings", "Settings", ":material/settings:", "views/settings.py"),
]
NAV_AR = {"overview": "نظرة عامة", "reconcile": "المطابقة", "drift": "الانحراف",
          "patterns": "الأنماط", "documents": "المستندات", "chat": "المحادثة",
          "changes": "التغييرات", "admin": "مركز الإدارة", "settings": "الإعدادات"}


def nav_label(key: str) -> str:
    """A page's name in the running language (sidebar tooltip, browser tab)."""
    return tr(next(label for k, label, *_ in NAV + NAV_EXTRA if k == key), NAV_AR[key])


STATIC = APP / "static"
FOOTER_MARKS = (  # (alt, dark file, light file, optical scale) in static/: corner field first
    ("agentization-core", "ac-mark.svg", "ac-mark-for-light.svg", 0.92),
    ("sojourner", "sojourner-mark.svg", "sojourner-mark-for-light.svg", 0.92),
)  # builder, then the sibling that develops this app (its deploys are the Changes page).
   # Light files carry gray ink (AC's from the website's brand assets, sojourner's from
   # scripts/brand-marks.py); the scale corrects equal ink area optically.
MARK_AREA = 2200       # px² of ink per footer mark before its optical scale
MARK_BOX = (120, 52)   # the most one mark may occupy inside its field


def farm_logo(theme: str | None = None) -> Path:
    """The farm's logo (profile.yaml): an SVG whose viewBox is its ink. On a light
    theme its `-for-light` twin (gray ink) when there is one — White carries no
    white-on-black marks."""
    logo = ROOT / PROFILE["farm"]["logo"]
    light = logo.with_name(f"{logo.stem}-for-light{logo.suffix}")
    return light if THEMES[theme or current_theme()]["base"] == "light" and light.exists() else logo


def footer_mark(name: str, optical: float = 1.0) -> dict:
    """Display geometry for a footer mark, whatever file is dropped in: its ink
    (a raster's transparent margins cropped away; an SVG's viewBox is its ink)
    scaled to MARK_AREA, then by its optical scale, capped by MARK_BOX. The crop
    is CSS on the static file: `w`×`h` is the ink box, the image is offset inside
    it by `dx`/`dy`."""
    return _mark_geometry(name, (STATIC / name).stat().st_mtime_ns, optical)


@lru_cache(maxsize=16)
def _mark_geometry(name: str, _mtime_ns: int, optical: float) -> dict:
    path = STATIC / name
    if path.suffix == ".svg":
        svg = path.read_text()
        box = re.search(r'viewBox="([^"]+)"', svg)
        nat_w, nat_h = (map(float, box.group(1).split()[2:]) if box else
                        (float(re.search(r'width="([\d.]+)', svg).group(1)),
                         float(re.search(r'height="([\d.]+)', svg).group(1))))
        x0, y0, x1, y1 = 0.0, 0.0, nat_w, nat_h
    else:
        from PIL import Image
        with Image.open(path) as im:
            rgba = im.convert("RGBA")
        nat_w, nat_h = rgba.size
        x0, y0, x1, y1 = rgba.getchannel("A").getbbox() or (0, 0, nat_w, nat_h)
    ink_w, ink_h = x1 - x0, y1 - y0
    scale = min((MARK_AREA / (ink_w * ink_h)) ** .5 * optical,
                MARK_BOX[0] / ink_w, MARK_BOX[1] / ink_h)
    return {"src": f"app/static/{name}", "w": round(ink_w * scale), "h": round(ink_h * scale),
            "img_w": round(nat_w * scale, 2), "img_h": round(nat_h * scale, 2),
            "dx": round(x0 * scale, 2), "dy": round(y0 * scale, 2)}


def footer_html(theme: str | None = None) -> str:
    """The footer band: a rule across the sidebar and two equal fields split by a
    divider, each mark centred in its field at the same ink area. The geometry
    never changes with the theme; on a light theme the marks use their gray-ink
    files, since their own white ink would vanish."""
    light = THEMES[theme or current_theme()]["base"] == "light"
    fields = []
    for alt, dark_file, light_file, optical in FOOTER_MARKS:
        m = footer_mark(light_file if light else dark_file, optical)
        fields.append(
            f"<span class='field'><span class='mark' style='width:{m['w']}px;height:{m['h']}px'>"
            f"<img src='{m['src']}' alt='{escape(alt)}' style='width:{m['img_w']}px;"
            f"height:{m['img_h']}px;margin:-{m['dy']}px 0 0 -{m['dx']}px'></span></span>")
    return f"<div class='ac-footer'>{''.join(fields)}</div>"


def sidebar(pages: dict, current_key: str) -> None:
    """Farm logo → 3×3 icon navigation (seven analysis pages, Admin center,
    Settings) → the footer band. Each square is an st.page_link in a wrapper
    whose key carries its state (`--current`, `--alert`) for design/ac.css."""
    if current_key == "chat":                 # alerts are read once Chat is open
        st.session_state["unread_alerts"] = []
    flush_toast()
    unread = len(st.session_state.get("unread_alerts", []))
    with st.sidebar:
        with st.container(key="farm-logo"):
            st.image(str(farm_logo()), width=220)
        with st.container(key="app-nav"):
            for key, _label, icon, _ in NAV + NAV_EXTRA:
                alert_dot = key == "chat" and unread > 0
                state = ("--current" if key == current_key else "") + ("--alert" if alert_dot else "")
                label = nav_label(key)
                with st.container(key=f"nav-{key}{state}"):
                    st.page_link(pages[key], icon=icon, width="stretch",
                                 label=f"{label} · {unread} {tr('new', 'جديد')}"
                                 if alert_dot else label)
        st.markdown(footer_html(), unsafe_allow_html=True)
        # The nav name tag (design/ac-lens.js): the app's one script — it places the glass
        # tag that rises over a nav square. Its carrier is hidden by ac.css.
        with st.container(key="ac-lens"):
            js = _lens_js_at((DESIGN / "ac-lens.js").stat().st_mtime_ns)
            st.html(f"<script>{js}</script>", unsafe_allow_javascript=True)


# ---- data + agent ------------------------------------------------------------------------

def load_json(path: Path, default=None):
    """Parsed JSON, re-read only when the file changes. Shared across reruns and
    sessions — treat the result as read-only."""
    try:
        return _json_at(str(path), path.stat().st_mtime_ns)
    except Exception:
        return default


@lru_cache(maxsize=64)
def _json_at(path: str, _mtime_ns: int):
    return json.loads(Path(path).read_text())


def mock_meta() -> dict | None:
    return load_json(ROOT / "data" / "mock_meta.json")


def graph():
    """This tenant's graph — its tools, KB and prompt; cached per tenant."""
    return tenant_graph(TENANT, RESOURCES)


def ask_agent(question: str, model: str, thread_id: str) -> dict:
    from new_horizons.shared.harness.graph import ask
    return ask(graph(), question, model, thread_id, toolset=TENANT)


@st.cache_resource
def db():
    import psycopg
    url = RESOURCES.resolve(TENANT).db_url or os.environ.get(
        "DATABASE_URL", "postgresql://horizons:horizons@localhost:5432/horizons")
    return psycopg.connect(url, autocommit=True)


def q(sql: str, params: Sequence | None = None) -> list[tuple]:
    with db().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()
