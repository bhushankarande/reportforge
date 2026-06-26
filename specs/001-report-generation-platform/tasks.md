# Tasks: ReportForge Multi-Agent Report Generation Platform

## Phase 0: LLM Infrastructure & Free-Tier Guardrails (Sequential)

- [x] 0.1 ModelRouter: tools/llm/model_router.py — reads ACTIVE_LLM_PROVIDER, returns correct AgentScope wrapper for gemini/groq/ollama/kimi. Hard-blocks Kimi if MAX_COST_USD_PER_JOB=0.00.
- [x] 0.2 QuotaManager: tools/llm/quota_manager.py — SQLite-backed daily counters. Enforces Gemini 1,500 req/day and Groq 1M tok/day limits. Raises graceful QuotaExceededError.
- [x] 0.3 CostEstimator: tools/llm/cost_estimator.py — computes actual $0.00 for free-tier calls; computes estimated Kimi-equivalent cost for migration planning. Pure pricing logic, no side effects.
- [x] 0.4 Configuration: app/config.py — pydantic-settings with all provider API keys, quotas, cost guards, and ACTIVE_LLM_PROVIDER defaulting to gemini.

## Phase 1: Foundation (Sequential — must complete before any agent work)

- [x] 1.1 Project scaffold: pyproject.toml, .env.example, .gitignore, README with architecture diagram
- [x] 1.2 Pydantic schemas in schemas/: ReportJob, ReportSection, Source, Claim, AgentTrace, CostMetrics, PlannerOutput, WriterInput, WriterOutput, VerifierOutput, CriticOutput, FormatterOutput, JobProgress, CreateJobRequest, CreateJobResponse
- [x] 1.3 Logging: app/logging_config.py with structlog JSON output, agent trace serialization
- [x] 1.4 Database layer: SQLite setup with SQLAlchemy models matching Pydantic schemas, migration stubs
- [x] 1.5 Storage layer: storage/ directory manager with cleanup logic for 7-day retention

## Phase 2: RAG & Document Processing (Depends on 1.5)

- [x] 2.1 Chunking: tools/rag/chunking.py with semantic + fixed overlap strategies
- [x] 2.2 Embeddings: tools/rag/embeddings.py with local sentence-transformers (all-MiniLM-L6-v2 for M1)
- [x] 2.3 Vector store: tools/rag/vector_store.py with ChromaDB per-job collections
- [x] 2.4 BM25: tools/rag/bm25_store.py with rank-bm25 indexing
- [x] 2.5 Hybrid retriever: tools/rag/hybrid_retriever.py combining vector + BM25 with cross-encoder reranking
- [x] 2.6 Reranker: tools/rag/reranker.py with cross-encoder model loading and inference
- [x] 2.7 Document parsers: tools/pdf_reader.py (pymupdf), tools/docx_reader.py (python-docx), tools/csv_reader.py (pandas)
- [x] 2.8 Citation checker: tools/citation_checker.py validating claim-to-source linkage

## Phase 3: Agents (Depends on Phase 2 and 0.1)

- [x] 3.1 Planner Agent: agents/planner_agent.py — topic → PlannerOutput (Gemini Flash free tier) [P]
- [x] 3.2 Research Agent: agents/research_agent.py — mock search → ResearchOutput (Gemini Flash free tier) [P]
- [x] 3.3 Document Reader Agent: agents/document_reader_agent.py — files → DocumentReaderOutput [P]
- [x] 3.4 Data Analyst Agent: agents/data_analyst_agent.py — CSV → charts + insights [P]
- [x] 3.5 Report Writer Agent: agents/writer_agent.py — WriterInput → WriterOutput (Gemini Flash, section-by-section)
- [x] 3.6 Verifier Agent: agents/verifier_agent.py — claims → VerifierOutput (Gemini Flash free tier)
- [x] 3.7 Critic Agent: agents/critic_agent.py — full report → CriticOutput (Gemini Flash free tier)
- [x] 3.8 Formatter Agent: agents/formatter_agent.py — sections → Markdown/PDF/DOCX

## Phase 4: Orchestration (Depends on Phase 3 — pipeline coordination only)

- [x] 4.1 Live pipeline state: orchestration/job_manager.py — JobManager owns lifecycle, progress, retry, and persistence handoff
- [x] 4.2 Persistence rehydration: app/services/report_store.py — reload jobs, sections, sources, traces, URLs, and provider choices
- [x] 4.3 Cost tracking wrapper: orchestration/cost_tracking.py — CostTrackingModel decorator for AgentScope. Calls tools/llm/cost_estimator.py for math. Logs $0.00 actual + Kimi estimate.
- [x] 4.4 ReportPipeline: orchestration/job_manager.py — single live Planner -> Evidence/RAG -> Writer -> Verifier -> Critic sequence
- [x] 4.5 HITL logic: orchestration/hitl.py — pause/resume for human approval
- [x] 4.6 Job manager: orchestration/job_manager.py — queue, status updates, progress streaming

## Phase 5: API & Frontend (Depends on Phase 4)

- [x] 5.1 FastAPI app: app/main.py with lifespan events, dependency injection, CORS
- [x] 5.2 Job endpoints: app/routers/jobs.py — POST /jobs, GET /jobs/{id}, GET /jobs/{id}/progress
- [x] 5.3 Section endpoints: app/routers/sections.py — regenerate, approve, retry
- [x] 5.4 Export endpoints: app/routers/export.py — PDF/DOCX/Markdown streaming
- [x] 5.5 Cost endpoints: app/routers/costs.py — summary dashboard showing free-tier $0.00 + Kimi migration estimate
- [x] 5.6 Streamlit frontend: frontend/streamlit_app.py — upload, progress, source panel, export, provider selector (Gemini/Groq/Ollama)

## Phase 6: Production Hardening

- [x] 6.1 Ollama setup script: scripts/setup_ollama.sh — pulls llama3.1:8b for local testing
- [x] 6.2 Dockerfile with multi-stage build for linux/arm64
- [x] 6.3 docker-compose.yml with SQLite volume mounts, Chroma persistence, optional Ollama sidecar
- [x] 6.4 Unit tests: tests/test_*.py covering every agent and tool with mocked LLM calls (mock Gemini responses)
- [x] 6.5 Retry logic: tenacity decorators on all external API calls
- [x] 6.6 Response caching: diskcache for repeated retrievals and LLM prompts
- [x] 6.7 Evaluation suite: evaluation/report_quality_eval.py, evaluation/citation_eval.py
- [x] 6.8 End-to-end test: one full report generation from topic to PDF using Gemini Flash
- [x] 6.9 Provider swap test: verify changing ACTIVE_LLM_PROVIDER env var switches models without code changes
