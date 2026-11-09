# syntax=docker/dockerfile:1
FROM python:3.13-slim

WORKDIR /app

# ---------------------------------------------------------------------------
# 1. Install app-layer dependencies (cached layer — changes rarely)
# ---------------------------------------------------------------------------
COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt

# ---------------------------------------------------------------------------
# 2. Install handler-layer dependencies from src/requirements.txt
#    boto3 is in that file for SAM compatibility; it installs fine here
#    but is only *used* when STORAGE=dynamodb.
# ---------------------------------------------------------------------------
COPY src/requirements.txt ./src-requirements.txt
RUN pip install --no-cache-dir -r src-requirements.txt

# ---------------------------------------------------------------------------
# 3. Copy application source
#    - src/  : all Lambda handlers + storage layer
#    - data/ : canonical baseline fingerprint (required for legacy scoring)
#    - app/  : FastAPI adapter
# ---------------------------------------------------------------------------
COPY src/ src/
COPY data/ data/
COPY app/ app/

# ---------------------------------------------------------------------------
# 4. Non-root user for security
# ---------------------------------------------------------------------------
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# ---------------------------------------------------------------------------
# 5. Runtime configuration
# ---------------------------------------------------------------------------
ENV STORAGE=memory
ENV PORT=8000
EXPOSE 8000

# Use sh -c so $PORT is expanded at runtime (the variable is set above, but
# can be overridden by the container orchestrator at start time).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port $PORT"]

