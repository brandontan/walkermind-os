FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml to /app so setuptools can find the package.
# (Build context is crusaderbot/ — one level above is the logical project root
#  that pyproject.toml was designed for.)
COPY pyproject.toml /app/

# Copy all source files into /app/crusaderbot/ so the package is importable
# as `import crusaderbot`.
COPY . /app/crusaderbot/

# Install the package and all dependencies.
# setuptools finds /app/crusaderbot/ (matches "crusaderbot*") via pyproject.toml.
RUN pip install --no-cache-dir /app/

# Create a non-root user and hand it ownership of the application files.
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --shell /usr/sbin/nologin --no-create-home app \
    && chown -R app:app /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

EXPOSE 8080

USER app

CMD ["sh", "-c", "uvicorn crusaderbot.main:app --host 0.0.0.0 --port ${PORT}"]
