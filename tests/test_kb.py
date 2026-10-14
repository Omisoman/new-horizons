"""KB contract: generic corpus, overlays, citation registry, chunking, retrieval.

The corpus is chunked in-process (no Ollama) for the registry and content
checks; the built index (data/kb) is checked for freshness and, when Ollama
answers, for retrieval of the terms the analytics and the intake alert cite.

Two rules this file exists to hold:
  * kb_synthetic/ stays GENERIC — "the Farm", no real farm, company or person,
    no currency name in prose ({{currency}} renders it from profile.yaml).
  * local documents live in kb_market/<name>/ and are indexed only when
    profile.yaml enables the overlay; a skeleton (front-matter `status:`) is
    skipped along with its citation keys.
"""

import json
import re

import httpx
import pytest
import yaml

from new_horizons.app.ingest import run as kb_build
from new_horizons.app.ingest.chunker import chunk_markdown, section_number
from new_horizons.paths import APP, ROOT

pytestmark = pytest.mark.domain

INGEST = APP / "ingest"
CORPUS = INGEST / "kb_synthetic"
OVERLAYS = INGEST / "kb_market"
KB_DIR = ROOT / "data" / "kb"
PROFILE = yaml.safe_load((APP / "profile.yaml").read_text(encoding="utf-8"))
CURRENCY = re.compile(r"\bEUR\b|\beuros?\b|يورو|€|\$|\bdollars?\b", re.I)

CORPUS_RENDERED = kb_build.load_corpus()
CHUNKS = kb_build.build_chunks(CORPUS_RENDERED)
REGISTRY = kb_build.load_registry()


def _section_text(chunks, source, section):
    return "\n".join(c["text"] for c in chunks
                     if c["meta"]["source"] == source and c["meta"]["section"] == section)


# ---- citation registry -------------------------------------------------------

@pytest.mark.parametrize("key", sorted(REGISTRY))
def test_citation_resolves_with_terms(key):
    entry = REGISTRY[key]
    text = _section_text(CHUNKS, entry["source"], entry["section"])
    assert text, f"{key}: no chunk for {entry['source']} §{entry['section']}"
    low = text.lower()
    missing = [t for t in entry["must_contain"] if t.lower() not in low]
    assert not missing, f"{key}: §{entry['section']} lacks {missing}"


def test_registry_is_the_contract_the_app_cites():
    """Every key the analytics, the metrics layer and the intake cite is live."""
    used = set()
    for path in (APP / "analytics").glob("*.py"):
        used |= set(re.findall(r"""cite\(["']([a-z_]+)["']\)""", path.read_text()))
    intents = yaml.safe_load((APP / "agents" / "analytics" / "intents.yaml").read_text(encoding="utf-8"))
    used |= {i["cite"] for i in intents["intents"]}
    assert used and used <= set(REGISTRY), sorted(used - set(REGISTRY))
    assert len(REGISTRY) >= 26


def test_built_index_is_fresh_and_resolves_registry():
    stats_path, chunks_path = KB_DIR / "stats.json", KB_DIR / "chunks.jsonl"
    if not (stats_path.exists() and chunks_path.exists()):
        pytest.skip("KB not built (run `make kb`)")
    stats = json.loads(stats_path.read_text())
    assert stats["corpus_hash"] == kb_build.corpus_hash(CORPUS_RENDERED), \
        "data/kb is stale — rebuild with `make kb`"
    built = [json.loads(line) for line in chunks_path.read_text().splitlines() if line.strip()]
    assert len(built) == stats["chunks"] == len(CHUNKS)
    for key, e in REGISTRY.items():
        assert _section_text(built, e["source"], e["section"]), key


# ---- chunker -----------------------------------------------------------------

@pytest.mark.parametrize("heading,expected", [
    ("## 4. Commanded vs observed", "4"),
    ("### 3.1 Readings — القراءات", "3.1"),
    ("## 12) Twelve", "12"),
    ("#### 2.3.1 Deep", "2.3.1"),
    ("# Pump Maintenance SOP — إجراءات", ""),
    ("## Annex A", ""),
    ("## 2026 figures", ""),          # a year is not a section number
])
def test_section_number(heading, expected):
    assert section_number(heading) == expected


def test_chunk_markdown_sections_and_context():
    md = ("---\ntitle: \"Demo Doc — وثيقة\"\n---\n\n# Demo Doc — وثيقة\n\nIntro line.\n\n"
          "## 1. First — الأول\n\nAlpha text.\n\n## 2. Empty parent\n\n"
          "### 2.1 Child\n\nBeta text.\n")
    chunks = chunk_markdown(md, "demo.md")
    meta = [(c["meta"]["section"], c["meta"]["heading"]) for c in chunks]
    assert meta == [("", "Demo Doc — وثيقة"), ("1", "1. First — الأول"), ("2.1", "2.1 Child")]
    first = chunks[1]
    assert first["text"].startswith("Demo Doc — وثيقة › 1. First — الأول\n")
    assert set(first["meta"]) == {"source", "section", "page", "title", "heading",
                                  "market", "lang", "synthetic"}
    assert len({c["id"] for c in chunks}) == len(chunks)


