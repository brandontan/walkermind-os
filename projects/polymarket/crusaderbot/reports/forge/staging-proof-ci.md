# WARP-74 Lane 2 — Staging-proof CI workflow

Branch: WARP/staging-proof-ci
Role: WARP•FORGE
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: a manual, mobile-triggerable GitHub Actions workflow that runs the already-merged staging-proof harness (#1621) against the real Polymarket CLOB from the runner, with all wallet/market inputs from GitHub Secrets and a default-safe (no-USDC) posture.
Not in Scope: no production runtime code change; no execution / risk / gate / async-core change; no change to the harness itself; no Fly deploy; ENABLE_LIVE_TRADING / USE_REAL_CLOB prod defaults untouched.
Suggested Next Step: WARP🔹CMD adds the STAGING_* repo secrets (throwaway wallet + market ids), then triggers the workflow from github.com Actions tab on mobile — Case 3 first, fills off.

## 1. What was built

`.github/workflows/staging-proof.yml` — a `workflow_dispatch`-only GitHub Actions
workflow so a mobile-only operator can run the WARP-74 live-broker reconcile
proof from the github.com Actions tab. No laptop, no `flyctl`. It drives the
merged harness (`tests/staging/test_live_reconcile_staging.py`) against the real
Polymarket CLOB directly from the `ubuntu-latest` runner; the harness DB side is
the in-memory recording fake, so no Supabase is touched.

## 2. Current system architecture

```
github.com (mobile)  →  workflow_dispatch (inputs: case, allow_fills,
                          signature_type, neg_risk)
        │
        ▼
ubuntu-latest runner
  checkout → setup-python 3.11 → install tooling+pyproject deps → force cffi
        │  env: STAGING_* from GitHub Secrets + dispatch inputs
        ▼
  pytest tests/staging/test_live_reconcile_staging.py [-k <case>]
        │                 │
        │ REAL CLOB        │ in-memory recording fake (_Conn/_Pool)
        ▼                 ▼
  Polymarket (Polygon)   NO database (prod Supabase never touched)
        │
        ▼
  job summary (mobile-readable table + tail) + upload-artifact
   (staging-proof-output.txt, staging-proof-junit.xml)
```

Concurrency group `staging-proof` (cancel-in-progress: false) serialises runs so
two proofs can never place live orders at once and a running proof finishes its
own order teardown.

## 3. Files created / modified (full repo-root paths)

Created:
- `.github/workflows/staging-proof.yml`
- `projects/polymarket/crusaderbot/reports/forge/staging-proof-ci.md`

Modified:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

No production code, no harness, no requirements/pyproject change.

## 4. What is working

- YAML parses (`yaml.safe_load`): single `workflow_dispatch` trigger; 4 inputs
  (`case`, `allow_fills`, `signature_type`, `neg_risk`); 8 steps.
- Install path mirrors the green `crusaderbot-ci.yml` exactly (Python 3.11,
  tooling+pyproject deps with retry, cffi force-reinstall) so the same dep set
  that passes CI is present; `pytest-asyncio>=0.23` (in pyproject) resolves the
  async markers.
- Default-safe capital posture: `allow_fills` defaults **false** →
  `STAGING_ALLOW_FILLS=0`, so a default run only places resting orders far below
  market that never fill and are cancelled on teardown (≈ no USDC). The
  fill-burning finalize case stays skipped unless the operator opts in.
- Empty-secret safety: numeric tuning vars (REST_PRICE / ORDER_SHARES /
  TICK_SIZE) are intentionally NOT wired — passing them as empty secrets would
  crash `float("")`. `signature_type` and `neg_risk` are dispatch inputs with
  fixed valid values, so `int()` / bool parsing can never see an empty string.
  Market-id / wallet secrets are read as plain strings (empty → harness skips,
  never crashes).
- Hard guard: the run step fails fast with an actionable `::error::` if
  `STAGING_WALLET_KEY` is unset (otherwise every case would silently skip).
- Mobile UX: `GITHUB_STEP_SUMMARY` renders a result table + last 30 lines of
  output inline on the phone; full log + JUnit XML uploaded as an artifact
  (30-day retention).
- Least privilege: `permissions: contents: read`.

## 5. Known issues

- Capital safety is operator-discipline + the default-false gate, not a hard
  technical lock: anyone with repo write access who sets `allow_fills=true` will
  spend real USDC. Recommended hardening (optional, deferred to WARP🔹CMD): wrap
  the job in a protected GitHub Environment (`environment: staging-proof`) with a
  required reviewer so a fill-enabled run needs an explicit approval tap. Left
  out per the "keep it simple for mobile" directive; the boss is the sole
  approver regardless.
- Secrets must be provisioned before first use: `STAGING_WALLET_KEY` (required),
  `STAGING_TOKEN_ID` + `STAGING_MARKET_ID` (required for the broker cases), and
  optionally `STAGING_NO_TOKEN_ID` / `STAGING_FUNDER_ADDRESS` /
  `STAGING_POLYMARKET_API_KEY|SECRET|PASSPHRASE` / `STAGING_FILLED_CLOSE_ID`.
- Polymarket is Polygon mainnet only (no testnet): the wallet MUST be an isolated
  throwaway funded with minimal USDC, never the prod trading wallet.

## 6. What is next

- WARP🔹CMD: add the STAGING_* secrets (throwaway wallet + a liquid market's
  condition id + YES/NO token ids), then trigger from the Actions tab — run
  Case 3 first with fills off, capture the artifact + summary per
  `docs/runbooks/warp74-staging-proof.md` §4.
- After all five cases pass (and the operator opts into the fill case once),
  file the 4-artifact evidence bundle and return to WARP🔹CMD for the
  `ENABLE_LIVE_TRADING` go/no-go.

Note on tier: the workflow file changes no execution/risk/runtime code and runs
an already-built harness, so it is classified STANDARD. The fill-enabled path
does move real capital — WARP🔹CMD should treat the first `allow_fills=true`
dispatch as a gated operator action.
