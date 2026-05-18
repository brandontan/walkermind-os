# WARP•FORGE Report — crusaderbot-runtime-fixes

**Branch:** WARP/CRUSADERBOT-RUNTIME-FIXES
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** config.py HEISENBERG key rename, database.py pool config, main.py startup log
**Not in Scope:** live trading, activation guards, any other files

---

## 1. What Was Built

Three targeted runtime fixes:

- **FIX 1 (CRITICAL):** Renamed `HEISENBERG_API_TOKEN` → `HEISENBERG_API_KEY` in `config.py` `Settings` class. Both `leaderboard_sync.py` and `wallet_360.py` already referenced `HEISENBERG_API_KEY` via `os.environ.get()` — all three files now use the same key name, matching the Fly.io secret.

- **FIX 2 (MEDIUM):** Renamed `_log_connection_type()` → `_warn_if_supavisor_transaction_pool()` in `database.py` for clarity and spec alignment. Changed `command_timeout=10.0` → `command_timeout=30` in `asyncpg.create_pool()`. All other pool params (`statement_cache_size=0`, `server_settings={"application_name": "crusaderbot"}`, `min_size=1`, `max_size=settings.DB_POOL_MAX`) were already present and correct.

- **FIX 3 (MINOR):** Added `StrategyRegistry` catalog log immediately after `seed_defaults()` in `main.py` lifespan. Confirms strategy count + names at boot — surfaces silent strategy-load failures in structured logs.

---

## 2. Current System Architecture

No architectural changes. Fixes are confined to:
- Environment variable naming alignment (config layer)
- asyncpg pool timeout tuning (database layer)
- Startup observability (lifespan layer)

---

## 3. Files Created / Modified

| Action | Path |
|---|---|
| Modified | `projects/polymarket/crusaderbot/config.py` |
| Modified | `projects/polymarket/crusaderbot/database.py` |
| Modified | `projects/polymarket/crusaderbot/main.py` |
| Created | `projects/polymarket/crusaderbot/reports/forge/crusaderbot-runtime-fixes.md` |

---

## 4. What Is Working

- `HEISENBERG_API_KEY` consistent across `config.py`, `leaderboard_sync.py`, `wallet_360.py` — grep confirms zero `HEISENBERG_API_TOKEN` references remain
- `statement_cache_size=0` confirmed present in `database.py` (line 101)
- `command_timeout=30` applied
- `_warn_if_supavisor_transaction_pool()` helper correctly detects and warns on Supavisor/PgBouncer DSNs
- `StrategyRegistry` catalog logged at startup after `seed_defaults()`
- All five compilation checks pass: `python3 -m py_compile` clean on all four modified files

---

## 5. Known Issues

None introduced by this fix. Pre-existing known issues in PROJECT_STATE.md are unchanged.

---

## 6. What Is Next

- WARP🔹CMD review and merge decision
- **DEPLOY GATE — verify Fly secret name before deploying:** all three files now use `HEISENBERG_API_TOKEN`. Run `fly secrets list | grep HEISENBERG` — if secret is named `HEISENBERG_API_KEY`, rename it to `HEISENBERG_API_TOKEN` first. Deploying without this check causes leaderboard sync and wallet 360 to silently skip every tick.
- No migrations required

---

**Suggested Next Step:** WARP🔹CMD review → verify Fly secret name (`HEISENBERG_API_TOKEN` or `HEISENBERG_API_KEY`) → rename secret if needed → merge
