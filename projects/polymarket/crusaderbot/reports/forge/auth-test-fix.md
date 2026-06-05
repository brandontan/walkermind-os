# WARP-76 H1 — Auth / bcrypt / CI test fix

Branch: WARP/auth-test-fix
Role: WARP•R00T (executing as build/fix)
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: auth / bcrypt / account-link / paper-signup / playbook-roster test suites collect + pass in CI; degrade to documented SKIP (not collection ERROR) in dependency-less environments.
Not in Scope: production code; other 144 dep-less collection errors outside the named H1 suites; CI workflow / requirements changes; the deprecation-warning escape-sequence noise in bot/messages.py + bot/handlers/trades.py.
Suggested Next Step: WARP🔹CMD review + merge, then proceed to WARP-76 H2 (monitoring/alerting, branch WARP/monitoring-alerting).

## 1. What was built

The five named H1 test suites previously failed at **collection time** with a
hard pytest ERROR in any environment lacking the full optional runtime stack
(the Codex `work` worktree and bare local checkouts). Each module did a bare
`from projects.polymarket.crusaderbot...` import whose transitive chain pulls an
optional runtime dependency that is not installed there.

Root cause is **purely missing optional dependencies at import time — no logic
bug**. Verified by installing the declared `pyproject.toml` dependency set into a
clean venv and running all five suites: **74 passed, 0 failed**.

The fix converts those collection ERRORs into clean, documented module-level
SKIPs (naming the exact missing dependency) while leaving CI behaviour — where
the full stack is installed from `pyproject.toml` — completely unchanged. This
matches the repo's existing idiom (`test_warp54_closed_beta_hardening.py`
`pytest.skip(...)`, `test_order_lifecycle.py` `pytest.importorskip("web3")`).

### Root cause per suite (the dep the import chain fails on, dep-less env)

| Suite (file) | First missing dep | Chain |
|---|---|---|
| auth/bcrypt — `test_webtrader_auth_bcrypt.py` | `bcrypt` | webtrader/backend/auth.py:11 `import bcrypt` |
| auth (clob) — `test_clob_auth.py` | `pydantic` | integrations/clob/auth.py chain |
| account-link — `test_account_link.py` | `asyncpg` | domain/activation/account_link.py → audit → database:9 `import asyncpg` |
| paper-signup — `test_paper_default_invariant.py` | `structlog` | users.py import chain |
| playbook-roster — `test_playbook_engine.py` | `asyncpg` | domain/strategy/strategies → copy_trade → database:9 `import asyncpg` |

All listed deps ARE present in `pyproject.toml [project.dependencies]`, so CI
(`.github/workflows/crusaderbot-ci.yml` installs from there) collects + runs them
normally — confirmed green on `main`. The failures only manifest in dep-less
sandboxes.

## 2. Current system architecture

New shared test helper `tests/_runtime_deps.py` exposes a context manager
`optional_runtime_imports(suite)`:

- wraps the project-level imports in each affected test module;
- on `ModuleNotFoundError` it calls `pytest.skip(..., allow_module_level=True)`
  with a message naming the suite + the exact missing dependency;
- imports only stdlib + pytest (always available), and is named with a leading
  underscore so the `test_*.py` collection glob never picks it up.

In CI the wrapped imports succeed → the context manager is a no-op → suites run.
In a dep-less env the first missing dep → module SKIPPED (not ERRORED).

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/tests/_runtime_deps.py`

Modified (import block wrapped in `optional_runtime_imports(...)`; no test logic changed):
- `projects/polymarket/crusaderbot/tests/test_webtrader_auth_bcrypt.py`
- `projects/polymarket/crusaderbot/tests/test_clob_auth.py`
- `projects/polymarket/crusaderbot/tests/test_account_link.py`
- `projects/polymarket/crusaderbot/tests/test_paper_default_invariant.py`
- `projects/polymarket/crusaderbot/tests/test_playbook_engine.py`

No production code, no requirements/pyproject, no CI workflow changes.

## 4. What is working

- Dep-less env (isolated pytest, no project deps): **5 skipped, 0 error** — each
  with a documented reason, e.g. `webtrader auth/bcrypt suite skipped — optional
  runtime dependency 'bcrypt' not installed in this environment (CI installs the
  full stack from pyproject.toml)`.
- Deps-present env (clean venv mirroring CI install): **74 passed, 0 failed**.
- `ruff check .` (project config, select E9/F63/F7/F82): All checks passed.

## 5. Known issues

- Out of H1 scope: the remaining ~144 test modules also hard-ERROR at collection
  in dep-less environments for the same root cause. Only the five WARP-76-named
  suites were treated this chunk. A repo-wide sweep would be a separate lane.
- Deprecation warnings (`invalid escape sequence '\.'`) surface from
  `bot/messages.py` + `bot/handlers/trades.py` when telegram is installed —
  pre-existing, not failures, out of scope.

## 6. What is next

- WARP🔹CMD review + merge of WARP/auth-test-fix.
- Proceed to WARP-76 H2 — monitoring/alerting (branch WARP/monitoring-alerting).
