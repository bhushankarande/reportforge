"""Verifier agent for claim coverage.

This verifier combines:
1. deterministic citation validation,
2. candidate-source retrieval,
3. lightweight contradiction / numeric-mismatch checks,
4. optional LLM-backed verification using actual claim + evidence snippets.

It remains backward-compatible with:

    verify(claims: list[Claim]) -> VerifierOutput
    run(section: ReportSection, sources: list[Source]) -> VerifierOutput
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Iterable

from app.logging_config import get_logger
from orchestration.cost_tracking import CostTrackingModel
from schemas.agent_outputs import VerifierOutput
from schemas.reports import ReportSection
from schemas.sources import Claim, Source, VerificationStatus
from tools.citation_checker import validate_claim_sources
from tools.llm.model_router import ModelRouter

logger = get_logger(__name__)

CITATION_PATTERN = re.compile(r"\[([A-Za-z0-9_-]+)\]")
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?")


class VerifierAgent:
    """Audit claims and produce export blockers or warnings."""

    def __init__(
        self,
        router: ModelRouter | None = None,
        *,
        use_llm: bool = True,
        max_candidate_sources: int = 4,
        max_evidence_chars_per_source: int = 1_800,
    ) -> None:
        """Initialize verifier.

        Args:
            router: Optional model router.
            use_llm: Whether to use LLM verification after deterministic retrieval.
            max_candidate_sources: Number of candidate sources to inspect per claim.
            max_evidence_chars_per_source: Evidence snippet budget per source.
        """
        self.router = router or ModelRouter()
        self.use_llm = use_llm
        self.max_candidate_sources = max_candidate_sources
        self.max_evidence_chars_per_source = max_evidence_chars_per_source
        self.model = CostTrackingModel(self.router.get_model())

        self.sys_prompt = (
            "You are ReportForge VerifierAgent. Verify claims against the supplied evidence only. "
            "Assign one of: SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED, CONTRADICTED. "
            "SUPPORTED means the evidence directly supports the claim. "
            "PARTIALLY_SUPPORTED means the evidence supports only part of the claim or lacks precision. "
            "UNSUPPORTED means the evidence does not prove the claim. "
            "CONTRADICTED means the evidence says the opposite or uses conflicting numbers/dates. "
            "Return confidence between 0.0 and 1.0."
        )

    def verify(self, claims: list[Claim]) -> VerifierOutput:
        """Backward-compatible claim-only verification.

        This path cannot truly verify evidence because no Source records are provided.
        It only prevents unsupported export by downgrading claims that lack citations.
        """
        normalized: list[Claim] = []

        for claim in claims:
            source_ids = self._safe_source_ids(claim)
            current_status = self._get_claim_status(claim)

            if not source_ids and current_status == VerificationStatus.SUPPORTED:
                status = VerificationStatus.UNVERIFIED
                confidence = min(self._get_claim_confidence(claim), 0.25)
            else:
                status = current_status
                confidence = self._get_claim_confidence(claim)

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
        return VerifierOutput(claims=normalized, blockers=blockers, warnings=warnings)

    def run(self, section: ReportSection, sources: list[Source]) -> VerifierOutput:
        """Verify section claims against collected sources."""
        claims = list(getattr(section, "claims", []) or [])

        logger.info(
            "verifier_started",
            job_id=getattr(section, "job_id", None),
            section_id=getattr(section, "id", None),
            claims=len(claims),
            sources=len(sources),
        )

        if not claims:
            warning = (
                f"Section '{getattr(section, 'title', 'unknown')}' has no extracted claims. "
                "Verifier could not check factual coverage."
            )
            return VerifierOutput(claims=[], blockers=[], warnings=[warning])

        source_index = self._build_source_index(sources)
        normalized: list[Claim] = []

        for claim in claims:
            verified_claim = self._verify_claim_with_sources(
                claim=claim,
                all_sources=sources,
                source_by_id=source_index["by_id"],
                source_by_key=source_index["by_key"],
            )
            normalized.append(verified_claim)

        blockers, warnings = validate_claim_sources(normalized)

        logger.info(
            "verifier_completed",
            job_id=getattr(section, "job_id", None),
            section_id=getattr(section, "id", None),
            blockers=len(blockers),
            warnings=len(warnings),
        )

        return VerifierOutput(claims=normalized, blockers=blockers, warnings=warnings)

    def _verify_claim_with_sources(
        self,
        *,
        claim: Claim,
        all_sources: list[Source],
        source_by_id: dict[str, Source],
        source_by_key: dict[str, Source],
    ) -> Claim:
        """Verify one claim and return an updated Claim object."""
        claim_text = self._claim_text(claim)
        explicit_source_ids = self._safe_source_ids(claim)

        candidate_sources = self._candidate_sources(
            claim=claim,
            all_sources=all_sources,
            source_by_id=source_by_id,
            source_by_key=source_by_key,
        )

        if not candidate_sources:
            return claim.model_copy(
                update={
                    "source_ids": explicit_source_ids,
                    "verification_status": VerificationStatus.UNSUPPORTED,
                    "confidence": 0.0,
                }
            )

        evidence_items = [
            self._evidence_item_for_source(claim_text, source)
            for source in candidate_sources
        ]

        deterministic_status, deterministic_confidence = self._deterministic_verify(
            claim_text=claim_text,
            evidence_items=evidence_items,
            has_explicit_citation=bool(explicit_source_ids or self._citation_keys_from_text(claim_text)),
        )

        final_status = deterministic_status
        final_confidence = deterministic_confidence

        if self.use_llm:
            llm_result = self._llm_verify_claim(
                claim_text=claim_text,
                evidence_items=evidence_items,
                deterministic_status=deterministic_status,
                deterministic_confidence=deterministic_confidence,
            )

            if llm_result is not None:
                llm_status = llm_result["status"]
                llm_confidence = llm_result["confidence"]

                final_status, final_confidence = self._combine_verdicts(
                    deterministic_status=deterministic_status,
                    deterministic_confidence=deterministic_confidence,
                    llm_status=llm_status,
                    llm_confidence=llm_confidence,
                )

        source_ids = [self._source_id(source) for source in candidate_sources]
        source_ids = [source_id for source_id in source_ids if source_id]

        return claim.model_copy(
            update={
                "source_ids": source_ids,
                "verification_status": final_status,
                "confidence": round(final_confidence, 3),
            }
        )

    def _deterministic_verify(
        self,
        *,
        claim_text: str,
        evidence_items: list[dict[str, str]],
        has_explicit_citation: bool,
    ) -> tuple[VerificationStatus, float]:
        """Use deterministic checks before asking the LLM."""
        if not evidence_items:
            return VerificationStatus.UNSUPPORTED, 0.0

        evidence_text = "\n".join(item["evidence"] for item in evidence_items)

        if self._has_numeric_mismatch(claim_text, evidence_text):
            return VerificationStatus.CONTRADICTED, 0.78

        if self._has_negation_conflict(claim_text, evidence_text):
            return VerificationStatus.CONTRADICTED, 0.72

        best_score = max(
            self._support_score(claim_text, item["evidence"])
            for item in evidence_items
        )

        if best_score >= 0.72:
            status = VerificationStatus.SUPPORTED
            confidence = min(0.88, best_score)
        elif best_score >= 0.42:
            status = VerificationStatus.PARTIALLY_SUPPORTED
            confidence = min(0.68, best_score)
        else:
            status = VerificationStatus.UNSUPPORTED
            confidence = min(0.35, best_score)

        if not has_explicit_citation and status == VerificationStatus.SUPPORTED:
            status = VerificationStatus.PARTIALLY_SUPPORTED
            confidence = min(confidence, 0.62)

        return status, confidence

    def _llm_verify_claim(
        self,
        *,
        claim_text: str,
        evidence_items: list[dict[str, str]],
        deterministic_status: VerificationStatus,
        deterministic_confidence: float,
    ) -> dict[str, Any] | None:
        """Ask the LLM to verify a claim using actual evidence snippets."""
        prompt = self._build_verification_prompt(
            claim_text=claim_text,
            evidence_items=evidence_items,
            deterministic_status=deterministic_status,
            deterministic_confidence=deterministic_confidence,
        )

        try:
            raw_response = self.model(prompt)
            return self._parse_llm_verdict(raw_response)
        except Exception as exc:
            logger.warning(
                "verifier_llm_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None

    def _build_verification_prompt(
        self,
        *,
        claim_text: str,
        evidence_items: list[dict[str, str]],
        deterministic_status: VerificationStatus,
        deterministic_confidence: float,
    ) -> str:
        """Create a strict evidence-only verification prompt."""
        evidence_payload = [
            {
                "source_id": item["source_id"],
                "citation_key": item["citation_key"],
                "title": item["title"],
                "evidence": item["evidence"],
            }
            for item in evidence_items
        ]

        return f"""
{self.sys_prompt}

