# WARP-74 staging proof — auto-resolve by DEFAULT (ignore stale pinned secrets)

Validation Tier: MINOR (CI workflow + runbook; no code/runtime change)
Claim Level: NARROW INTEGRATION (workflow gating fix; validated by the next dispatch)
Validation Target: the staging proof must auto-resolve a live market by default and NOT be silently forced onto the stale `STAGING_TOKEN_ID`/`STAGING_MARKET_ID` repo secrets.
Not in Scope: trading/execution code; the resolver itself (#1641, already merged); LIVE gating.
Suggested Next Step: re-dispatch `staging-proof-fly.yml` (case3, nrt, defaults) — `pin_market=false` now blanks the market secrets so the harness resolves a live market.

---

## 1. Problem

After the runtime resolver merged (#1641), proof run #7 STILL failed with
`the orderbook does not exist`. The run env revealed why: `STAGING_TOKEN_ID` and
`STAGING_MARKET_ID` are **actually set as repo secrets** (to the stale market).
The harness honours an explicit override when both are present, so it used the
pinned stale market and never auto-resolved. The owner's intent — "don't make me
set those secrets, they roll over every 5m/15m" — was defeated by the secrets
still existing and being forwarded unconditionally.

## 2. Fix

`.github/workflows/staging-proof-fly.yml`:
- New dispatch input `pin_market` (boolean, default **false**).
- The market secrets are now forwarded only when `pin_market=true`:
  `STAGING_TOKEN_ID: ${{ inputs.pin_market && secrets.STAGING_TOKEN_ID || '' }}`
  (same for `STAGING_MARKET_ID`/`STAGING_NO_TOKEN_ID`).

So by default the machine receives EMPTY market envs → `_ensure_market_resolved`
resolves a live OPEN market at runtime. The stale secrets are ignored unless the
operator explicitly checks `pin_market` to reproduce a specific market. The owner
never has to maintain those secrets again.

## 3. Files modified (full repo-root paths)

- `.github/workflows/staging-proof-fly.yml` — `pin_market` input + conditional market-secret forwarding.
- `projects/polymarket/crusaderbot/docs/runbooks/warp74-staging-proof.md` — env table notes pinning needs `pin_market=true`.
- `projects/polymarket/crusaderbot/reports/forge/staging-proof-default-autoresolve.md` — this report.
- `state/PROJECT_STATE.md`, `state/CHANGELOG.md` — lane sync.

## 4. What is working

- YAML validated. No code/runtime change; the resolver (merged) is unchanged.
- `STAGING_WALLET_KEY` remains the only required staging secret.

## 5. Known issues / boundaries

- The stale `STAGING_TOKEN_ID`/`STAGING_MARKET_ID` secrets can be left in place
  harmlessly (ignored unless `pin_market=true`), or deleted — owner's choice.

## 6. What is next

1. Re-dispatch `staging-proof-fly.yml` case3 (nrt, defaults) → harness resolves a live market; a real GTC should rest + kill switch cancel.
2. `all-broker` for cases 1–2–4; confirm `signature_type` proxy inference; close GTC-only gap; pass all 5 before any LIVE flip.

---

Validation Handoff (NEXT PRIORITY): WARP🔹CMD review — MINOR. Source: projects/polymarket/crusaderbot/reports/forge/staging-proof-default-autoresolve.md.
