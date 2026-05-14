"""Report quality evaluation utilities."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QualityEvaluation:
    """Report quality evaluation result."""

    rouge_l: float
    section_coverage: float
    word_count_adherence: float
    overall_score: float


def rouge_l_score(candidate: str, reference: str) -> float:
    """Return ROUGE-L F1 using longest common subsequence over tokens."""
    candidate_tokens = _tokens(candidate)
    reference_tokens = _tokens(reference)
    if not candidate_tokens or not reference_tokens:
        return 0.0
    lcs = _lcs_length(candidate_tokens, reference_tokens)
    precision = lcs / len(candidate_tokens)
    recall = lcs / len(reference_tokens)
    if precision + recall == 0:
        return 0.0
    return (2 * precision * recall) / (precision + recall)


def section_coverage(markdown: str, planned_sections: list[str]) -> float:
    """Return fraction of planned sections present as Markdown headings."""
    if not planned_sections:
        return 1.0
    headings = {heading.lower().strip() for heading in re.findall(r"^#{1,3}\s+(.+)$", markdown, re.MULTILINE)}
    covered = sum(1 for section in planned_sections if section.lower().strip() in headings)
    return covered / len(planned_sections)


def word_count_adherence(markdown: str, target_word_count: int, tolerance: float = 0.2) -> float:
    """Score whether a report is within the target word-count tolerance."""
    words = len(_tokens(markdown))
    if target_word_count <= 0:
        return 1.0
    lower = target_word_count * (1 - tolerance)
    upper = target_word_count * (1 + tolerance)
    if lower <= words <= upper:
        return 1.0
    distance = min(abs(words - lower), abs(words - upper))
    return max(0.0, 1.0 - (distance / target_word_count))


def evaluate_report(
    markdown: str,
    *,
    reference_markdown: str,
    planned_sections: list[str],
    target_word_count: int,
) -> QualityEvaluation:
    """Evaluate report text against reference, outline, and word-count target."""
    rouge = rouge_l_score(markdown, reference_markdown)
    coverage = section_coverage(markdown, planned_sections)
    adherence = word_count_adherence(markdown, target_word_count)
    overall = (0.4 * rouge) + (0.35 * coverage) + (0.25 * adherence)
    return QualityEvaluation(
        rouge_l=rouge,
        section_coverage=coverage,
        word_count_adherence=adherence,
        overall_score=overall,
    )


def score_report(markdown: str) -> float:
    """Return a simple backward-compatible report quality score."""
    return 1.0 if "## Bibliography" in markdown else 0.5


def _tokens(text: str) -> list[str]:
    """Tokenize text for evaluation."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _lcs_length(left: list[str], right: list[str]) -> int:
    """Return longest common subsequence length using dynamic programming."""
    previous = [0] * (len(right) + 1)
    for left_token in left:
        current = [0]
        for index, right_token in enumerate(right, start=1):
            if left_token == right_token:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]
