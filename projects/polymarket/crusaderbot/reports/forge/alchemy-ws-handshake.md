# WARP•R00T — M3: Alchemy WS Health Check Full Handshake

Branch: WARP/ROOT/alchemy-ws-handshake
Role: WARP•R00T
Date: 2026-05-27
Validation Tier: STANDARD (monitoring accuracy; not trading/risk/capital core)
Claim Level: NARROW INTEGRATION
Validation Target: `monitoring/health.py::check_alchemy_ws` now performs a real WS handshake + JSON-RPC probe
Not in Scope: other health checks; alerting thresholds; the WS subscription runtime (scheduler.ws_connect)
Suggested Next Step: WARP🔹CMD review; deploy picks it up via CD

---

## 1. What was built

Replaced the TCP-only `check_alchemy_ws` probe with a full WebSocket
handshake plus a single `eth_blockNumber` JSON-RPC round-trip. The check now
fails when the endpoint completes TCP/TLS but cannot actually serve the WS
RPC protocol (bad upgrade, auth rejection, protocol error) — closing the M3
gap where `/health` could read green on a broken WS.

## 2. Current system architecture

`/health` runs four checks in parallel under a 3s-per-check timeout
(`run_health_checks`). `check_alchemy_ws` previously only opened a raw socket
(`asyncio.open_connection`) and closed it — TCP reachability only. Now it
opens a real `websockets.connect(...)` session (TLS + HTTP Upgrade), sends
`eth_blockNumber`, and validates a `result` field, mirroring
`check_alchemy_rpc`. The existing `_with_timeout` wrapper still catches every
exception and sanitises it to the class name only (Alchemy embeds the API key
in the URL path, so URL/secret leakage is prevented). Soft import of
`websockets` matches the pattern in `integrations/clob/ws.py` so test
environments without the dep degrade to a clear RuntimeError rather than an
import-time failure.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/monitoring/health.py` — `check_alchemy_ws` rewritten; `import json` added.
- `projects/polymarket/crusaderbot/tests/test_health.py` — 4 hermetic tests (`import json` added).
- `projects/polymarket/crusaderbot/reports/forge/alchemy-ws-handshake.md` — this report.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — 7-section update.
- `projects/polymarket/crusaderbot/state/WORKTODO.md` — M3 checked done.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane entry.

## 4. What is working

- `test_check_alchemy_ws_ok_on_rpc_result` — handshake + `result` → True.
- `test_check_alchemy_ws_raises_on_rpc_error` — JSON-RPC error → raises (fails the check).
- `test_check_alchemy_ws_missing_url_raises` — unset WS URL → hard error.
- `test_check_alchemy_ws_handshake_failure_surfaces_sanitised` — handshake exception with embedded secret URL → `error: OSError`, no key leak.
- Full `tests/test_health.py`: 42 passed. ruff clean. py_compile clean.

## 5. Known issues

- The check now opens a real WS connection per `/health` call (comparable to the existing per-call HTTP RPC probe). Acceptable; bounded by the 3s timeout. No connection is leaked (async context manager + `close_timeout=1`).
- websockets pin is `>=12.0,<14.0`; `websockets.connect` (top-level) is valid across that range. The newer `websockets.asyncio.client` API was intentionally avoided for version safety.

## 6. What is next

- WARP🔹CMD review (STANDARD). CD deploy picks it up on merge.
- Remaining public-ready lanes: H1 ops-auth hardening (MAJOR/SENTINEL); C1 live-capital wiring (MAJOR — owner decision + SENTINEL + staged).

Validation handoff:
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/alchemy-ws-handshake.md
Tier: STANDARD
