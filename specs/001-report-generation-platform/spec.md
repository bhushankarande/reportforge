# Feature Specification: ReportForge Multi-Agent Report Generation Platform

**Feature Branch**: `002-report-generation-platform`

**Created**: 2026-05-13

**Status**: Draft

**Input**: User description: "Build ReportForge: a web platform where a user submits a research topic and optional documents (PDF, DOCX, CSV, URLs). The system generates a structured, citation-grounded business report through multi-agent collaboration."

## Clarifications

### Session 2026-05-13

- Q: What user/session model should isolate concurrent report jobs? → A: Anonymous browser sessions; each session owns isolated report jobs.
- Q: How strict should source confidence be before export? → A: Export is blocked for unsourced claims; low-confidence sourced claims show warnings.
- Q: How long should uploaded documents and generated artifacts be retained? → A: Retain during the anonymous session; users explicitly save or export final artifacts.
- Q: How many report jobs may run concurrently per anonymous session? → A: Up to three active report jobs per anonymous session.
- Q: Which report jobs require a human review gate before final export? → A: Investment Memo, Policy Brief, and all Deep reports require review.

Additional resolutions provided by the user:

- MVP research uses mock search by default, with optional Tavily integration
  enabled by environment variable; real web search is deferred to V2.
- Uploaded files and indexes are scoped per report and cleaned up after 7 days
  by a scheduler when not explicitly saved or exported.
- Long report generation runs section by section with rolling summaries; the
  system never places the full report into one prompt, and no prompt may exceed
  180K tokens.
- Verification outcomes use four claim states: `SUPPORTED`,
  `PARTIALLY_SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED`, plus `UNVERIFIED` when
  no better source exists. Export is blocked on `UNSUPPORTED` or
  `CONTRADICTED`, warns on `PARTIALLY_SUPPORTED`, and allows `UNVERIFIED` with
  warning when no better source exists.
- Chart generation uses matplotlib and plotly. Charts are saved under
  `storage/charts/`, embedded as base64 in Markdown, and referenced as files in
  PDF and DOCX exports.
- MVP concurrency uses FastAPI BackgroundTasks; V2 adds Celery and Redis. Each
  report job gets an isolated Chroma collection.
- Citations use bracket keys such as `[AuthorYear]` or `[SourceID]`, with a full
  bibliography in the appendix.
- If an agent fails after 3 retries, the job is marked `FAILED`, partial output
  is stored, the user is notified, and manual retry reruns the live pipeline.
- MVP authentication is anonymous. V2 adds optional API key authentication.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate a Cited Business Report (Priority: P1)

A user enters a research topic, selects a report type and depth, optionally adds
documents or URLs, starts report generation, watches progress, reviews a
citation-grounded report, and exports the final result.

**Why this priority**: This is the core product journey and provides the minimum
useful ReportForge outcome.

**Independent Test**: A user can generate a Standard Market Research report from
a topic plus one uploaded document, confirm every claim is linked to a source,
preview the report, and export it.

**Acceptance Scenarios**:

1. **Given** a user has entered a topic and selected report type and depth,
   **When** they start generation, **Then** the system creates a structured
   outline, researches sources, drafts sections, verifies claim coverage, and
   presents a report preview.
2. **Given** the generated report contains claims, **When** the user opens the
   source panel, **Then** each claim shows a linked source and confidence score.
3. **Given** verification finds an unsourced claim, **When** the report reaches
   review, **Then** the system blocks final export and shows the unresolved
   source issue.

---

### User Story 2 - Ingest User Documents and URLs (Priority: P2)

A user uploads PDF, DOCX, CSV, XLSX, and URL-list inputs so the generated report
can use both user-provided material and external research.

**Why this priority**: User-provided evidence is essential for company profiles,
investment memos, technical reports, literature reviews, and data-driven
analysis.

**Independent Test**: A user can upload one file of each supported type and a
URL list, then see those sources available in the report's source panel after
generation.

**Acceptance Scenarios**:

1. **Given** a user uploads supported files, **When** generation begins, **Then**
   the system extracts readable content, indexes it for retrieval, and records
   source metadata.
2. **Given** a spreadsheet contains numeric data, **When** the report requires
   data analysis, **Then** the system produces relevant charts or tables with
   source references.
