"""Planner agent for report outlines and section-level research plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from json import JSONDecodeError
import re
from typing import Any

from app.logging_config import get_logger
from schemas.agent_outputs import PlannerOutput
from schemas.reports import ReportDepth, ReportJob
from orchestration.cost_tracking import CostTrackingModel
from tools.llm.model_router import ModelRouter

logger = get_logger(__name__)

DEPTH_SECTION_RANGES = {
    ReportDepth.BRIEF: (2, 3),
    ReportDepth.STANDARD: (5, 7),
    ReportDepth.DEEP: (8, 12),
}

DEPTH_WORD_COUNTS = {
    ReportDepth.BRIEF: 1200,
    ReportDepth.STANDARD: 3500,
    ReportDepth.DEEP: 8000,
}


class PlannerAgentError(RuntimeError):
    """Raised when the planner cannot produce a usable plan."""


@dataclass
class PlannedSection:
    """A section-level plan used by downstream research and writing."""

    section_id: str
    title: str
    purpose: str
    research_questions: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    preferred_source_types: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    target_words: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable section plan."""
        return asdict(self)


@dataclass
class PlanManifest:
    """Full planner manifest retained in memory for orchestration."""

    job_id: str
    topic: str
    report_type: str
    depth: str
    target_word_count: int
    sections: list[PlannedSection]
    global_research_questions: list[str] = field(default_factory=list)
    source_strategy: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable manifest."""
        return {
            "job_id": self.job_id,
            "topic": self.topic,
            "report_type": self.report_type,
            "depth": self.depth,
            "target_word_count": self.target_word_count,
            "sections": [section.to_dict() for section in self.sections],
            "global_research_questions": self.global_research_questions,
            "source_strategy": self.source_strategy,
            "assumptions": self.assumptions,
            "warnings": self.warnings,
            "fallback_used": self.fallback_used,
        }


class PlannerAgent:
    """
    Create a report plan that is still compatible with PlannerOutput.

    Existing API compatibility:
        run(...) returns PlannerOutput(outline, research_questions, target_word_count)

    New behavior:
        self.last_manifest stores structured section plans with search queries,
        evidence requirements, source preferences, and per-section word budgets.
    """

    def __init__(
        self,
        router: ModelRouter | None = None,
        *,
        allow_fallback: bool = True,
        raise_on_failure: bool = False,
    ) -> None:
        """Initialize planner with model router."""
        self.router = router or ModelRouter()
        self.model = CostTrackingModel(self.router.get_model())
        self.allow_fallback = allow_fallback
        self.raise_on_failure = raise_on_failure
        self.last_manifest: PlanManifest | None = None
        self.last_raw_response: str | None = None
        self.last_warnings: list[str] = []

    def plan(self, topic: str, report_type: str, depth: str) -> PlannerOutput:
        """Plan a report from primitive inputs."""
        job = ReportJob(
            id="planning-preview",
            topic=topic,
            type=report_type,
            depth=depth,
            created_at="1970-01-01T00:00:00+00:00",
        )
        return self.run(job)

    def run(self, job: ReportJob) -> PlannerOutput:
        """Return a validated PlannerOutput and retain a structured manifest."""
        depth = self._depth_key(job.depth)
        report_type = self._enum_value(job.type)

        logger.info(
            "planner_started",
            job_id=job.id,
            report_type=report_type,
            depth=depth.value,
        )

        prompt = self._build_prompt(job)
        raw_response = self.model(prompt).text
        self.last_raw_response = raw_response

        try:
            manifest = self._parse_manifest(raw_response, job)
        except Exception as exc:
            logger.warning(
                "planner_parse_failed",
                job_id=job.id,
                error=str(exc),
            )
            correction_prompt = self._build_correction_prompt(
                original_prompt=prompt,
                raw_response=raw_response,
                error=exc,
            )
            corrected_response = self.model(correction_prompt).text
            self.last_raw_response = corrected_response
            try:
                manifest = self._parse_manifest(corrected_response, job)
            except Exception as second_exc:
                logger.warning(
                    "planner_correction_failed",
                    job_id=job.id,
                    error=str(second_exc),
                )
                if self.raise_on_failure or not self.allow_fallback:
                    raise PlannerAgentError(
                        f"Planner failed to produce valid JSON: {second_exc}"
                    ) from second_exc
                manifest = self._fallback_manifest(job)
                manifest.fallback_used = True
                manifest.warnings.append(
                    "Planner model failed validation; deterministic fallback manifest used."
                )

        manifest = self._enforce_manifest(manifest, depth)
        self.last_manifest = manifest
        self.last_warnings = manifest.warnings

        output = self._manifest_to_output(manifest)

        logger.info(
            "planner_completed",
            job_id=job.id,
            sections=len(output.outline),
            target_word_count=output.target_word_count,
            fallback_used=manifest.fallback_used,
        )

        return output

    def get_section_plan(self, section_title: str) -> dict[str, Any] | None:
        """Return a structured plan for a section title from the last run."""
        if self.last_manifest is None:
            return None

        wanted = self._slug(section_title)

        for section in self.last_manifest.sections:
            if self._slug(section.title) == wanted or section.section_id == wanted:
                return section.to_dict()

        return None

    def section_plan_for_writer(self, section_title: str) -> str:
        """
        Return section plan as compact JSON for passing into WriterInput.rolling_summary.

        This is a compatibility bridge until WriterInput has a first-class
        section_plan field.
        """
        section = self.get_section_plan(section_title)
        if section is None:
            return ""
        return json.dumps({"section_plan": section}, ensure_ascii=False)

    def _build_prompt(self, job: ReportJob) -> str:
        """Build a schema-specific planner prompt."""
        depth = self._depth_key(job.depth)
        min_sections, max_sections = DEPTH_SECTION_RANGES[depth]
        target_words = DEPTH_WORD_COUNTS[depth]
        report_type = self._enum_value(job.type)

        return f"""
