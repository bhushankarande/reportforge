FROM python:3.11-slim AS runtime

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY agents ./agents
COPY app ./app
COPY evaluation ./evaluation
COPY frontend ./frontend
COPY orchestration ./orchestration
COPY schemas ./schemas
COPY src ./src
COPY templates ./templates
COPY tools ./tools

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
