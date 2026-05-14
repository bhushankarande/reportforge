"""PDF export helper."""

from pathlib import Path


def write_pdf(markdown: str, path: str | Path) -> Path:
    """Write a minimal valid PDF containing the report text.

    The production path can swap this for WeasyPrint/Jinja2 rendering without
    changing callers. This MVP writer intentionally avoids native dependencies
    while still producing a PDF file that readers can open.
    """
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    text_lines = _escape_pdf_text(markdown).splitlines() or ["ReportForge report"]
    pages = _chunk_lines(text_lines, lines_per_page=48)
    font_object_number = 3 + (2 * len(pages))
    page_refs = " ".join(f"{3 + (index * 2)} 0 R" for index in range(len(pages)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{page_refs}] /Count {len(pages)} >>".encode("ascii"),
    ]
    for index, page_lines in enumerate(pages):
        page_object_number = 3 + (index * 2)
        content_object_number = page_object_number + 1
        stream = _page_stream(page_lines)
        objects.extend(
            [
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 {font_object_number} 0 R >> >> "
                    f"/Contents {content_object_number} 0 R >>"
                ).encode("ascii"),
                b"<< /Length "
                + str(len(stream)).encode("ascii")
                + b" >>\nstream\n"
                + stream
                + b"\nendstream",
            ]
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pdf = _assemble_pdf(objects)
    output.write_bytes(pdf)
    return output


def _escape_pdf_text(text: str) -> str:
    """Escape text for a PDF literal string."""
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _chunk_lines(lines: list[str], *, lines_per_page: int) -> list[list[str]]:
    """Split report lines into PDF pages."""
    return [lines[index : index + lines_per_page] for index in range(0, len(lines), lines_per_page)]


def _page_stream(lines: list[str]) -> bytes:
    """Build a PDF text stream for one page."""
    content_lines = ["BT", "/F1 11 Tf", "50 780 Td", "14 TL"]
    for line in lines:
        content_lines.append(f"({line[:96]}) Tj")
        content_lines.append("T*")
    content_lines.append("ET")
    return "\n".join(content_lines).encode("latin-1", errors="replace")


def _assemble_pdf(objects: list[bytes]) -> bytes:
    """Assemble PDF objects into a single-file PDF document."""
    chunks = [b"%PDF-1.4\n"]
    offsets: list[int] = []
    for index, payload in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{index} 0 obj\n".encode("ascii") + payload + b"\nendobj\n")
    xref_offset = sum(len(chunk) for chunk in chunks)
    chunks.append(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    chunks.append(b"0000000000 65535 f \n")
    for offset in offsets:
        chunks.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    chunks.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return b"".join(chunks)
