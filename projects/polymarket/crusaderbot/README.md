# CrusaderBot

Multi-user auto-trade service for Polymarket. **R1 skeleton.**

Status: paper mode only. All activation guards default OFF. No live trading.
Target architecture: see `docs/blueprint/crusaderbot.md` (Blueprint v3.1).

## Run

From `projects/polymarket/` (so `crusaderbot` is importable as a package):

```bash
cp crusaderbot/.env.example crusaderbot/.env
# fill in real values

cd crusaderbot
poetry install

# from one level up so crusaderbot is on sys.path
cd ..
poetry --directory=crusaderbot run uvicorn crusaderbot.main:app \
    --host 0.0.0.0 --port 8000 --reload
```

## Endpoints

- `GET /health` — liveness probe (`{"status": "ok", "env": "..."}`)
- `GET /ready` — DB + cache ping + guard state visibility

## Telegram commands (R1)

- `/start` — confirms bot online and paper mode
- `/status` — shows all activation guard states

## Boundary

- Paper mode only at R1
- All activation guards default OFF (`ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `FEE_COLLECTION_ENABLED`, `AUTO_REDEEM_ENABLED`)
- Hard-wired risk constants live at `domain/risk/constants.py` — PR-protected

## Roadmap

R1 skeleton → R2 onboarding/HD wallet → R3 allowlist → R4 deposit watcher → R5 strategy config → R6 signal engine → R7 risk gate → R8 paper exec → R9 exit logic → R10 auto-redeem → R11 fee/referral → R12 ops/monitoring.
