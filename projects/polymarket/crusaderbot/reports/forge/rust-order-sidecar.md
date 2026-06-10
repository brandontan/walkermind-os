# rust-order-sidecar

**Role:** WARP•R00T
**Branch:** WARP/root-rust-order-sidecar
**Validation Tier:** MAJOR
**Claim Level:** FOUNDATION

## 1. What was built

The owner-authorized Rust-SDK sidecar lane — path 2 of the three documented options for the EIP-7702 deposit-wallet L1 auth wall (the LAST code-side blocker for live orders on migrated Polymarket accounts, including the owner's).

Root cause recap: Polymarket migrated Magic/email accounts to EIP-7702 deposit wallets; `py-clob-client-v2` cannot sign orders for them (upstream #52/#53/#64/#70/#71, all OPEN; our own corrected-L1 attempt in PR #1727 hit `401 Invalid L1 Request headers` — the server's ERC-7739 verification is closed-source). The official Rust SDK's canary line (`polymarket_client_sdk_v2 = 0.6.0-canary.1`) is the only client carrying `SignatureType::Poly1271 = 3` plus `sign_poly1271_order` (the wrapped EIP-1271 order signature).

**Key architecture finding:** the Rust SDK keeps **L1 auth = plain EOA ECDSA** (`POLY_ADDRESS` = signer EOA, standard `ClobAuth` EIP-712 — see vendored `src/auth.rs::l1::create_headers`) and the deposit wallet enters only as the **funder on the Poly1271-signed order**. This is the OPPOSITE of what PR #1727 tried (deposit-wallet-bound L1 with a wrapped ClobAuth) — and explains why that attempt was rejected. The wall was never the L1 encoding; it was that the L1 should never have been deposit-wallet-bound at all.

**Incidental broker proof during development:** a smoke test of the compiled sidecar (intended to exercise the unknown-action error path) authenticated against the real CLOB and minted L2 credentials with a throwaway key — the Rust L1 derive path works from this environment, zero iterations needed.

## 2. Current system architecture

```
Python bot (risk gate FIRST — unchanged, RISK before EXECUTION always)
   └─ get_clob_client(s)
        ├─ USE_RUST_SIDECAR=1  → RustSidecarClient   ★ NEW (highest precedence)
        ├─ USE_CLOB_V2=1       → ClobV2Client
        ├─ USE_PYSDK_CLOB=1    → PolymarketSdkClient
        └─ default             → ClobAdapter / MockClobClient

RustSidecarClient (integrations/clob/rust_sidecar.py)
   • ClobClientProtocol surface — callers unchanged
   • ONE subprocess per call, stateless (no daemon, no zombie loops)
   • breaker + limiter wrap each invocation exactly like an HTTP call
   • secrets via child env (SIDECAR_PRIVATE_KEY / SIDECAR_FUNDER /
     SIDECAR_API_*) — NEVER argv (argv is world-readable in /proc)
   • ok=false+exit0 → ClobAPIError (broker said no)
     exit≠0 / bad JSON / timeout → ClobNetworkError (infra)
     missing binary → ClobConfigError

order-sidecar (sidecar/ crate, Rust)
   stdin  {"action": "...", "params": {...}}
   stdout {"ok": true, "result": ...} | {"ok": false, "kind", "error"}
   actions: derive_creds, place_order, cancel_order, cancel_all,
            get_open_orders, get_order, get_trades
   • Client::new(clob-v2).authentication_builder(signer)
       .funder(deposit_wallet).signature_type(Poly1271).authenticate()
   • L2 creds via env skip the create/derive round-trip
   • action validated BEFORE any env read / network call
   • response JSON carries orderID + order_id + id aliases so the Python
     side reuses the proven alias-tolerant readers

Dockerfile Stage 1b (rust:1-slim)
   → cargo build --release → /usr/local/bin/order-sidecar in the runtime image
   → dep-cache layer via stub-main pre-build (source edits don't recompile deps)
```

## 3. Files created / modified

* **NEW** `projects/polymarket/crusaderbot/sidecar/Cargo.toml` — pinned `polymarket_client_sdk_v2 = "=0.6.0-canary.1"` (clob feature only), release profile LTO+strip.
* **NEW** `projects/polymarket/crusaderbot/sidecar/Cargo.lock` — committed for reproducible builds.
* **NEW** `projects/polymarket/crusaderbot/sidecar/src/main.rs` — the JSON-stdio binary (7 actions). Hand-mapped response JSON (SDK structs are Deserialize-only).
* **NEW** `projects/polymarket/crusaderbot/integrations/clob/rust_sidecar.py` — `RustSidecarClient` implementing `ClobClientProtocol`; per-call subprocess; timeout-kill + reap; typed error mapping; `_decimal_str` so price/size reach the broker as decimal strings (never float dust).
* **MODIFIED** `projects/polymarket/crusaderbot/integrations/clob/__init__.py` — `USE_RUST_SIDECAR` branch in `get_clob_client`, highest precedence, fail-fast on missing key/funder.
* **MODIFIED** `projects/polymarket/crusaderbot/config.py` — `USE_RUST_SIDECAR: bool = False` + `RUST_SIDECAR_PATH: str = "/usr/local/bin/order-sidecar"`.
* **MODIFIED** `projects/polymarket/crusaderbot/Dockerfile` — Stage 1b builds the sidecar; binary lands at the `RUST_SIDECAR_PATH` default.
* **MODIFIED** `projects/polymarket/crusaderbot/.dockerignore` + repo `.gitignore` — exclude `sidecar/target/`.
* **NEW** `projects/polymarket/crusaderbot/tests/test_rust_sidecar.py` — 18 hermetic tests (fake python sidecar speaking the protocol; no Rust toolchain needed in CI).

## 4. What is working

* `cargo build` + `cargo build --release` + `cargo clippy` — zero warnings.
* Sidecar protocol smoke-tested: invalid JSON → exit 2; unknown action → clean `ok=false` (validated before any network call); empty env → clean config errors.
* **Real-broker L1 derive proven incidentally** (see §1) — credentials minted against `clob-v2.polymarket.com` with a throwaway key during the error-path smoke test.
* 18/18 hermetic Python tests: env-not-argv secret passing pinned; ok=false→`ClobAPIError`; exit≠0→`ClobNetworkError`; garbage stdout→`ClobNetworkError`; missing binary→`ClobConfigError`; hang killed at timeout + reaped; GTD refused pre-spawn; market-scoped cancel_all refused loudly (account-wide cancel when one market was asked would cancel MORE than requested); factory precedence (sidecar > v2 > pysdk) pinned; factory funder fail-fast pinned; decimal rendering pinned (`0.1+0.2 → "0.3"`).
* 37/37 clob_v2 + user_clob regression pass; ruff clean on all Python files.

## 5. Known issues

* **Order placement not yet broker-proven for Poly1271.** The L1 derive is proven; an actual deposit-wallet order (allow_fills=false staging proof) has NOT run — that needs the owner's deposit-wallet key on the staging harness, same WARP-74 pattern. The flag stays OFF until that proof.
* **Canary pin.** `0.6.0-canary.1` is a pre-release. Pinned exact; bump only with a fresh proof. If upstream yanks it, the lockfile + vendored registry cache keep CI green; a vendoring lane is the escape hatch.
* **GTD unsupported** (matches the ClobV2Client limitation — needs an expiration arg the Protocol doesn't carry).
* **Market-scoped cancel_all unsupported** (SDK has `cancel_market_orders`; small follow-up; refusing loudly is the safe v1).
* **Per-call subprocess** = ~10ms spawn + full auth round-trip per order when L2 creds aren't passed. With creds in env (the factory passes them when available) the auth round-trip is skipped. A persistent daemon mode is a measured-need follow-up, not a default.
* **CI does not build the Rust crate** — the Dockerfile does (deploy-time) and the hermetic tests don't need it. A `cargo build` CI job is a small follow-up if drift becomes a concern.

## 6. What is next

1. **Staging proof** (owner-gated, WARP-74 pattern): dispatch the staging harness with `USE_RUST_SIDECAR=1` + the deposit-wallet key, `allow_fills=false` — prove build→sign(Poly1271)→POST→accept→readback→cancel on the real broker.
2. On green: flip `USE_RUST_SIDECAR=1` in Fly for the single-wallet path. Live trading still independently gated by `ENABLE_LIVE_TRADING` + the 5 guards.
3. Per-user lane convergence: `user_client.py` Step 4 can construct `RustSidecarClient` per user (key from vault, funder from `wallets.polymarket_deposit_wallet` — Step 2 already persisted it).
4. Follow-ups as needed: GTD expiration arg, market-scoped cancel, CI cargo job, daemon mode.

## Metadata

* **Validation Tier:** MAJOR
* **Claim Level:** FOUNDATION
* **Validation Target:** sidecar protocol correctness; wrapper process/error handling; factory precedence + fail-fasts; secret hygiene (env-not-argv, no secret on stdout); decimal rendering.
* **Not in Scope:** the staging broker proof (owner-gated); flipping USE_RUST_SIDECAR; per-user wiring (Step 4 lane); GTD; market-scoped cancel; daemon mode; risk constants / Kelly / ENABLE_LIVE_TRADING / kill switch / strategy entry-exit (all untouched).
* **Suggested Next Step:** owner dispatches the staging proof with `USE_RUST_SIDECAR=1` (the harness already honours backend env toggles per runbook §7 pattern; the sidecar needs a one-line toggle added to `_staging_settings` — included in the staging dispatch lane).
