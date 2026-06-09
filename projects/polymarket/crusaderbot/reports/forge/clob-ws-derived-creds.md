# WARP•R00T FORGE REPORT — clob-ws-derived-creds

Branch: `WARP/ROOT/clob-ws-derived-creds`
Role: WARP•R00T (live-readiness bug, owner-reported via Sentry/Fly logs)
Validation Tier: **MAJOR** (live CLOB WebSocket auth — fill/order-update path)
Claim Level: NARROW INTEGRATION
Validation Target: CLOB user WebSocket authenticates with auto-derived credentials (no reconnect loop).
Not in Scope: REST order path (already correct); the funder/sig-type operator config.
Suggested Next Step: WARP🔹CMD review + merge → deploy → confirm WS stops flapping.

---

## 1. What was fixed

Production Fly logs showed the CLOB user WebSocket flapping:
```
WARNING clob.ws: ws: session ended with error: no close frame received or sent
INFO    clob.ws: ws: reconnect attempt 2 in 0.94s   (repeating)
```

Root cause: `ws.py:_send_subscribe` built the subscribe auth frame by reading
`settings.POLYMARKET_API_KEY/SECRET/PASSPHRASE` **directly**. When credentials
are **auto-derived** (env vars unset, derived from `POLYMARKET_PRIVATE_KEY` and
cached in `clob.__init__._derived`), those settings are empty — so the WS sent
an empty auth frame, the broker rejected/closed the socket, and it reconnected
forever. The REST client (`get_clob_client`) already resolved `env OR _derived`
correctly; the WS path did not.

Fix: extracted the resolution into `clob.effective_credentials()` (env first,
then `_derived`) and used it in BOTH `get_clob_client` (refactor, same result)
and `ws.py:_send_subscribe` (via a deferred import to avoid the package
`__init__ → ws` circular import).

## 2. Current system architecture

```
ensure_clob_credentials()  → derives creds → clob.__init__._derived
effective_credentials(s)   → env vars OR _derived   ← single source of truth
   ├─ get_clob_client()      (REST orders)
   └─ ws._send_subscribe()   (user WS: fills / order updates)   ← was bypassing _derived
```

## 3. Files modified (full repo-root paths)

- `projects/polymarket/crusaderbot/integrations/clob/__init__.py` (add `effective_credentials`; `get_clob_client` uses it)
- `projects/polymarket/crusaderbot/integrations/clob/ws.py` (`_send_subscribe` resolves env-or-derived via deferred import)
- `projects/polymarket/crusaderbot/tests/test_clob_ws_creds.py` (4 tests, new)

## 4. What is working

- WS subscribe now sends the derived creds when env is unset (verified by test).
- REST path unchanged (refactor is behaviour-preserving).
- No circular import (verified).
- 158 clob tests pass; full suite **2030/2030**; ruff + py_compile clean.

## 5. Known issues

- Not a code issue: live trading also requires the operator to set
  `POLYMARKET_FUNDER_ADDRESS` to the wallet that actually holds USDC for the
  configured account (Magic account `0xe82c…`), and to opt a user into live.

## 6. What is next

Merge → deploy → confirm the `clob.ws` reconnect-loop warnings stop and the WS
authenticates. Then the live test-order validates the full path end-to-end.
