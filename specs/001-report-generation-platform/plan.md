# Implementation Plan: ReportForge Multi-Agent Report Generation Platform

**Branch**: `002-report-generation-platform` | **Date**: 2026-05-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-report-generation-platform/spec.md`

## Summary

Build ReportForge as a local-first web platform for citation-grounded business
report generation. Users submit a topic, choose report type and depth, optionally
attach documents or URLs, and receive a verified report with source panel,
progress tracking, cost dashboard, section regeneration, and Markdown/PDF/DOCX
exports. The MVP uses FastAPI, Streamlit, AgentScope, SQLite, per-report Chroma
collections, mock search with optional Tavily, and zero-cost LLM routing through
NVIDIA NIM/Groq/Ollama.

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: FastAPI, Pydantic v2, pydantic-settings, Streamlit,
AgentScope, ChromaDB, rank-bm25, sentence-transformers, pymupdf, python-docx,
pandas, openpyxl, unstructured fallback, matplotlib, plotly, Jinja2, WeasyPrint,
structlog, tenacity, pytest, ruff

**Storage**: SQLite for job state, sections, sources, traces, cost metrics, and
artifact metadata. Local `storage/` for uploads, reports, charts, per-report
indexes, and LLM logs. Docker Compose includes a Postgres service profile/path
for V2 migration but MVP persistence remains SQLite.

**Testing**: pytest with mandatory tests for every agent and tool; contract tests
for FastAPI endpoints; integration tests for export gates, persistence,
session isolation, and retry recovery.

**Target Platform**: Local M1 Mac through Docker Compose with `linux/arm64`
support; direct local Python/uv development remains supported.

**Project Type**: Web platform with FastAPI backend, Streamlit Phase 1 frontend,
multi-agent workflow engine, local retrieval pipeline, and export tooling.

**Performance Goals**: Standard report with one uploaded document and at least
five sources completes in under 15 minutes locally; progress status is visible
within 5 seconds; section regeneration modifies only the selected section in 99%
of attempts; failed jobs preserve retryable partial state after 3 retries.

**Constraints**: No paid LLM provider is wired into the MVP. No prompt may exceed
180K tokens despite model context claims. Long
reports generate section by section with rolling summaries. Up to three active
jobs per anonymous browser session. Report-scoped uploads and indexes are
cleaned up after 7 days unless saved/exported.

**Scale/Scope**: MVP supports anonymous browser sessions, three active jobs per
session, per-report isolated Chroma collections, mock search by default,
optional Tavily search via env var, and BackgroundTasks for job execution. V2
adds Next.js, API key auth, Celery, Redis, and real search.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Hexagonal boundaries: PASS. Business logic is under `agents/` and `tools/`.
  Framework adapters are under `app/` and `frontend/`. `orchestration/` owns
  only live workflow coordination, job lifecycle, retry, and HITL flow.
- Agent contracts: PASS. Each agent has a discrete module in `agents/` and
  Pydantic input/output schemas in `schemas/agent_outputs.py` or related schema
  modules. Agents do not call other agents directly.
- Model abstraction: PASS. `ModelRouter` and `CostTrackingModel` live under
  `tools/llm/`; agents depend on abstractions only and do not import
  provider-specific clients.
- Cost and trace logging: PASS. Every model call records token count, actual
  cost, latency, provider, model, prompt metadata, and raw response to
  `storage/` plus SQLite trace tables.
- Report integrity: PASS. Claims carry `source_ids`; `UNSUPPORTED` and
  `CONTRADICTED` claims block export; `PARTIALLY_SUPPORTED` and eligible
  `UNVERIFIED` claims warn.
- Retrieval/parsing/export: PASS. RAG components live under `tools/rag/` and use
  Chroma + BM25 + cross-encoder reranking. Parsing is under `tools/parsing/`.
  Markdown/PDF/DOCX exports use Jinja2 templates under `templates/`.
- Operations: PASS. External API calls use tenacity retries with exponential
  backoff. Docker Compose targets local M1 Mac with `linux/arm64`.
- Context and idempotency: PASS. The live pipeline has explicit retry behavior
  and enforces 180K prompt cap with rolling summaries.
- Typing and tests: PASS. Type hints are mandatory. `Any` in signatures requires
  justification. Every agent and tool receives corresponding tests.

## Project Structure

### Documentation (this feature)

```text
specs/001-report-generation-platform/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── openapi.yaml
└── tasks.md
```

### Source Code (repository root)

```text
agents/
├── planner.py
├── research.py
├── document_reader.py
├── data_analyst.py
├── report_writer.py
├── verifier.py
├── critic.py
└── formatter.py

app/
├── main.py
├── dependencies.py
├── routes/
│   ├── jobs.py
│   ├── exports.py
│   ├── costs.py
│   └── traces.py
└── services/
    └── background.py

frontend/
└── streamlit_app.py

orchestration/
├── job_manager.py
├── cost_tracking.py
└── hitl.py

schemas/
├── reports.py
├── sources.py
├── claims.py
├── agent_outputs.py
├── costs.py
└── api.py

tools/
├── llm/
│   ├── model_router.py
│   ├── cost_tracking.py
│   ├── providers.py
│   └── quotas.py
├── search/
│   ├── mock_search.py
│   └── tavily_search.py
├── parsing/
│   ├── pdf.py
│   ├── docx.py
│   ├── tabular.py
│   └── fallback.py
├── rag/
│   ├── chunking.py
│   ├── embeddings.py
│   ├── vector_store.py
│   ├── bm25_store.py
│   ├── hybrid_retriever.py
│   └── reranker.py
├── citations/
│   └── checker.py
├── charts/
│   └── generation.py
├── export/
│   ├── markdown.py
│   ├── pdf.py
│   └── docx.py
└── cleanup/
    └── retention.py

evaluation/
├── report_quality.py
├── citation_eval.py
└── regression.py

templates/
├── report.md.j2
├── report.html.j2
└── report.docx.j2

storage/
├── uploads/
├── reports/
├── charts/
├── indexes/
└── llm_logs/

tests/
├── agents/
├── tools/
├── contract/
├── integration/
└── unit/

docker-compose.yml
Dockerfile
```

**Structure Decision**: Use constitution-aligned hexagonal boundaries. The user
requested a top-level `rag/` and `ModelRouter` in `orchestration/`, but the
approved resolution places retrieval under `tools/rag/` and model routing under
`tools/llm/`. `orchestration/` calls these capabilities but does not own them.

## Phase 0: Research Decisions

See [research.md](./research.md). All plan inputs are resolved; no `NEEDS
CLARIFICATION` items remain.

## Phase 1: Design Artifacts

- Data model: [data-model.md](./data-model.md)
- API contract: [contracts/openapi.yaml](./contracts/openapi.yaml)
- Quickstart: [quickstart.md](./quickstart.md)

## Post-Design Constitution Check

- Hexagonal boundaries: PASS after replacing top-level `rag/` with `tools/rag/`
  and placing `ModelRouter` under `tools/llm/`.
- Agent contracts: PASS. Planned modules include schema ownership and test
  coverage requirements.
- Model abstraction and cost tracking: PASS. Planned zero-cost routing honors
  `ACTIVE_LLM_PROVIDER` and the zero-cost provider set.
- Source-grounding: PASS. Claim status and export gates are explicit.
- RAG/parsing/export discipline: PASS. RAG, parsing, and export locations match
  the constitution.
- Operations/idempotency/retries: PASS. Checkpoints, retries, failure state, and
  retry endpoint are included.
- Docker-first: PASS. Docker Compose with M1 `linux/arm64` and Postgres
  migration profile is planned.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | N/A | N/A |