You are ReportForge PlannerAgent.
Return one valid JSON object only. No markdown fences. No commentary.

Topic: {job.topic}
Report type: {report_type}
Depth: {depth.value}
Required section count: {min_sections}-{max_sections}
Target total word count: {target_words}

Create a research-ready plan, not just a table of contents.
Each section must have its own purpose, research questions, search queries,
required evidence, preferred source types, avoid rules, and target word count.

JSON schema:
{{
  "target_word_count": {target_words},
  "outline": [
    {{
      "section_title": "string",
      "purpose": "what this section must prove or explain",
      "research_questions": ["specific answerable evidence question"],
      "search_queries": ["web search query or URL discovery query"],
      "required_evidence": ["data/report/quote/metric/comparison needed"],
      "preferred_source_types": ["official documentation", "academic paper", "company report", "regulatory source", "credible news"],
      "avoid": ["unsupported claim type or source type to avoid"],
      "target_words": 300
    }}
  ],
  "global_research_questions": ["question that affects the whole report"],
  "source_strategy": {{
    "must_have_source_types": ["official/primary source", "independent secondary source"],
    "freshness_requirement": "state how recent sources should be when recency matters",
    "quality_rules": ["prefer primary sources", "avoid marketing-only claims"],
    "excluded_sources": ["low quality source categories"]
  }},
  "assumptions": ["explicit assumption if the topic is broad"],
  "warnings": ["important planning limitation or ambiguity"]
}}

Rules:
- Do not use generic filler section titles unless they fit the topic.
- Do not create a section that cannot be researched from evidence.
- Search queries must be useful for the ResearchAgent.
- Research questions must map directly to sections.
- Target words across sections should add up close to {target_words}.
""".strip()

    @staticmethod
    def _build_correction_prompt(
        original_prompt: str,
        raw_response: str,
        error: Exception,
    ) -> str:
        """Build a correction prompt that includes the broken response and error."""
        return f"""
The previous planner response failed JSON/schema validation.

Original instructions:
{original_prompt}

Previous response:
{raw_response}

Parser or validation error:
{type(error).__name__}: {error}

