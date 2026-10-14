"""Heading-aware chunking, ~600 tokens per chunk.

Markdown docs split on headings, then pack lines. Every chunk opens with a
context line — `<doc title> › <section heading>` — so the embedding sees what
the chunk is about even when a long section is split. Section numbers come
from the headings (`## 4. Invoicing` → "4", `### 3.1 Overpayment` → "3.1");
citations are (source, section). Token count approximated at 0.75
words/token for Arabic-heavy text (word_count / 0.75 ≈ tokens).

Metadata: {source, section, page, title, heading, market, lang, synthetic} —
`page` is the section ordinal, kept for back-compat with page-cited consumers;
`market` is "" for the generic corpus and the overlay name for jurisdiction
documents (kb_market/<market>/).
"""

from __future__ import annotations

import re

from new_horizons.shared.text.arabic import detect_lang, index_normalize

TARGET_TOKENS = 600
_HEADING = re.compile(r"^(#{1,4}\s+.+|.{0,80}(بيان|قائمة|إيضاح)\s.*)$", re.M)
_MD_HEADING = re.compile(r"^#{1,4}\s+(.+?)\s*$")
_SECTION_NO = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)[.)]?\s+\S")   # not years
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def _tokens(text: str) -> int:
    return int(len(text.split()) / 0.75) + 1


def _pack(units: list[str], header: str = "") -> list[str]:
    chunks, cur, cur_tok = [], [], 0
    for u in units:
        t = _tokens(u)
        if cur and cur_tok + t > TARGET_TOKENS:
            chunks.append("\n".join(cur))
            cur, cur_tok = [], 0
        cur.append(u)
        cur_tok += t
    if cur:
        chunks.append("\n".join(cur))
    if header:
        chunks = [f"{header}\n{c}" if header not in c else c for c in chunks]
    return chunks


def section_number(heading: str) -> str:
    """'## 4. Invoicing' → '4'; '### 3.1 Overpayment' → '3.1'; else ''."""
    m = _MD_HEADING.match(heading.strip())
    text = m.group(1) if m else heading.strip()
    s = _SECTION_NO.match(text)
    return s.group(1) if s else ""


def front_matter(md: str) -> dict[str, str]:
    """Flat `key: value` front matter (quotes stripped); {} when absent."""
    m = _FRONT_MATTER.match(md)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def chunk_page(text: str, source: str, page: int, synthetic: bool = False) -> list[dict]:
    """One PDF page → chunks with heading context carried into each chunk."""
    lines = [l for l in (ln.rstrip() for ln in text.split("\n")) if l.strip()]
    if not lines:
        return []
    header = next((l.strip() for l in lines[:6] if _HEADING.match(l.strip())), "")
    out = []
    for i, c in enumerate(_pack(lines, header)):
        out.append({
            "id": f"{source}#p{page}#c{i}",
            "text": c,
            "index_text": index_normalize(c),
            "meta": {"source": source, "page": page, "section": "",
                     "lang": detect_lang(c), "synthetic": synthetic},
        })
    return out


def chunk_markdown(md: str, source: str, synthetic: bool = True,
                   market: str = "") -> list[dict]:
    """Front-mattered markdown doc → one or more chunks per heading section.

    `market` names the overlay a document came from (kb_market/<market>/);
    "" is the generic corpus, so retrieval can tell law from house procedure."""
    title = front_matter(md).get("title", source)
    body = _FRONT_MATTER.sub("", md)
    sections = re.split(r"(?=^#{1,4}\s)", body, flags=re.M)
    out, ordinal = [], 0
    for sec in sections:
        if not sec.strip():
            continue
        first, _, rest = sec.partition("\n")
        is_heading = bool(_MD_HEADING.match(first.strip()))
        heading = _MD_HEADING.match(first.strip()).group(1) if is_heading else ""
        units = [l.rstrip() for l in (rest if is_heading else sec).split("\n") if l.strip()]
        if not units:                       # heading with no body of its own
            continue
        ordinal += 1
        section = section_number(first) if is_heading else ""
        context = f"{title} › {heading}" if heading and heading != title else title
        for i, c in enumerate(_pack(units)):
            text = f"{context}\n{c}"
            out.append({
                "id": f"{source}#s{ordinal}#c{i}",
                "text": text,
                "index_text": index_normalize(text),
                "meta": {"source": source, "section": section, "page": ordinal,
                         "title": title, "heading": heading, "market": market,
                         "lang": detect_lang(text), "synthetic": synthetic},
            })
    return out
