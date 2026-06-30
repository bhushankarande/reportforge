# Phase 0 Research: ReportForge Multi-Agent Report Generation Platform

## Decision: FastAPI Backend with Async Endpoints and Dependency Injection

Rationale: FastAPI matches the Python 3.11 stack, supports Pydantic v2 request
and response schemas, works with BackgroundTasks for MVP async job execution,
and provides OpenAPI contracts for frontend and tests.

Alternatives considered: Flask was simpler but weaker for typed contracts.
Django was heavier than needed for a local-first MVP.

## Decision: Streamlit Phase 1 Frontend, Next.js Phase 3

Rationale: Streamlit gives a fast local UI for topic input, uploads, progress,
source panel, cost dashboard, and exports. Next.js is deferred until product
flows stabilize.

Alternatives considered: Building Next.js first would slow iteration and add
auth/session complexity before the report workflow is validated.

## Decision: AgentScope for Orchestration

Rationale: AgentScope is assigned for multi-agent orchestration, conversation,
ReAct loops, handoffs, and graph-like workflow coordination. It belongs in
`orchestration/` with pipeline assembly and durable job execution.

Alternatives considered: Hand-rolled orchestration was rejected because the
constitution requires AgentScope pipelines.

## Decision: Zero-Cost ModelRouter for Testing

Rationale: `ModelRouter` reads `ACTIVE_LLM_PROVIDER`. NVIDIA NIM DeepSeek is the
default provider. Groq Qwen3-32B is the fallback for prompt iteration. Ollama
supports offline unit testing.

Alternatives considered: Direct provider imports in agents violate the
constitution.

## Decision: CostTrackingModel Wrapper

Rationale: Every LLM call records actual cost, tokens, latency, provider, model,
prompt metadata, and raw response. Free-tier calls record `$0.00` actual cost.

Alternatives considered: Logging only aggregate job cost was rejected because
debugging, compliance, and provider migration require call-level traces.

## Decision: SQLite MVP with Postgres Migration Path

Rationale: SQLite is sufficient for local MVP job state, sections, sources,
traces, and cost metrics. Docker Compose includes a Postgres profile/path for
migration without forcing early operational complexity.

Alternatives considered: Starting on Postgres adds setup cost for local testing.
File-only persistence is not adequate for traceability and replay.

## Decision: Per-Report Chroma Collections plus BM25 and Reranking

Rationale: Each report job gets an isolated Chroma collection to prevent state
leakage. BM25 via rank-bm25 complements vector retrieval. Cross-encoder
reranking improves evidence quality before writing and verification.

Alternatives considered: A shared vector collection risks cross-session leakage.
Vector-only retrieval misses keyword-specific evidence.

## Decision: Mock Search by Default with Optional Tavily

Rationale: Mock search keeps MVP testing deterministic and zero-cost. Tavily can
be enabled by environment variable for richer external research without changing
agent code. Real search is deferred to V2.

Alternatives considered: Real search by default adds quota, cost, network, and
reproducibility risks.

## Decision: Document Parsing in Tools

Rationale: pymupdf, python-docx, pandas/openpyxl, and unstructured fallback live
under `tools/parsing/`, keeping agent modules focused on reasoning with parsed
evidence rather than file-format handling.

Alternatives considered: Parser logic inside agents violates the constitution
and makes tests harder to isolate.

## Decision: Section-by-Section Generation with Rolling Summaries

Rationale: Long reports must never stuff the full report into one prompt. The
workflow enforces a 180K token prompt cap, generates section by section, and uses
rolling summaries for cross-section coherence.

Alternatives considered: Full-report generation is simpler but violates the
constitution and fails on long reports.

## Decision: Verification Status Export Gates

Rationale: `UNSUPPORTED` and `CONTRADICTED` claims block export. `PARTIALLY_SUPPORTED`
warns. `UNVERIFIED` is allowed with warning only when no better source exists.
This satisfies strict provenance while preserving user review paths.

Alternatives considered: Blocking every low-confidence claim would make exports
too brittle. Allowing unsupported claims would violate the constitution.

## Decision: Chart Generation with Matplotlib and Plotly

Rationale: Matplotlib covers static export-friendly charts, while Plotly supports
interactive Streamlit exploration. Charts are saved to `storage/charts/`,
embedded as base64 in Markdown, and referenced as files in PDF/DOCX.

Alternatives considered: Plotly-only outputs are less reliable for document
exports. Matplotlib-only loses useful frontend interactivity.

## Decision: BackgroundTasks MVP, Celery and Redis V2

Rationale: FastAPI BackgroundTasks are sufficient for local MVP job execution.
Celery and Redis are deferred to V2 for production-grade distributed execution.

Alternatives considered: Celery in MVP adds operational moving parts before the
workflow is validated.

## Decision: Structlog plus Custom Span-Like Agent Traces

Rationale: structlog provides JSON logs, while custom OpenTelemetry-style spans
in SQLite give agent-level traceability without requiring a full telemetry
backend in local MVP.

Alternatives considered: Plain text logs are insufficient for debugging and cost
analysis. Full OpenTelemetry infrastructure is too heavy for Phase 1.

## Decision: Docker Compose on M1 Mac with linux/arm64

Rationale: Docker Compose gives reproducible local services and aligns with the
constitution. Services must run on M1 Mac with `linux/arm64` support.

Alternatives considered: Host-only execution remains useful for development but
does not satisfy Docker-first governance.
