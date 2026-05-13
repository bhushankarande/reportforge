<!--
Sync Impact Report
Version change: template -> 1.0.0
Modified principles:
- Template placeholders -> I. Hexagonal Agent Boundaries
- Template placeholders -> II. Provider-Neutral LLM Access and Cost Traceability
- Template placeholders -> III. Source-Grounded Report Integrity
- Template placeholders -> IV. Retrieval, Parsing, and Export Discipline
- Template placeholders -> V. Replayable, Tested, Docker-First Delivery
Added sections:
- Platform Architecture and Technology Constraints
- Development Workflow and Quality Gates
Removed sections:
- None
Templates requiring updates:
- .specify/templates/plan-template.md: updated
- .specify/templates/spec-template.md: updated
- .specify/templates/tasks-template.md: updated
Follow-up TODOs:
- None
-->

# ReportForge Constitution

## Core Principles

### I. Hexagonal Agent Boundaries
ReportForge MUST keep business logic in `agents/` and `tools/`, with framework
adapters in `app/` and `frontend/`. Every agent MUST be a discrete Python module
under `agents/` with explicit Pydantic v2 input and output schemas. Agent logic
MUST NOT live in `orchestration/`, and agents MUST NOT call other agents
directly. All multi-agent coordination MUST flow through
`orchestration/workflow.py` using AgentScope pipelines.

Rationale: discrete agent modules with typed contracts make behavior auditable,
replaceable, and testable while preserving a clean hexagonal architecture.

### II. Provider-Neutral LLM Access and Cost Traceability
All agents MUST use a `ModelRouter` abstraction that reads
`ACTIVE_LLM_PROVIDER` from pydantic-settings loaded from `.env`. Agents MUST NOT
import provider-specific clients directly. The router MUST support provider
switching among `gemini`, `groq`, `ollama`, and `kimi` without code changes.
Gemini 1.5 Flash is the default testing model, and the architecture MUST allow
Kimi K2.6 to be selected by environment variable only.

Every LLM call MUST pass through a mandatory `CostTrackingModel` wrapper. Each
call MUST be logged under `storage/` with token count, estimated cost, latency,
provider, model name, prompt metadata, and raw response. Free-tier testing MUST
record `$0.00` cost while still preserving token usage for future Kimi cost
estimation.

Rationale: provider isolation and complete LLM telemetry keep development
zero-cost today while preserving production cost governance.

### III. Source-Grounded Report Integrity
Every claim in a generated report MUST carry a `source_id`. Claims without
sources MUST block verification and export. Agent outputs MUST be versioned and
stored in SQLite for traceability, including schema version, input reference,
output payload, checkpoint state, and execution metadata.

Rationale: ReportForge is a report generation platform; provenance is a product
requirement, not an optional quality improvement.

### IV. Retrieval, Parsing, and Export Discipline
The RAG pipeline MUST use hybrid retrieval: Chroma vector search plus BM25
keyword search, followed by cross-encoder reranking. PDF, DOCX, and CSV parsing
MUST happen in `tools/` and MUST NOT be embedded inside agent logic. Markdown,
PDF, and DOCX report exports MUST be rendered through Jinja2 templates stored
under `templates/`.

Rationale: retrieval quality, parsing isolation, and template-based exports keep
report generation explainable, testable, and reusable across interfaces.

### V. Replayable, Tested, Docker-First Delivery
Every agent call MUST be idempotent and replay-safe. Implementations MUST check
checkpoint state before executing side-effecting work. No single prompt may
exceed 180K tokens; workflows MUST use rolling summaries for cross-section
coherence when context grows.

All external API calls MUST use tenacity retry with exponential backoff.
Failures MUST be traced and surfaced, not swallowed. Type hints are mandatory
throughout the codebase, and `Any` MUST NOT appear in function signatures unless
a comment justifies why it is unavoidable. Every tool and agent MUST have a
corresponding test file under `tests/`. Every service MUST run through
`docker-compose.yml` on M1 Mac using `linux/arm64`.

Rationale: reproducible execution, complete tests, and Docker-first operation
are required for a production multi-agent platform.

## Platform Architecture and Technology Constraints

ReportForge uses Python 3.11 with FastAPI, Streamlit, AgentScope, ChromaDB,
SQLite, Pydantic v2, pydantic-settings, Jinja2, and tenacity. The repository
MUST preserve the following ownership boundaries:

- `agents/`: business-capability agents and their Pydantic input/output schemas.
- `tools/`: parsing, retrieval, storage, export, and integration utilities.
- `orchestration/`: AgentScope pipeline assembly and workflow coordination only.
- `app/`: FastAPI adapters, dependency injection, and HTTP concerns.
- `frontend/`: Streamlit UI and user-facing interaction code.
- `templates/`: Jinja2 templates for Markdown, PDF, and DOCX exports.
- `storage/`: local runtime logs, checkpoints, and generated artifacts; ignored
  by Git.

API keys and provider configuration MUST NOT be hardcoded. Configuration MUST be
loaded through pydantic-settings from `.env`, and `.env` MUST remain ignored by
Git.

## Development Workflow and Quality Gates

Specification, planning, task generation, and implementation MUST check this
constitution before proceeding. A feature plan MUST explicitly describe:

- agent modules and Pydantic schemas affected;
- ModelRouter and CostTrackingModel behavior for all LLM calls;
- source provenance and verification gates for report claims;
- hybrid retrieval, reranking, parsing, and export paths when applicable;
- SQLite versioning and checkpoint strategy;
- Docker Compose service impact for `linux/arm64`;
- tests for every changed agent and tool.

Implementation is blocked when any new agent lacks schemas, any agent imports a
provider-specific model client, any report claim can be emitted without
`source_id`, any external API call lacks retry tracing, or any changed agent/tool
lacks tests.

## Governance

This constitution supersedes conflicting implementation habits, templates, and
ad hoc instructions. Amendments MUST be recorded in this file with a Sync Impact
Report, semantic version update, and ISO-formatted amendment date. Changes that
remove or redefine core principles require a MAJOR version bump. New principles,
mandatory constraints, or quality gates require a MINOR version bump. Editorial
clarifications require a PATCH version bump.

Every feature plan, task list, and implementation review MUST verify compliance
with the Core Principles. Violations are allowed only when documented in the
feature plan's Complexity Tracking section with a concrete rationale and a
simpler alternative that was rejected.

**Version**: 1.0.0 | **Ratified**: 2026-05-13 | **Last Amended**: 2026-05-13
