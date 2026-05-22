# WARP•SENTINEL — CrusaderBot System Audit (Pre-Client-Handoff CORE AUDIT)

Last Updated : 2026-05-23 05:53 Asia/Jakarta
Branch       : WARP/crusaderbot-system-audit
HEAD         : 9caaabc (== origin/main, 0 ahead / 0 behind — audited state IS the deployable state)
Verdict      : BLOCKED
Score        : 62/100
Critical     : 1

---

## Environment

- Audit surface: `main` deployable state (HEAD 9caaabc), per WARP🔹CMD scope decision.
- Runner: Python 3.11.15, Node 22.22, npm 10.9, ruff 0.x present.
- Python deps installed from `pyproject.toml` (21 deps) + pytest/pytest-asyncio.
- Env note: native crypto binding initially panicked (`pyo3_runtime.PanicException:
  No module named '_cffi_backend'`) — the Debian system `cryptography` shadows the pip
  build and needs `cffi`. Resolved by `pip install cffi` (env artifact, NOT a code defect).
- Live verification channels (authenticated MCP, since GitHub/Fly secrets are not injected
  locally and are not API-readable): Supabase MCP → live CrusaderBot DB
  (`ykyagjdeqcgcktnpdhes`, ACTIVE_HEALTHY, Postgres 17); Sentry MCP (org `vurtnex`);
  GitHub MCP (repo `bayuewalker/walkermind-os`).
- Frontend: `npm ci` + `npm run build` executed in-container.

## Validation Context

- Tier: MAJOR (full-system audit — runtime, backend, frontend, safety, blueprint).
- Claim under test: "bot working in backend, data realtime in frontend, WebTrader +
  Telegram UI/UX functioning, conforms to docs/blueprint/crusaderbot.md v3.1."
- Blueprint = target-architecture INTENT; code truth defines current reality (AGENTS.md).
  Blueprint/code deltas are conformance findings, not blockers unless safety/claim contra.
- Default posture: SAFE DEFAULT MODE — system UNSAFE until proven.

## Phase 0 — Pre-Test Checks

- Audit branch compliant (`WARP/...`); harness-assigned `claude/...` branch rejected per
  AGENTS.md branch law. PASS.
- HEAD == origin/main confirmed (audited state = ship state). PASS.
- Working tree clean before audit. PASS.
- Report at correct path + naming + structure. PASS.

## Findings

### F-CRIT-1 — main HEAD cannot start the application (DEPLOYMENT BLOCKER)
Severity: CRITICAL. Claim contradiction: "bot working."

`bot/ui/__init__.py:2` imports names that no longer exist in `bot/ui/tree.py`:
`BAR, BRANCH, LAST, STATUS_RUNNING, STATUS_STOPPED, STATUS_PAUSED, STATUS_NOT_SET,
STATUS_SYNCING, PAPER, LIVE, LOCKED` (only `pnl/section/leaf/nested/title/cta/divider/
DIV/DIVIDER/CARD_DIVIDER` remain). `tree.py` was rewritten by WARP-67 (2989b7c),
WARP-68 (b735554), WARP-71 (e443c21), WARP-73 (7bb7a69) — the glyph/status constants were
removed but `bot/ui/__init__.py` (last touched 5c49786) was never updated to match.

Runtime import chain that breaks:
`main.py:23 from .bot.dispatcher import register` → `bot/dispatcher.py register()` →
imports MVP handlers (`dashboard, autotrade, copy_wallet, portfolio, markets, settings,
help, onboarding`) → each `from ... import messages_mvp` → `bot/messages_mvp.py:16
from .ui.tree import (...)` → executes `bot/ui/__init__.py` → ImportError.

Evidence (in-container, this audit):
- `python3 -c "import ...bot.messages_mvp"` → `ImportError: cannot import name 'BAR'`.
- `python3 -c "import ...bot.dispatcher"` → same ImportError.
- pytest: `test_activation_handlers.py::test_dispatcher_routes_activation_confirm_before_setup`
  FAILED with this exact ImportError; `test_warp59_copy_wallet_bridge.py` ERRORED at
  collection (imports `BAR`). Both = same root cause.

Impact: FastAPI app + Telegram handler registration cannot import on main → app fails to
boot. Production currently runs an OLDER commit; main has regressed since last deploy.
Deploying / handing off main as-is = bot down. THIS BLOCKS HANDOFF.

