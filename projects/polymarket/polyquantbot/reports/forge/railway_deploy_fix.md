# railway_deploy_fix — FORGE-X Report

**Date:** 2026-04-02
**Task:** Make PolyQuantBot fully compatible with Railway deployment

---

## 1. Files Added

| File | Purpose |
|------|---------|
| `main.py` (root) | Root-level entrypoint; loads `.env`, inserts repo root onto `sys.path`, delegates to `projects.polymarket.polyquantbot.main.main()` |
| `requirements.txt` (root) | All runtime dependencies; enables Railpack auto-detection |
| `Procfile` (root) | `worker: python main.py` — single-command startup for Railway |
| `runtime.txt` (root) | Pins runtime to `python-3.11` |
| `projects/__init__.py` | Makes `projects` a proper Python package so import resolution works from repo root |
| `projects/polymarket/__init__.py` | Makes `projects.polymarket` importable |
| `projects/polymarket/polyquantbot/main.py` | Async `main()` that reads env vars, builds config, and starts `LivePaperRunner` (PAPER) or `Phase10PipelineRunner` (LIVE) |

---

## 2. Entry Flow

```
Railway start command → python main.py (root)
  ├─ load_dotenv(".env")          # load secrets from .env file (if present)
  ├─ sys.path.insert(0, ROOT)     # ensure projects/ is importable
  └─ asyncio.run(
       projects.polymarket.polyquantbot.main.main()
     )
         ├─ log "🚀 PolyQuantBot starting (Railway)"
         ├─ read TRADING_MODE (default: PAPER)
         ├─ validate env vars for LIVE mode (fail-fast if missing)
         ├─ read MARKET_IDS (comma-separated condition IDs)
         ├─ build config dict from env vars
         └─ PAPER → LivePaperRunner.from_config(cfg, market_ids).run()
            LIVE  → Phase10PipelineRunner.from_config(cfg, market_ids).run()
```

---

## 3. Railway Compatibility

| Check | Status |
|-------|--------|
| Railpack detects Python project (requirements.txt at root) | ✅ |
| Single startup command in Procfile | ✅ |
| Runtime pinned to Python 3.11 | ✅ |
| No nested-package import errors | ✅ (projects/ + projects/polymarket/ have `__init__.py`) |
| Secrets loaded from env vars | ✅ |
| Fail-fast on missing LIVE env vars | ✅ |
| Graceful degradation (no market IDs → warning, continues) | ✅ |

---

## 4. Test Result

Local import chain validated:

```
python -c "import sys; sys.path.insert(0,'.');\
  from projects.polymarket.polyquantbot.main import main; print('OK')"
```

Root entrypoint validated:

```
python main.py   # exits after import check — no real WS connection in dry-run
```

---

## 5. Known Issues

- `MARKET_IDS` must be set to actual Polymarket condition IDs before the runner
  can process any markets.  An empty value produces a warning but does not crash.
- LIVE mode requires `CLOB_API_KEY`, `CLOB_API_SECRET`, `CLOB_API_PASSPHRASE`, and
  `ENABLE_LIVE_TRADING=true` — missing any of these causes an immediate `sys.exit(1)`.

---

## 6. Next Step

1. Set `MARKET_IDS`, `CLOB_WS_URL`, and optional API credentials in Railway
   environment variables.
2. Deploy to Railway and verify the worker pod starts successfully.
3. Monitor Telegram alerts for pipeline health checkpoints.