3. **Given** an uploaded file cannot be read, **When** ingestion runs, **Then**
   the user sees a clear warning and the remaining usable inputs continue.

---

### User Story 3 - Track Progress, Cost, and Agent Activity (Priority: P3)

A user monitors report generation through live progress, current step, active
agent, estimated token usage, and actual token usage after completion.

**Why this priority**: Long-running report jobs need transparency so users know
what is happening, whether the job is healthy, and what usage was incurred.

**Independent Test**: During report generation, the user can observe progress
moving across planning, research, ingestion, writing, verification, critique,
formatting, and final review, then inspect estimated and actual token usage.

**Acceptance Scenarios**:

1. **Given** a report job is running, **When** the user views the progress
   tracker, **Then** it shows the current active agent and running step.
2. **Given** a report job completes, **When** the user opens the cost dashboard,
   **Then** it shows estimated and actual token usage by report job.
3. **Given** a job fails and is resumed, **When** progress continues, **Then**
   completed steps are not repeated and the user can see the recovered state.

---

### User Story 4 - Regenerate a Single Section (Priority: P4)

A user requests a rewrite of only one report section while preserving the rest
of the report, its source grounding, and its approved outline.

**Why this priority**: Section-level iteration makes the platform practical for
editing without paying the time or token cost of full report regeneration.

**Independent Test**: A user can select one section, request a rewrite, and
confirm that only that section changes while source links and confidence scores
remain present.

**Acceptance Scenarios**:

1. **Given** a completed report, **When** the user asks to regenerate one
   section, **Then** only that section is rewritten and reverified.
2. **Given** the rewritten section includes unsupported claims, **When**
   verification runs, **Then** those claims block replacement until fixed.

---

### User Story 5 - Review Gated Reports Before Export (Priority: P5)

A user receives an explicit review gate before final export for reports that may
affect financial or policy decisions, plus any report generated at Deep depth.

**Why this priority**: High-stakes outputs require human review before they are
packaged as final deliverables.

**Independent Test**: A user generating an Investment Memo, Policy Brief, or
Deep report sees a final review gate and cannot export until they approve
or request fixes.

**Acceptance Scenarios**:

1. **Given** an Investment Memo, Policy Brief, or Deep report is generated,
   **When** generation reaches final review, **Then** the system requires human
   approval before export.
2. **Given** the user requests fixes at the review gate, **When** revisions run,
   **Then** the report returns to review with updated verification results.

### Edge Cases

- Empty or overly broad topics are rejected with guidance to make the topic
  researchable.
- Unsupported files are rejected before generation while supported files remain
  available.
- Duplicate uploads or repeated URLs are deduplicated without losing source
  traceability.
- External sources may be unavailable, rate-limited, low quality, missing
  metadata, or unavailable because the MVP is running with mock search instead
  of an optional search provider.
- Large document sets may exceed available context and require summarized
  intermediate evidence.
- CSV or XLSX files may contain missing values, mixed data types, or no useful
  numeric columns.
- Concurrent report jobs from different sessions must not share sources, costs,
  or generated sections.
- A session that already has three active report jobs must queue or reject new
  job starts with a clear message.
- Browser refresh, server restart, or process crash must not discard completed
  report steps.
- If an agent fails after 3 retries, the job is marked `FAILED`, partial output
  is preserved, the user is notified, and manual retry reruns the live pipeline.
- Session expiration or user-initiated clearing removes session-retained uploads,
  intermediate artifacts, and generated outputs that were not explicitly
  exported or saved.
- Export is blocked when verification finds unsourced claims or unresolved
  hallucination flags.
- Human review gates for Investment Memo, Policy Brief, and Deep reports
  must be visible and cannot be bypassed by a normal export action.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow users to submit a research topic.
- **FR-002**: System MUST allow users to choose a report type from Market
  Research, Company Profile, Technical Report, Investment Memo, Competitive
  Analysis, Policy Brief, and Literature Review.
- **FR-003**: System MUST allow users to choose report depth from Brief (2-3
  pages), Standard (5-8 pages), and Deep (10-15 pages).
- **FR-004**: System MUST allow users to upload PDF, DOCX, CSV, XLSX, and URL
  list inputs for a report job.
- **FR-005**: System MUST validate uploaded inputs and clearly report files or
  URLs that cannot be used.
- **FR-006**: System MUST create a report outline with research questions before
  drafting report content.
