"""Cross-encoder reranking abstraction with deterministic fallback."""


def rerank(query: str, documents: list[str], *, limit: int = 5) -> list[tuple[str, float]]:
    """Rerank documents by simple term overlap for local tests."""
    query_terms = set(query.lower().split())
    scored: list[tuple[str, float]] = []
    for document in documents:
        terms = set(document.lower().split())
        score = len(query_terms & terms) / max(len(query_terms), 1)
        scored.append((document, score))
    return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]
