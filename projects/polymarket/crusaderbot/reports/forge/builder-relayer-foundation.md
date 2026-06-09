# WARP•R00T Report — Builder Relayer Foundation (Custody Migration Chunk 1/4)

Branch: WARP/ROOT/builder-relayer-foundation
Date: 2026-05-28 17:30 Asia/Jakarta
Validation Tier: STANDARD
Claim Level: FOUNDATION
Validation Target: New `integrations/builder_relayer.py` wrapper around the Polymarket Builder relayer SDK, gated behind credentials + `USE_BUILDER_RELAYER` toggle. Not consumed by any active code path yet.
Not in Scope: Safe wallet deployment (Chunk 2), SafeCustody / gasless capital paths (Chunk 3), cutover (Chunk 4). The actual relayer credential acquisition (`polymarket.com/settings?tab=builder`) — owner-only.
Suggested Next Step: WARP🔹CMD review; Chunk 2 (Safe deploy + per-user safe_address column) after credentials are issued.

---

## 1. What was built

Chunk 1 of the gasless / Safe-proxy custody migration: a single, tested
integration surface for the Polymarket Builder relayer SDK, behind feature
flags. Pure foundation — no active runtime path consumes it yet. PAPER and the
shipped capital paths (`#1402` withdraw, `#1403` sweep) are unchanged.

Activation requires four things, all of which default OFF / None:
1. `POLY_BUILDER_API_KEY` / `_SECRET` / `_PASSPHRASE` from
   `polymarket.com/settings?tab=builder` (owner-only).
2. `USE_BUILDER_RELAYER=true` master toggle.

With any of these missing, `is_relayer_configured()` returns False and
`make_relayer_client()` raises a typed `BuilderRelayerUnavailable` — callers
never silently fall back.

## 2. Current system architecture

```
EXISTING (unchanged):
  CLOB orders → integrations/clob/adapter.py (signature_type=2 default;
                                              Safe-aware already)
  Capital paths → integrations/polygon_usdc.py (EOA master-funded,
                                                guarded OFF)

NEW (this lane — dormant until enrolled):
  integrations/builder_relayer.py
    ├─ is_relayer_configured()        — all-or-nothing gate
    ├─ build_builder_config()         — BuilderConfig from settings, or raise
    ├─ make_relayer_client(signer_pk) — RelayClient bound to a Safe signer
    ├─ relayer_sdk_importable()       — cheap probe (no creds needed)
    └─ class BuilderRelayerUnavailable(RuntimeError)
```

The wrapper soft-imports the SDK (mirrors how `integrations/clob/__init__.py`
handles `py-clob-client`) so a boot without the package never crashes the bot,
and centralises credential handling so every future consumer goes through one
audited factory — no scattered direct `RelayClient` constructions.

## 3. Files created / modified (full repo-root paths)

- CREATED: `projects/polymarket/crusaderbot/integrations/builder_relayer.py`
- CREATED: `projects/polymarket/crusaderbot/tests/test_builder_relayer.py` (9 tests)
- MODIFIED: `projects/polymarket/crusaderbot/config.py` (POLY_BUILDER_* creds; POLY_RELAYER_URL; USE_BUILDER_RELAYER; CUSTODY_MODE)
- MODIFIED: `requirements.txt` (`py-builder-relayer-client>=0.0.1`, `py-builder-signing-sdk>=0.0.2`)

## 4. What is working

- Full suite: 1836 passed (1827 + 9 new), 0 failures. ruff + py_compile clean.
- Unconfigured (default) — `is_relayer_configured()=False`; factories raise `BuilderRelayerUnavailable` with a clear remediation message.
- Partial credentials — still reported unconfigured (no half-arming).
- Fully configured — real SDK `BuilderConfig` / `RelayClient` objects returned without monkeypatching SDK internals.
- SDK availability probe (`relayer_sdk_importable`) never raises; returns True here (both packages installed).

## 5. Known issues

- None functional. Future-phase prerequisites (not blockers for this PR):
  * Builder credentials must be obtained by the owner (Polymarket Builder Program).
  * Safe wallet deployment + per-user `safe_address` column come in Chunk 2.

## 6. What is next

- Chunk 2 — Safe deploy + per-user safe_address column + deposit watcher learns Safe addresses.
- Chunk 3 — SafeCustody implementations of transfer_usdc + sweep via relayer.execute() (replaces master-funded gas top-up when CUSTODY_MODE='safe').
- Chunk 4 — Staged cutover to CUSTODY_MODE='safe' with rollback path.

---

Validation Handoff (NEXT PRIORITY in PROJECT_STATE):

WARP🔹CMD review required. STANDARD tier — SENTINEL not allowed per CLAUDE.md
on STANDARD; reclassify to MAJOR if a deeper validation is desired.
Source: projects/polymarket/crusaderbot/reports/forge/builder-relayer-foundation.md
