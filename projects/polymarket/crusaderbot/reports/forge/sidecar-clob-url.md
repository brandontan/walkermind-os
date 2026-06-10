# WARP•R00T Forge Report — sidecar-clob-url

**Branch:** WARP/root-sidecar-clob-url
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** Rust order sidecar `POST /order` path against the real Polymarket CLOB (nrt/Tokyo, sig_type=3 Poly1271, allow_fills=false)
**Not in Scope:** Python CLOB clients, staging harness infrastructure, per-user-execution-wiring flag, ENABLE_LIVE_TRADING
**Suggested Next Step:** OWNER flip `USE_RUST_SIDECAR=1` in Fly after SENTINEL Step 5 validation passes (per-user-execution-wiring drift-injection test)

---

## 1. What Was Built

**Root cause fixed:** `DEFAULT_CLOB_URL` in `sidecar/src/main.rs` line 55 was `"https://clob-v2.polymarket.com"` — a wrong host that returns HTTP 405 Method Not Allowed on `POST /order`. All Python CLOB clients in this repo use `"https://clob.polymarket.com"`. The sidecar used its compiled-in default because `SIDECAR_CLOB_URL` is not set in the staging workflow environment.

**Fix:** One constant changed:
```rust
// Before (caused 405 on every POST /order)
const DEFAULT_CLOB_URL: &str = "https://clob-v2.polymarket.com";
// After (matches all Python CLOB clients)
const DEFAULT_CLOB_URL: &str = "https://clob.polymarket.com";
```

This closed the final blocker in a 3-fix chain that took 7 staging proof runs to diagnose:

| Run | Blocker | Fix |
|-----|---------|-----|
| #1 | Binary missing in `python:3.11-slim` | Moved Rust compile to GH runner (#1746) |
| #2 | LTO build hit 25-min timeout | Debug build + 45-min ceiling (#1745) |
| #3–#4 | In-machine Rust compile 22+ min on shared-cpu-1x | Binary pre-built on GH runner, downloaded via GH API (#1746) |
| #5 | `curl` missing in `python:3.11-slim` | Added `curl unzip` to `apt-get install` (#1747) |
| #6 | `ClobAPIError: 405 Method Not Allowed` on `POST /order` | Wrong `DEFAULT_CLOB_URL` → this fix (#1748) |
| **#7** | **PROOF_RESULT=PASS** | — |

---

## 2. Current System Architecture

The Rust sidecar (`sidecar/` crate) is a one-shot JSON-over-stdio binary wrapping `polymarket_client_sdk_v2=0.6.0-canary.1` (the only client with `SignatureType::Poly1271` + `sign_poly1271_order`). The Python bot invokes it as a subprocess via `RustSidecarClient` when `USE_RUST_SIDECAR=True`.

CLOB endpoint resolution (sidecar, unchanged):
```
SIDECAR_CLOB_URL env var (if set) → DEFAULT_CLOB_URL constant (now correct)
```

`RustSidecarClient._child_env()` passes `SIDECAR_CLOB_URL` only if explicitly configured. The staging workflow does not set it, so the binary's constant was the sole URL source — and the wrong constant caused every `POST /order` to hit the wrong host.

L1 auth remains plain EOA ECDSA (proven architecture: POLY_ADDRESS = signer EOA). The deposit wallet enters only as `funder` on the Poly1271-signed order. The GH runner compiles the binary in ~80s; the Fly machine downloads it via the GitHub Artifacts API using the `GITHUB_TOKEN` passed as `GH_TOKEN`.

---

## 3. Files Created / Modified

| File | Change |
|------|--------|
| `projects/polymarket/crusaderbot/sidecar/src/main.rs` | Line 55: `DEFAULT_CLOB_URL` fixed from `clob-v2.polymarket.com` to `clob.polymarket.com` |
| `projects/polymarket/crusaderbot/reports/forge/sidecar-clob-url.md` | This report (new) |
| `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` | Surgical update: timestamp, sidecar-clob-url added to COMPLETED, NEXT PRIORITY updated |
| `projects/polymarket/crusaderbot/state/CHANGELOG.md` | Append: sidecar-clob-url lane closure entry |

---

## 4. What Is Working

**PROOF_RESULT=PASS 27290744773-1** — run #7 (GitHub Actions run `27290744773`, attempt `1`):

- Step 6 "Build Rust sidecar on runner": completed in ~80s (GH ubuntu-latest, 4 cores, Rust pre-installed)
- Step 7 "Upload sidecar binary": completed in 3s (89 MB artifact)
- Step 8 "Export artifact ID": completed in 1s
- Step 9 "Run order-placing proof on Fly" (nrt/Tokyo, `python:3.11-slim`):
  - `SIDECAR_READY: -rwxr-xr-x 1 root root 89M` — binary downloaded and executable
  - `DIAG post_order_resp= {"orderID": "0xfdcae2a0...", "status": "live", "success": true}` — order accepted by the real CLOB
  - `PASSED` — pytest case3 assertion green
  - `PROOF_RESULT=PASS 27290744773-1`
- All 11 workflow steps: success

The complete Poly1271 order placement path is proven end-to-end:
```
GH runner compiles sidecar (80s)
  → artifact uploaded
  → Fly nrt machine downloads via GitHub API
  → sidecar binary invoked with SIDECAR_PRIVATE_KEY + SIDECAR_FUNDER + sig_type=3
  → L1 ECDSA auth (EOA) → L2 creds derived
  → Poly1271 order built + signed (deposit wallet as funder)
  → POST https://clob.polymarket.com/order → 200 {"status": "live", "success": true}
  → GET open orders → order present in readback
  → cancel_all → order gone
  → PROOF_RESULT=PASS
```

---

## 5. Known Issues

**None introduced by this fix.** The wrong URL was the sole root cause for run #6's 405.

Preexisting operational constraints (unchanged):
- `USE_RUST_SIDECAR` default `False` — still OFF in prod until SENTINEL Step 5 and per-user-execution-wiring validation complete
- `ENABLE_LIVE_TRADING` — owner-gated, untouched
- `SIDECAR_CLOB_URL` env override exists but is not set in any environment — the fixed constant is now the correct default for all deployments

---

## 6. What Is Next

1. **SENTINEL Step 5** (WARP🔹CMD schedule): Validate per-user-execution-wiring drift-injection — flip a staging user's `wallets.polymarket_deposit_wallet` to a wrong value, attempt a per-user order via the Rust sidecar (allow_fills=false), confirm `WalletIdentityMismatch` raised and broker call NEVER made.

2. **After SENTINEL green:**
   - `(a)` Run `backfill_deposit_wallets()` once on prod (migration 094 landed in #1736)
   - `(b)` Flip `USE_RUST_SIDECAR=1` in Fly secrets (single-wallet path)
   - `(c)` Flip `USE_PER_USER_EXECUTION=1` in Fly secrets
   - `(d)` Owner: `ENABLE_LIVE_TRADING` (independent gate, 5-guard activation sequence unchanged)

3. **Activation sequence** (unchanged, WARP-74 §4):
   `RISK_CONTROLS_VALIDATED` → `EXECUTION_PATH_VALIDATED` → `CAPITAL_MODE_CONFIRMED` → `ENABLE_LIVE_TRADING`
