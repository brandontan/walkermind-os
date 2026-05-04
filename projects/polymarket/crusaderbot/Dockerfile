FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml to the /app root so setuptools can find the package.
# (Build context is crusaderbot/ — one level above is the logical project root
#  that pyproject.toml was designed for.)
COPY pyproject.toml /app/

# Copy all source files into /app/crusaderbot/ so the package is importable
# as `import crusaderbot`.
COPY . /app/crusaderbot/

# Install the package and all dependencies.
# setuptools finds /app/crusaderbot/ (matches "crusaderbot*") using pyproject.toml.
RUN pip install --no-cache-dir /app/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "uvicorn crusaderbot.main:app --host 0.0.0.0 --port ${PORT}"]
