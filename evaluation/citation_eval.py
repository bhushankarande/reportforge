"""Citation evaluation stubs."""


def citation_coverage(total_claims: int, sourced_claims: int) -> float:
    """Return sourced-claim coverage."""
    if total_claims == 0:
        return 1.0
    return sourced_claims / total_claims
