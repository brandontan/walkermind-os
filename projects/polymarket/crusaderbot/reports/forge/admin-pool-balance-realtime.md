# WARP•FORGE Report — admin-pool-balance-realtime

Branch: `WARP/admin-pool-balance-realtime`
Role: WARP•FORGE
Validation Tier: **STANDARD** (admin UI / non-trading; zero runtime/risk/strategy change)
Claim Level: **NARROW INTEGRATION** (new lightweight backend endpoint + frontend polling loop)
Validation Target: master hot-pool USDC balance on the admin console updates every 10 s (vs. the previous 30 s full-overview poll), without adding DB load.
Not in Scope: WebSocket/SSE push on deposit-detected event (follow-up); fixing the `get_usdc_balance`→`0.0`-on-RPC-failure ambiguity (separate lane if needed); the hot-pool funding itself.

---

## 1. What was built

The admin console "Master Hot-Pool" card polled `/admin/overview` every 30 s. That endpoint also queries users, strategies, settings, and scan_runs from the DB — expensive to call frequently. The result: a USDC deposit to the hot-pool wallet took up to 30 s to appear, and operator could not see balance changes quickly.

Three surgical changes:

1. **Backend — new `/admin/pool-balance` endpoint** (`router.py`). Lightweight: only calls `master_wallet()` + `polygon.get_usdc_balance` + `polygon.get_native_balance` (on-chain RPC only, zero DB queries). Safe to call every 10 s.

2. **Frontend `api.ts`** — added `AdminPoolBalance` type + `getAdminPoolBalance()` API method.

3. **Frontend `AdminPage.tsx`** — added `loadPool` callback + 10 s `setInterval` that calls `/admin/pool-balance` and patches only `overview.pool`. The expensive full overview (users/strategies/settings/scan) remains on its existing 30 s schedule.

## 2. Current system architecture

```
AdminPage.tsx
  ├── load() ──30s──▶ GET /admin/overview   [full: DB + RPC, unchanged]
  │                   → setOverview(full snapshot)
  │
  └── loadPool() ─10s─▶ GET /admin/pool-balance  [NEW: RPC only, no DB]
                         → setOverview(prev ⇒ { ...prev, pool: p })
```

On-chain path (both endpoints share the same call):
```
pool_address = master_wallet()
polygon.get_usdc_balance(address)  ──▶ POLYGON RPC (balanceOf, retry×3)
polygon.get_native_balance(address) ─▶ POLYGON RPC (eth_getBalance, retry×3)
```

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — added `admin_pool_balance` GET `/admin/pool-balance` endpoint (22 lines).
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` — added `AdminPoolBalance` interface + `getAdminPoolBalance()` method.
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AdminPage.tsx` — imported `AdminPoolBalance`; added `loadPool` callback + 10 s poll effect.
- `projects/polymarket/crusaderbot/tests/test_admin_console.py` — added `test_admin_pool_balance_endpoint_exists` (inspect.getsource guard).

Created:
- `projects/polymarket/crusaderbot/reports/forge/admin-pool-balance-realtime.md` — this report.

## 4. What is working

- `test_admin_pool_balance_endpoint_exists` + `test_admin_overview_exposes_polymarket_config` → **2 passed**.
- `python -m py_compile projects/polymarket/crusaderbot/webtrader/backend/router.py` → clean.
- Frontend: `AdminPoolBalance` type exported and imported; `loadPool` + 10 s interval added; `setOverview` patch is None-safe (`prev ? { ...prev, pool: p } : prev`).
- Full overview poll (30 s) unchanged — no regression to other admin sections.

## 5. Known issues

- `polygon.get_usdc_balance` swallows permanent RPC failures and returns `0.0`, so `$0.00 USDC` is ambiguous (genuine zero OR RPC failure). The `admin_pool_balance` try/except block for that call is dead code. Distinguishing these cases requires making `get_usdc_balance` re-raise — deferred (separate lane; the current 0.0-vs-None distinction does not affect trading safety).
- True realtime (sub-second) on deposit would require an SSE push from the deposit-confirm flow (`scheduler._confirm_ready_deposits → SSE broadcast`). The 10 s poll is a sufficient UX improvement for the operator go-live use case.

## 6. What is next

- WARP🔹CMD: deploy + verify the hot-pool balance on the admin console now refreshes within 10 s of a USDC transfer landing on Polygon.
- Follow-up (optional): emit a `pool_balance_update` SSE broadcast from `scheduler._confirm_ready_deposits` so the frontend refreshes immediately on deposit confirmation rather than waiting up to 10 s.
- Follow-up: make `polygon.get_usdc_balance` raise on permanent failure so `pool_usdc=None` displays `—` instead of `$0.00` on RPC error.

Suggested Next Step: deploy to Fly, fund the hot-pool with a test USDC amount, confirm the balance appears on the admin console within 10 s.

---

Validation Handoff (per tier):

```
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/admin-pool-balance-realtime.md
Tier: STANDARD
```