Return only one corrected valid JSON object using the required schema.
No markdown fences. No commentary.
""".strip()

    def _parse_manifest(self, raw_response: str, job: ReportJob) -> PlanManifest:
        """Parse model JSON into a structured manifest."""
        json_text = self._extract_first_json_object(raw_response)
        if not json_text:
            raise JSONDecodeError("Planner response did not contain a JSON object", raw_response, 0)

        payload = json.loads(json_text)
        if not isinstance(payload, dict):
            raise ValueError("Planner JSON root must be an object.")

        return self._payload_to_manifest(payload, job)

    def _payload_to_manifest(self, payload: dict[str, Any], job: ReportJob) -> PlanManifest:
        """Normalize a model payload into PlanManifest."""
        depth = self._depth_key(job.depth)
        report_type = self._enum_value(job.type)
        target_word_count = self._safe_int(
            payload.get("target_word_count"),
            DEPTH_WORD_COUNTS[depth],
        )

        raw_sections = payload.get("outline") or payload.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise ValueError("Planner payload must include non-empty outline/sections list.")

        sections: list[PlannedSection] = []

        for index, item in enumerate(raw_sections, start=1):
            if isinstance(item, str):
                title = item.strip()
                section_payload: dict[str, Any] = {}
            elif isinstance(item, dict):
                section_payload = item
                title = str(
                    item.get("section_title")
                    or item.get("title")
                    or item.get("name")
                    or f"Section {index}"
                ).strip()
            else:
                title = str(item).strip()
                section_payload = {}

            if not title:
                title = f"Section {index}"
            if title.strip().lower() in {"string", "section title"}:
                raise ValueError("Planner returned schema placeholder section title.")

            section_id = self._slug(title) or f"section_{index}"
            purpose = str(
                section_payload.get("purpose")
                or section_payload.get("goal")
                or f"Explain the evidence-backed role of {title} in the report topic."
            ).strip()

            research_questions = self._string_list(
                section_payload.get("research_questions")
                or section_payload.get("key_questions")
                or section_payload.get("questions")
            )

            search_queries = self._string_list(
                section_payload.get("search_queries")
                or section_payload.get("queries")
            )

            required_evidence = self._string_list(
                section_payload.get("required_evidence")
                or section_payload.get("evidence_requirements")
                or section_payload.get("evidence_needed")
            )

            preferred_source_types = self._string_list(
                section_payload.get("preferred_source_types")
                or section_payload.get("source_types")
            )

            avoid = self._string_list(section_payload.get("avoid"))

            if not research_questions:
                research_questions = [
                    f"What evidence directly supports the section '{title}' for the topic '{job.topic}'?",
                    f"What limitations or contrary evidence should qualify claims in '{title}'?",
                ]

            if not search_queries:
                search_queries = [
                    f"{job.topic} {title} evidence report",
                    f"{job.topic} {title} data analysis sources",
                ]

            if not required_evidence:
                required_evidence = [
                    "At least one concrete evidence snippet, metric, example, or cited finding."
                ]

            if not preferred_source_types:
                preferred_source_types = [
                    "official or primary source",
                    "credible independent analysis",
                    "technical or academic source when relevant",
                ]

            if not avoid:
                avoid = [
                    "marketing-only claims without evidence",
                    "uncited predictions",
                    "sources that do not directly address this section",
                ]

            sections.append(
                PlannedSection(
                    section_id=section_id,
                    title=title,
                    purpose=purpose,
                    research_questions=research_questions,
                    search_queries=search_queries,
                    required_evidence=required_evidence,
                    preferred_source_types=preferred_source_types,
                    avoid=avoid,
                    target_words=self._safe_int(section_payload.get("target_words"), 0),
                )
            )

        global_questions = self._string_list(
            payload.get("global_research_questions")
            or payload.get("research_questions")
        )

        if not global_questions:
            global_questions = [
                f"What is the strongest evidence-backed answer to the report topic: {job.topic}?",
                "What important uncertainty, risk, or counterargument should the report include?",
            ]

        source_strategy = payload.get("source_strategy")
        if not isinstance(source_strategy, dict):
            source_strategy = {
                "must_have_source_types": ["primary source", "credible secondary source"],
                "freshness_requirement": "Use recent sources when the topic is time-sensitive.",
                "quality_rules": [
                    "Prefer source text that directly supports claims.",
                    "Avoid using citation markers as proof of support.",
                ],
                "excluded_sources": ["thin SEO pages", "uncited marketing pages"],
            }

        return PlanManifest(
            job_id=job.id,
            topic=job.topic,
            report_type=report_type,
            depth=depth.value,
            target_word_count=target_word_count,
            sections=sections,
            global_research_questions=global_questions,
            source_strategy=source_strategy,
            assumptions=self._string_list(payload.get("assumptions")),
            warnings=self._string_list(payload.get("warnings")),
        )

    def _fallback_manifest(self, job: ReportJob) -> PlanManifest:
        """Create a deterministic topic-aware fallback manifest."""
        depth = self._depth_key(job.depth)
        min_sections, _max_sections = DEPTH_SECTION_RANGES[depth]
        target_word_count = DEPTH_WORD_COUNTS[depth]
        report_type = self._enum_value(job.type)

        base_titles = [
            "Executive Summary",
            "Scope, Context, and Definitions",
            "Evidence Landscape",
            "Key Findings and Analysis",
            "Risks, Constraints, and Counterarguments",
            "Recommendations and Decision Implications",
            "Implementation Roadmap",
            "Source Notes and Evidence Gaps",
            "Market or Ecosystem View",
            "Technical Architecture or Operating Model",
            "Evaluation Metrics",
            "Future Outlook",
        ]

        sections: list[PlannedSection] = []
        for index, title in enumerate(base_titles[:min_sections], start=1):
            sections.append(
                PlannedSection(
                    section_id=self._slug(title),
                    title=title,
                    purpose=f"Explain {title.lower()} for the topic '{job.topic}' using only verifiable evidence.",
                    research_questions=[
                        f"What evidence is required to write '{title}' for '{job.topic}'?",
                        f"What risks, limits, or contrary evidence affect '{title}'?",
                    ],
                    search_queries=[
                        f"{job.topic} {title} evidence report",
                        f"{job.topic} {title} data sources",
                    ],
                    required_evidence=[
                        "Concrete cited evidence, not generic explanation.",
                        "At least one source that directly supports the section's main claim.",
                    ],
                    preferred_source_types=[
                        "official or primary source",
                        "credible independent report",
                        "technical documentation or academic source when relevant",
                    ],
                    avoid=[
                        "unsupported claims",
                        "citation-free predictions",
                        "generic filler not tied to the topic",
                    ],
                )
            )

        return PlanManifest(
            job_id=job.id,
            topic=job.topic,
            report_type=report_type,
            depth=depth.value,
            target_word_count=target_word_count,
            sections=sections,
            global_research_questions=[
                f"What recent evidence directly supports the core claims about {job.topic}?",
                f"Which measurable risks or constraints affect a {report_type} report on {job.topic}?",
                f"What contrary or qualifying evidence should prevent overclaiming about {job.topic}?",
            ],
            source_strategy={
                "must_have_source_types": ["primary source", "credible secondary source"],
                "freshness_requirement": "Use recent sources when the topic is time-sensitive; otherwise prefer authoritative durable sources.",
                "quality_rules": [
                    "Every major claim must be traceable to source evidence.",
                    "Prefer primary sources over summaries where possible.",
                    "Avoid marketing-only claims unless clearly labeled as vendor claims.",
                ],
                "excluded_sources": ["thin SEO pages", "uncited blogs", "duplicated scraped pages"],
            },
            warnings=["Fallback manifest used; review section plan before production use."],
            fallback_used=True,
        )

    def _enforce_manifest(self, manifest: PlanManifest, depth: ReportDepth) -> PlanManifest:
        """Enforce depth section ranges and allocate section word budgets."""
        min_sections, max_sections = DEPTH_SECTION_RANGES[depth]
        target_word_count = DEPTH_WORD_COUNTS[depth]

        sections = list(manifest.sections[:max_sections])

        while len(sections) < min_sections:
            index = len(sections) + 1
            title = f"Evidence-Backed Section {index}"
            sections.append(
                PlannedSection(
                    section_id=self._slug(title),
                    title=title,
                    purpose=f"Cover an evidence-backed subtopic required for {manifest.topic}.",
                    research_questions=[
                        f"What evidence is still needed for {manifest.topic} in section {index}?"
                    ],
                    search_queries=[f"{manifest.topic} evidence section {index}"],
                    required_evidence=["Directly cited evidence snippet."],
                    preferred_source_types=["credible source"],
                    avoid=["generic unsupported filler"],
                )
            )
            manifest.warnings.append(
                f"Planner returned too few sections; added '{title}'."
            )

        self._allocate_target_words(sections, target_word_count)

        manifest.sections = sections
        manifest.target_word_count = target_word_count
        return manifest

    @staticmethod
    def _allocate_target_words(sections: list[PlannedSection], total_words: int) -> None:
        """Distribute total word count across sections using simple section weights."""
        if not sections:
            return

        weights: list[float] = []
        for section in sections:
            title = section.title.lower()
            if "executive" in title or "summary" in title:
                weights.append(0.7)
            elif "appendix" in title or "source notes" in title:
                weights.append(0.6)
            elif "analysis" in title or "finding" in title or "technical" in title:
                weights.append(1.25)
            else:
                weights.append(1.0)

        weight_total = sum(weights) or 1.0
        allocated = [max(140, int(total_words * weight / weight_total)) for weight in weights]
        difference = total_words - sum(allocated)

        index = 0
        while difference != 0 and allocated:
            step = 1 if difference > 0 else -1
            if allocated[index] + step >= 120:
                allocated[index] += step
                difference -= step
            index = (index + 1) % len(allocated)

        for section, words in zip(sections, allocated, strict=False):
            section.target_words = words

    @staticmethod
    def _manifest_to_output(manifest: PlanManifest) -> PlannerOutput:
        """Convert rich manifest into existing PlannerOutput schema."""
        outline = [section.title for section in manifest.sections]

        questions: list[str] = []
        questions.extend(manifest.global_research_questions)
        for section in manifest.sections:
            questions.extend(section.research_questions)

        questions = PlannerAgent._dedupe_strings(questions)

        return PlannerOutput(
            outline=outline,
            research_questions=questions,
            target_word_count=manifest.target_word_count,
        )

    @staticmethod
    def _extract_first_json_object(text: str) -> str | None:
        """Extract the first balanced JSON object from model text."""
        start = text.find("{")
        if start < 0:
            return None

        depth = 0
        in_string = False
        escape = False

        for index in range(start, len(text)):
            char = text[index]

            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]

        return None

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        """Normalize unknown model output into a list of non-empty strings."""
        if value is None:
            return []

        if isinstance(value, str):
            value = [value]

        if not isinstance(value, list):
            return [str(value).strip()] if str(value).strip() else []

        items: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = (
                    item.get("question")
                    or item.get("text")
                    or item.get("query")
                    or item.get("name")
                    or item.get("title")
                    or str(item)
                )
            else:
                text = str(item)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                items.append(text)

        return PlannerAgent._dedupe_strings(items)

    @staticmethod
    def _dedupe_strings(items: list[str]) -> list[str]:
        """Deduplicate strings while preserving order."""
        seen: set[str] = set()
        output: list[str] = []
        for item in items:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            output.append(item)
        return output

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        """Convert model value into int with fallback."""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _slug(text: str) -> str:
        """Create a stable slug for section IDs."""
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
        return slug or "section"

    @staticmethod
    def _enum_value(value: Any) -> str:
        """Return enum value or string."""
        return str(getattr(value, "value", value))

    @staticmethod
    def _depth_key(depth: ReportDepth | str) -> ReportDepth:
        """Return ReportDepth enum from enum or string."""
        if isinstance(depth, ReportDepth):
            return depth
        return ReportDepth(str(depth))

    @staticmethod
    def _parse_output(raw_response: str, fallback_job: ReportJob | None = None) -> PlannerOutput:
        """Compatibility parser returning PlannerOutput from rich planner JSON."""
        job = fallback_job or ReportJob(
            id="planning-preview",
            topic="Report",
            type="market_research",
            depth="standard",
            created_at="1970-01-01T00:00:00+00:00",
        )
        agent = PlannerAgent()
        manifest = agent._parse_manifest(raw_response, job)
        if fallback_job is not None:
            manifest = agent._enforce_manifest(manifest, agent._depth_key(job.depth))
        return agent._manifest_to_output(manifest)
