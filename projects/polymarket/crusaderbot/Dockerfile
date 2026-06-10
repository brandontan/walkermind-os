# Stage 1: build React frontend
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY webtrader/frontend/package.json webtrader/frontend/package-lock.json ./
RUN npm ci
COPY webtrader/frontend/ ./
# Bot username injected at build time; defaults to CrusaderBot
ARG VITE_BOT_USERNAME=CrusaderPolybot
ENV VITE_BOT_USERNAME=$VITE_BOT_USERNAME
RUN npm run build
# Output: /build/dist/

# Stage 1b: build the Rust order sidecar (WARP/root-rust-order-sidecar).
# The official polymarket_client_sdk_v2 canary is the only client that signs
# POLY_1271 deposit-wallet orders; the sidecar wraps it behind JSON-stdio for
# the Python bot. Dormant at runtime until USE_RUST_SIDECAR=1.
FROM rust:1-slim AS sidecar-build
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
        pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*
COPY sidecar/Cargo.toml sidecar/Cargo.lock ./
# Pre-build deps against a stub main so source-only edits reuse the dep cache.
RUN mkdir src && echo 'fn main() {}' > src/main.rs \
    && cargo build --release \
    && rm -rf src target/release/order-sidecar target/release/deps/order_sidecar*
COPY sidecar/src ./src
RUN cargo build --release
# Output: /build/target/release/order-sidecar

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

# The Rust order sidecar from Stage 1b — at the RUST_SIDECAR_PATH default.
COPY --from=sidecar-build /build/target/release/order-sidecar /usr/local/bin/order-sidecar

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