Correlation (out-of-band, needs Fly confirmation): live `job_runs` heartbeat stopped at
2026-05-22 22:12 UTC (05:12 WIB) after running every minute (15,207 runs/24h, 0 failed);
WARP-73 merged to main at 22:14 UTC. A redeploy of broken main ~that window would
crash-loop on startup. Sentry shows 0 issues in 24h — consistent with a crash BEFORE the
Sentry SDK initializes (module-import ImportError) OR a clean Fly auto-stop. Confirm via
`fly logs` / `fly status`.

Fix: realign `bot/ui/__init__.py` exports to `tree.py` (drop the removed names, or re-add
them to `tree.py`). Then prove: `python -m pytest tests/ -q` 0 collection errors +
`python -c "import ...bot.dispatcher"` clean; un-skip `test_warp59`, fix `test_activation_handlers`.

### F-HIGH-2 — zero trade data in production (frontend would render empty)
Severity: HIGH. Affects "data realtime in frontend."

Live DB counts: `users`=6 (5 `auto_trade_on`, all non-demo), but `positions`=0,
`orders`=0, `fills`=0, `portfolio_snapshots`=0. Historical trades existed (CHANGELOG: bad-
trade + ledger cleanups for walk3r69 etc.) but were cleaned; none since. The realtime
pipe is wired and healthy (see F-PASS-3) but no trade data is flowing through it. A client
opening Dashboard / Portfolio / Positions today sees empty state. Root: scanner runs (15k
jobs/24h) yet nothing clears the risk gate to execution — expected-but-empty under a
strict gate (liquidity $10k, edge 2%) OR a functional gap in scan→trade. Recommend a
controlled paper-trade smoke (1 user, relaxed filter) post-fix to prove scan→risk→exec→
position→snapshot end-to-end produces a row the frontend renders.

### F-PASS-3 — realtime data path WIRED in production
Live `pg_trigger`: `trg_cb_orders`/`trg_orders_notify`→`_cb_notify_orders`,
`trg_cb_fills`/`trg_fills_notify`, `trg_cb_positions`/`trg_positions_notify`,
`trg_cb_portfolio_snapshots`, `trg_cb_system_alerts` — all present. Migrations 029/030 ARE
applied (PROJECT_STATE "[NOT STARTED] apply 029/030" is STALE DRIFT — see F-DRIFT-7).
SSE path `event_bus → webtrader/backend/sse.py → frontend useSSE/SSEStatusContext` intact.
NOTIFY → SSE realtime plumbing is correct; only trade data is absent (F-HIGH-2).

### F-PASS-4 — safety core spec-compliant (all PASS)
- Risk constants `domain/risk/constants.py`: KELLY_FRACTION=0.25, MAX_POSITION_PCT=0.10,
  MAX_CONCURRENT_TRADES=5, DAILY_LOSS_HARD_STOP=-2000, MAX_DRAWDOWN_HALT=0.08,
  MIN_LIQUIDITY=10000, MIN_EDGE_BPS=200, DEDUP_WINDOW_SECONDS=300. Matches AGENTS.md table.
- `domain/risk/hardening.py` asserts constants at boot; Kelly clamped `0 < K <= 0.25`.
- Risk-before-execution: `domain/risk/gate.py` 14-step gate → `domain/execution/router.py`
  (paper default); no bypass path.
- Kill switch `domain/risk/kill_switch_exec.py` writes `system_settings`, unconditional
  audit log, reset path. Live: `kill_switch_active=false`, `kill_switch_lock_mode=false`.
- Live guards `config.py:148-155` default OFF; enforced `domain/execution/live.py
  assert_live_guards()` (5 conditions). Paper is default.
- asyncio-only: 0 `import threading` (only docstrings). Zero `except: pass` / bare `except:`.
- Safety-critical tests: 108 passed (health, live_opt_in_gate, live_gate_hardening,
  kill_switch).

### F-PASS-5 — test suite + lint
- `pytest tests/` (cffi fixed, excl. broken-collection file): 1606 passed, 1 failed,
  1 skipped, 23 warnings (86.7s). The 1 fail + 1 excluded collection error = F-CRIT-1.
- `ruff check .`: All checks passed (CI lint baseline).
- Frontend `npm run build`: exit 0 (tsc + Vite); `dist/` produced; bundle 690 kB JS
  (>500 kB advisory, non-blocking). No frontend test framework (advisory). No mocks/TODOs.

## Blueprint Conformance Matrix (docs/blueprint/crusaderbot.md v3.1)

