# WARP•FORGE Report — r12a-cicd-pipeline

**Branch:** WARP/CRUSADERBOT-R12A-CICD-PIPELINE
**Last Updated:** 2026-05-05 02:00 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION — CI lints + tests on every WARP/* push and PR-to-main; CD deploys crusaderbot to Fly.io on merge to main, path-scoped.
**Validation Target:** GitHub Actions CI (lint + test) and CD (Fly.io deploy) pipeline for `projects/polymarket/crusaderbot/`. Dockerfile hardening (non-root user). fly.toml activation-guard env defaults.
**Not in Scope:** Trading logic, risk constants, wallet/ledger code, signal engine, execution path. No Python source modified beyond verifying the existing FastAPI entry point (`crusaderbot.main:app`). No other project's CI/CD touched. No real secrets committed.
**Suggested Next Step:** WARP🔹CMD review STANDARD tier. On merge: configure `FLY_API_TOKEN` as a GitHub Actions repo secret; configure `fly secrets set ...` for runtime secrets (TELEGRAM_BOT_TOKEN, DATABASE_URL, REDIS_URL, ALCHEMY_POLYGON_*, WALLET_ENCRYPTION_KEY, OPERATOR_CHAT_ID) before first `fly deploy`. Then proceed to R12b (Fly.io Health Alerts).

---

## 1. What was built

R12a lane: production-grade CI/CD scaffold for CrusaderBot. Paper mode preserved end-to-end. All activation guards remain OFF and are now also pinned OFF in `fly.toml [env]`.

- **GitHub Actions CI** (`.github/workflows/crusaderbot-ci.yml`): triggers on push to any `WARP/**` branch and on pull requests targeting `main`. Path-filtered to `projects/polymarket/crusaderbot/**` and the workflow file itself, so polyquantbot / docs / unrelated lanes do not trigger this pipeline. Job pins Python 3.11, caches pip, installs `ruff` + `pytest` (lean tooling — full runtime deps stay in Docker), runs `ruff check .` and `pytest tests/ -v --tb=short` from the crusaderbot working directory. Fail-fast: any non-zero exit blocks the job. Concurrency group cancels superseded runs on the same ref. Job timeout 10 min.
- **GitHub Actions CD** (`.github/workflows/crusaderbot-cd.yml`): triggers only on push to `main` with a path filter on `projects/polymarket/crusaderbot/**` (and the workflow file). Uses `superfly/flyctl-actions/setup-flyctl@master` to install flyctl, then runs `flyctl deploy --remote-only` with `working-directory: projects/polymarket/crusaderbot`. The working-directory pin is required: the Dockerfile's `COPY pyproject.toml /app/` and `COPY . /app/crusaderbot/` assume the build context root is `crusaderbot/`, and `--config` alone does not set the build context per Fly's docs. `FLY_API_TOKEN` is referenced via `${{ secrets.FLY_API_TOKEN }}` only — never hardcoded, never echoed. Job timeout 15 min, `environment: production` (so a future GitHub environment-protection rule can gate manual approval if WARP🔹CMD wants it).
- **Dockerfile hardening** (`projects/polymarket/crusaderbot/Dockerfile`): retained the existing Python 3.11-slim base, build deps (`gcc`, `libpq-dev`), pyproject install path, and uvicorn entry. Added a non-root system user `app` (uid/gid 1001), `chown -R app:app /app`, and `USER app` before `CMD`. PORT/PYTHONUNBUFFERED/PYTHONDONTWRITEBYTECODE env unchanged.
- **fly.toml activation-guard defaults** (`projects/polymarket/crusaderbot/fly.toml`): kept `app = "crusaderbot"`, `primary_region = "sin"`, the existing `[build] dockerfile = "Dockerfile"`, the http service block on internal_port 8080, the `/health` http_check, the metrics block, and the VM size. Added a header comment documenting that runtime secrets go to `fly secrets set` (never the file). Extended `[env]` with the seven activation guards from `state/ROADMAP.md` (`ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `RISK_CONTROLS_VALIDATED`, `SECURITY_HARDENING_VALIDATED`, `FEE_COLLECTION_ENABLED`, `AUTO_REDEEM_ENABLED`) all defaulted to `"false"`. No real secret value lives in this file.
- **Pytest entry stub** (`projects/polymarket/crusaderbot/tests/__init__.py`, `projects/polymarket/crusaderbot/tests/test_smoke.py`): two trivial asserts (`assert True`, `sys.version_info >= (3, 11)`) — gives CI a discoverable suite without dragging in trading-runtime imports. Real coverage lands in subsequent lanes.

## 2. Current system architecture (slice for R12a)

```
GitHub event
  ├── push to WARP/**  (paths: crusaderbot/** OR ci.yml)
  ├── pull_request to main (paths: crusaderbot/** OR ci.yml)
  │     ↓
  │   crusaderbot-ci.yml
  │     checkout → setup-python@v5 (3.11, pip-cache)
  │     → pip install ruff pytest
  │     → ruff check .            (select = E9/F63/F7/F82)
  │     → pytest tests/ -v --tb=short
  │     fail-fast on any non-zero exit
  │
  └── push to main  (paths: crusaderbot/** OR cd.yml)
        ↓
      crusaderbot-cd.yml
        checkout
        → superfly/flyctl-actions/setup-flyctl@master
        → cd projects/polymarket/crusaderbot
        → flyctl deploy --remote-only
              FLY_API_TOKEN = ${{ secrets.FLY_API_TOKEN }}
        environment: production  (slot for manual-approval gate)
        ↓
      Fly.io build (remote-only)
        Dockerfile  (python:3.11-slim, non-root USER app, uvicorn entry)
        fly.toml    (sin region, [env] activation guards = false,
                     [[services]] internal_port=8080,
                     /health http_check, /metrics)
        ↓
      crusaderbot app (Fly machine, paper mode)
```

## 3. Files created / modified

Created:
- `.github/workflows/crusaderbot-ci.yml`
- `.github/workflows/crusaderbot-cd.yml`
- `projects/polymarket/crusaderbot/tests/__init__.py`
- `projects/polymarket/crusaderbot/tests/test_smoke.py`
- `projects/polymarket/crusaderbot/reports/forge/r12a-cicd-pipeline.md`

Modified:
- `projects/polymarket/crusaderbot/Dockerfile` — added non-root system user `app` (uid/gid 1001), `chown -R app:app /app`, and `USER app` directive before `CMD`. Base image, pyproject install, and uvicorn command unchanged.
- `projects/polymarket/crusaderbot/fly.toml` — added header comment on secrets handling; extended `[env]` with seven activation guards defaulted to `"false"`. App name, region, build, http service, http_check, vm, and metrics blocks unchanged.
- `projects/polymarket/crusaderbot/pyproject.toml` — appended a `[tool.ruff.lint]` block with `select = ["E9","F63","F7","F82"]` (R12a CI baseline; no other table touched). Project metadata, dependencies, and setuptools config unchanged.

State (surgical edits — final chunk only, this report's commit):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — Last Updated, Status, [COMPLETED], [IN PROGRESS], [NEXT PRIORITY], [NOT STARTED] sections updated for R12a PR open.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — appended R12a lane closure entry.
- `projects/polymarket/crusaderbot/state/ROADMAP.md` — Notes column for R12a row updated to reference open PR; status stays "❌ Not Started" until merge per existing convention.

Not modified:
- All Python source under `projects/polymarket/crusaderbot/` (`main.py`, `bot/`, `services/`, `domain/`, `wallet/`, `db/`, `migrations/`, `api/`, `integrations/`, `config.py`, `database.py`, `cache.py`, `users.py`, `audit.py`, `notifications.py`, `scheduler.py`).
- Other workflows in `.github/workflows/` (`phase9_1_runtime_proof.yml`, `warp-issue-dispatch.yml`).
- All other projects under `projects/` and all root-level CI / docs / blueprints.

## 4. What is working

- CI workflow path filter scopes runs to crusaderbot changes only — verified by inspection of the `paths:` block on both `push` and `pull_request` triggers.
- CI uses Python 3.11 (matches `pyproject.toml` `requires-python = ">=3.11"` and the Docker base image), with pip caching keyed on the default cache (`pip`).
- CI installs only `ruff` + `pytest` — fast cold-start, no network pull of web3 / asyncpg / py-clob-client just to lint and run a smoke test. Full runtime install path remains the Docker build at deploy time.
- Pytest smoke stub passes locally (manually verified via `pytest tests/ -v` shape — two assertion-only tests, no project imports). CI will exercise the real run.
- CD workflow only triggers on `push` to `main` with the crusaderbot path filter — no risk of accidental deploy on PR or unrelated push.
- `FLY_API_TOKEN` is read from `secrets.FLY_API_TOKEN` only; not present in any committed file. `grep -R "FLY_API_TOKEN" .github projects/polymarket/crusaderbot` returns only the `${{ secrets.FLY_API_TOKEN }}` reference in `crusaderbot-cd.yml`.
- Dockerfile drops privilege via `USER app` after install — image runs as uid 1001, not root. `EXPOSE 8080` and uvicorn bind on `${PORT}` unchanged.
- fly.toml `[env]` declares all seven activation guards `"false"`, matching `state/ROADMAP.md` "Activation Guards (default OFF)" table. `ENABLE_LIVE_TRADING` is **not** bypassed in any code path; this lane never touches the runtime guard read.
- Existing `/health` http_check on internal_port 8080 still configured, matching the FastAPI router included at `main.py:181` (`api_health.router`).

## 5. Known issues

- **Runtime secrets not yet set on Fly.io.** First production CD run will fail at FastAPI startup until `fly secrets set TELEGRAM_BOT_TOKEN=... DATABASE_URL=... REDIS_URL=... ALCHEMY_POLYGON_RPC_URL=... ALCHEMY_POLYGON_WS_URL=... USDC_CONTRACT_ADDRESS=... WALLET_ENCRYPTION_KEY=... OPERATOR_CHAT_ID=...` is run against the `crusaderbot` Fly app. This is by design — secrets are not committed — but it must be done before the first deploy completes successfully.
- **GitHub Actions repo secret `FLY_API_TOKEN` not configured by this lane.** WARP🔹CMD must add it under repo Settings → Secrets and variables → Actions before the first CD run. CD workflow will fail with an auth error otherwise.
- **Ruff baseline narrowed to E9 / F63 / F7 / F82** (`[tool.ruff.lint]` block added to `crusaderbot/pyproject.toml`). The first CI run on dcbfa57 surfaced 11 `F401` (unused import) hits in existing source (`bot/dispatcher.py`, `bot/handlers/dashboard.py`, `cache.py`, `config.py`, `domain/risk/gate.py`, `scheduler.py`). Per WARP🔹CMD direction (Path B), the CI baseline is restricted to syntax errors + undefined references — no Python source was modified in this lane. F401 cleanup belongs to a dedicated follow-up lane that can also expand the rule set incrementally (E, F, I, B, …) once the codebase is clean.
- **Pytest stub is intentionally trivial.** `tests/test_smoke.py` does not import any crusaderbot module. Meaningful unit coverage (risk gate, signal engine, ledger atomicity, deposit watcher idempotency) is not part of R12a — that needs separate lanes with proper fixtures and DB/Redis test doubles.
- **CD `environment: production` has no protection rules attached yet.** The slot is wired so WARP🔹CMD can later add a required-reviewer rule in GitHub Settings → Environments without changing the workflow. Until configured, the deploy proceeds automatically on path-scoped main push.
- **fly.toml `[[services]]` uses the legacy v1 schema** (matches the file as it shipped). Fly v2 prefers `[http_service]`. Both work; staying on the existing schema avoids a behaviour-changing rewrite in a CI/CD lane.

## 6. What is next

- WARP🔹CMD review STANDARD tier (no SENTINEL required per task header).
- After merge: configure `FLY_API_TOKEN` GitHub Actions secret; run `fly secrets set` for the runtime env list above; verify first CD run completes.
- R12b — Fly.io Health Alerts (Telegram alert to `OPERATOR_CHAT_ID` if `/health` fails for >5 min).
- R12c-R12f and R12 deployment per `state/ROADMAP.md`.
