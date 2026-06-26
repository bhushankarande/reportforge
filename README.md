# ReportForge

ReportForge is a local-first app for generating structured, citation-grounded business reports. It uses a Streamlit interface, a FastAPI backend, and one live pipeline for planning, evidence collection, writing, verification, review, and export.

## Features

- Generate reports from a topic, URLs, and uploaded files
- Use Gemini, Groq, local Ollama, or guarded Kimi routing
- Review sources and progress
- Approve human-review reports and regenerate sections
- Export reports as Markdown, PDF, or DOCX
- Track usage and estimated costs

## Quick Start

### Option 1: Docker

```bash
cp .env.example .env
# Add the API key for your selected provider in .env
docker compose up --build
```

### Option 2: Local Development

Install dependencies:

```bash
cp .env.example .env
# Add the API key for your selected provider in .env
uv sync
```

Start the backend:

```bash
uv run uvicorn app.main:app --reload
```

In a second terminal, start the frontend:

```bash
REPORTFORGE_API_URL=http://localhost:8000 uv run streamlit run frontend/streamlit_app.py
```

Open:

- App: `http://localhost:8501`
- API health check: `http://localhost:8000/health`

## Configuration

Set the active provider in `.env`:

```text
ACTIVE_LLM_PROVIDER=gemini
```

Then add the matching API key:

```text
GEMINI_API_KEY=your-key
GROQ_API_KEY=your-key
```

For local Ollama, use:

```text
ACTIVE_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL_NAME=llama3.1:8b
```

See `.env.example` for all available settings.

## Development Checks

```bash
uv run pytest
uv run ruff check .
docker compose config --quiet
```

## Live Architecture

The production path is:

```text
Streamlit -> FastAPI routers -> JobManager -> ReportPipeline
Planner -> Evidence/RAG -> Writer -> Verifier -> Critic
```

Markdown, PDF, and DOCX exports all go through `FormatterAgent.export_artifact`.
Older checkpoint workflow files were removed during the cleanup phase; retry is
a full live-pipeline rerun.

## License

MIT