| Blueprint dimension | Code reality | Status |
|---|---|---|
| §4 BaseStrategy + StrategyRegistry | `domain/strategy/base.py:15 class BaseStrategy(ABC)`, `registry.py`, 4 strategies (copy_trade, signal_following, momentum_reversal, confluence_scalper) | CONFORMS (value/hybrid/arbitrage deferred per phases) |
| §6 risk constants | constants.py matches; +MAX_CORRELATED_EXPOSURE / MIN_NET_EDGE present | CONFORMS |
| §6 risk-profile presets + precedence | `domain/risk/constants.py` conservative/balanced/aggressive/custom + strategy compat map; `domain/preset/presets.py` kelly fractions | CONFORMS |
| §6 TP/SL snapshot-at-entry | `positions.applied_tp_pct/applied_sl_pct` + live triggers `trg_positions_snapshot_applied` (snapshot at entry) + `trg_positions_immutable_applied` (rejects update) | CONFORMS (strong) |
| §6 risk gate ordering (kill→...→cost) | `domain/risk/gate.py` 14-step, RISK before EXECUTION | CONFORMS |
| §8 auto-trade scheduler + exit watcher | `scheduler.py` 20+ jobs; `domain/execution/exit_watcher.py` | CONFORMS |
| §9 auto-redeem instant/hourly | `services/redeem/instant_worker.py` + `hourly_worker.py` + `redeem_router.py` | CONFORMS |
| §10/§12 fee + referral guards default OFF | `config.py:156 FEE_COLLECTION_ENABLED=False`, `:163 REFERRAL_PAYOUT_ENABLED=False` | CONFORMS |
| §12 activation guards | ENABLE_LIVE_TRADING / EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED / RISK_CONTROLS_VALIDATED all default False | CONFORMS |
| §1 access tiers 1–4 | `users.role` (RBAC); `access_tier` dropped (mig 044, WARP-51) | DELIBERATE-DIVERGENCE (code is truth) |
| §11 copy_targets table | canonical `copy_trade_tasks` (mig 009+) | DELIBERATE-DIVERGENCE |
| §- audit log physically-separate DB | single-DB `audit_log` table (mig 002) | GAP (intent vs reality — documented) |
| §2/§7 wallet plane (KMS vault, hot/cold split, HD per-user) | custodial-light single pool (blueprint defers full split) | PARTIAL (per blueprint phasing) |

## Score Breakdown

| Dimension | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20 | 17 | Clean domain separation, registry, hard-wired gate; audit-DB + wallet-plane gaps vs blueprint |
| Functional | 20 | 5 | App entrypoint cannot import on main (F-CRIT-1); zero trade data (F-HIGH-2). 1606 unit tests pass but runtime boot broken |
| Failure modes | 20 | 16 | Gate→paper fallback, kill switch, idempotency, no silent failures |
| Risk | 20 | 20 | Constants + gate ordering + guards OFF all PASS |
| Infra + Telegram | 10 | 2 | Realtime triggers wired + CI lint green, BUT Telegram handler registration broken (F-CRIT-1), prod halted 05:12 WIB |
| Latency | 10 | 2 | Not independently measured in-container (no live latency harness); scheduler historically healthy |
| TOTAL | 100 | 62 | — |

## Critical Issues

- F-CRIT-1 — `bot/ui/__init__.py` imports removed names from `bot/ui/tree.py`; breaks
  `main.py` → `bot.dispatcher` → MVP handlers import chain. App will not start from main.

ANY single critical issue = BLOCKED (AGENTS.md). No exceptions.

## Status

VERDICT: BLOCKED. The deployable state (main HEAD 9caaabc) cannot boot the application.
This directly contradicts the handoff claim "bot working in backend / UI functioning."
Not eligible for client handoff or production deploy until F-CRIT-1 is fixed and a clean
runtime import + scan→trade→snapshot smoke is proven.

## PR Gate Result

- This audit (report + state) opens a PR on `WARP/crusaderbot-system-audit`. No code change.
- Handoff/deploy gate: HOLD until F-CRIT-1 fix lands on main and is re-validated.

## Reasoning

The safety architecture is genuinely strong — risk constants, gate ordering, guards,
kill switch, asyncio discipline, and no silent failures all PASS, and blueprint conformance
is high for the current phase. But "working" is decided by runtime, not unit tests: main's
own entrypoint raises ImportError on load. Unit tests largely pass because most don't
exercise the MVP handler import chain; the two that do (test_activation_handlers,
test_warp59) fail/error with exactly this root cause. The realtime pipeline is correctly
wired (NOTIFY triggers + SSE), yet there is currently no trade data to display. A client
handoff in this state would show a bot that cannot start (latest code) and an empty
dashboard.

