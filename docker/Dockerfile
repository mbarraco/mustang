# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.12-slim

# ---------- base ----------
FROM python:${PYTHON_VERSION} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

# System deps consolidated in one layer
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy requirement definitions only (cache-friendly)
COPY requirements.in requirements.in
COPY requirements-dev.in requirements-dev.in
COPY requirements-prod.in requirements-prod.in
COPY requirements.txt requirements.txt
COPY requirements-dev.txt requirements-dev.txt
COPY requirements-prod.txt requirements-prod.txt

# ---------- dev ----------
FROM base AS dev
RUN python -m pip install --upgrade pip && \
    # Ensure pip-tools (pip-compile) is available and pinned to a tested version
    pip install pip-tools==6.14.0 && \
    pip install -r requirements-dev.txt
CMD ["bash"]

# ---------- prod ----------
FROM base AS prod
ENV PYTHONOPTIMIZE=1
RUN python -m pip install --upgrade pip && \
    pip install -r requirements-prod.txt
# Default to a shell for now. Replace with a proper
# application server (e.g., gunicorn/uvicorn behind nginx)
# when wiring up the runtime entrypoint.
CMD ["bash"]
