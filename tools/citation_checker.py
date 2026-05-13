"""Claim-to-source citation validation."""

from schemas.sources import Claim, VerificationStatus


def validate_claim_sources(claims: list[Claim]) -> tuple[list[str], list[str]]:
    """Return export blockers and warnings for claim verification states."""
    blockers: list[str] = []
    warnings: list[str] = []
    for claim in claims:
        if claim.verification_status in {
            VerificationStatus.UNSUPPORTED,
            VerificationStatus.CONTRADICTED,
        }:
            blockers.append(claim.id)
        elif claim.verification_status in {
            VerificationStatus.PARTIALLY_SUPPORTED,
            VerificationStatus.UNVERIFIED,
        }:
            warnings.append(claim.id)
        elif not claim.source_ids:
            blockers.append(claim.id)
    return blockers, warnings
