"""Report quality evaluation stubs."""


def score_report(markdown: str) -> float:
    """Return a simple report quality score."""
    return 1.0 if "## Bibliography" in markdown else 0.5
