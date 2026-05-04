# WARP•SENTINEL — crusaderbot-replit-import

Verdict: **BLOCKED**
Score: **64 / 100**
Critical findings: **3**
Validation Tier: MAJOR
Claim Level: FULL RUNTIME INTEGRATION (R1-R11 import + P1 fixes)

Audited commit: `8c6aded3d6db2f7e92d2638ede72636976c17ea4` on `origin/WARP/CRUSADERBOT-REPLIT-IMPORT` (PR #852).
Reproduce findings (one-time setup from a fresh clone):
```
git fetch origin WARP/CRUSADERBOT-REPLIT-IMPORT       # makes 8c6aded3 resolvable
# OR: gh pr checkout 852
git show 8c6aded3:projects/polymarket/crusaderbot/<path>
```
Every `file:line` reference below resolves once the audited branch is fetched. The commit object is **not** present on PR #853's branch — that branch carries only the audit report, by design.
Worktree branch carrying THIS report: `claude/audit-crusaderbot-import-Ar983` (Claude Code worktree — Sentinel rule: do not block on branch name alone). The audit-report PR (#853) intentionally contains only `reports/sentinel/crusaderbot-replit-import.md`; the source files under audit live on PR #852.
Audit scope: every production source file and migration under `projects/polymarket/crusaderbot/` on the audited commit — 38 `.py` modules + 4 `migrations/*.sql` + `db/schema_r4.sql` + `.env.example` + `config/main` entry points. Out of scope: tests, deployment config (`Dockerfile`, `fly.toml`, `Procfile`), `state/` markdown.
Date: 2026-05-04 Asia/Jakarta

---

## 1. Test Plan

| Phase | Coverage |
|---|---|
| 0 — Pre-test | Report path / state files / structure / P1 fix evidence |
| 1 — Functional | 13-gate, paper/live engines, router, deposit credit, tier gate |
| 2 — Pipeline | DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING |
| 3 — Failure modes | CLOB ambiguous submit, reorg, RPC timeout, idempotent retry |
| 4 — Async safety | threading=0, time.sleep=0, requests=0, atomicity of credit/close |
| 5 — Risk rules | Kelly, max position, daily loss, drawdown, dedup, kill switch |
| 6 — Latency | Tenacity retry/backoff coverage, scheduler interval bounds |
| 7 — Infra | Postgres pool, Redis fallback, kill switch persistence |
| 8 — Telegram | 7 alert events + operator preview + secret-token validation |

Environment: dev (per APP_ENV default; production gates default OFF in `.env.example` even though runtime default for `ENABLE_LIVE_TRADING` is True in `config.py:57`).

---

## 2. Findings

### Phase 0 — Pre-test

- Report path correct ✓
- 6-section forge report exists for R1–R4 only; no R5–R11 forge reports present
  (`projects/polymarket/crusaderbot/reports/forge/` lists r1/r2/r3/r4 only, but
  the import covers R1–R11). Forge claim level `FULL RUNTIME INTEGRATION` is
  asserted without forge-side evidence for R5–R11 → BLOCKED on Phase 0
  evidence requirement.
- No `phase*/` folders ✓
- P1 fix evidence: all three fixes verifiable in tree (see §3).

### Phase 1 — Functional (per module)

- **13-gate (`domain/risk/gate.py`)**: every step writes to `risk_log`,
  short-circuits on first deny, and records final `approved_{mode}` decision
  on success. Gate context propagation from scheduler is type-clean.
- **Paper engine (`domain/execution/paper.py:15-80`)**: open path is fully
  atomic — order insert + position insert + ledger debit in one transaction,
  with `ON CONFLICT (idempotency_key) DO NOTHING` shielding retries. ✓
- **Live engine (`domain/execution/live.py`)**: pre-/post-submit error
  classification correctly modeled by `LivePreSubmitError` /
  `LivePostSubmitError`. `assert_live_guards` re-checks all three operator
  guards + `tier>=4` + `trading_mode=='live'`. ✓
- **Router (`domain/execution/router.py:57-60`)**: refuses paper fallback on
  `LivePostSubmitError` (correct — would otherwise duplicate exposure). ✓
- **Tier gate**: production path is via `bot.tier.has_tier` /
  `bot.handlers.dashboard._ensure` / `bot.handlers.setup._ensure_tier2`.
  The decorator at `bot/middleware/tier_gate.py` is **NOT registered on
  any handler** (zero usages, see §4 C2).

### Phase 2 — Pipeline

- DATA: `polygon.scan_from_cursor` + `polymarket.get_markets` ✓
- STRATEGY: `domain/signal/copy_trade.py` (only live strategy; value+momentum stubs return `[]`)
- INTELLIGENCE: signal candidates flow into `_process_candidate` ✓
- RISK: `evaluate(GateContext)` runs unconditionally before any router call ✓
- EXECUTION: `router.execute` dispatches paper vs live based on `chosen_mode`
- MONITORING: `audit.write` + `notifications.send` events on every state transition ✓

No skip path detected from candidate → execution that bypasses risk. ✓

### Phase 3 — Failure modes

- CLOB ambiguous submit → status='unknown' + operator notify + `LivePostSubmitError` raised → router does not paper-duplicate ✓ (`live.py:120-146`)
- Reorg handling: only present in DEAD service `services/deposit_watcher.py:531-593`. Active scheduler path (`scheduler.watch_deposits`) has NO reorg reversal → if a deposit credit is reorg-rolled-back on chain, the user balance stays inflated permanently. **HIGH severity.**
- RPC retry: tenacity `stop_after_attempt(3)` + exponential backoff applied to every `polygon.*` and `polymarket._get_json` ✓
- `scheduler.watch_deposits` only advances `chain_cursor` after every transfer in the range commits (`all_ok` flag, `scheduler.py:122/174`) ✓
- Idempotency keys table TTL=30min — race-safe via `ON CONFLICT (key) DO NOTHING` ✓

### Phase 4 — Async safety

- `import threading` / `from threading` — **0 occurrences** ✓
- `time.sleep` — **0 occurrences** in async paths (`cache.py` uses `time.time` only) ✓
- `requests` (sync HTTP) — **0 occurrences** ✓
- All 7 scheduler jobs (`market_sync`, `deposit_watch`, `signal_scan`,
  `exit_watch`, `redeem`, `resolution`, `sweep`) declared with `max_instances=1, coalesce=True` ✓

### Phase 5 — Risk rules (DETAILED — see §3 critical issues)

- Daily loss: enforced at gate step 5 (`gate.py:178-184`) using
  `wallet.ledger.daily_pnl` summing `trade_close+redeem+fee` since
  `date_trunc('day', NOW())` ✓
- Drawdown: enforced at gate step 6 (`gate.py:82-98`) via
  `(deposits − wallets.balance_usdc) / deposits ≥ 0.08` ✓
- Concurrent trades: gate step 7 (`gate.py:194-198`) ✓
- Correlated exposure: gate step 8 (`gate.py:202-208`) at 40% cap ✓
- Liquidity floor: gate step 11 ✓
- Edge floor: gate step 12 ✓
- Idempotency + dedup window: gate step 10 ✓
- Kill switch: gate step 1 + admin endpoints persist via `kill_switch` table ✓
- **Kelly fraction: NOT ENFORCED** — see C1.
- **`capital_alloc_pct` unbounded at 100%** — see C1.

### Phase 6 — Latency

- No latency instrumentation in this slice; can only assert structural
  ceilings: tenacity max wait=8s, polymarket book TTL=30s, gamma TTL=300s,
  command_timeout=30s on the asyncpg pool. No SLO targets violated by
  config alone, but unverified at runtime. (Out of scope for static audit.)

### Phase 7 — Infra

- Postgres pool: `init_pool(min=1, max=settings.DB_POOL_MAX)` ✓
- Redis: degrades to in-memory cache on init failure (`cache.py:33`) ✓
- Kill switch persistence via `kill_switch` table; latest-row read pattern ✓
- Migration runner: **NON-IDEMPOTENT — see C3**.

### Phase 8 — Telegram

- 7+ alert events: deposit confirmed, paper open, paper close, live open, live
  close (ambiguous submit), redeem won/lost, kill toggle, allowlist promotion,
  emergency pause/close ✓
- Webhook secret enforcement: `main.py:200-208` rejects unauthenticated
  /telegram/webhook with 403; ephemeral secret generated only when env var
  unset (warning logged) ✓
- Operator-only admin handler check: `_is_operator` compares
  `effective_user.id == OPERATOR_CHAT_ID` ✓
- Admin REST API: every endpoint protected via `_check` using
  `secrets.compare_digest` (`api/admin.py:21-27, 31-32, 68-69, 141, 148`) ✓


---

## 3. Critical Issues

Each finding cites file:line, observed behavior, expected behavior, and severity.

### C1 — CRITICAL — Kelly enforcement absent + capital_alloc_pct accepts 100%

- File: `domain/risk/constants.py:4` declares `KELLY_FRACTION = 0.25`.
- File: `domain/risk/gate.py` (entire file) — `KELLY_FRACTION` is NEVER referenced.
- File: `domain/signal/copy_trade.py:30-32` — sizing uses
  `capital_pct = Decimal(str(settings.get("capital_alloc_pct") or 0.5))`
  then `budget = balance * capital_pct`. No Kelly fraction is applied.
- File: `bot/handlers/setup.py:236-239` — `capital_alloc_pct` accepts any
  integer in the inclusive range `1..100`, then stored as `pct/100.0`. A
  user can therefore set 1.0 (= full allocation).
- Observed: copy-trade size is bounded only by `balance * capital_alloc_pct`
  (could be 100% of balance) and then clipped at gate step 13 to
  `balance * profile.max_pos_pct` (10% conservative cap). The Kelly
  constant declared in `constants.py` is decorative — it does not
  participate in any sizing decision.
- Expected (per CLAUDE.md HARD RULES + audit task scope):
  * Fractional Kelly `a = 0.25` must be applied to all sizing.
  * `capital_alloc_pct < 1.0` must be enforced at the input boundary.
- Severity: CRITICAL. Direct violation of explicit task criterion
  ("capital_alloc_pct must be < 1.0") and CLAUDE.md hard rule ("a = 1.0
  FORBIDDEN"). The 10% gate cap is a backstop, not Kelly.

### C2 — CRITICAL — `migrations/004` is non-idempotent → bot fails to restart

> Verification (run against the audited commit):
> ```
> $ git show 8c6aded3:projects/polymarket/crusaderbot/database.py | sed -n '45,57p'
> async def run_migrations() -> None:
>     pool = await init_pool()
>     migrations_dir = Path(__file__).parent / "migrations"
>     files = sorted(migrations_dir.glob("*.sql"))
>     ...
>     async with pool.acquire() as conn:
>         for f in files:
>             sql = f.read_text(encoding="utf-8")
>             logger.info("Running migration %s", f.name)
>             await conn.execute(sql)
> ```
> The runner globs `migrations/*.sql` only. `db/schema_r4.sql` is **not**
> referenced anywhere in `database.py` on this commit (the R4 forge
> report at `reports/forge/crusaderbot-r4-deposit-watcher.md:22, 99`
> claims it is, but that claim is stale — the wiring never landed). C2
> therefore depends solely on `migrations/004`'s shape, which is:


- File: `projects/polymarket/crusaderbot/migrations/004_deposit_log_index.sql:14-16`:
  ```sql
  ALTER TABLE deposits
      ADD CONSTRAINT deposits_tx_hash_log_index_key
      UNIQUE (tx_hash, log_index);
  ```
- File: `database.py:45-57` — `run_migrations` re-executes every `*.sql`
  in `migrations/` on every startup; there is no `schema_migrations`
  ledger table to skip already-applied files.
- Observed: PostgreSQL `ALTER TABLE … ADD CONSTRAINT` does NOT support
  `IF NOT EXISTS`. On the SECOND startup the constraint already exists
  → `duplicate_object` error → `run_migrations` raises → app lifespan
  startup aborts. `migrations/002` and `migrations/003` use
  `ADD COLUMN IF NOT EXISTS` correctly; only `004` is broken.
- Note: `db/schema_r4.sql:44-64` contains a `DO $$ … pg_constraint
  EXISTS check $$` that is correctly idempotent — but `db/schema_r4.sql`
  is never executed (`run_migrations` reads only `migrations/`).
- Expected: wrap the constraint add in `DO $$ … IF NOT EXISTS … $$`
  exactly like `db/schema_r4.sql:56-63`, OR introduce a
  `schema_migrations(filename PRIMARY KEY)` ledger table.
- Severity: CRITICAL. After the first deploy, every restart crashes
  before the FastAPI app finishes starting. Operationally fatal.

### C3 — CRITICAL — `scheduler.watch_deposits` promotes to Tier 3 on any deposit, ignoring `MIN_DEPOSIT_USDC`

- File: `scheduler.py:154-158`
  ```python
  await conn.execute(
      "UPDATE users SET access_tier = GREATEST(access_tier, 3) "
      "WHERE id = $1",
      user_id,
  )
  ```
- File: `config.py:67` — `MIN_DEPOSIT_USDC: float = 50.0` (the threshold
  the spec keys Tier-3 promotion to).
- Observed: ANY confirmed USDC deposit (including a 1-cent dust transfer)
  promotes the user from Tier 1/2 → Tier 3 ("Funded beta — auto-trade
  unlocked"). Tier-3 unlocks `auto_trade_on` toggling, dashboard balance,
  positions, and signal-scan inclusion (`scheduler.run_signal_scan`
  filters `WHERE access_tier >= 3`).
- Counter-evidence (correct path is in DEAD code): the unwired
  `services/deposit_watcher.py:484-508` correctly gates promotion on
  cumulative `balance >= MIN_DEPOSIT_USDC` and uses
  `services.user_service.bump_tier` for an audited atomic transition.
  None of that runs.
- Expected: gate `UPDATE users SET access_tier = GREATEST(...,3)` on
  `balance_usdc >= MIN_DEPOSIT_USDC`, audit the transition, and skip
  the bump otherwise.
- Severity: CRITICAL. Tier-escalation bypass — the entire Tier 3 gate
  is effectively `received_any_usdc`, defeating the funded-beta
  qualifier and giving auto-trade access to dust-deposit accounts.

---

## 4. High / Medium Findings

### H1 — Reorg handling absent in active deposit path

- File: `scheduler.watch_deposits` has no `removed=true` log handling.
- File: `services/deposit_watcher.py:328-347, 531-593` has the correct
  reorg-debit-and-delete pattern, but is dead code (see C2 in §4).
- Impact: a Polygon reorg that drops a previously-credited Transfer
  leaves the user balance permanently overstated until manual
  reconciliation. Polygon reorgs of >1 block are rare but documented.
- Severity: HIGH (operational integrity risk).

### H2 — Dead `services/*` module set with broken Settings + missing schema

- Imports: zero hits for `services.deposit_watcher`,
  `services.ledger`, `services.user_service`, `services.allowlist`
  anywhere in `main.py` / `scheduler.py` / `bot/dispatcher.py` /
  `bot/handlers/*`. (`bot/middleware/tier_gate.py` imports
  `services.allowlist` and `services.user_service`, but the decorator
  it defines is itself never bound to a handler — see Phase 1.)
- File: `services/deposit_watcher.py:108-110` references
  `self._config.ALCHEMY_POLYGON_WS_URL` and
  `self._config.USDC_CONTRACT_ADDRESS`; `config.py:11-79` declares
  neither, and `extra="ignore"` (line 15) silently drops them at load
  time. First attribute access would raise `AttributeError`.
- File: `services/ledger.py` writes to `sub_accounts` /
  `ledger_entries`, neither of which is created by any
  `migrations/*.sql`. The table DDL exists only in
  `db/schema_r4.sql`, which is not in the migration run path.
- Severity: **LOW (code-hygiene / latent)**. The runtime path on the
  audited commit does not import any of these modules, so today's
  go-live behavior is unaffected. Downgraded from the initial HIGH
  framing per Codex P2 review — severity should reflect demonstrated
  runtime behavior, not hypothetical future wiring. The cleanup is
  still worth doing (delete the `services/` tree, since R4 is
  satisfied by `scheduler.py` + `wallet/ledger.py`; alternatively,
  wire it as the canonical path with a matching migration
  `005_sub_accounts.sql` and retire the legacy poll), but it is not
  a go-live blocker.

### H3 — Two divergent ledger schemas in tree

- `wallet/ledger.py` (table `ledger`, balance materialized in
  `wallets.balance_usdc`) — used by paper.py, live.py, scheduler.py.
- `services/ledger.py` (table `ledger_entries` joined via
  `sub_accounts`) — used only by dead services/deposit_watcher.
- `daily_pnl` and gate.py drawdown/balance reads only consider the
  `ledger` table. Any future code that writes to `ledger_entries`
  will be invisible to the gate.
- Severity: **LOW (architectural drift, latent)**. Same downgrade
  rationale as H2: the `ledger_entries` half is unused on the audited
  runtime path, so today's gate sees a consistent view. The drift
  becomes a real defect only if/when the dead `services/` tree is
  wired in (tracked under H2). Not a go-live blocker.

### M1 — Dead `db/schema_r4.sql` duplicates migration 004

- File: `db/schema_r4.sql` re-declares `log_index` ALTER and the
  composite UNIQUE in addition to creating the `sub_accounts` /
  `ledger_entries` tables. Not run by `database.run_migrations`.
- Risk: misleads operators or future agents into thinking the
  sub-account ledger is provisioned in production.
- Recommendation: delete the file or move it under `migrations/` with
  a numeric prefix once C2 (idempotency) is fixed and the
  services/ledger code is the canonical path.
- Severity: MEDIUM (documentation drift).

### M2 — `scheduler.watch_deposits` and `wallet/ledger.credit_in_conn` skip drawdown's deposit-side denominator update

- `gate._max_drawdown_breached` reads
  `SUM(amount_usdc) FROM ledger WHERE type='deposit'` —
  `wallet.ledger.T_DEPOSIT == "deposit"` ✓ — this is consistent with
  the active path. No defect today, but the parallel
  `services.ledger.ENTRY_TYPE_DEPOSIT` ("deposit" string match) plus
  `ENTRY_TYPE_DEPOSIT_REORG` would silently disagree if the dead
  module were ever activated. Tracked under H2/H3.
- Severity: MEDIUM (latent).

### M3 — `services/__init__.py`, `bot/handlers/__init__.py`,
  `bot/middleware/__init__.py`, `domain/__init__.py` are all
  zero-byte.

- Pure import-namespace markers; no runtime impact.
- Severity: LOW (cosmetic).

### L1 — `wallet/generator.py:7` calls
  `Account.enable_unaudited_hdwallet_features()` at import time.

- The eth-account library prints a warning on first use; safe in
  practice but pins the project to BIP44 derivation that the upstream
  library has not formally audited. Documented hard requirement of
  the HD-wallet design.
- Severity: LOW (informational).

### L2 — `domain/execution/live.py:74` uses
  `shares = float(size_usdc) / max(price, 0.0001)`

- For pathological `price=0` markets the floor is 0.0001 → up to
  10000× notional shares. Gate step 11 (liquidity floor) and step 12
  (edge floor) make this unreachable in normal flow, but the live
  engine itself does not bound the result. Recommend rejecting prices
  below a sane min (e.g. 0.005) at submit time.
- Severity: LOW.

### L3 — `setup.py:298` validates copy-target address only by
  `startswith("0x") and len==42`, no checksum / EIP-55 check.

- Zero security impact (worst case: invalid address yields zero
  trades), but mismatches the wallet-side checksum in
  `wallet/generator.py`. Cosmetic.
- Severity: LOW.

---

## 5. Stability Score

| Category | Weight | Score |
|---|---|---|
| Architecture (clean structure, no shims, layered domain) | 20 | 16 |
| Functional (gate, paper, live, router, deposit credit) | 20 | 14 |
| Failure modes (CLOB ambiguity ✓, reorg ✗ in active path) | 20 | 12 |
| Risk rules (Kelly absent, tier-promo bypass) | 20 | 9 |
| Infra + Telegram (TLS webhook ✓, kill switch ✓, audit append-only ✓) | 10 | 8 |
| Latency (retry+backoff on every external call) | 10 | 5 |
| **Total** | **100** | **64** |

Architecture bumped +2 after H2/H3 severity downgrade (dead-code drift is hygiene, not runtime defect). Total band (CONDITIONAL) and verdict (BLOCKED, on critical findings alone) are unchanged.

---

## 6. Go-Live Status

**BLOCKED.** Score 64/100 (CONDITIONAL band) AND 3 critical findings.

Per WARP•SENTINEL rule "ANY single critical issue = BLOCKED. No exceptions",
verdict is BLOCKED on the strength of C1, C2, or C3 individually. Score
band is informational.

---

## 7. Fix Recommendations (priority ordered)

1. **C2 — fix migration 004 idempotency BEFORE any further deploy.**
   Replace the bare `ADD CONSTRAINT` with a `DO $$ … pg_constraint
   EXISTS … $$` block (template already in
   `db/schema_r4.sql:44-64`). Same restart will then succeed.
2. **C3 — gate the tier promotion in `scheduler.watch_deposits`.**
   Read accumulated `balance_usdc` after the credit; only execute
   `UPDATE users SET access_tier = GREATEST(...,3)` when
   `balance >= MIN_DEPOSIT_USDC`. Audit the transition via
   `audit.write` with `action='tier_promoted_funded'`.
3. **C1 — enforce Kelly + cap `capital_alloc_pct`.**
   * `setup.py:237-239`: change validator to `1 <= pct <= 99` (or 95)
     and persist as fraction. Update display string to match.
   * `copy_trade.py:30-32` (and any future strategy): apply
     `kelly_size = base_size * KELLY_FRACTION` at the strategy
     boundary, before clipping to `budget` and before gate step 13.
   * Promote `KELLY_FRACTION` from a dead constant to the actual
     sizing reducer.
4. **H1 — port the reorg-removal handler from
   `services/deposit_watcher._reverse_deposit` into
   `scheduler.watch_deposits`** (or finish wiring the WS service).
   Without this, a Polygon reorg can permanently inflate user balance.
5. **H2 + H3 + M1 — pick a single ledger model and delete the other.**
   Either:
   (a) keep `wallet/ledger.py` as canonical, delete
       `services/{deposit_watcher,ledger,allowlist,user_service}.py`,
       delete `bot/middleware/tier_gate.py`, delete `db/schema_r4.sql`; OR
   (b) migrate to `sub_accounts/ledger_entries` as canonical, add
       `migrations/005_sub_accounts.sql` with the table DDL, declare
       `ALCHEMY_POLYGON_WS_URL` + `USDC_CONTRACT_ADDRESS` in
       `config.Settings`, retire `scheduler.watch_deposits` in favor
       of the WS subscription, and rewrite gate.py daily-pnl /
       drawdown queries to consume `ledger_entries`.
6. **L2 — reject `price < 0.005` at the live order boundary**
   (`live.execute` and `polymarket.prepare_live_order`).

After these fixes, re-run WARP•SENTINEL with the same scope. C1–C3
must each produce a green finding; otherwise verdict remains BLOCKED.

---

## 8. Telegram Preview

```
🔒 GO-LIVE: BLOCKED  (CrusaderBot R1–R11 import)
Score: 64/100 · Critical: 3

Top blockers:
1. Kelly absent + capital_alloc_pct accepts 100%
   (setup.py:237 · copy_trade.py:30 · constants.py:4)
2. migrations/004 not idempotent — restart fails after first deploy
   (migrations/004_deposit_log_index.sql:14)
3. ANY deposit promotes Tier 3, ignoring MIN_DEPOSIT_USDC=50
   (scheduler.py:154)

Next:
• Patch C2 (DO $$ … IF NOT EXISTS), redeploy to confirm restart-clean.
• Patch C3 in scheduler.watch_deposits.
• Patch C1 in setup.py + copy_trade.py + gate.py.
• Then re-submit for WARP•SENTINEL revalidation.
```

Operator commands available unchanged in this slice:
`/admin`, `/allowlist <user> [tier]`, `/emergency` (pause / pause+close),
plus REST `POST /admin/kill`, `POST /admin/force-redeem`, and
`GET /admin/live-gate` (all bearer-token gated via
`secrets.compare_digest`).

---

## 9. Out of Scope (per task spec, recorded for traceability)

- Style / formatting / comments / whitespace
- Test coverage and missing tests
- Deployment (`Dockerfile`, `fly.toml`, `Procfile`)
- `state/` folder contents
- Performance / latency measurement
- Feature completeness vs blueprint v3.1

---

Done -- GO-LIVE: BLOCKED. Score: 64/100. Critical: 3.
PR: WARP/CRUSADERBOT-REPLIT-IMPORT (#852)
Report: projects/polymarket/crusaderbot/reports/sentinel/crusaderbot-replit-import.md
State: PROJECT_STATE.md NOT updated by Sentinel — declared worktree branch
       is `claude/audit-crusaderbot-import-Ar983`, not the canonical
       `WARP/CRUSADERBOT-REPLIT-IMPORT`. Per CLAUDE.md non-worktree mismatch
       rule, state-file edit is held until WARP🔹CMD confirms which branch
       owns the state update.
NEXT GATE: Return to WARP🔹CMD for final decision (fix C1–C3, then revalidate).
