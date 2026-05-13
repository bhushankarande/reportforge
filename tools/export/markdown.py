"""Markdown export helper."""


def render_markdown(title: str, sections: list[str], bibliography: list[str]) -> str:
    """Render a Markdown report with bibliography."""
    body = "\n\n".join(sections)
    refs = "\n".join(f"- {item}" for item in bibliography)
    return f"# {title}\n\n{body}\n\n## Bibliography\n\n{refs}\n"