Return only valid JSON:

{{
  "verification_status": "SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | CONTRADICTED",
  "confidence": 0.0,
  "reason": "Brief reason using only the supplied evidence."
}}

Important rules:
- Do not use outside knowledge.
- Do not infer beyond the evidence.
- If the evidence has similar words but does not prove the exact claim, use PARTIALLY_SUPPORTED or UNSUPPORTED.
- If numbers, dates, direction, or causality conflict, use CONTRADICTED.
- If the evidence is about a different entity, geography, metric, or time period, use UNSUPPORTED.

Claim:
{claim_text}

Candidate evidence:
{json.dumps(evidence_payload, indent=2, ensure_ascii=False)}

Deterministic pre-check:
{{
  "verification_status": "{deterministic_status.name}",
  "confidence": {deterministic_confidence}
}}
""".strip()

    def _parse_llm_verdict(self, raw_response: Any) -> dict[str, Any] | None:
        """Parse LLM JSON verdict."""
        text = self._response_to_text(raw_response).strip()

        if not text:
            return None

        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                return None
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

        status_text = str(parsed.get("verification_status", "")).strip().upper()
        confidence = parsed.get("confidence", 0.0)

        status = self._status_from_text(status_text)
        if status is None:
            return None

        try:
            confidence_float = float(confidence)
        except (TypeError, ValueError):
            confidence_float = 0.0

        return {
            "status": status,
            "confidence": self._clamp(confidence_float),
            "reason": str(parsed.get("reason", "")).strip(),
        }

    def _combine_verdicts(
        self,
        *,
        deterministic_status: VerificationStatus,
        deterministic_confidence: float,
        llm_status: VerificationStatus,
        llm_confidence: float,
    ) -> tuple[VerificationStatus, float]:
        """Combine deterministic and LLM verdicts conservatively."""
        severity = {
            VerificationStatus.SUPPORTED: 0,
            VerificationStatus.PARTIALLY_SUPPORTED: 1,
            VerificationStatus.UNVERIFIED: 2,
            VerificationStatus.UNSUPPORTED: 3,
            VerificationStatus.CONTRADICTED: 4,
        }

        if (
            deterministic_status == VerificationStatus.CONTRADICTED
            or llm_status == VerificationStatus.CONTRADICTED
        ):
            return VerificationStatus.CONTRADICTED, max(deterministic_confidence, llm_confidence)

        if severity.get(llm_status, 2) > severity.get(deterministic_status, 2):
            return llm_status, llm_confidence

        if severity.get(deterministic_status, 2) > severity.get(llm_status, 2):
            return deterministic_status, deterministic_confidence

        confidence = (deterministic_confidence + llm_confidence) / 2
        return llm_status, self._clamp(confidence)

    def _candidate_sources(
        self,
        *,
        claim: Claim,
        all_sources: list[Source],
        source_by_id: dict[str, Source],
        source_by_key: dict[str, Source],
    ) -> list[Source]:
        """Resolve explicit citations first, then retrieve likely sources."""
        claim_text = self._claim_text(claim)
        candidates: list[Source] = []

        for source_ref in self._safe_source_ids(claim):
            normalized_refs = self._normalize_source_ref_variants(source_ref)

            for ref in normalized_refs:
                if ref in source_by_id:
                    candidates.append(source_by_id[ref])
                if ref in source_by_key:
                    candidates.append(source_by_key[ref])

        for key in self._citation_keys_from_text(claim_text):
            for ref in self._normalize_source_ref_variants(key):
                if ref in source_by_key:
                    candidates.append(source_by_key[ref])
                if ref in source_by_id:
                    candidates.append(source_by_id[ref])

        candidates = self._dedupe_sources(candidates)

        if candidates:
            return candidates[: self.max_candidate_sources]

        ranked = sorted(
            all_sources,
            key=lambda source: self._support_score(claim_text, self._source_text(source)),
            reverse=True,
        )

        return [
            source
            for source in ranked[: self.max_candidate_sources]
            if self._support_score(claim_text, self._source_text(source)) >= 0.18
        ]

    def _build_source_index(self, sources: list[Source]) -> dict[str, dict[str, Source]]:
        """Build robust source indexes by ID and citation key."""
        by_id: dict[str, Source] = {}
        by_key: dict[str, Source] = {}

        for source in sources:
            source_id = self._source_id(source)
            citation_key = self._source_citation_key(source)

            if source_id:
                for key in self._normalize_source_ref_variants(source_id):
                    by_id[key] = source

            if citation_key:
                for key in self._normalize_source_ref_variants(citation_key):
                    by_key[key] = source

        return {"by_id": by_id, "by_key": by_key}

    def _evidence_item_for_source(self, claim_text: str, source: Source) -> dict[str, str]:
        """Create compact evidence item with the best passage from a source."""
        source_text = self._source_text(source)
        best_passage = self._best_passage_for_claim(claim_text, source_text)

        return {
            "source_id": self._source_id(source),
            "citation_key": self._source_citation_key(source),
            "title": self._safe_get(source, "title"),
            "evidence": best_passage[: self.max_evidence_chars_per_source],
        }

    def _best_passage_for_claim(self, claim_text: str, source_text: str) -> str:
        """Select the most claim-relevant passage from source text."""
        if len(source_text) <= self.max_evidence_chars_per_source:
            return source_text

        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n|(?<=[.!?])\s+", source_text)
            if len(paragraph.strip()) >= 40
        ]

        if not paragraphs:
            return source_text[: self.max_evidence_chars_per_source]

        ranked = sorted(
            paragraphs,
            key=lambda paragraph: self._support_score(claim_text, paragraph),
            reverse=True,
        )

        selected: list[str] = []
        total_chars = 0

        for paragraph in ranked[:5]:
            if total_chars + len(paragraph) > self.max_evidence_chars_per_source:
                break
            selected.append(paragraph)
            total_chars += len(paragraph)

        return "\n\n".join(selected) or source_text[: self.max_evidence_chars_per_source]

    def _support_score(self, claim_text: str, source_text: str) -> float:
        """Return lexical support score.

        This is not treated as proof by itself; it is only used for candidate
        retrieval and deterministic pre-checking.
        """
        claim_tokens = set(TOKEN_PATTERN.findall(claim_text.lower()))
        source_tokens = set(TOKEN_PATTERN.findall(source_text.lower()))

        if not claim_tokens or not source_tokens:
            return 0.0

        overlap = len(claim_tokens & source_tokens) / max(len(claim_tokens), 1)

        compact_source = source_text[:2_000].lower()
        sequence = SequenceMatcher(None, claim_text.lower(), compact_source).ratio()

        return (0.85 * overlap) + (0.15 * sequence)

    def _has_numeric_mismatch(self, claim_text: str, evidence_text: str) -> bool:
        """Detect likely numeric contradiction."""
        claim_numbers = set(self._extract_numbers(claim_text))
        evidence_numbers = set(self._extract_numbers(evidence_text))

        if not claim_numbers:
            return False

        if not evidence_numbers:
            return False

        shared = claim_numbers & evidence_numbers

        if not shared and self._support_score(claim_text, evidence_text) >= 0.55:
            return True

        return False

    def _has_negation_conflict(self, claim_text: str, evidence_text: str) -> bool:
        """Detect simple negation-direction conflicts."""
        claim_lower = claim_text.lower()
        evidence_lower = evidence_text.lower()

        claim_negative = self._contains_negation(claim_lower)
        evidence_negative = self._contains_negation(evidence_lower)

        if claim_negative == evidence_negative:
            return False

        return self._support_score(claim_text, evidence_text) >= 0.60

    def _contains_negation(self, text: str) -> bool:
        """Return whether text contains common negation markers."""
        return bool(
            re.search(
                r"\b(no|not|never|without|neither|nor|failed to|did not|does not|do not|cannot|can't|isn't|wasn't|aren't|won't)\b",
                text,
            )
        )

    def _extract_numbers(self, text: str) -> list[str]:
        """Extract normalized number tokens."""
        numbers = []

        for match in NUMBER_PATTERN.finditer(text):
            value = match.group(0).replace(",", "").strip()
            numbers.append(value)

        return numbers

    def _citation_keys_from_text(self, text: str) -> list[str]:
        """Extract citation keys from bracket citations."""
        return [match.group(1).strip() for match in CITATION_PATTERN.finditer(text)]

    def _normalize_source_ref_variants(self, value: Any) -> set[str]:
        """Normalize source references.

        Handles:
        - S1
        - [S1]
        - source-1
        - Source_1
        """
        if value is None:
            return set()

        raw = str(value).strip()

        if not raw:
            return set()

        stripped = raw.strip("[]").strip()

        return {
            raw,
            stripped,
            raw.lower(),
            stripped.lower(),
        }

    def _dedupe_sources(self, sources: Iterable[Source]) -> list[Source]:
        """Deduplicate source objects by stable source ID or citation key."""
        deduped: dict[str, Source] = {}

        for source in sources:
            key = self._source_id(source) or self._source_citation_key(source)

            if not key:
                key = str(id(source))

            deduped[key] = source

        return list(deduped.values())

    def _source_text(self, source: Source) -> str:
        """Return compact source text from common Source fields."""
        parts = [
            self._safe_get(source, "title"),
            self._safe_get(source, "summary"),
            self._safe_get(source, "description"),
            self._safe_get(source, "excerpt"),
            self._safe_get(source, "raw_text"),
            self._safe_get(source, "content"),
        ]

        return " ".join(part for part in parts if part and part.lower() != "none")

    def _source_id(self, source: Source) -> str:
        """Return source ID safely."""
        return (
            self._safe_get(source, "id")
            or self._safe_get(source, "source_id")
            or self._safe_get(source, "uid")
        )

    def _source_citation_key(self, source: Source) -> str:
        """Return source citation key safely."""
        return (
            self._safe_get(source, "citation_key")
            or self._safe_get(source, "key")
            or self._source_id(source)
        )

    def _safe_source_ids(self, claim: Claim) -> list[str]:
        """Return claim source IDs safely."""
        source_ids = getattr(claim, "source_ids", None) or []
        return [str(source_id).strip() for source_id in source_ids if str(source_id).strip()]

    def _claim_text(self, claim: Claim) -> str:
        """Return claim text safely."""
        return str(getattr(claim, "text", "") or "").strip()

    def _get_claim_status(self, claim: Claim) -> VerificationStatus:
        """Return existing claim status safely."""
        status = getattr(claim, "verification_status", None)

        if isinstance(status, VerificationStatus):
            return status

        parsed = self._status_from_text(str(status or "UNVERIFIED"))
        return parsed or VerificationStatus.UNVERIFIED

    def _get_claim_confidence(self, claim: Claim) -> float:
        """Return existing claim confidence safely."""
        try:
            return self._clamp(float(getattr(claim, "confidence", 0.0) or 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _status_from_text(self, status_text: str) -> VerificationStatus | None:
        """Parse status text into VerificationStatus enum."""
        normalized = status_text.strip().upper()

        for status in VerificationStatus:
            if status.name.upper() == normalized:
                return status

            if str(status.value).upper() == normalized:
                return status

        return None

    def _safe_get(self, obj: Any, key: str) -> str:
        """Get a string value from object or dict."""
        if obj is None:
            return ""

        if isinstance(obj, dict):
            value = obj.get(key)
        else:
            value = getattr(obj, key, None)

        if value is None:
            return ""

        return str(value)

    def _response_to_text(self, raw_response: Any) -> str:
        """Convert common model responses to text."""
        if raw_response is None:
            return ""

        if isinstance(raw_response, str):
            return raw_response

        if isinstance(raw_response, dict):
            for key in ("content", "text", "output", "response"):
                value = raw_response.get(key)
                if value:
                    return str(value)

            return json.dumps(raw_response, default=str)

        content = getattr(raw_response, "content", None)
        if content is not None:
            return str(content)

        text = getattr(raw_response, "text", None)
        if text is not None:
            return str(text)

        return str(raw_response)

    def _clamp(self, value: float) -> float:
        """Clamp confidence into [0, 1]."""
        return max(0.0, min(1.0, float(value)))
