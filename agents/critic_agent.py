"""Critic agent for report quality feedback."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from schemas.agent_outputs import CriticOutput
from orchestration.cost_tracking import CostTrackingModel
from tools.llm.model_router import ModelRouter


@dataclass(frozen=True)
class CriticInput:
    """Inputs for final report quality review."""

    report_markdown: str
    sources: Sequence[Any] = ()
    verifier_results: Sequence[Any] = ()
    report_plan: Any | None = None
    section_outputs: Sequence[Any] = ()


class CriticAgent:
    """Review final report quality and suggest concrete fixes."""

    PLACEHOLDER_PATTERNS = [
        r"\[SourceID\]",
        r"\[source id\]",
        r"\[citation needed\]",
        r"\[TODO\]",
        r"\bTODO\b",
        r"\bTBD\b",
        r"\blorem ipsum\b",
        r"<insert .*?>",
        r"\{\{.*?\}\}",
    ]

    def __init__(self, router: ModelRouter | None = None, *, use_llm: bool = True) -> None:
        """Initialize critic with model router."""
        self.router = router or ModelRouter()
        self.use_llm = use_llm

    def run(self, critic_input: CriticInput) -> CriticOutput:
        """Review a final report draft from an explicit input contract."""
        return self.critique(
            critic_input.report_markdown,
            sources=critic_input.sources,
            verifier_results=critic_input.verifier_results,
            report_plan=critic_input.report_plan,
            section_outputs=critic_input.section_outputs,
        )

    def critique(
        self,
        report_markdown: str,
        *,
        sources: Sequence[Any] | None = None,
        verifier_results: Sequence[Any] | None = None,
        report_plan: Any | None = None,
        section_outputs: Sequence[Any] | None = None,
    ) -> CriticOutput:
        """Return a quality score and prioritized fixes for a report draft."""
        report_markdown = report_markdown or ""
        deterministic_score, deterministic_fixes = self._deterministic_review(
            report_markdown=report_markdown,
            sources=sources or [],
            verifier_results=verifier_results or [],
        )
        llm_score: float | None = None
        llm_fixes: list[str] = []

        if self.use_llm:
            try:
                prompt = self._build_llm_prompt(
                    report_markdown=report_markdown,
                    sources=sources or [],
                    verifier_results=verifier_results or [],
                    report_plan=report_plan,
                    section_outputs=section_outputs or [],
                    deterministic_fixes=deterministic_fixes,
                )
                raw_response = CostTrackingModel(self.router.get_model())(prompt)
                parsed = self._parse_llm_response(raw_response)
                if parsed:
                    llm_score = parsed.get("quality_score")
                    llm_fixes = parsed.get("fixes", []) or []
            except Exception as exc:
                llm_fixes = [
                    (
                        "Critic LLM review failed; deterministic checks were used instead. "
                        f"Internal error: {type(exc).__name__}."
                    )
                ]

        final_score = (
            min(deterministic_score, self._clamp_score(llm_score))
            if llm_score is not None
            else deterministic_score
        )
        fixes = self._dedupe_fixes([*deterministic_fixes, *llm_fixes])
        if final_score >= 0.85 and not fixes:
            fixes = ["No blocking issues found. Minor copy-editing may still improve readability."]
        return CriticOutput(quality_score=round(final_score, 3), fixes=fixes)

    def _deterministic_review(
        self,
        *,
        report_markdown: str,
        sources: Sequence[Any],
        verifier_results: Sequence[Any],
    ) -> tuple[float, list[str]]:
        """Perform non-LLM quality checks that should always run."""
        fixes: list[str] = []
        score = 1.0
        text = report_markdown.strip()
        word_count = len(re.findall(r"\b\w+\b", text))

        if not text:
            return 0.0, ["Report is empty. Generate report sections before critique."]
        if word_count < 300:
            score -= 0.25
            fixes.append(
                "Report is very short; expand sections with evidence, interpretation, and conclusions."
            )

        placeholders = self._find_placeholders(text)
        if placeholders:
            score -= 0.25
            fixes.append(
                "Remove unresolved placeholders before export: "
                + ", ".join(sorted(placeholders)[:8])
                + "."
            )

        source_ids = self._extract_source_ids(sources)
        citation_tokens = self._extract_citation_tokens(text)
        if sources and not citation_tokens:
            score -= 0.30
            fixes.append("No source citations were detected even though sources are available.")
        if "[SourceID]" in text:
            score -= 0.30
            fixes.append("Replace the placeholder citation [SourceID] with real source IDs.")

        unknown_citations = self._find_unknown_citations(citation_tokens, source_ids)
        if source_ids and unknown_citations:
            score -= 0.15
            fixes.append(
                "Some citations do not match collected Source records: "
                + ", ".join(sorted(unknown_citations)[:10])
                + "."
            )

        citation_density_issue = self._citation_density_issue(text, citation_tokens)
        if citation_density_issue:
            score -= 0.15
            fixes.append(citation_density_issue)

        missing_core_sections = self._find_missing_core_sections(text)
        if missing_core_sections:
            score -= 0.08
            fixes.append(
                "Consider adding or clearly labeling missing report sections: "
                + ", ".join(missing_core_sections)
                + "."
            )

        verifier_fixes, verifier_penalty = self._review_verifier_results(verifier_results)
        if verifier_fixes:
            score -= verifier_penalty
            fixes.extend(verifier_fixes)

        contradiction_markers = self._detect_contradiction_markers(text)
        if contradiction_markers:
            score -= 0.10
            fixes.append(
                "Resolve weak or contradictory phrasing before final export: "
                + ", ".join(contradiction_markers[:5])
                + "."
            )
        return self._clamp_score(score), self._dedupe_fixes(fixes)

    def _build_llm_prompt(
        self,
        *,
        report_markdown: str,
        sources: Sequence[Any],
        verifier_results: Sequence[Any],
        report_plan: Any | None,
        section_outputs: Sequence[Any],
        deterministic_fixes: Sequence[str],
    ) -> str:
        """Create a grounded prompt for the model-based critic."""
        return f"""
