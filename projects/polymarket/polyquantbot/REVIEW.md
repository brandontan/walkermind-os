# polyquantbot MVP — Audit Report

Branch reviewed: `feature/forge/polyquantbot-mvp-v2`
Date: 2026-03-28
Reviewer: FORGE-X

---

## 1. What Was Built

A minimal async paper trading bot for Polymarket. End-to-end loop:
scan markets → generate EV signal → size position → simulate fill →
persist to SQLite → send Telegram alerts → monitor and auto-close
on TP / SL / timeout.

---

## 2. Current Structure

```
projects/polymarket/polyquantbot/mvp/
├── config.yaml
├── .env.example
├── requirements.txt
├── infra/
│   ├── polymarket_client.py    ← Gamma API fetch + parse
│   └── telegram_service.py    ← OPEN/CLOSED alerts
├── core/
│   ├── signal_model.py         ← BayesianSignalModel + EV calc
│   ├── risk_manager.py         ← fractional Kelly sizing
│   └── execution/
│       └── paper_executor.py  ← simulated fill with slippage
└── engine/
    ├── state_manager.py        ← aiosqlite: portfolio + trades
    └── runner.py               ← main async loop
```

---

## 3. What's Working

| Component | Status | Notes |
|-----------|--------|-------|
| Gamma API fetch | ✅ | 3x retry, 10s timeout, parses `outcomePrices` correctly |
| Market filtering | ✅ | Skips inactive/closed, validates `0 < p < 1` |
| EV calculation | ✅ | `EV = p·b − (1−p)` correct formula |
| Bayesian signal | ✅ | `p_model = p_market + 0.05` alpha boost |
| Signal selection | ✅ | Picks highest EV across scanned markets |
| Kelly sizing | ✅ | 0.25x fractional Kelly, capped at `max_position_pct` |
| Paper executor | ✅ | 100–250ms simulated latency, slippage applied |
| SQLite state | ✅ | WAL mode, idempotent `init()`, portfolio + trades tables |
| Exit logic | ✅ | TP/SL/timeout all handled |
| Telegram alerts | ✅ | Non-blocking, never raises, OPEN + CLOSED messages |
| Config loading | ✅ | Zero hardcoded values, all from `config.yaml` + `.env` |
| Error handling | ✅ | Cycle-level `try/except`, logs exception, continues |
| Cooldown cycle | ✅ | Skips 1 scan cycle after a close |

---

## 4. What's Missing vs Production Standards

### Critical Gaps

- **No real order execution** — `paper_executor.py` is the only executor.
  There is no `live_executor.py` touching the Polymarket CLOB API.
  The bot cannot place real orders.
- **No CLOB API integration** — no wallet auth, no `POST /order`, no order
  book polling. The entire live trading path is absent.
- **Exit price is fake** — `current_price` in `runner.py` is
  `entry_price + random.uniform(-0.03, 0.05)`. In production it must come
  from a live price feed or order book.
- **No market liquidity filter** — `MIN_LIQUIDITY = $10,000` required by
  CLAUDE.md. The `volume` field is fetched but never checked before trading.
- **No daily loss limit enforcement** — rule says `−$2,000` stops all trading.
  Not implemented.
- **No max drawdown check** — 8% MDD → stop. Not implemented.
- **No kill switch** — CLAUDE.md requires one in every bot. Missing entirely.
- **No dedup check** — rule: dedup before every order. `trade_id` is a UUID
  but there is no check for the same `market_id` being traded twice in a row.

### Missing Infrastructure

- No `Dockerfile` / `docker-compose.yml` — required for server deployment
- No process manager config — no `systemd` unit, `supervisord`, or `pm2`
- No health check endpoint — no way to confirm the bot is alive remotely
- No `config.yaml` validation — missing key raises bare `KeyError`
- `structlog` never configured with a renderer — output format undefined at
  runtime (defaults to plain text, not JSON)
- No test suite — zero test files
- No `__main__.py` in `engine/` — must run from `mvp/` directory

### Signal Model Weaknesses

- `ALPHA = 0.05` is a hardcoded constant with no empirical basis — will
  generate signals on almost every market
- Only trades YES — NO side never evaluated, halves the opportunity set
- No minimum volume filter on signals — could trade illiquid markets

---

## 5. Issues Found

| Severity | Location | Issue |
|----------|----------|-------|
| 🔴 High | `runner.py:42` | `current_price = entry_price + random.drift` — completely fake; produces nonsense P&L |
| 🔴 High | `risk_manager.py` | `max(1.0, ...)` forces a $1 minimum trade even when Kelly says 0 — can trade with negative EV |
| 🟡 Medium | `signal_model.py` | `ALPHA = 0.05` magic number — generates signals on nearly every market with `p_market > 0.02` |
| 🟡 Medium | `state_manager.py` | `assert self._db` throws `AssertionError` if `init()` not called — should raise `RuntimeError` with message |
| 🟡 Medium | `polymarket_client.py` | No minimum volume filter — evaluates markets with $0 volume |
| 🟡 Medium | `runner.py` | `load_config("config.yaml")` uses relative path — breaks if process not started from `mvp/` |
| 🟡 Medium | `runner.py` | No graceful shutdown — `SIGTERM` leaves DB connection open; needs `try/finally` around main loop |
| 🟢 Low | `telegram_service.py` | `exit_price` used in `send_closed` without None guard — `TypeError` if `None` passed |
| 🟢 Low | All files | `structlog` not configured with renderer — log output format undefined |

---

## Summary

Solid MVP skeleton — the architecture, async patterns, DB schema, and config
approach are all correct. The bot will start, fetch markets, generate paper
signals, and send Telegram messages.

**Not production-ready** because:
1. Real price feed replaced by random drift
2. No live CLOB execution path
3. Risk rules (daily loss limit, MDD, kill switch, liquidity floor) absent from code

### Next Steps (Phase 2)

1. Replace `random.drift` with live price from CLOB order book
2. Build `live_executor.py` with wallet auth + `POST /order`
3. Add `RiskGate` class enforcing daily loss limit, MDD, kill switch
4. Add `min_volume` filter to `signal_model.py`
5. Configure `structlog` JSON renderer at startup
6. Add `Dockerfile` + health check endpoint
7. Write unit tests for EV calc, Kelly sizing, and state manager
