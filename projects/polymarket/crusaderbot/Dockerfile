# Stage 1: build React frontend
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY webtrader/frontend/package.json webtrader/frontend/package-lock.json ./
RUN npm ci
COPY webtrader/frontend/ ./
# Bot username injected at build time; defaults to CrusaderBot
ARG VITE_BOT_USERNAME=CrusaderBot
ENV VITE_BOT_USERNAME=$VITE_BOT_USERNAME
RUN npm run build
# Output: /build/dist/

# Stage 2: Python application
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml to /app so setuptools can find the package.
COPY pyproject.toml /app/

# Copy all source files into /app/crusaderbot/ so the package is importable
# as `import crusaderbot`.
COPY . /app/crusaderbot/

# Overlay the frontend production build from Stage 1.
# This is done after COPY . so the pre-built dist is not clobbered.
COPY --from=frontend-build /build/dist /app/crusaderbot/webtrader/frontend/dist

# Install the package and all dependencies.
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
