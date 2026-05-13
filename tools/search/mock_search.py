"""Deterministic mock search for zero-cost MVP testing."""


def mock_search(query: str, *, limit: int = 5) -> list[dict[str, object]]:
    """Return deterministic mock search results."""
    return [
        {
            "title": f"Mock source {index + 1} for {query}",
            "url": None,
            "summary": f"Mock summary for {query}",
            "relevance_score": max(0.1, 0.9 - index * 0.1),
        }
        for index in range(limit)
    ]