- **FR-007**: System MUST collect external web sources with metadata and
  relevance scores.
- **FR-007a**: System MUST use mock search by default for MVP research and MUST
  support optional Tavily-backed search when enabled by environment variable.
- **FR-008**: System MUST extract, chunk, and index uploaded document content so
  it can be used as report evidence.
- **FR-009**: System MUST generate charts and statistical tables from usable
  CSV or XLSX data when the report requires data analysis.
- **FR-009a**: System MUST save generated charts under the report's chart
  storage area and include them in Markdown, PDF, and DOCX deliverables.
- **FR-010**: System MUST compose report sections using only the approved
  outline and retrieved evidence.
- **FR-011**: System MUST audit every generated claim for source coverage before
  final export.
- **FR-012**: System MUST flag likely hallucinations and unsupported claims for
  user review or regeneration.
- **FR-012a**: System MUST block export for any unsourced claim and MUST show
  warnings for sourced claims with low confidence.
- **FR-012b**: System MUST block export for claims marked `UNSUPPORTED` or
  `CONTRADICTED`, warn for `PARTIALLY_SUPPORTED`, and allow `UNVERIFIED` with a
  warning only when no better source exists.
- **FR-013**: System MUST score report quality and provide specific improvement
  suggestions.
- **FR-014**: System MUST show a live progress tracker with the active agent and
  current step.
- **FR-015**: System MUST show a source panel linking every report claim to its
  source and confidence score.
- **FR-016**: System MUST show estimated token usage before or during report
  generation and actual token usage after completion.
- **FR-017**: System MUST provide Markdown preview, PDF export, and DOCX export
  for verified reports.
- **FR-017a**: System MUST cite claims using bracket keys such as `[AuthorYear]`
  or `[SourceID]` and include a full bibliography appendix.
- **FR-018**: System MUST require a human approval gate before final
  export for Investment Memo, Policy Brief, and all Deep reports.
- **FR-019**: System MUST allow users to regenerate one report section without
  regenerating the entire report.
- **FR-020**: System MUST store report job traces, agent steps, source metadata,
  verification results, costs, and final artifacts for debugging and compliance.
- **FR-021**: System MUST preserve stored job data and expose retry for failed
  jobs without leaking state across sessions.
- **FR-021a**: System MUST mark a report job `FAILED` after an agent fails 3
  retries, preserve partial output, notify the user, and allow manual retry by
  rerunning the live pipeline.
- **FR-022**: System MUST support multiple concurrent report jobs while keeping
  job inputs, sources, costs, and outputs isolated.
- **FR-022a**: System MUST isolate each report job's retrieval index from other
  jobs.
- **FR-023**: System MUST support long report generation workflows using context
  management appropriate for up to 256K-token report work.
- **FR-023a**: System MUST generate long reports section by section with rolling
  summaries and MUST NOT place the full report into one prompt.
- **FR-024**: System MUST isolate report jobs by anonymous browser session in
  the initial version; each session owns its report jobs, inputs, sources,
  costs, and outputs.
- **FR-025**: System MUST retain uploaded documents, intermediate artifacts, and
  generated outputs only for the anonymous session unless the user explicitly
  saves or exports final artifacts.
- **FR-025a**: System MUST clean up report-scoped uploaded files and indexes
  after 7 days unless the user explicitly saved or exported the final artifacts.
- **FR-026**: System MUST allow no more than three active report jobs per
  anonymous browser session at one time.

### ReportForge Constitution Requirements

- **CR-001**: Any generated report claim MUST include a `source_id`, and
  unsourced claims MUST block verification and export.
- **CR-002**: Any feature that adds or changes an agent MUST define its Pydantic
  v2 input and output schemas and keep agent logic inside `agents/`.
- **CR-003**: Any feature that performs LLM calls MUST route them through
  `ModelRouter` and `CostTrackingModel` with token, cost, latency, and raw
  response logging.
- **CR-004**: Any feature that parses PDF, DOCX, or CSV content MUST perform
  parsing in `tools/`, not in agent modules.
- **CR-005**: Any feature that exports Markdown, PDF, or DOCX reports MUST use
  Jinja2 templates from `templates/`.
- **CR-006**: Any feature that affects retrieval MUST preserve hybrid Chroma +
  BM25 retrieval with cross-encoder reranking.