def test_chunks_fit_the_context_budget():
    assert max(len(c["text"].split()) for c in CHUNKS) <= 450  # ~600 tokens


# ---- overlays ------------------------------------------------------------------

def test_no_overlay_is_enabled_and_the_template_is_dormant():
    assert kb_build.enabled_overlays() == []
    assert (OVERLAYS / "_template" / "citations.yaml").exists()
    assert all(c["meta"]["market"] == "" for c in CHUNKS)
    assert kb_build.skipped_docs() == []


def test_an_enabled_skeleton_overlay_is_skipped_with_its_keys(tmp_path, monkeypatch):
    overlay = tmp_path / "demo"
    overlay.mkdir()
    (overlay / "local-rule.md").write_text("---\nsynthetic: false\nstatus: skeleton\ntitle: \"Local\"\n---\n"
                                           "# Local\n\n## 1. Rule\n\nText.\n", encoding="utf-8")
    (overlay / "citations.yaml").write_text("local_rule: {source: local-rule.md, section: '1', "
                                            "must_contain: [Text]}\n", encoding="utf-8")
    monkeypatch.setattr(kb_build, "OVERLAYS", tmp_path)
    monkeypatch.setattr(kb_build, "enabled_overlays", lambda: ["demo"])
    assert kb_build.skipped_docs() == [("local-rule.md", "demo")]
    assert "local_rule" not in kb_build.load_registry()


# ---- generic, reusable content -------------------------------------------------

def test_corpus_is_generic_and_says_the_farm():
    for p in CORPUS.glob("*.md"):
        raw = p.read_text(encoding="utf-8")
        assert "the Farm" in raw or "{{farm_en}}" in raw, p.name
        found = CURRENCY.findall(re.sub(r"`[^`]*`", " ", raw))     # `eur` is a column name
        assert not found, f"{p.name} names a currency {found} — write {{{{currency}}}}"


def test_every_doc_is_marked_synthetic():
    docs = sorted(CORPUS.glob("*.md"))
    assert len(docs) == 10
    for p in docs:
        raw = p.read_text(encoding="utf-8")
        assert raw.startswith("---\nsynthetic: true\n"), p.name
        assert "SYNTHETIC demo document" in raw, p.name
        assert re.search(r"^title: ", raw, re.M), p.name


def test_templates_fully_rendered():
    for source, md, _market in CORPUS_RENDERED:
        assert "{{" not in md and "}}" not in md, source


def test_price_list_quotes_the_profile():
    """The KB's price list and the generator's are one list: profile.yaml."""
    text = _section_text(CHUNKS, "harvest-shipping-procedure.md", "5")
    for plant, price in PROFILE["prices"].items():
        assert re.search(rf"{plant}.*{float(price):.2f}", text, re.I | re.S), plant


def test_kb_states_the_thresholds_the_code_enforces():
    from new_horizons.app.analytics import drift, recon
    assert f"{recon.RISE_CM:g} cm" in _section_text(CHUNKS, "pump-maintenance-sop.md", "4")
    assert f"{drift.DUTY_LIMIT:.0%}" in _section_text(CHUNKS, "pump-maintenance-sop.md", "5")
    assert f"{recon.PRICE_TOLERANCE:.0%}" in _section_text(CHUNKS, "supplier-invoice-controls.md", "2")
    assert "6.6" in _section_text(CHUNKS, "water-quality-sop.md", "2")


# ---- retrieval (needs Ollama + the built index) --------------------------------

def _ollama_up() -> bool:
    try:
        return httpx.get("http://localhost:11434/api/version", timeout=2).status_code == 200
    except Exception:
        return False


retrieval = pytest.mark.skipif(not _ollama_up() or not (KB_DIR / "chroma").exists(),
                               reason="needs Ollama (bge-m3) and a built KB")


@pytest.fixture(scope="module")
def kb():
    from new_horizons.shared.kb.store import KB
    return KB(str(KB_DIR))


def _top(kb, query, k):
    return [(h["meta"]["source"], h["meta"]["section"]) for h in kb.search(query, k=k)]


@retrieval
@pytest.mark.parametrize("query,expected,k", [
    ("how fast must a water pump failure be answered", {("pump-maintenance-sop.md", "3")}, 3),
    ("a pump run that does not raise the water level", {("pump-maintenance-sop.md", "4")}, 3),
    ("invoice price above the purchase order", {("supplier-invoice-controls.md", "2")}, 3),
    ("feed consumed with no purchase behind it", {("supplier-invoice-controls.md", "4")}, 3),
    ("is the pH probe wrong or did the water change", {("sensor-calibration.md", "3")}, 3),
    ("مضخة الهواء تعمل أكثر من نصف اليوم", {("pump-maintenance-sop.md", "5")}, 5),
    ("which business keys join the five systems", {("data-dictionary.md", "1")}, 3),
])
def test_retrieval_finds_governing_terms(kb, query, expected, k):
    top = _top(kb, query, k)
    assert expected & set(top), f"{query!r} -> {top}"
