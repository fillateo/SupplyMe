# Cloud Run image. Small on purpose: scale-to-zero means cold starts are the
# common case, and every megabyte is pull time on the first request.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --no-cache-dir . && \
    adduser --disabled-password --gecos "" --uid 10001 appuser && \
    chown -R appuser /app
USER appuser

ENV PORT=8080
EXPOSE 8080

# One worker per instance: the orchestrator's idempotency is cross-instance safe
# via Firestore, but a single worker keeps per-instance memory predictable and
# lets Cloud Run's concurrency setting do the scaling.
CMD exec uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT} --workers 1
