"""Chunking + full-text (BM25) index for Mobile_Provider_Billing_Guide.md.

Indexing approach
-----------------
1. Chunking: the Markdown is split by headings. Every `### x.y` subsection becomes one chunk;
   a `## x` section without subsections (e.g. "1. Scope and terminology") is one chunk; the text
   before the first `##` heading is the "0 / Document overview" chunk. Headings inside fenced
   code blocks are ignored. Each chunk keeps: section id, heading, parent heading, text.
2. Tokenizing: lowercase, alphanumeric tokens, English stop words removed, light plural
   stemming ("blocks" -> "block"). Heading tokens are counted twice (headings are strong signals).
3. Index: an in-memory inverted index with BM25 scoring (k1=1.5, b=0.75). It is built ONCE when
   the MCP server starts and reused for every query (never re-indexed per question).
4. Query expansion: a small domain synonym table maps user words to document words
   (e.g. "data" -> "internet", "extra" -> "additional", "calls" -> "phone").
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DOC_PATH = Path(__file__).parent / "data" / "Mobile_Provider_Billing_Guide.md"

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how",
    "i", "if", "in", "is", "it", "its", "me", "my", "of", "on", "or", "the", "this", "that", "to",
    "what", "when", "which", "why", "will", "with", "you", "your", "should", "not", "it", "has",
    "have", "was", "were", "there", "their", "they", "any", "all", "per", "than", "then", "so",
}

SYNONYMS: dict[str, list[str]] = {
    "data": ["internet"],
    "mobile": ["internet"],
    "gigabyte": ["gb"],
    "megabyte": ["mb"],
    "extra": ["additional"],
    "overage": ["additional"],
    "exceed": ["additional"],
    "call": ["phone", "minute"],
    "calling": ["phone", "minute"],
    "talk": ["phone", "minute"],
    "price": ["pricing", "cost"],
    "fee": ["cost"],
    "expensive": ["cost", "charge"],
    "higher": ["charge", "usage"],
    "pay": ["payment"],
    "paid": ["payment"],
    "part": ["partial"],
    "partially": ["partial"],
    "installment": ["partial", "payment"],
    "deadline": ["due"],
    "overdue": ["late", "due"],
    "suspend": ["restriction", "restricted"],
    "suspension": ["restriction", "restricted"],
    "cut": ["restriction", "restricted"],
    "complaint": ["dispute"],
    "refund": ["dispute", "adjustment"],
    "wrong": ["dispute"],
    "free": ["included"],
    "allowance": ["included"],
}

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss") and not token[-2].isdigit():
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    tokens = []
    for raw in _TOKEN_RE.findall(text.lower().replace(",", "")):
        if raw in STOP_WORDS:
            continue
        tokens.append(_stem(raw))
    return tokens


def expand_query(tokens: list[str]) -> list[str]:
    expanded = list(tokens)
    for tok in tokens:
        expanded.extend(_stem(s) for s in SYNONYMS.get(tok, []))
    return expanded


@dataclass
class Chunk:
    section: str
    heading: str
    parent_heading: str | None
    text: str
    tokens: list[str] = field(default_factory=list, repr=False)

    def to_match(self, score: float) -> dict:
        return {
            "section": self.section,
            "heading": self.heading,
            "parentHeading": self.parent_heading,
            "text": self.text,
            "score": round(score, 3),
        }


_H2 = re.compile(r"^##\s+(\d+)\.\s+(.*)$")
_H3 = re.compile(r"^###\s+(\d+\.\d+)\s+(.*)$")
_DOC_ID = re.compile(r"\*\*Document ID:\*\*\s*([A-Z0-9-]+)")


def chunk_markdown(markdown: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    section, heading, parent = "0", "Document overview", None
    h2_label: str | None = None
    buffer: list[str] = []
    in_code = False

    def flush():
        text = "\n".join(buffer).strip()
        if text:
            chunks.append(Chunk(section=section, heading=heading, parent_heading=parent, text=text))
        buffer.clear()

    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            buffer.append(line)
            continue
        if not in_code:
            if line.startswith("# "):  # document title
                continue
            m2, m3 = _H2.match(line), _H3.match(line)
            if m2:
                flush()
                h2_label = f"{m2.group(1)}. {m2.group(2).strip()}"
                section, heading, parent = m2.group(1), m2.group(2).strip(), None
                continue
            if m3:
                flush()
                section, heading, parent = m3.group(1), m3.group(2).strip(), h2_label
                continue
        buffer.append(line)
    flush()
    return chunks


class BillingDocsIndex:
    def __init__(self, chunks: list[Chunk], document: str, document_id: str, k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.document = document
        self.document_id = document_id
        self.k1, self.b = k1, b
        for c in chunks:
            heading_tokens = tokenize(c.heading)
            parent_tokens = tokenize(c.parent_heading or "")
            c.tokens = heading_tokens * 2 + parent_tokens + tokenize(c.text)
        self.doc_len = [len(c.tokens) for c in chunks]
        self.avg_len = sum(self.doc_len) / len(chunks)
        self.term_freqs = [Counter(c.tokens) for c in chunks]
        df: Counter[str] = Counter()
        for tf in self.term_freqs:
            df.update(tf.keys())
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    @classmethod
    def from_file(cls, path: Path = DEFAULT_DOC_PATH) -> "BillingDocsIndex":
        markdown = path.read_text(encoding="utf-8")
        m = _DOC_ID.search(markdown)
        return cls(chunk_markdown(markdown), document=path.name, document_id=m.group(1) if m else path.stem)

    def _score(self, query_tokens: list[str], i: int) -> float:
        tf, dl = self.term_freqs[i], self.doc_len[i]
        score = 0.0
        for t in query_tokens:
            f = tf.get(t, 0)
            if f:
                score += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg_len))
        return score

    def search(self, query: str, top_k: int = 3) -> dict:
        query_tokens = expand_query(tokenize(query))
        scored = [(self._score(query_tokens, i), i) for i in range(len(self.chunks))]
        scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda s: (-s[0], s[1]))
        return {
            "document": self.document,
            "documentId": self.document_id,
            "query": query,
            "matches": [self.chunks[i].to_match(score) for score, i in scored[:top_k]],
        }
