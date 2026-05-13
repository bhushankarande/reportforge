# Quickstart: ReportForge MVP

## Prerequisites

```bash
python3.11 --version
uv --version
docker --version
git --version
```

## Environment

Create or update `.env` in the project root:

```bash
ACTIVE_LLM_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-key-here
GEMINI_MODEL_NAME=gemini-1.5-flash
GROQ_API_KEY=
OLLAMA_MODEL_NAME=llama3.1:8b
KIMI_API_KEY=
MAX_COST_USD_PER_JOB=0.00
ENABLE_COST_PREVIEW=true
ENABLE_TAVILY_SEARCH=false
TAVILY_API_KEY=
ENVIRONMENT=development
LOG_LEVEL=INFO
STORAGE_DIR=./storage
DATABASE_URL=sqlite:///./storage/reportforge.db
```

## Install

```bash
uv sync
```

## Run Backend

```bash
uv run fastapi dev app/main.py
```

Expected backend URL:

```text
http://localhost:8000
```

## Run Streamlit Frontend

```bash
uv run streamlit run frontend/streamlit_app.py
```

Expected frontend URL:

```text
http://localhost:8501
```

## Docker Compose

```bash
docker compose up --build
```

All services must support M1 Mac with `linux/arm64`. The MVP uses SQLite by
default. A Postgres service/profile is included for the migration path but is not
required for Phase 1.

## Smoke Test Flow

1. Open the Streamlit app.
2. Enter topic: `US market for AI-assisted financial reporting`.
3. Select report type: `Market Research`.
4. Select depth: `Standard`.
5. Upload one small PDF or CSV, or leave uploads empty.
6. Start report generation.
7. Confirm progress shows active agent and current step.
8. Confirm cost dashboard shows zero actual cost and estimated Kimi cost.
9. Confirm source panel links claims to source ids and confidence scores.
10. Export Markdown after verification passes.

## Verification Gates

Exports are blocked when:

- any claim is `UNSUPPORTED`;
- any claim is `CONTRADICTED`;
- required human approval is missing for Investment Memo, Policy Brief, or Deep
  reports.

Exports warn when:

- a claim is `PARTIALLY_SUPPORTED`;
- a claim is `UNVERIFIED` and no better source exists.

## Retry Recovery

If an agent fails after 3 retries:

1. Job status becomes `FAILED`.
2. Partial output and traces are preserved.
3. The user can call `POST /jobs/{id}/retry`.
4. The workflow resumes from the last checkpoint.

## Planned Checks

```bash
uv run pytest
uv run ruff check .
docker compose config
```
