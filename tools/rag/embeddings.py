"""Embedding helpers with deterministic local fallback."""

import hashlib
import math


def embed_text(text: str, *, dimensions: int = 64) -> list[float]:
    """Create a deterministic lightweight embedding for local tests."""
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [digest[index % len(digest)] / 255.0 for index in range(dimensions)]
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Return cosine similarity for two vectors."""
    if len(left) != len(right):
        raise ValueError("vectors must have equal length")
    return sum(a * b for a, b in zip(left, right, strict=True))
