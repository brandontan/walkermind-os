FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . /app

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import os, sys, urllib.request
url = 'http://127.0.0.1:' + os.environ.get('PORT', '8080') + '/health'
status = 1
try:
    with urllib.request.urlopen(url, timeout=5) as response:
        status = 0 if response.status == 200 else 1
except Exception:
    status = 1
sys.exit(status)"

CMD ["python", "-m", "projects.polymarket.polyquantbot.scripts.run_api"]
