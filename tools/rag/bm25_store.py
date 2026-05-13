"""BM25-like keyword retrieval with optional rank-bm25 fallback."""

import math
import re
from collections import Counter
from dataclasses import dataclass


def tokenize(text: str) -> list[str]:
    """Tokenize text for keyword scoring."""
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class BM25Record:
    """Stored keyword record."""

    id: str
    text: str
    source_id: str
    terms: Counter[str]


class BM25Store:
    """Small BM25-style store for local retrieval tests."""

    def __init__(self) -> None:
        """Initialize empty store."""
        self.records: list[BM25Record] = []

    def add_text(self, record_id: str, text: str, source_id: str) -> None:
        """Index text for keyword scoring."""
        self.records.append(BM25Record(record_id, text, source_id, Counter(tokenize(text))))

    def search(self, query: str, *, limit: int = 5) -> list[tuple[BM25Record, float]]:
        """Return keyword-ranked records."""
        query_terms = tokenize(query)
        if not query_terms:
            return []
        scored: list[tuple[BM25Record, float]] = []
        total_docs = max(len(self.records), 1)
        for record in self.records:
            score = 0.0
            for term in query_terms:
                docs_with_term = sum(1 for candidate in self.records if term in candidate.terms) or 1
                idf = math.log((total_docs + 1) / docs_with_term)
                score += record.terms.get(term, 0) * idf
            scored.append((record, score))
        return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]
