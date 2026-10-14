"""Vector store: bge-m3 embeddings (via Ollama) + Chroma persistent collection.

Written by the KB build (`make kb`), read by the kb_search tool. Chunk
metadata: {source, section, page, title, heading, lang, synthetic}; cite as
(source, section). Optional CPU reranker (bge-reranker-v2-m3) behind
RERANKER_ENABLED=true.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from new_horizons.paths import data_path


def _ollama_host() -> str:
    # bge-m3 is a local model: it stays on the Ollama host even when chat runs
    # on a rented GPU or Claude (shared/llm/provider.py).
    from new_horizons.shared.llm.provider import ollama_host
    return ollama_host()


def embed_texts(texts: list[str], batch: int = 32) -> list[list[float]]:
    model = os.environ.get("EMBED_MODEL", "bge-m3")
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        r = httpx.post(f"{_ollama_host()}/api/embed",
                       json={"model": model, "input": texts[i:i + batch]},
                       timeout=300)
        r.raise_for_status()
        out.extend(r.json()["embeddings"])
    return out


COLLECTION = "farm_kb"


class KB:
    def __init__(self, path: str | None = None):
        import chromadb
        root = Path(path or data_path(os.environ.get("KB_DIR"), "kb")) / "chroma"
        self.client = chromadb.PersistentClient(path=str(root))
        self.col = self.client.get_or_create_collection(
            COLLECTION, metadata={"hnsw:space": "cosine"})

    def reset(self) -> None:
        """Drop and recreate the collection (full rebuild)."""
        self.client.delete_collection(COLLECTION)
        self.col = self.client.get_or_create_collection(
            COLLECTION, metadata={"hnsw:space": "cosine"})

    def add(self, ids: list[str], texts: list[str], index_texts: list[str],
            metadatas: list[dict]) -> None:
        """`texts` = display chunks (stored); `index_texts` = normalized form
        (embedded). Display keeps originals; the index gets the aggressive
        normalization."""
        embs = embed_texts(index_texts)
        self.col.upsert(ids=ids, documents=texts, embeddings=embs,
                        metadatas=metadatas)

    def count(self) -> int:
        return self.col.count()

    def search(self, query: str, k: int = 6, where: dict | None = None) -> list[dict]:
        from new_horizons.shared.text.arabic import index_normalize
        norm_query = index_normalize(query)
        emb = embed_texts([norm_query])[0]
        res = self.col.query(query_embeddings=[emb], n_results=k, where=where)
        hits = []
        for i in range(len(res["ids"][0])):
            hits.append({
                "id": res["ids"][0][i],
                "text": res["documents"][0][i],
                "meta": res["metadatas"][0][i],
                "distance": res["distances"][0][i],
            })
        if os.environ.get("RERANKER_ENABLED", "false").lower() == "true":
            hits = _rerank(norm_query, hits, k)
        return hits


def _rerank(query: str, hits: list[dict], k: int) -> list[dict]:
    from sentence_transformers import CrossEncoder  # CPU, optional extra
    ce = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cpu")
    scores = ce.predict([(query, h["text"]) for h in hits])
    for h, s in zip(hits, scores):
        h["rerank_score"] = float(s)
    return sorted(hits, key=lambda h: -h["rerank_score"])[:k]