- **CR-007**: Any changed agent or tool MUST have a corresponding test file
  under `tests/`.

### Key Entities *(include if feature involves data)*

- **Report Job**: A single report generation request, including topic, report
  type, depth, status, review state, usage estimates, actual usage, and final
  deliverables, owned by one anonymous browser session.
- **Browser Session**: An anonymous user session that owns report jobs and
  isolates inputs, sources, costs, and generated outputs from other sessions.
- **User Input Source**: An uploaded file or URL list entry supplied by the
  user, including type, validation status, source metadata, and extracted
  evidence references.
- **External Source**: A web research source collected for the report, including
  URL, title, publisher, retrieval time, relevance score, and metadata quality.
- **Evidence Chunk**: A retrievable piece of source material linked to its
  source and used to support claims.
- **Report Outline**: The approved structure of sections and research questions
  used to guide drafting.
- **Report Section**: A generated section with status, version history, claims,
  cited sources, critique results, and regeneration history.
- **Claim**: A discrete report assertion that must reference a source and carry
  verification status and confidence score.
- **Verification Status**: A claim audit outcome: `SUPPORTED`,
  `PARTIALLY_SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED`, or `UNVERIFIED`.
- **Agent Trace**: A recorded step in the multi-agent workflow, including
  inputs, outputs, timing, usage, status, and error details.
- **Export Artifact**: A Markdown, PDF, or DOCX deliverable linked to a verified
  report version.
- **Chart Artifact**: A generated visualization saved for a report and embedded
  or referenced by final deliverables.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: At least 95% of generated claims in accepted reports have a
  visible source link and confidence score; the remaining 5% cannot be exported
  until resolved.
- **SC-002**: A user can generate a Standard report with one uploaded document
  and at least five external sources in under 15 minutes on a local laptop.
- **SC-003**: Users can identify the active generation step within 5 seconds of
  opening the progress tracker during a running job.
- **SC-004**: Completed reports can be exported to Markdown, PDF, and DOCX with
  matching section structure and citations.
- **SC-005**: Section-level regeneration changes only the selected section and
  preserves the rest of the report in at least 99% of regeneration attempts.
- **SC-006**: Persisted report jobs can reload completed sections, sources, and
  traces after the job manager is recreated.
- **SC-007**: Concurrent report jobs keep inputs, sources, costs, and outputs
  isolated with zero observed cross-session leakage in test runs.
- **SC-008**: Users can compare estimated and actual token usage for each
  completed report job.
- **SC-009**: Investment Memo, Policy Brief, and Deep reports cannot be exported
  until a human review gate is completed.
- **SC-010**: Reports with unsourced claims cannot be exported, while reports
  with only low-confidence sourced claims remain exportable with visible
  warnings.
- **SC-011**: Session-retained uploads and generated artifacts are unavailable
  after session clearing unless the user explicitly exported or saved them.
- **SC-012**: Starting a fourth active report job in one anonymous session is
  prevented or queued with a clear user-visible message.
- **SC-013**: Report jobs with `UNSUPPORTED` or `CONTRADICTED` claims cannot be
  exported, while `PARTIALLY_SUPPORTED` and eligible `UNVERIFIED` claims are
  visible as warnings.
- **SC-014**: A failed agent step after 3 retries leaves a visible failed job
  state, preserved partial output, and a retry option that reruns the live
  pipeline.
- **SC-015**: Generated reports include bracket-key citations and a bibliography
  appendix.

## Assumptions

- The initial version uses anonymous browser sessions for isolation and does
  not require user accounts before report generation.
- Optional API key authentication is deferred to V2.
- Session-retained data is available for crash recovery during the active
  anonymous session but is not treated as long-term storage.
- Human review is required for Investment Memo, Policy Brief, and every Deep
  report, with room to classify additional report types later.
- URL lists contain normal web URLs and do not require private browsing
  credentials in the initial version.
- Report page counts are approximate and vary with formatting, charts, and
  citation density.
- The system may warn users when requested depth, uploaded material, or source
  availability makes the desired report quality unlikely.
- Cost displayed during free-tier testing may be zero dollars while still
  showing token usage and estimated usage for future paid providers.
- Real web search, Celery, and Redis are V2 capabilities; the MVP uses mock
  search and local background execution unless optional providers are enabled.
