# gasless-custody — Safe-proxy custody cutover via the Builder relayer

Role: WARP•R00T (owner-authorized via AskUserQuestion 2026-06-12: "Build gasless custody lane")
Branch: WARP/root-gasless-custody
Date: 2026-06-12 12:05 Asia/Jakarta

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : relayer credential aliasing; custody-aware deposit-address surfaces; safe-address backfill trigger; boot custody-posture evidence; CUSTODY_MODE=safe flip readiness
Not in Scope      : SafeCustody/relayer transfer internals (pre-existing, #1734/#1761-hardened, byte-unchanged), order execution, risk constants, the stranded $3 on user EOAs (recovery note below)
Suggested Next    : merge on CI green -> CD deploy -> WARP•R00T sets CUSTODY_MODE=safe + USE_BUILDER_RELAYER=true + SWEEP_ONCHAIN_ENABLED=true (Fly secrets; authorized by lane choice) -> verify boot custody line -> owner taps Backfill -> deposits to the displayed Safe are fully gasless

## 1. What was built

CONTEXT: withdrawal/sweep completion was blocked on the master EOA pool
holding MATIC for gas (plus SWEEP_ONCHAIN_ENABLED never set). Owner chose the
gasless path over sending POL: cut custody over to the Polymarket Safe-proxy +
Builder-relayer mode that the repo built and parked ("'safe' enabled after
Phase 4 cutover"). In safe mode the relayer pays ALL gas: user-Safe → master-
Safe sweeps and master-Safe → user withdrawal payouts move USDC only.

INVESTIGATION FINDINGS (why safe mode could never have been flipped as-is):
1. CREDENTIAL NAMING WALL — the relayer reads `POLY_BUILDER_API_KEY/SECRET/
   PASSPHRASE`; prod provisions the same Builder Program credential set as
   `POLYMARKET_BUILDER_*` (order attribution). `is_relayer_configured()` was
   permanently false in prod; the `RELAYER_API_KEY*` Fly secrets are inert
   (referenced nowhere in code).
2. NO BACKFILL TRIGGER — `wallet.safe.backfill_safe_addresses` (pure LOCAL
   CREATE2 via `RelayClient.get_expected_safe`, no network/funds) had no
   caller anywhere.
3. WRONG DEPOSIT SURFACE — both deposit-address surfaces (Telegram /wallet ×3
   sites + WebTrader /wallet) hardcoded the EOA; in safe mode users must
   deposit to their SAFE (the watcher already watches both columns).

BUILT:
- `config._alias_poly_builder_creds` — populates POLY_BUILDER_* from
  POLYMARKET_BUILDER_* (order-independent of the existing secret-spelling
  alias; canonical wins). The relayer lights up from existing prod secrets.
- `wallet.custody.effective_deposit_address(row)` — single custody-aware
  display rule: safe mode → safe_address (EOA fallback while unbackfilled);
  eoa mode unchanged. Wired into Telegram (3 sites, `vault.get_wallet`
  widened to fetch safe_address) and WebTrader `/wallet`.
- Admin "Backfill deposit wallets" button now ALSO runs
  `backfill_safe_addresses()` (idempotent; response + audit carry both
  summaries).
- Boot validation logs one custody-posture line every deploy (CUSTODY_MODE /
  relayer_configured / sweep_onchain / master Safe address — local derive,
  no secrets) and flags safe-mode-without-relayer as a boot problem.

## 2. Current system architecture (relevant slice)

```
CUSTODY_MODE=eoa  (current prod): master EOA pays gas  -> blocked on MATIC
CUSTODY_MODE=safe (this lane):    relayer pays gas     -> zero MATIC anywhere
  deposits -> user SAFE (displayed by effective_deposit_address; watcher watches it)
  sweep    -> SafeCustody.sweep: user Safe -> master Safe   (relayer, USDC only)
  payout   -> SafeCustody.transfer: master Safe -> user dest (relayer, USDC only)
  gates    -> EXECUTION_PATH_VALIDATED + USE_BUILDER_RELAYER + creds
              + SWEEP_ONCHAIN_ENABLED (sweeps); every failure typed + refunded
```

## 3. Files created / modified

- projects/polymarket/crusaderbot/config.py — POLY_BUILDER_* alias validator
- projects/polymarket/crusaderbot/wallet/custody.py — effective_deposit_address
- projects/polymarket/crusaderbot/wallet/vault.py — get_wallet fetches safe_address
- projects/polymarket/crusaderbot/bot/handlers/wallet.py — 3 display sites use the helper
- projects/polymarket/crusaderbot/webtrader/backend/router.py — /wallet custody-aware; admin backfill runs safe backfill
- projects/polymarket/crusaderbot/main.py — boot custody-posture line + safe-mode guard
- projects/polymarket/crusaderbot/tests/test_gasless_custody.py — new (12 tests)
- projects/polymarket/crusaderbot/tests/test_admin_backfill_trigger.py — harness extended
- projects/polymarket/crusaderbot/reports/forge/gasless-custody.md + state files

## 4. What is working

- FULL SUITE 3471 passed / 11 skipped (+12); ruff clean.
- New tests: alias from prod secret names (incl. short-secret spelling chain,
  canonical-wins), custody-aware display (4 cases + both-surfaces source pin),
  backfill extension pin, boot problem on safe-without-relayer / clean eoa /
  derive-failure-is-evidence-only.

## 5. Known issues

- The $3.00 already on the owner's deposit EOA stays there (an EOA needs gas
  to move funds in any architecture). Recovery options: one-time ~0.1 POL to
  that EOA, or treat as test dust. New deposits to the Safe are unaffected.
- SafeCustody relayer round-trip is broker-validated infrastructure (WARP-74
  staging ran sig-2 GNOSIS_SAFE flows) but THIS app's first live relayed sweep
  happens with the first real Safe deposit — fail-closed (typed refusal +
  refund) if Polymarket rejects, surfaced by the watch/sweep logs.
- Per-user LIVE ORDER funding (polymarket_deposit_wallet as funder) is a
  separate flow from custody Safes — unchanged by this lane.

## 6. What is next

1. Merge on CI green -> CD deploy.
2. WARP•R00T ops (authorized): `fly secrets set CUSTODY_MODE=safe
   USE_BUILDER_RELAYER=true SWEEP_ONCHAIN_ENABLED=true` -> boot log must show
   `custody posture — CUSTODY_MODE=safe relayer_configured=True ... master_safe=0x…`.
3. Owner: tap Admin Backfill (fills safe_address ×6 + deposit wallets) ->
   /wallet now displays the SAFE address -> deposit USDC.e there ->
   sweeps + withdrawals run gaslessly. No MATIC ever needed.
