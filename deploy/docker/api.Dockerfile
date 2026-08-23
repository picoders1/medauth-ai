# syntax=docker/dockerfile:1.7
#
# Multi-stage: the builder holds uv and the toolchain; the runtime holds a
# virtualenv and the source, and nothing else. Dependencies are installed from
# uv.lock only - there is deliberately no fallback path, because a fallback that
# resolves differently from the lock produces an image the lockfile does not
# describe.

# --------------------------------------------------------------------- builder
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /src

# Dependency layer first: it changes far less often than the source, so edits to
# app/ do not invalidate the install.
COPY pyproject.toml uv.lock ./
RUN uv venv /opt/venv \
 && uv export --frozen --no-dev --no-emit-project --format requirements-txt -o /tmp/req.txt \
 && uv pip install --python /opt/venv/bin/python --no-cache -r /tmp/req.txt

# --------------------------------------------------------------------- runtime
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app ./app
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini ./

# Non-root. The compose/k8s manifests additionally mount the root filesystem
# read-only and drop every capability.
RUN useradd --system --uid 10001 --no-create-home medauth \
 && chown -R 10001:10001 /app
USER 10001

EXPOSE 8010

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=3).status == 200 else 1)"]

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8010"]
