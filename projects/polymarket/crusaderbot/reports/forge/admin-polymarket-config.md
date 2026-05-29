# WARP•R00T FORGE REPORT — admin-polymarket-config

Branch: `WARP/ROOT/admin-polymarket-config`
Role: WARP•R00T (operator UX — verify live config)
Validation Tier: MINOR (read-only admin display)
Claim Level: FOUNDATION

## 1. What was built
Operator couldn't verify the Polymarket trading config from the Ops Console —
funder/sig-type/creds live in env/secrets, not the DB, so they were invisible
(operator kept asking "funder gak nampak di admin"). Added a **Polymarket
Trading Account** block to `GET /api/web/admin/overview` + AdminPage:
- `funder_address` (POLYMARKET_FUNDER_ADDRESS, "NOT SET" if empty)
- `signature_type`
- `use_real_clob`
- `creds_source` (env | derived | none) + `creds_ready`

So the operator can confirm the funder/sig/creds actually loaded post-restart.

## 2. Current system architecture
Read-only. Reuses `clob.effective_credentials()` to report whether CLOB auth is
ready and from where (env vs auto-derived).

## 3. Files modified
- projects/polymarket/crusaderbot/webtrader/backend/router.py (admin_overview polymarket block)
- projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts (AdminOverview.polymarket)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AdminPage.tsx (Polymarket section)
- projects/polymarket/crusaderbot/tests/test_admin_console.py (+1 pin)

## 4. What is working
Ops Console shows funder + sig type + CLOB creds status. 12 admin tests pass;
ruff + py_compile + tsc + vite build clean.

## 5. Known issues
None. Display only — no behaviour change.

## 6. What is next
WARP🔹CMD review + merge → deploy → operator verifies funder in Ops Console.
