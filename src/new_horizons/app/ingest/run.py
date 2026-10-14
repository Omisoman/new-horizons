"""KB build — the Farm's generic corpus (+ overlays) -> bge-m3 -> Chroma.

Corpus: ingest/kb_synthetic/*.md, written for "the Farm" (no real farm named),
English with an Arabic mirror per clause. Profile values are templated at build
time (`{{currency}}`, `{{farm_en}}`, `{{farm_ar}}`), so the KB can never drift
from profile.yaml.

Overlays (local law, a buyer's specification) never enter the generic corpus:
they live in ingest/kb_market/<name>/ and are indexed only when profile.yaml
lists them under `market.kb_overlays` — see that folder's README. A document
whose front matter carries a `status:` line is a skeleton awaiting real text:
the build skips it, and skips its citation keys with it.

Outputs: data/kb/chroma/ (collection farm_kb), chunks.jsonl, stats.json.
Skips when the templated corpus is unchanged (content hash) unless --force.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from new_horizons.app.ingest.chunker import chunk_markdown, front_matter
from new_horizons.paths import APP, ROOT

load_dotenv(ROOT / ".env")

KB_DIR = ROOT / os.environ.get("KB_DIR", "data/kb")
CORPUS = Path(__file__).parent / "kb_synthetic"
OVERLAYS = Path(__file__).parent / "kb_market"
PROFILE = APP / "profile.yaml"
BATCH = 64

_PLACEHOLDER = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def profile_market() -> dict:
    return yaml.safe_load(PROFILE.read_text(encoding="utf-8"))["market"]


def template_values() -> dict:
    prof = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    return {"currency": prof["market"]["currency"],
            "farm_en": prof["farm"]["name_en"], "farm_ar": prof["farm"]["name_ar"]}


def enabled_overlays() -> list[str]:
    """Overlay directory names from profile.yaml `market.kb_overlays` (may be empty)."""
    return [str(m) for m in (profile_market().get("kb_overlays") or [])]


def is_skeleton(md: str) -> bool:
    """A `status:` front-matter line marks a document awaiting real text."""
    return "status" in front_matter(md)


def render(md: str, values: dict, name: str = "") -> str:
    """Substitute {{key}} / {{a.b.c}}; an unknown placeholder is a build error."""
    def sub(m: re.Match) -> str:
        cur = values
        for part in m.group(1).split("."):
            if not isinstance(cur, dict) or part not in cur:
                raise KeyError(f"{name}: unknown placeholder {{{{{m.group(1)}}}}}")
            cur = cur[part]
        if isinstance(cur, float) and cur.is_integer():
            cur = int(cur)
        return f"{cur:,}" if isinstance(cur, int) and cur >= 10_000 else str(cur)
    return _PLACEHOLDER.sub(sub, md)


def load_corpus() -> list[tuple[str, str, str]]:
    """[(source, rendered markdown, market)] — generic corpus first, then each
    enabled overlay in profile order. Skeletons (front matter `status:`) are
    left out; `skipped_docs()` reports them."""
    values = template_values()
    out = [(p.name, render(p.read_text(encoding="utf-8"), values, p.name), "")
           for p in sorted(CORPUS.glob("*.md"))]
    for market in enabled_overlays():
        for p in sorted((OVERLAYS / market).glob("*.md")):
            md = p.read_text(encoding="utf-8")
            if is_skeleton(md):
                continue
            out.append((p.name, render(md, values, p.name), market))
    return out


def skipped_docs() -> list[tuple[str, str]]:
    """[(source, market)] skeletons held back from the index."""
    return [(p.name, market) for market in enabled_overlays()
            for p in sorted((OVERLAYS / market).glob("*.md"))
            if is_skeleton(p.read_text(encoding="utf-8"))]


def load_registry() -> dict:
    """The citation registry the build stands behind: the generic registry plus
    the registries of enabled overlays, minus any key whose document was
    skipped as a skeleton. Placeholders are rendered like the corpus, so a term
    can be market-neutral (e.g. must_contain: ["{{currency}}"])."""
    values = template_values()
    reg = yaml.safe_load((CORPUS / "citations.yaml").read_text(encoding="utf-8")) or {}
    indexed = {source for source, _, _ in load_corpus()}
    for market in enabled_overlays():
        path = OVERLAYS / market / "citations.yaml"
        if path.exists():
            reg.update(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    live = {}
    for key, entry in reg.items():
        if entry["source"] not in indexed:
            continue                      # dormant: its document is not indexed
        live[key] = {**entry, "must_contain": [render(t, values, key)
                                               for t in entry.get("must_contain", [])]}
    return live


def build_chunks(corpus: list[tuple[str, str, str]]) -> list[dict]:
    chunks = []
    for source, md, market in corpus:
        chunks.extend(chunk_markdown(md, source, synthetic=True, market=market))
    return chunks


def corpus_hash(corpus: list[tuple[str, str, str]]) -> str:
    h = hashlib.sha256()
    for source, md, market in corpus:
        h.update(source.encode() + b"\0" + md.encode() + b"\0" + market.encode() + b"\0")
    h.update((Path(__file__).parent / "chunker.py").read_bytes())
    return h.hexdigest()[:16]


def build(force: bool = False) -> dict:
    from new_horizons.shared.kb.store import COLLECTION, KB
    t0 = time.time()
    KB_DIR.mkdir(parents=True, exist_ok=True)
    corpus = load_corpus()
    digest = corpus_hash(corpus)
    stats_path, chunks_path = KB_DIR / "stats.json", KB_DIR / "chunks.jsonl"

    if not force and stats_path.exists() and chunks_path.exists():
        old = json.loads(stats_path.read_text())
        if old.get("corpus_hash") == digest and KB(str(KB_DIR)).count() == old.get("chunks"):
            print(f"kb: unchanged ({old['chunks']} chunks, hash {digest}) — skip; --force to rebuild")
            return old

    chunks = build_chunks(corpus)
    kb = KB(str(KB_DIR))
    kb.reset()
    for col in kb.client.list_collections():     # dir is dedicated to farm_kb:
        if col.name != COLLECTION:               # drop strays (e.g. a collection
            kb.client.delete_collection(col.name)  # auto-created by a query)
    for i in range(0, len(chunks), BATCH):
        part = chunks[i:i + BATCH]
        kb.add(ids=[c["id"] for c in part], texts=[c["text"] for c in part],
               index_texts=[c["index_text"] for c in part],
               metadatas=[c["meta"] for c in part])
        print(f"  indexed {min(i + BATCH, len(chunks))}/{len(chunks)}", end="\r")
    print()
    chunks_path.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks))

    documents = []
    for source, _, market in corpus:
        mine = [c for c in chunks if c["meta"]["source"] == source]
        documents.append({
            "source": source,
            "title": mine[0]["meta"]["title"] if mine else source,
            "market": market,
            "chunks": len(mine),
            "sections": sorted({c["meta"]["section"] for c in mine if c["meta"]["section"]},
                               key=lambda s: [int(x) for x in s.split(".")]),
        })
    skipped = skipped_docs()
    stats = {
        "docs": len(corpus),
        "chunks": len(chunks),
        "sections": sum(len(d["sections"]) for d in documents),
        "overlays": enabled_overlays(),
        "skipped": [{"source": s, "market": m, "reason": "skeleton"} for s, m in skipped],
        "citation_keys": len(load_registry()),
        "elapsed_s": round(time.time() - t0, 1),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus_hash": digest,
        "collection": COLLECTION,
        "embed_model": os.environ.get("EMBED_MODEL", "bge-m3"),
        "documents": documents,
    }
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--force", action="store_true", help="rebuild even if unchanged")
    args = ap.parse_args()
    s = build(force=args.force)
    print(f"kb: {s['docs']} docs, {s['chunks']} chunks, {s['sections']} sections, "
          f"{s.get('citation_keys', 0)} citation keys in {s['elapsed_s']}s -> {KB_DIR}")
    if s.get("overlays"):
        print(f"  overlays: {', '.join(s['overlays'])}")
    for sk in s.get("skipped", []):
        print(f"  skipped (skeleton): {sk['market']}/{sk['source']} — its citation keys stay dormant")


if __name__ == "__main__":
    main()
