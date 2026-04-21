FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local
RUN mkdir -p /app/projects/polymarket/polyquantbot
COPY . /app/projects/polymarket/polyquantbot

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["python", "-m", "projects.polymarket.polyquantbot.scripts.run_api"]
