# ReportForge Rewrite Plan

Updated after Phase 9 cleanup.

## Current Source Of Truth

Read the live system in this order:

1. `app/main.py`
2. `app/routers/jobs.py`
3. `app/routers/sections.py`
4. `app/routers/export.py`
5. `app/services/job_registry.py`
6. `orchestration/job_manager.py`
7. `tools/rag/evidence_pipeline.py`
8. `agents/planner_agent.py`
9. `agents/research_agent.py`
10. `agents/document_reader_agent.py`
11. `agents/writer_agent.py`
12. `agents/verifier_agent.py`
13. `agents/critic_agent.py`
14. `agents/formatter_agent.py`
15. `frontend/streamlit_app.py`

The `specs/001-report-generation-platform/` directory is a product brief and
historical planning artifact. It is not the implementation source of truth.

## Live Pipeline

```text
Streamlit
  -> POST /jobs
  -> app.routers.jobs.create_job
  -> app.services.job_registry.manager
  -> JobManager.create_job
  -> FastAPI BackgroundTasks
  -> JobManager.execute
  -> JobManager.run_job
  -> ReportPipeline.run
```

The live agent sequence is:

```text
Planner -> Evidence/RAG -> Writer -> Verifier -> Critic
```

Runtime details:

- `JobManager` owns lifecycle, progress, retry, approval, section mutation, and
  persistence handoff.
- `ReportPipeline` owns the agent sequence.
- URL research is normalized into `Source` records by `ResearchAgent`.
- Uploads are sent to `POST /jobs/{job_id}/uploads` and normalized by
  `UploadService` plus `DocumentReaderAgent`.
- Evidence chunks and retrieval are internal to `tools/rag/evidence_pipeline.py`
  and `tools/rag/hybrid_retriever.py`.
- SQLite persistence is handled by `app/services/report_store.py` for jobs,
  inputs, sections, sources, and traces.
- Retry is an explicit full pipeline rerun, not a checkpoint resume.

## Export Path

There is one live export path:

```text
GET /jobs/{job_id}/export/{format}
  -> app.routers.export.export_report
  -> FormatterAgent.export_artifact
  -> FormatterAgent.format_report
  -> tools.export.report.render_report_markdown
  -> tools.export.pdf.write_pdf / tools.export.docx.write_docx when requested
```

Export is blocked unless the job is completed. Claims marked `UNSUPPORTED` or
`CONTRADICTED` block export through `tools.export.report.assert_report_exportable`.

## Live Components

| Area | Current owner |
| --- | --- |
| API surface | `app/routers/*` |
| Job lifecycle | `orchestration/job_manager.py` |
| Pipeline sequence | `ReportPipeline` in `orchestration/job_manager.py` |
| Persistence | `app/services/report_store.py` |
| URL evidence | `agents/research_agent.py` |
| Uploaded-file evidence | `app/services/uploads.py`, `agents/document_reader_agent.py` |
| Retrieval | `tools/rag/evidence_pipeline.py`, `tools/rag/hybrid_retriever.py` |
| Writing | `agents/writer_agent.py` |
| Verification | `agents/verifier_agent.py` |
| Critique | `agents/critic_agent.py` |
| Exports | `agents/formatter_agent.py`, `tools/export/report.py` |
| Streamlit UI | `frontend/streamlit_app.py` |

## Removed During Cleanup

The following were removed because call-site search showed they were not used by
the FastAPI routes, `JobManager`, export route, or frontend:

- `orchestration/workflow.py`
- `orchestration/checkpoints.py`
- `orchestration/state.py`
- `app/dependencies.py`
- `tests/integration/test_workflow.py`
- stale docs that described the removed alternate workflow

The duplicate `JobManager.export_markdown` helper was also removed. Markdown,
PDF, and DOCX exports now share the formatter/export policy path.

## Remaining Latent Components

These are intentionally kept because they still have tests or support live
capabilities:

- `DataAnalystAgent` and chart helpers are not in the main report pipeline, but
  remain tested export-adjacent tooling.
- `tools/search/tavily_search.py` remains an optional search adapter, but URL
  research currently uses normalized direct URL evidence.
- `tools/cleanup/retention.py` remains an ops helper, not a runtime dependency.
- `tools/export/markdown.py`, `pdf.py`, and `docx.py` are format writers used by
  the single export path.

## Risks

- Upload timing: the UI sends files to the backend after job creation. If a job
  starts immediately, uploaded sources may not influence the first generation
  pass without a future backend sequencing change.
- Retry semantics: retry is a full rerun. There is no remaining checkpoint
  resume implementation.
- Spec drift: older files under `specs/` still describe the larger intended
  product. Treat them as requirements history until they are rewritten.
- Cost safety: zero-spend defaults still matter. Do not enable paid provider
  behavior without explicit approval.

## Test Strategy

Keep these checks as the rewrite safety net:

- API contract tests for job creation, progress, uploads, sources, sections,
  approval, retry, and export errors.
- Orchestration tests for failed jobs, retry, rehydration, and the live
  `Planner -> Evidence/RAG -> Writer -> Verifier -> Critic` sequence.
- Persistence tests proving jobs, sections, sources, traces, URLs, and provider
  choices can be loaded again.
- Evidence tests for URL normalization, uploaded documents, indexing, and
  retrieval.
- Export tests proving all formats share blocker checks.
- Frontend tests for job submit payloads, URL parsing, and multipart uploads.

Fast verification:

```bash
uv run ruff check .
uv run pytest -q
```
