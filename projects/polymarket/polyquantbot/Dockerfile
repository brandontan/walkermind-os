FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.12-slim

# /workspace is the repo root in the container.
# projects/polymarket/polyquantbot/ is mounted at the correct import path
# so that `from projects.polymarket.polyquantbot.X import Y` resolves cleanly.
WORKDIR /workspace

COPY --from=builder /install /usr/local

# Scaffold the import-path directory structure, then copy project files.
RUN mkdir -p projects/polymarket/polyquantbot
COPY . projects/polymarket/polyquantbot/

# Make parent packages importable.
RUN touch projects/__init__.py projects/polymarket/__init__.py

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /workspace
USER appuser

# Fly.io injects PORT; default matches the http_service internal_port in fly.toml.
ENV PORT=8080
# PYTHONPATH makes `projects.polymarket.polyquantbot.*` imports work without sys.path hacks.
ENV PYTHONPATH=/workspace

EXPOSE 8080

# Working directory matches where scripts resolve their __file__ parents.
WORKDIR /workspace/projects/polymarket/polyquantbot

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Primary entry: FastAPI control-plane surface (binds PORT, serves /health + /ready).
CMD ["python", "scripts/run_api.py"]
