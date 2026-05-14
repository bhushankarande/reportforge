"""Citation evaluation utilities."""

import random
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from schemas.sources import Claim, Source


@dataclass(frozen=True)
class CitationEvaluation:
    """Citation evaluation result."""

    coverage: float
    accuracy: float
    hallucination_rate: float
    sampled_claim_ids: list[str]


def citation_coverage(total_claims: int, sourced_claims: int) -> float:
    """Return sourced-claim coverage."""
    if total_claims == 0:
        return 1.0
    return sourced_claims / total_claims


def citation_accuracy(
    claims: list[Claim],
    sources: list[Source],
    *,
    sample_size: int = 10,
    seed: int = 7,
) -> CitationEvaluation:
    """Evaluate citation coverage, sampled accuracy, and hallucination risk."""
    source_by_id = {source.id: source for source in sources}
    sourced_claims = [claim for claim in claims if claim.source_ids]
    coverage = citation_coverage(len(claims), len(sourced_claims))
    sample = _sample_claims(sourced_claims, sample_size, seed)
    accurate = 0
    hallucinations = 0
    for claim in sample:
        score = max((_claim_source_score(claim, source_by_id[source_id]) for source_id in claim.source_ids if source_id in source_by_id), default=0.0)
        if score >= 0.3:
            accurate += 1
        else:
            hallucinations += 1
    accuracy = accurate / len(sample) if sample else 1.0
    hallucination_rate = hallucinations / len(claims) if claims else 0.0
    return CitationEvaluation(
        coverage=coverage,
        accuracy=accuracy,
        hallucination_rate=hallucination_rate,
        sampled_claim_ids=[claim.id for claim in sample],
    )


def hallucination_claims(claims: list[Claim], sources: list[Source], threshold: float = 0.3) -> list[Claim]:
    """Return claims with no sufficiently matching source text."""
    source_by_id = {source.id: source for source in sources}
    unsupported: list[Claim] = []
    for claim in claims:
        best = max(
            (_claim_source_score(claim, source_by_id[source_id]) for source_id in claim.source_ids if source_id in source_by_id),
            default=0.0,
        )
        if best < threshold:
            unsupported.append(claim)
    return unsupported


def _sample_claims(claims: list[Claim], sample_size: int, seed: int) -> list[Claim]:
    """Return a deterministic random sample."""
    if len(claims) <= sample_size:
        return claims
    rng = random.Random(seed)
    return rng.sample(claims, sample_size)


def _claim_source_score(claim: Claim, source: Source) -> float:
    """Return a text-match score between a claim and source."""
    claim_tokens = set(re.findall(r"[a-z0-9]+", claim.text.lower()))
    source_text = f"{source.title} {source.summary} {source.raw_text}"
    source_tokens = set(re.findall(r"[a-z0-9]+", source_text.lower()))
    overlap = len(claim_tokens & source_tokens) / max(len(claim_tokens), 1)
    fuzzy = SequenceMatcher(None, claim.text.lower(), source_text.lower()).ratio()
    return (0.8 * overlap) + (0.2 * fuzzy)
