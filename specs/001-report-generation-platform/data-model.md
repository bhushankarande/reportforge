# Data Model: ReportForge Multi-Agent Report Generation Platform

## Enums

### ReportType

- `market_research`
- `company_profile`
- `technical_report`
- `investment_memo`
- `competitive_analysis`
- `policy_brief`
- `literature_review`

### ReportDepth

- `brief`: 2-3 pages
- `standard`: 5-8 pages
- `deep`: 10-15 pages

### JobStatus

- `pending`
- `running`
- `awaiting_approval`
- `completed`
- `failed`
- `cancelled`

### SectionStatus

- `pending`
- `drafting`
- `verifying`
- `needs_revision`
- `approved`
- `failed`

### VerificationStatus

- `SUPPORTED`
- `PARTIALLY_SUPPORTED`
- `UNSUPPORTED`
- `CONTRADICTED`
- `UNVERIFIED`

### SourceType

- `upload_pdf`
- `upload_docx`
- `upload_csv`
- `upload_xlsx`
- `url`
- `mock_search`
- `tavily_search`

## Entities

### BrowserSession

Anonymous session boundary for MVP job isolation.

| Field | Type | Validation |
|-------|------|------------|
| id | str | Stable opaque session id |
| created_at | datetime | Required |
| last_seen_at | datetime | Required |
| active_job_count | int | 0-3 active jobs |

Relationships:

- Owns many `ReportJob` records.

### ReportJob

Single report generation request and lifecycle root.

| Field | Type | Validation |
|-------|------|------------|
| id | str | Unique job id |
| session_id | str | References `BrowserSession.id` |
| topic | str | Non-empty, researchable topic |
| type | ReportType | Required |
| depth | ReportDepth | Required |
| status | JobStatus | Required |
| cost | CostMetrics | Defaults to zero-cost metrics |
| estimated_cost_usd | Decimal | Must respect configured cost guard |
| estimated_kimi_cost_usd | Decimal | Computed for migration planning |
| created_at | datetime | Required |
| completed_at | datetime null | Set when completed |
| failed_at | datetime null | Set when failed |
| failure_reason | str null | Required when failed |
| approval_required | bool | True for Investment Memo, Policy Brief, Deep |
| approved_at | datetime null | Required before export if approval required |
| checkpoint_key | str null | Last completed checkpoint |
| chroma_collection | str | Per-report isolated collection id |

State transitions:

- `pending -> running`
- `running -> awaiting_approval`
- `running -> completed`
- `running -> failed`
- `awaiting_approval -> completed`
- `failed -> running` via retry from checkpoint

### ReportSection

Generated report section with claim, source, and chart links.

| Field | Type | Validation |
|-------|------|------------|
| id | str | Unique section id |
| job_id | str | References `ReportJob.id` |
| title | str | Non-empty |
| content | str | Markdown section body |
| order | int | Positive, unique per job |
| status | SectionStatus | Required |
| sources | list[str] | Source ids used by section |
| claims | list[str] | Claim ids included in section |
| charts | list[str] | Chart artifact ids |
| version | int | Increments on regeneration |
| rolling_summary | str null | Summary for cross-section coherence |

### Source

Uploaded or external evidence source.

| Field | Type | Validation |
|-------|------|------------|
| id | str | Unique source id |
| job_id | str | References `ReportJob.id` |
| type | SourceType | Required |
| title | str | Required when available |
| url | str null | Required for URL/search sources |
| date | date null | Source publication/access date |
| summary | str | Short source summary |
| relevance_score | float | 0.0-1.0 |
| raw_text | str | Extracted text or fetched content |
| citation_key | str | `[AuthorYear]` or `[SourceID]` format |
| metadata | dict | Publisher, author, file info, or fetch metadata |

Relationships:

- Has many `EvidenceChunk` records.
- Supports many `Claim` records through `Claim.source_ids`.

### EvidenceChunk

Retrievable unit of source evidence.

| Field | Type | Validation |
|-------|------|------------|
| id | str | Unique chunk id |
| job_id | str | References `ReportJob.id` |
| source_id | str | References `Source.id` |
| text | str | Non-empty |
| chunk_index | int | Non-negative |
| embedding_id | str null | Vector store reference |
| bm25_terms | list[str] | Tokenized terms |
| relevance_score | float null | Set after retrieval |

### Claim

Auditable statement in a generated report.

| Field | Type | Validation |
|-------|------|------------|
| id | str | Unique claim id |
| section_id | str | References `ReportSection.id` |
| text | str | Non-empty |
| source_ids | list[str] | Required except when `UNVERIFIED` with warning |
| verification_status | VerificationStatus | Required |
| confidence | float | 0.0-1.0 |
| verifier_notes | str null | Required for non-supported states |

Export rules:

- `UNSUPPORTED` blocks export.
- `CONTRADICTED` blocks export.
- `PARTIALLY_SUPPORTED` warns.
- `UNVERIFIED` warns only when no better source exists.

### AgentTrace

Trace for one agent execution step.

| Field | Type | Validation |
|-------|------|------------|
| id | str | Unique trace id |
| job_id | str | References `ReportJob.id` |
| agent_name | str | Planner, Research, DocumentReader, etc. |
| input | str | Serialized input payload |
| output | str | Serialized output payload or error |
| tokens | int | Total tokens |
| cost | Decimal | Actual cost, `$0.00` for free-tier |
| estimated_kimi_cost_usd | Decimal | Computed migration estimate |
| latency | int | Milliseconds |
| timestamp | datetime | Required |
| retry_attempt | int | 0-3 |
| span_id | str | Trace span id |
| parent_span_id | str null | Parent span id |
| status | str | success, retrying, failed |

### CostMetrics

Cost accounting attached to report jobs and model calls.

| Field | Type | Validation |
|-------|------|------------|
| prompt_tokens | int | Non-negative |
| completion_tokens | int | Non-negative |
| total_tokens | int | Sum of prompt and completion |
| estimated_cost_usd | Decimal | Actual provider cost estimate |
| latency_ms | int | Non-negative |
| model_name | str | Provider model name |
| estimated_kimi_cost_usd | Decimal | Kimi migration estimate |

### ChartArtifact

Generated chart or statistical table artifact.

| Field | Type | Validation |
|-------|------|------------|
| id | str | Unique chart id |
| job_id | str | References `ReportJob.id` |
| section_id | str null | Section embedding the chart |
| title | str | Required |
| path | str | Under `storage/charts/` |
| chart_type | str | matplotlib, plotly, table |
| source_ids | list[str] | Evidence sources for chart |
| markdown_base64 | str null | Markdown embed payload |

### ExportArtifact

Generated report deliverable.

| Field | Type | Validation |
|-------|------|------------|
| id | str | Unique artifact id |
| job_id | str | References `ReportJob.id` |
| format | str | markdown, pdf, docx |
| path | str | Under `storage/reports/` |
| created_at | datetime | Required |
| bibliography_included | bool | Must be true |
| verification_snapshot | str | Verification state at export |

## Agent Schemas

Each agent has a Pydantic input/output schema. Required outputs:

- Planner: outline, section list, research questions, approval flags.
- Research: sources, summaries, relevance scores, citation keys.
- Document Reader: parsed sources, chunks, index references.
- Data Analyst: chart artifacts, statistical summaries, source links.
- Report Writer: section drafts, claims, cited source ids.
- Verifier: claim statuses, confidence scores, blocker list, warnings.
- Critic: quality score, specific fixes, section-level recommendations.
- Formatter: export artifact references and bibliography status.
