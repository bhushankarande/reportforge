# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]

**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]

**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]

**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]

**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]

**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]

**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]

**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]

**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]

**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Hexagonal boundaries: business logic in `agents/` and `tools/`; framework
  adapters in `app/` and `frontend/`; orchestration only in
  `orchestration/workflow.py`.
- Agent contracts: every changed agent has a discrete module and Pydantic v2
  input/output schemas; no direct agent-to-agent calls.
- Model abstraction: all LLM use goes through `ModelRouter` and
  `CostTrackingModel`; no provider-specific model client imports inside agents.
- Cost and trace logging: token count, cost, latency, provider/model, raw
  response, checkpoint state, and versioned outputs are recorded to
  `storage/`/SQLite as applicable.
- Report integrity: every generated report claim carries `source_id`; unsourced
  claims block verification and export.
- Retrieval/parsing/export: RAG uses Chroma + BM25 + cross-encoder reranking;
  PDF/DOCX/CSV parsing lives in `tools/`; Markdown/PDF/DOCX exports use Jinja2
  templates in `templates/`.
- Operations: external API calls use tenacity retry with exponential backoff;
  every service runs via `docker-compose.yml` on M1 Mac (`linux/arm64`).
- Context and idempotency: prompts stay under 180K tokens, rolling summaries are
  used for long workflows, and agent calls check checkpoints before execution.
- Typing and tests: type hints everywhere, no unjustified `Any` in function
  signatures, and every changed agent/tool has a corresponding test file.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
agents/
├── [agent_name].py
└── schemas/

tools/
├── parsing/
├── retrieval/
├── storage/
└── export/

orchestration/
└── workflow.py

app/
└── [fastapi adapters]

frontend/
└── [streamlit UI]

templates/
└── [jinja2 report templates]

storage/
└── [runtime artifacts, gitignored]

tests/
├── agents/
├── tools/
├── contract/
├── integration/
└── unit/

docker-compose.yml
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
