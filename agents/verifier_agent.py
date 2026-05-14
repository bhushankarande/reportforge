"""Verifier agent for claim coverage."""

import re
from difflib import SequenceMatcher

from app.logging_config import get_logger
from schemas.agent_outputs import VerifierOutput
from schemas.reports import ReportSection
from schemas.sources import Source
from schemas.sources import Claim, VerificationStatus
from orchestration.cost_tracking import CostTrackingModel
from tools.citation_checker import validate_claim_sources
from tools.llm.model_router import ModelRouter

logger = get_logger(__name__)
CITATION_KEY_PATTERN = re.compile(r"^\[[A-Za-z0-9_-]+\]$")


class VerifierAgent:
    """Audit claims and produce export blockers or warnings."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize verifier with model router."""
        self.router = router or ModelRouter()
        self.sys_prompt = (
            "You are ReportForge VerifierAgent. Check every claim against available sources. "
            "Assign verification_status as SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED, or "
            "CONTRADICTED. Confidence must be 0.0-1.0. Any UNSUPPORTED or CONTRADICTED "
            "claim blocks export."
        )
        self.model = CostTrackingModel(self.router.get_model())

    def verify(self, claims: list[Claim]) -> VerifierOutput:
        """Backward-compatible claim-only verification."""
        self.model(f"{self.sys_prompt}\nVerify {len(claims)} claims with existing source ids.")
        normalized = [
            claim.model_copy(
                update={
                    "verification_status": (
                        VerificationStatus.UNVERIFIED
                        if not claim.source_ids and claim.verification_status == VerificationStatus.SUPPORTED
                        else claim.verification_status
                    )
                }
            )
            for claim in claims
        ]
        blockers, warnings = validate_claim_sources(normalized)
        return VerifierOutput(claims=normalized, blockers=blockers, warnings=warnings)

    def run(self, section: ReportSection, sources: list[Source]) -> VerifierOutput:
        """Verify claim source status."""
        logger.info(
            "verifier_started",
            job_id=section.job_id,
            section_id=section.id,
            claims=len(section.claims),
            sources=len(sources),
        )
        self.model(f"{self.sys_prompt}\nSection: {section.title}\nClaims: {len(section.claims)}")
        source_by_id = {source.id: source for source in sources}
        source_by_key = {source.citation_key.strip("[]"): source for source in sources}
        normalized: list[Claim] = []
        for claim in section.claims:
            status, confidence, source_ids = self._verify_claim(claim, source_by_id, source_by_key)
            normalized.append(
                claim.model_copy(
                    update={
                        "source_ids": source_ids,
                        "verification_status": status,
                        "confidence": confidence,
                    }
                )
            )
        blockers, warnings = validate_claim_sources(normalized)
        logger.info(
            "verifier_completed",
            job_id=section.job_id,
            section_id=section.id,
            blockers=len(blockers),
            warnings=len(warnings),
        )
        return VerifierOutput(claims=normalized, blockers=blockers, warnings=warnings)

    @staticmethod
    def _verify_claim(
        claim: Claim,
        source_by_id: dict[str, Source],
        source_by_key: dict[str, Source],
    ) -> tuple[VerificationStatus, float, list[str]]:
        """Verify one claim using source IDs, citation keys, and fuzzy matching."""
        candidate_sources = VerifierAgent._candidate_sources(claim, source_by_id, source_by_key)
        if not candidate_sources:
            return VerificationStatus.UNSUPPORTED, 0.0, []
        best_score = max(
            VerifierAgent._support_score(claim.text, f"{source.title} {source.summary} {source.raw_text}")
            for source in candidate_sources
        )
        source_ids = [source.id for source in candidate_sources]
        if best_score >= 0.62:
            return VerificationStatus.SUPPORTED, min(best_score, 1.0), source_ids
        if best_score >= 0.30:
            return VerificationStatus.PARTIALLY_SUPPORTED, best_score, source_ids
        return VerificationStatus.UNSUPPORTED, best_score, source_ids

    @staticmethod
    def _candidate_sources(
        claim: Claim,
        source_by_id: dict[str, Source],
        source_by_key: dict[str, Source],
    ) -> list[Source]:
        """Resolve claim source references to Source objects."""
        sources: list[Source] = []
        for source_id in claim.source_ids:
            if source_id in source_by_id:
                sources.append(source_by_id[source_id])
            elif source_id in source_by_key:
                sources.append(source_by_key[source_id])
        citation_keys = [match.group(0).strip("[]") for match in re.finditer(r"\[[A-Za-z0-9_-]+\]", claim.text)]
        for key in citation_keys:
            if key in source_by_key:
                sources.append(source_by_key[key])
        deduped: dict[str, Source] = {}
        for source in sources:
            if CITATION_KEY_PATTERN.match(source.citation_key):
                deduped[source.id] = source
        return list(deduped.values())

    @staticmethod
    def _support_score(claim_text: str, source_text: str) -> float:
        """Return fuzzy support score between a claim and source text."""
        claim_tokens = set(re.findall(r"[a-z0-9]+", claim_text.lower()))
        source_tokens = set(re.findall(r"[a-z0-9]+", source_text.lower()))
        overlap = len(claim_tokens & source_tokens) / max(len(claim_tokens), 1)
        sequence = SequenceMatcher(None, claim_text.lower(), source_text.lower()).ratio()
        return (0.75 * overlap) + (0.25 * sequence)
