# WARP-74 — CLOB live order-signing Signer kwarg fix

Branch: WARP/clob-signer-key-fix
Role: WARP•FORGE (owner-directed during WARP-74 staging proof)
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: `ClobAdapter._build_signed_order` constructs a py-clob-client `Signer` with the correct keyword so live order signing (`post_order`) succeeds against py-clob-client 0.34.6.
Not in Scope: risk gate, Kelly, ENABLE_LIVE_TRADING / USE_REAL_CLOB guards, order economics, signature-type selection.
Suggested Next Step: WARP•SENTINEL validation of the live order-signing path before any real-money LIVE flip; complete the WARP-74 staging proof (case3 → case5) on a proxy wallet (signature_type=1).

## 1. What was built

One-line correctness fix to the live order-signing path. The staging proof
(WARP-74 Lane 2, run #4) exercised real order placement for the first time and
hit:

```
integrations/clob/adapter.py:471  _build_signed_order
    signer = Signer(key=..., chain_id=...)
E   TypeError: Signer.__init__() got an unexpected keyword argument 'key'
```

`py_clob_client.signer.Signer.__init__(self, private_key: str, chain_id: int)`
(verified against py-clob-client source / 0.34.6) takes `private_key`, never
`key`. The adapter passed `key=` → every signed-order build raised `TypeError`.

Fix: `Signer(key=...)` → `Signer(private_key=...)` at adapter.py:471. No other
occurrence (line 174 is the distinct `ClobAuthSigner`, already correct).

## 2. Current system architecture

Unchanged. `post_order` → `_build_signed_order` → `Signer(private_key, chain_id)`
→ `OrderBuilder(signer, sig_type, funder)` → signed order to the CLOB. Only the
keyword name changed; the value (`self._signer.private_key`) and call shape are
identical.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/integrations/clob/adapter.py` (Signer kwarg)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

Created:
- `projects/polymarket/crusaderbot/reports/forge/clob-signer-key-fix.md`

## 4. What is working

- Latent-bug confirmation: the signing path was never exercised before because
  the bot runs paper-only (USE_REAL_CLOB=False); the staging proof surfaced it.
- `key` → `private_key` verified the only valid kwarg for the installed library.
- Gated behind USE_REAL_CLOB — paper mode never reaches this code; no change to
  paper behavior.

## 5. Known issues

- Live order signing has NOT yet completed end-to-end on a real wallet — this fix
  unblocks the `Signer` construction; the next staging-proof run validates the
  full place → cancel path. A Magic-link Polymarket account is a PROXY wallet, so
  the run must use signature_type=1 (POLY_PROXY) + STAGING_FUNDER_ADDRESS (the
  proxy address), not signature_type=0.
- MAJOR / execution path: WARP•SENTINEL validation recommended before relying on
  this for any real-money LIVE trade.

## 6. What is next

- Re-run WARP-74 staging proof case3 with signature_type=1 (proxy) once the
  Magic-link wallet secret + funder address are set.
- WARP•SENTINEL: validate the live order-signing + reconcile path (MAJOR).
- Proceed through case2/case1/case4/case5, then file the evidence bundle.
