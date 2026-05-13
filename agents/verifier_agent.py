"""Verifier agent for claim coverage."""

from schemas.agent_outputs import VerifierOutput
from schemas.sources import Claim, VerificationStatus
from orchestration.cost_tracking import CostTrackingModel
from tools.citation_checker import validate_claim_sources
from tools.llm.model_router import ModelRouter


class VerifierAgent:
    """Audit claims and produce export blockers or warnings."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize verifier with model router."""
        self.router = router or ModelRouter()

    def verify(self, claims: list[Claim]) -> VerifierOutput:
        """Verify claim source status."""
        tracked_model = CostTrackingModel(self.router.get_model("gemini"))
        tracked_model(f"Verify {len(claims)} claims")
        normalized: list[Claim] = []
        for claim in claims:
            if not claim.source_ids and claim.verification_status == VerificationStatus.SUPPORTED:
                normalized.append(claim.model_copy(update={"verification_status": VerificationStatus.UNVERIFIED}))
            else:
                normalized.append(claim)
        blockers, warnings = validate_claim_sources(normalized)
        return VerifierOutput(claims=normalized, blockers=blockers, warnings=warnings)