## Fix Recommendations (priority order)

1. (CRITICAL) Realign `bot/ui/__init__.py` exports to the current `bot/ui/tree.py` API —
   remove `BAR, BRANCH, LAST, STATUS_*, PAPER, LIVE, LOCKED` (or re-add them to tree.py if
   still referenced downstream). Prove: `python -m pytest tests/ -q` → 0 collection errors,
   `python -c "import projects.polymarket.crusaderbot.bot.dispatcher"` clean, un-skip
   test_warp59, fix test_activation_handlers. Tier MAJOR (touches runtime boot).
2. (HIGH) Confirm prod status out-of-band: `fly status` / `fly logs` for crash-loop since
   2026-05-22 22:12 UTC; redeploy only AFTER fix #1.
3. (HIGH) Post-fix scan→trade smoke: 1 paper user + relaxed market filter, confirm a
   position + portfolio_snapshot row is written and surfaces in WebTrader/Telegram.
4. (MEDIUM) Add a runtime import smoke to CI (`python -c "import ...bot.dispatcher; import
   ...main"`) so handler-chain breaks fail CI, not production.
5. (LOW) Supabase: pin `search_path` on the 9 trigger functions
   (`function_search_path_mutable` WARN). https://supabase.com/docs/guides/database/database-linter?lint=0011_function_search_path_mutable
6. (LOW) Frontend: code-split the 690 kB bundle; add a minimal vitest smoke.

## Broader Audit Finding (out of declared scope)

~50 open PRs against `main` (per PROJECT_STATE) — large unmerged backlog / drift risk.
Out of scope per WARP🔹CMD (main-only audit). The duplicate `warp-gate[bot]` state-sync
commits (3× identical messages within 2s, e.g. 9caaabc/19d662a/ef73a79) indicate a noisy
GATE sync process worth tidying. Recommend a dedicated `cek pr` triage lane.

## Out-of-scope Advisory

- Live on-device Telegram tap-through and browser WebTrader render against live data
  require Mr. Walker's device/session — see on-device checklist below; not claimed proven.
- Live Fly.io runtime/`/health` not reachable here (network policy).
- Latency SLOs (ingest<100ms / signal<200ms / exec<500ms) not measured in-container.

## Deferred Minor Backlog

- [DEFERRED] Supabase function_search_path_mutable WARN ×9 — found in crusaderbot-system-audit.
- [DEFERRED] WebTrader 690 kB single-chunk bundle — found in crusaderbot-system-audit.
- [DEFERRED] No frontend test framework — found in crusaderbot-system-audit.
- [DEFERRED] PROJECT_STATE [NOT STARTED] migrations 029/030 note is stale (triggers live).

## On-Device / Out-of-Band Verification Checklist (for Mr. Walker, AFTER F-CRIT-1 fix + redeploy)

- [ ] `fly status` shows machine running; `fly logs` free of ImportError on boot.
- [ ] Telegram @CrusaderPolybot `/start` → onboarding renders; main menu buttons respond.
- [ ] Auto-Trade setup → preset select → toggle ON (paper) persists.
- [ ] WebTrader loads via Telegram login; Dashboard/Portfolio/Positions render.
- [ ] Trigger a paper trade; confirm position + realtime SSE update appears in WebTrader
      AND a Telegram trade notification fires.
- [ ] Kill switch from Telegram/ops halts; resume restores.

## Telegram Visual Preview (post-fix expected)

```
🤖 CrusaderBot — Dashboard
──────────────────────────────
Balance: $X,XXX.XX   PnL today: +$XX.XX
Open: N   Auto: 🟢 RUNNING (balanced)
Last scan: HH:MM:SS  ·  Mode: PAPER
[ 📊 Portfolio ] [ 📈 Positions (N) ]
[ 🤖 Auto Mode ] [ ⚙️ Settings ]
──────────────────────────────
System in paper trading mode. No real capital deployed.
```

Note: preview is the intended render once F-CRIT-1 is fixed; NOT observed live this audit.

---

Done — GO-LIVE: BLOCKED. Score: 62/100. Critical: 1.
Branch: WARP/crusaderbot-system-audit
Report: projects/polymarket/crusaderbot/reports/sentinel/crusaderbot-system-audit.md
State: PROJECT_STATE.md updated
NEXT GATE: Return to WARP🔹CMD — fix F-CRIT-1, redeploy, re-validate before handoff.
