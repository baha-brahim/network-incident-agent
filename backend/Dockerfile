# check=skip=FromPlatformFlagConstDisallowed
FROM --platform=linux/amd64 python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first, so editing the source does not reinstall them. pyarrow (170 MB) is left
# out: only the simulator's parquet files use it, and the API never touches them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-editable --no-install-project --no-install-package pyarrow

COPY src ./src
RUN uv sync --locked --no-dev --no-editable --no-install-package pyarrow \
    && find /app/.venv -type d -name tests -prune -exec rm -rf {} +

# The embedding model goes into the image, so a cold start downloads nothing.
RUN EMBEDDING_CACHE_DIR=/opt/fastembed /app/.venv/bin/python -c \
    "from incident_agent.rag.embedder import FastEmbedEmbedder; FastEmbedEmbedder().embed_query('warm up')"


FROM --platform=linux/amd64 python:3.12-slim-bookworm

# Lambda Web Adapter: turns Lambda invocations into HTTP requests to the app below.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /opt/fastembed /opt/fastembed

# Lambda's file system is read-only except /tmp. Secrets come from the function's environment.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    HF_HUB_OFFLINE=1 \
    PORT=8080 \
    AWS_LWA_INVOKE_MODE=response_stream \
    AWS_LWA_READINESS_CHECK_PATH=/api/ping \
    LLM_CACHE_MODE=off \
    LLM_CACHE_DIR=/tmp/llm_cache \
    EMBEDDING_CACHE_DIR=/opt/fastembed

WORKDIR /app
EXPOSE 8080

# One worker: a Lambda instance serves one request at a time. The client address arrives in
# X-Forwarded-For. Access logs are off because they would record every visitor's address.
CMD ["uvicorn", "incident_agent.api.app:app", "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
