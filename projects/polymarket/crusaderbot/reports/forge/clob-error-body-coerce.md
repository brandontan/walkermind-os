# clob-error-body-coerce — CLOB v2 order-error formatter crash fix

Role: WARP•R00T
Branch: WARP/root-clob-error-body-coerce
Validation Tier: MAJOR (CLOB order-path error plumbing)
Claim Level: NARROW INTEGRATION (the v2 backend HTTP-error mapping path)
Validation Target: ClobAPIError formats any non-str body (notably the
  py-clob-client-v2 dict `error_msg`) without raising, and surfaces the real
  broker reason as a typed ClobAPIError.
Not in Scope: the operator wallet-registration blocker (RC-1, the underlying
  400); running the full v2 staging proof; the v1/legacy retirement lane; GTD
  support in ClobV2Client.
Suggested Next Step: WARP🔹CMD — after the operator registers the throwaway
  staging wallet through Polymarket, re-dispatch the v2 staging proof
  (case3 → case2 → case4, use_clob_v2=true, allow_fills=false).

---

## 1. What was built

A one-line-class root-cause fix plus a regression test, closing the formatter
crash that the first live WARP-74 v2 staging proof exposed.

The first dispatch of the v2 cutover staging proof (GitHub Actions run
`27150856603`, case3, `use_clob_v2=true`, region `nrt`, `signature_type=1`,
`allow_fills=false`) failed. The job-summary CLOB-backend row confirmed the v2
toggle took (`py-clob-client-v2 (USE_CLOB_V2)`), so the run was valid. The
pytest failure had two stacked causes:

- The live CLOB returned HTTP 400 `{"error": "maker address not allowed,
  please use the deposit wallet flow"}` — i.e. the throwaway staging wallet is
  not registered through Polymarket's deposit-wallet flow (operator blocker,
  RC-1, out of scope for this code lane).
- While mapping that broker error, the adapter CRASHED with
  `TypeError: unhashable type: 'slice'`, masking the real 400 (code bug, RC-2,
  fixed here).

Root cause of RC-2: `py_clob_client_v2.PolyApiException` exposes `error_msg` as
the parsed JSON **dict** (`{"error": "..."}`). `ClobV2Client._map_error` reads
`msg = getattr(exc, "error_msg", None) or str(exc)` and forwards it as
`body=msg` into `ClobAPIError`. `ClobAPIError.__init__` then formatted the
message with `(body or '')[:200]` — slicing a dict raises
`TypeError: unhashable type: 'slice'`. The declared `body: str` contract was
violated at the call site and the sink did not defend against it.

Fix (at the contract boundary, covering every caller): `ClobAPIError.__init__`
now coerces `body` to text exactly once and stores/formats the coerced value.
A raw `bytes` body (HTTP response bodies are bytes) is decoded as UTF-8 with
replacement rather than `str()`-wrapped (which would leave a literal `b'...'`
excerpt in the operator-facing message) — adopted from the Gemini review on
PR #1724:

```python
if isinstance(body, bytes):
    body_text = body.decode("utf-8", errors="replace")
elif body is None:
    body_text = ""
else:
    body_text = str(body)
self.body = body_text
super().__init__(message or f"CLOB {status_code} on {path}: {body_text[:200]}")
```

This makes `.body` honour its documented `str` contract for every caller —
the v2 mapper, the v1 `ClobAdapter`, and the local-signing `ClobAuthError`
path — without changing `_map_error`. Any future Polymarket 4xx/5xx via the v2
backend now re-raises as a clean typed `ClobAPIError` carrying the broker
reason, instead of a `TypeError` that buries it.

## 2. Current system architecture (relevant slice)

```
ClobV2Client.post_order / get_order / cancel_* (integrations/clob/v2_client.py)
  └─ SDK call raises py_clob_client_v2.PolyApiException
         .status_code = 400
         .error_msg   = {"error": "maker address not allowed, ..."}   # dict
  └─ _map_error(exc, ctx):
         status = 400
         msg    = exc.error_msg            # dict (was forwarded verbatim)
         return ClobAPIError(status_code=400, path=ctx, body=msg)
  └─ ClobAPIError.__init__:
         body_text = "" if body is None else str(body)   # <-- FIX: coerce once
         self.body = body_text
         super().__init__(... f"{body_text[:200]}")       # no longer slices a dict
```

The error taxonomy (`ClobError` → `ClobAPIError` → `ClobAuthError` /
`ClobRateLimitError` / `ClobServerError`, plus the timeout/network/circuit
classes) is unchanged. Only the body-formatting step inside the base
`ClobAPIError` constructor is hardened.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/integrations/clob/exceptions.py` — coerce
  `body` to text once in `ClobAPIError.__init__`; `.body` now always a `str`.
- `projects/polymarket/crusaderbot/tests/test_clob_v2.py` — new regression
  test `test_error_mapping_dict_body_does_not_crash_formatter` reproducing the
  production `PolyApiException` shape (status_code=400 + dict `error_msg`) and
  asserting a clean `ClobAPIError` whose `.body` and message preserve the
  broker reason.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — Status head,
  `[COMPLETED]`, `[NEXT PRIORITY]` (v2 proof gate), `[KNOWN ISSUES]` (operator
  wallet blocker) updated.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane closure entry.
- `projects/polymarket/crusaderbot/reports/forge/clob-error-body-coerce.md` —
  this report.

## 4. What is working

- `python -m py_compile` clean on both touched source files.
- `pytest tests/test_clob_v2.py tests/test_clob_error_classification.py` →
  **29 passed** (warnings are pre-existing asyncio-marker noise, unrelated).
  Includes `test_clob_api_error_decodes_bytes_body` (bytes body decoded, not
  `str()`-wrapped; non-UTF-8 falls back to replacement, never raises).
- `ruff check` clean on both touched source files.
- The new regression test passes on the fixed code; the pre-fix formatter was
  characterised to crash on the identical dict input
  (`(body or '')[:200]` → `TypeError: unhashable type: 'slice'`), confirming
  the test guards the real defect.
- The fix is caller-agnostic: v2 mapper, v1 adapter, and local-signing paths
  all now get a guaranteed-`str` `.body`.

## 5. Known issues

- RC-1 (operator, NOT code): the v2 staging proof case3 cannot pass until the
  throwaway staging wallet is registered through Polymarket's deposit-wallet
  flow — the 400 "maker address not allowed" is a wallet-config rejection, not
  a signing failure. The v2 signing chain reached the live CLOB and the signed
  POST was accepted by the endpoint; only wallet registration + readback
  remain. Tracked in PROJECT_STATE `[KNOWN ISSUES]`.
- This lane does not run the proof itself (needs an allowed-region egress + a
  registered wallet) — re-dispatch is the next gate.

## 6. What is next

- Operator registers the staging wallet on Polymarket.
- Re-dispatch the v2 staging proof case3 → case2 → case4 (one at a time,
  `use_clob_v2=true`, `nrt`, `signature_type=1`, `allow_fills=false`); accept
  when all three PASS with the job-summary CLOB-backend row =
  `py-clob-client-v2`.
- On green: WARP🔹CMD decides the `USE_CLOB_V2=1` prod cutover (live still
  separately gated by `ENABLE_LIVE_TRADING`), then the v1/legacy retirement
  lane.
