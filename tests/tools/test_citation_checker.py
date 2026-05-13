from schemas.sources import Claim, VerificationStatus
from tools.citation_checker import validate_claim_sources


def test_citation_checker_accepts_supported_claim_with_source():
    claim = Claim(
        id="claim-1",
        section_id="section-1",
        text="Revenue increased.",
        source_ids=["source-1"],
        verification_status=VerificationStatus.SUPPORTED,
        confidence=0.9,
    )

    blockers, warnings = validate_claim_sources([claim])

    assert blockers == []
    assert warnings == []


def test_citation_checker_blocks_missing_source():
    claim = Claim(
        id="claim-1",
        section_id="section-1",
        text="Revenue increased.",
        source_ids=[],
        verification_status=VerificationStatus.SUPPORTED,
        confidence=0.9,
    )

    blockers, warnings = validate_claim_sources([claim])

    assert blockers == ["claim-1"]
    assert warnings == []
