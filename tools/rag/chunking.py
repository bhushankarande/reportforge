"""Text chunking strategies for retrieval."""


def fixed_overlap_chunks(text: str, *, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    """Split text into fixed-size overlapping chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be between 0 and chunk_size - 1")
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunk = text[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def semantic_chunks(text: str, *, max_chars: int = 1200) -> list[str]:
    """Split text on paragraph boundaries with a maximum character target."""
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        current = paragraph
    if current:
        chunks.append(current)
    return chunks or fixed_overlap_chunks(text, chunk_size=max_chars, overlap=0)
