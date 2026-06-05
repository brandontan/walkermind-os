# WARP-74 Lane 2 Staging Proof → CLOB v2 Migration — Handoff

Validation Tier: MINOR (handoff doc — non-runtime)
Claim Level: FOUNDATION
Validation Target: this handoff captures full session state for a fresh chat to resume the CLOB v2 migration investigation.
Not in Scope: any execution-code change (deferred until plan approved).
Suggested Next Step: read-only investigation of `py-clob-client-v2` + `integrations/clob`, then produce migration plan.

---

## 1. What was built
A self-contained handoff so a new session resumes the WARP-74 staging proof with zero context loss. No runtime change.

## 2. Current system architecture (relevant slice)
Live order path: `integrations/clob/adapter.py` builds + signs orders via the archived `py-clob-client` (v1) `OrderBuilder`/`Signer`/`OrderArgs`, posts to `https://clob.polymarket.com`. Credentials resolve through `integrations/clob/__init__.py` (`_derived` cache, `ensure_clob_credentials`, `effective_credentials`, `get_clob_client`). The staging harness (`tests/staging/test_live_reconcile_staging.py`) drives this against the REAL CLOB with an isolated throwaway wallet; DB side is an in-memory recording fake; `notify_operator` monkeypatched.

## 3. Mission
Validate live Polymarket CLOB order placement/cancel via the staging-proof harness before enabling live trading. Drive iteratively — boss wants ZERO hands-on operation. Owner: Bayue Walker (TheBoss). Role: WARP•FORGE (no merge authority).

## 4. What is working — DONE (all merged)
- #1631 create-api-key credential fallback (fresh staging wallet self-provisions L2 creds when derive fails).
- #1632 latent prod bug fixed: `adapter.py:471` `Signer(key=)` -> `Signer(private_key=)`.
- #1633 `runner` input (github-hosted | self-hosted) on `staging-proof.yml`.
- #1634/#1635/#1636 isolated Fly proof workflow `.github/workflows/staging-proof-fly.yml` — dedicated app `crusaderbot-staging-proof`, NO prod secrets, STAGING_* only, runs from Tokyo (`nrt`). Orchestration proven: launch -> git clone -> pip install -> pytest -> capture `PROOF_RESULT` -> destroy machine.
- case5 (infra-degraded -> paper fallback) PASSES on hosted runner.

## 5. Known issues — THE BLOCKER (root cause found)
Cases 1-4 (real orders) fail. Diagnosis sequence: `403 region-restricted` (GitHub IP geoblocked) -> Fly Singapore (`sin` = close-only, still 403) -> Fly Tokyo (`nrt`) -> `400 order_version_mismatch`, invariant across `neg_risk` and `signature_type` 1/2.

Cause: order path uses the archived `py-clob-client` (v1), whose EIP-712 order schema Polymarket's CLOB v2 (~Apr 30 2026) now rejects. Fix = migrate to `py-clob-client-v2` (https://github.com/Polymarket/py-clob-client-v2). v1 archived May 11 2026.

## 6. What is next — APPROVED step (boss: "Investigate + plan first")
Produce a migration plan ONLY — NO execution-path code change yet:
1. Study `py-clob-client-v2` API: `Signer`, `OrderBuilder`/order creation, `ClobClient`, `OrderArgs`/`CreateOrderOptions`, v2 EIP-712 order schema, install/package name.
2. Map against current usage in `integrations/clob/adapter.py` (`_build_signed_order`, `post_order`, `create_api_credentials`) and `__init__.py` (`_derived`, `ensure_clob_credentials`, `effective_credentials`, `get_clob_client`) + `pyproject.toml` dep (currently unpinned `py-clob-client`, ~line 19).
3. Deliver concrete migration plan + effort/risk. MAJOR tier (execution/capital path) — SENTINEL likely needed before merge.
Present plan; get approval before touching execution code.

---

## Key files
- `projects/polymarket/crusaderbot/integrations/clob/adapter.py` — order build/sign/post (breaks).
- `projects/polymarket/crusaderbot/integrations/clob/__init__.py` — cred derivation/cache (`_derived`), client factory.
- `projects/polymarket/crusaderbot/tests/staging/test_live_reconcile_staging.py` — harness; module-level `STAGING_WALLET_KEY` skipif.
- `.github/workflows/staging-proof-fly.yml` — zero-op runner from Tokyo.
- `.github/workflows/staging-proof.yml` — hosted/self-hosted; case5 path.
- `projects/polymarket/crusaderbot/pyproject.toml` (~line 19) — `py-clob-client` (unpinned).
- `projects/polymarket/crusaderbot/docs/runbooks/warp74-staging-proof.md` §6 — geoblock + Fly path.

## Hard constraints / safety
- Isolated Fly app holds NONE of prod secrets — proof can never touch real wallet. STAGING_* only.
- `ENABLE_LIVE_TRADING` guard never bypassed; Kelly a=0.25; asyncio only; secrets in `.env`.
- Must pass ALL 5 cases before any real-money LIVE flip. `allow_fills=true` (real USDC) stays gated.
- WARP•FORGE does NOT merge. Declare WARP branch, write forge report, surgical state-file updates, CHANGELOG append.
- Deferred (separate boss decision): prod `fly.toml primary_region=sin` is close-only — revisit before go-live.

## First action for new chat
Read-only investigation of `py-clob-client-v2` (WebFetch README + source) and the three `integrations/clob` files, then produce the plan. NO execution-code edits until boss approves the plan.
