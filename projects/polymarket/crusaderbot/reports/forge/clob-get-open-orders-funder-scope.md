# WARP-74 — get_open_orders funder-scoping (F1 pattern) + readback diagnostics

Validation Tier: MAJOR (CLOB execution backend — open-orders read; dormant under USE_PYSDK_CLOB=False)
Claim Level: NARROW INTEGRATION (fix + unit tests; live confirmation via the next dispatch, which also emits root-cause diagnostics)
Validation Target: a placed proxy-wallet order is visible to `get_open_orders` on the pysdk CLOB v2 backend.
Not in Scope: GTD/FOK/FAK/market orders; LIVE flip.
Suggested Next Step: dispatch `staging-proof-fly.yml` case3 (nrt, defaults) — the diagnostics confirm the fix or pinpoint the cause in one run.

---

## 1. Problem

Order placement on the CLOB v2 backend is PROVEN (run #9: built+signed+posted+
ACCEPTED). But case3's precondition — `get_open_orders` showing the just-placed
order — failed even after a full 41s bounded poll (run #10), market-scoped AND
unscoped. Not latency, and not a fill (BUY at 0.10 can't cross a verified 0.15+
ask).

## 2. Root cause (leading hypothesis) + fix

`get_open_orders` called `client.list_open_orders()` with **no owner scope**.
Proxy wallets (signature_type 1/2 + funder — the staging/prod config) record their
orders under the **FUNDER** address, not the EOA signer, so a list keyed on the
authenticated EOA returns nothing. This is the SAME defect class already fixed for
`get_fills` (F1, maker_address=funder).

Fix (`integrations/clob/sdk_client.py`): new `_owner_kwargs(fn)` resolves the owner
to `self._funder or self._address` and passes it under whichever owner-style kwarg
the installed pysdk `list_open_orders` exposes (`maker_address`/`owner`/…),
detected via `inspect.signature` so it is correct regardless of the exact param
name and falls back to default auth scoping if none is supported. `get_open_orders`
now scopes every query by the funder.

This is a genuine prod-correctness fix (the reconciler/drift/kill-switch all read
open orders for a proxy-funded bot), consistent with the get_fills F1 fix.

## 3. Diagnostics (same dispatch — conclusive either way)

Per owner directive, the proof run also logs (pytest `-s` so they surface on PASS
and FAIL):
- resolved `market_id`, `token_id`, `signature_type`
- `signer_address` vs `funder_address`
- `post_order` response (orderID + status)
- RAW `get_open_orders` payloads — market-scoped AND unscoped — before filtering

If the fix works, the run goes green; if not, these logs give the root cause
(fill vs owner-scoping vs id-alias) without another cycle.

## 4. Files modified (full repo-root paths)

- `projects/polymarket/crusaderbot/integrations/clob/sdk_client.py` — `_owner_kwargs`; `get_open_orders` funder-scoped.
- `projects/polymarket/crusaderbot/tests/test_clob_pysdk.py` — 2 unit tests (funder scope + EOA fallback).
- `projects/polymarket/crusaderbot/tests/staging/test_live_reconcile_staging.py` — case3 + `_place_resting_buy` diagnostics.
- `.github/workflows/staging-proof-fly.yml` — pytest `-s` so diagnostics stream to the machine log.
- `projects/polymarket/crusaderbot/reports/forge/clob-get-open-orders-funder-scope.md` — this report.
- `state/PROJECT_STATE.md`, `state/CHANGELOG.md` — lane sync.

## 5. What is working

- `_owner_kwargs` introspects safely; existing `_FakeSecureClient` (**kwargs) → no owner passed → existing tests unchanged.
- New unit tests assert funder scoping + EOA fallback. `py_compile` + YAML clean.
- Dormant: `USE_PYSDK_CLOB` default False; prod path unchanged.

## 6. Known issues / boundaries

- If the installed pysdk `list_open_orders` auto-scopes by auth and exposes no
  owner kwarg, `_owner_kwargs` returns {} (unchanged behaviour) — the diagnostics
  then reveal whether the order is under the funder (needs an auth-as-funder
  approach) or an id-alias mismatch. One dispatch decides.

## 7. What is next

1. Dispatch case3 (nrt, defaults) → expect PASS, else read the DIAG logs.
2. `all-broker` for cases 1–2–4; confirm signature_type proxy inference; close GTC-only gap; pass all 5 before any LIVE flip.

---

Validation Handoff (NEXT PRIORITY): WARP•SENTINEL validation required for CLOB v2 get_open_orders funder-scoping before LIVE. Source: projects/polymarket/crusaderbot/reports/forge/clob-get-open-orders-funder-scope.md — Tier: MAJOR (dormant).