You are the CriticAgent in a production report-generation system.

Review the final Markdown report for unsupported claims, missing citations,
source mismatches, incomplete sections, contradictions, weak reasoning, shallow
conclusions, formatting issues, and whether the report answers the user's topic.

Return only valid JSON:
{{
  "quality_score": 0.0,
  "fixes": ["Concrete fix"]
}}

Collected source summary:
{json.dumps(self._summarize_sources(sources), indent=2, default=str)}

Verifier results:
{json.dumps(self._summarize_objects(verifier_results, max_items=20), indent=2, default=str)}

Report plan:
{json.dumps(self._safe_jsonable(report_plan), indent=2, default=str)}

Section outputs:
{json.dumps(self._summarize_objects(section_outputs, max_items=20), indent=2, default=str)}

Deterministic issues already found:
{json.dumps(list(deterministic_fixes), indent=2)}

Final report markdown:
---
{self._truncate(report_markdown, 14_000)}
---
""".strip()

    def _parse_llm_response(self, raw_response: Any) -> dict[str, Any] | None:
        """Parse JSON from common LLM response shapes."""
        text = self._response_to_text(raw_response).strip()
        if not text:
            return None
        text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text.strip()).strip()
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
        if not isinstance(parsed, dict):
            return None
        score = parsed.get("quality_score")
        fixes = parsed.get("fixes", [])
        if not isinstance(score, (int, float)):
            score = None
        if isinstance(fixes, str):
            fixes = [fixes]
        elif not isinstance(fixes, list):
            fixes = []
        return {
            "quality_score": self._clamp_score(score) if score is not None else None,
            "fixes": [str(fix).strip() for fix in fixes if str(fix).strip()],
        }

    def _response_to_text(self, raw_response: Any) -> str:
        """Convert common model response objects into plain text."""
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

    def _find_placeholders(self, text: str) -> set[str]:
        """Find placeholder text that should not appear in final reports."""
        found: set[str] = set()
        for pattern in self.PLACEHOLDER_PATTERNS:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                found.add(match.group(0))
        return found

    def _extract_source_ids(self, sources: Sequence[Any]) -> set[str]:
        """Extract possible source IDs from Source-like objects."""
        source_ids: set[str] = set()
        for source in sources:
            for attr in ("source_id", "id", "uid", "key", "citation_key"):
                value = self._get_value(source, attr)
                if value:
                    source_ids.add(str(value).strip().strip("[]"))
        return {source_id for source_id in source_ids if source_id}

    def _extract_citation_tokens(self, text: str) -> set[str]:
        """Extract bracket-style citation tokens, ignoring Markdown links."""
        tokens: set[str] = set()
        for match in re.finditer(r"\[([A-Za-z0-9_.:-]{1,100})\](?!\()", text):
            token = match.group(1).strip()
            lowered = token.lower()
            if lowered in {"sourceid", "todo", "citation needed", "source id"}:
                continue
            if " " in token and not token.lower().startswith(("source", "src", "ref")):
                continue
            tokens.add(token)
        return tokens

    def _find_unknown_citations(
        self,
        citation_tokens: Iterable[str],
        source_ids: set[str],
    ) -> set[str]:
        """Return citations that do not match known source IDs."""
        if not source_ids:
            return set()
        normalized_source_ids = {source_id.lower() for source_id in source_ids}
        return {token for token in citation_tokens if token.lower() not in normalized_source_ids}

    def _citation_density_issue(self, text: str, citation_tokens: set[str]) -> str | None:
        """Check whether citations are too sparse for a source-backed report."""
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", text)
            if len(paragraph.strip()) >= 120
        ]
        if not paragraphs:
            return None
        cited_paragraphs = [
            paragraph for paragraph in paragraphs if self._extract_citation_tokens(paragraph)
        ]
        coverage = len(cited_paragraphs) / max(len(paragraphs), 1)
        if citation_tokens and coverage < 0.35:
            return (
                "Citation coverage is sparse; attach citations to the specific paragraphs "
                "that make factual or quantitative claims."
            )
        return None

    def _find_missing_core_sections(self, text: str) -> list[str]:
        """Find important sections that appear to be missing."""
        lowered = text.lower()
        missing: list[str] = []
        if "executive summary" not in lowered and "summary" not in lowered:
            missing.append("Executive Summary")
        if "conclusion" not in lowered and "recommendation" not in lowered:
            missing.append("Conclusion or Recommendations")
        return missing

    def _review_verifier_results(self, verifier_results: Sequence[Any]) -> tuple[list[str], float]:
        """Convert verifier outputs into critic fixes and score penalty."""
        fixes: list[str] = []
        penalty = 0.0
        for idx, result in enumerate(verifier_results, start=1):
            result_dict = self._safe_jsonable(result)
            text_blob = json.dumps(result_dict, default=str).lower()
            has_blocking = any(
                marker in text_blob
                for marker in [
                    "blocking",
                    "unsupported",
                    "not supported",
                    "failed",
                    "hallucinated",
                    "citation mismatch",
                ]
            )
            if has_blocking:
                penalty += 0.12
                section_name = (
                    result_dict.get("section_id")
                    or result_dict.get("section")
                    or result_dict.get("title")
                    or f"section {idx}"
                )
                fixes.append(
                    f"Resolve verifier issues in {section_name}; at least one claim appears unsupported or blocking."
                )
        return self._dedupe_fixes(fixes), min(penalty, 0.35)

    def _detect_contradiction_markers(self, text: str) -> list[str]:
        """Find phrases that often indicate unresolved uncertainty."""
        markers = []
        patterns = [
            r"\bthis is unclear\b",
            r"\bneeds verification\b",
            r"\bnot sure\b",
            r"\bpossibly\b",
            r"\bmaybe\b",
            r"\bunknown\b",
        ]
        for pattern in patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                markers.append(pattern.replace(r"\b", "").replace("\\", ""))
        return markers

    def _summarize_sources(
        self, sources: Sequence[Any], max_sources: int = 30
    ) -> list[dict[str, Any]]:
        """Create a compact source summary for the critic prompt."""
        summary: list[dict[str, Any]] = []
        for source in list(sources)[:max_sources]:
            item = {
                "id": self._get_value(source, "source_id") or self._get_value(source, "id"),
                "title": self._get_value(source, "title"),
                "url": self._get_value(source, "url"),
                "publisher": self._get_value(source, "publisher"),
                "published_at": self._get_value(source, "published_at"),
                "source_type": self._get_value(source, "source_type")
                or self._get_value(source, "type"),
            }
            summary.append({key: value for key, value in item.items() if value is not None})
        return summary

    def _summarize_objects(self, objects: Sequence[Any], max_items: int = 20) -> list[Any]:
        """Safely summarize arbitrary objects for prompting."""
        return [self._safe_jsonable(item) for item in list(objects)[:max_items]]

    def _safe_jsonable(self, value: Any) -> Any:
        """Convert dataclasses, Pydantic models, and plain objects to JSONable forms."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): self._safe_jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._safe_jsonable(item) for item in value]
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return self._safe_jsonable(model_dump())
        dict_method = getattr(value, "dict", None)
        if callable(dict_method):
            return self._safe_jsonable(dict_method())
        if hasattr(value, "__dict__"):
            return self._safe_jsonable(vars(value))
        return str(value)

    def _get_value(self, obj: Any, key: str) -> Any:
        """Get a value from dict-like or object-like records."""
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    def _truncate(self, text: str, max_chars: int) -> str:
        """Truncate long text while preserving the beginning and end."""
        if len(text) <= max_chars:
            return text
        head = text[: int(max_chars * 0.70)]
        tail = text[-int(max_chars * 0.25) :]
        return head + "\n\n...[TRUNCATED FOR CRITIC PROMPT]...\n\n" + tail

    def _clamp_score(self, score: float | int | None) -> float:
        """Clamp score into [0, 1]."""
        if score is None:
            return 0.0
        return max(0.0, min(1.0, float(score)))

    def _dedupe_fixes(self, fixes: Sequence[str]) -> list[str]:
        """Deduplicate fixes while preserving order."""
        seen: set[str] = set()
        deduped: list[str] = []
        for fix in fixes:
            cleaned = str(fix).strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(cleaned)
        return deduped
