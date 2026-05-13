# reportforge

A fresh Python project for report generation workflows.

## Setup

```bash
uv sync
```

## Run

```bash
uv run reportforge
```

## Test and lint

```bash
uv run pytest
uv run ruff check .
```

## Docker

```bash
docker build -t reportforge .
docker run --rm reportforge
```
