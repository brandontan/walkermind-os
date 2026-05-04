# WARP•SENTINEL Re-Verify — CrusaderBot C1/C2/C3

- Task: CRUSADERBOT-C1C2C3-REVERIFY
- Scope: Targeted re-audit of three critical findings raised in PR #853.
- Source PR: bayuewalker/walkermind-os#852
- Branch under audit: `WARP/CRUSADERBOT-REPLIT-IMPORT`
- Commit verified: `aca485e fix(crusaderbot): resolve SENTINEL C1+C2+C3 critical findings`
- Mode: read-only verification. No source files modified.

This is NOT a full audit. Only C1, C2, C3 from the prior BLOCKED verdict
(PR #853) were re-checked. All other findings, scope, and stability scoring
from the original audit are out of scope and untouched.

---

## C1 — Kelly enforcement + capital_alloc_pct cap

### 1. KELLY_FRACTION declared

`projects/polymarket/crusaderbot/domain/risk/constants.py:4`

```python
KELLY_FRACTION = 0.25
```

Declared at module top, hard-wired, not env/yaml/db overridable
(per the module docstring at line 1).

### 2. KELLY_FRACTION imported and used in the position sizing path

`projects/polymarket/crusaderbot/domain/risk/gate.py:13`

```python
from . import constants as K
```

`projects/polymarket/crusaderbot/domain/risk/gate.py:250-258` (gate step 13,
final size cap — the live sizing math):

```python
# Fractional Kelly enforcement (CLAUDE.md hard rule: a=0.25, full Kelly forbidden).
# Global K.KELLY_FRACTION acts as the hard cap; per-profile kelly is clamped to it.
assert 0 < K.KELLY_FRACTION <= 0.5, \
    f"KELLY_FRACTION {K.KELLY_FRACTION} out of safe range"
kelly = min(float(profile.get("kelly", K.KELLY_FRACTION)), K.KELLY_FRACTION)
max_pos_pct = float(profile["max_pos_pct"])
assert 0 < max_pos_pct < 1.0, \
    f"max_pos_pct {max_pos_pct} must be < 1.0"
max_pos_size = balance * Decimal(str(max_pos_pct)) * Decimal(str(kelly))
final_size = min(ctx.proposed_size_usdc, max_pos_size)
```

Per-profile kelly (e.g. `aggressive` = 0.25, `balanced` = 0.20) is clamped
by `min(..., K.KELLY_FRACTION)` so no profile can ever escape the
`0.25` global cap. `final_size` is `min(proposed, max_pos_size)` and the
result feeds the actual order, so this is on the live execution path.

### 3. capital_alloc_pct validator rejects values >= 1.0

`projects/polymarket/crusaderbot/bot/handlers/setup.py:236-250`

```python
if awaiting == "capital_pct":
    pct = float(text)
    # Cap strictly < 1.0 (max 95%). Full allocation is forbidden by
    # CLAUDE.md hard rule (no full Kelly equivalent).
    if not 1 <= pct <= 95:
        await update.message.reply_text(
            "❌ capital_alloc_pct must be less than 1.0 (100%). "
            "Max allowed: 0.95"
        )
        # Keep `awaiting` so the user can retry immediately.
        return True
    capital_alloc = pct / 100.0
    assert 0 < capital_alloc < 1.0, \
        f"capital_alloc_pct {capital_alloc} must be < 1.0"
    await update_settings(user["id"], capital_alloc_pct=capital_alloc)
```

Range check is `1 <= pct <= 95` (strictly less than 100, i.e. strictly less
than 1.0 after `/100`). Anything `>= 1.0` falls through the negation, the
user is rejected, and `awaiting` is preserved so they can retry. The
post-divide assertion (`0 < capital_alloc < 1.0`) is a runtime guard against
any future code path that might bypass the surface validator.

### 4. Runtime assertions in the sizing path

Three independent guards confirmed:

- `gate.py:252-253` — `assert 0 < K.KELLY_FRACTION <= 0.5` (global cap sanity).
- `gate.py:256-257` — `assert 0 < max_pos_pct < 1.0` (per-profile cap sanity).
- `setup.py:248-249` — `assert 0 < capital_alloc < 1.0` (per-user cap sanity).

### Verdict — C1: PASS

- KELLY_FRACTION lives in the live execution path, not just declared. ✅
- capital_alloc_pct is strictly `< 1.0` (max 0.95). ✅
- Runtime assertion guards exist on `KELLY_FRACTION`, `max_pos_pct`, and
  `capital_alloc_pct`. ✅

---

## C2 — migrations/004 idempotency

### Full content of migration

`projects/polymarket/crusaderbot/migrations/004_deposit_log_index.sql`:

```sql
-- 004_deposit_log_index.sql
-- Fix: a single Polygon tx can emit multiple USDC Transfer logs to different
-- tracked deposit addresses. With UNIQUE(tx_hash) only the first log was
-- credited; subsequent logs in the same tx were silently dropped as duplicates,
-- under-crediting users. Make uniqueness (tx_hash, log_index) so every log in
-- the same tx is treated as a distinct deposit row.
--
-- Idempotency: PostgreSQL ALTER TABLE ADD CONSTRAINT does not support
-- IF NOT EXISTS, so each statement is wrapped in a DO $$ guard. This file
-- must be safe to run multiple times — run_migrations re-executes it on
-- every startup.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'deposits'
        AND column_name = 'log_index'
    ) THEN
        ALTER TABLE deposits
            ADD COLUMN log_index INTEGER NOT NULL DEFAULT 0;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'deposits_tx_hash_key'
    ) THEN
        ALTER TABLE deposits
            DROP CONSTRAINT deposits_tx_hash_key;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'deposits_tx_hash_log_index_key'
    ) THEN
        ALTER TABLE deposits
            ADD CONSTRAINT deposits_tx_hash_log_index_key
            UNIQUE (tx_hash, log_index);
    END IF;
END $$;
```

### Idempotency check matrix

| Statement                                          | Guard                               | Lines |
|----------------------------------------------------|-------------------------------------|-------|
| `ADD COLUMN log_index`                             | `DO $$ ... IF NOT EXISTS (...) ...` | 13–23 |
| `DROP CONSTRAINT deposits_tx_hash_key` (old)       | `DO $$ ... IF EXISTS (...) ...`     | 25–34 |
| `ADD CONSTRAINT deposits_tx_hash_log_index_key`    | `DO $$ ... IF NOT EXISTS (...) ...` | 36–46 |

Bare `ALTER TABLE` statements at file scope: **0**. Every `ALTER TABLE` is
inside a `DO $$ ... END $$` block whose body checks the relevant catalog
view (`information_schema.columns` for the column, `pg_constraint` for the
two constraints) before acting.

### Verdict — C2: PASS

- ADD COLUMN wrapped in `DO $$` with `IF NOT EXISTS` against
  `information_schema.columns`. ✅
- DROP CONSTRAINT (old `deposits_tx_hash_key`) wrapped in `DO $$` with
  `IF EXISTS` against `pg_constraint`. ✅
- ADD CONSTRAINT (new `deposits_tx_hash_log_index_key`) wrapped in `DO $$`
  with `IF NOT EXISTS` against `pg_constraint`. ✅
- Zero bare `ALTER TABLE` statements that would fail on re-run. ✅

Re-running this migration on a database that has already been migrated is a
no-op — every guard short-circuits.

---

## C3 — Tier 3 promotion MIN_DEPOSIT_USDC gate

### Code under audit

`projects/polymarket/crusaderbot/scheduler.py` — `watch_deposits()`,
inside the per-transfer `pool.acquire() / conn.transaction()` block:

```python
# scheduler.py:103-104
settings = get_settings()
min_deposit = Decimal(str(settings.MIN_DEPOSIT_USDC))
```

```python
# scheduler.py:152-184  (inside conn.transaction())
await ledger.credit_in_conn(
    conn, user_id, amount, ledger.T_DEPOSIT,
    ref_id=row["id"], note=t["tx_hash"],
)
# Tier 3 promotion gated on cumulative confirmed deposits
# >= MIN_DEPOSIT_USDC. Dust deposits must not bypass the
# funded-beta tier gate.
total_balance = Decimal(str(await conn.fetchval(
    "SELECT COALESCE(SUM(amount_usdc), 0) FROM deposits "
    "WHERE user_id = $1 AND confirmed_at IS NOT NULL",
    user_id,
) or 0))
tier_promoted = total_balance >= min_deposit
if tier_promoted:
    await conn.execute(
        "UPDATE users SET access_tier = GREATEST(access_tier, 3) "
        "WHERE id = $1",
        user_id,
    )
    logger.info(
        "user promoted to Tier 3: user_id=%s "
        "total_balance=%s min_required=%s",
        user_id, float(total_balance),
        float(settings.MIN_DEPOSIT_USDC),
    )
else:
    logger.info(
        "deposit credited but below MIN_DEPOSIT_USDC — "
        "Tier 3 not granted: user_id=%s total_balance=%s "
        "min_required=%s",
        user_id, float(total_balance),
        float(settings.MIN_DEPOSIT_USDC),
    )
```

User notification path also branches on `tier_promoted`:

```python
# scheduler.py:206-213
for tg_id, amt, tx, tier_promoted in notify_after:
    if tier_promoted:
        tail = "You're now Tier 3 — auto-trade unlocked."
    else:
        tail = (
            f"Below minimum (${float(min_deposit):.2f} USDC) — "
            "Tier 3 not yet unlocked. Top up to enable auto-trade."
        )
```

### Check matrix

| Required behaviour                                   | Found at                                            |
|------------------------------------------------------|-----------------------------------------------------|
| `MIN_DEPOSIT_USDC` accessed from settings            | scheduler.py:104, 175, 183 (`settings.MIN_DEPOSIT_USDC`) |
| Cumulative confirmed-deposit balance queried         | scheduler.py:159–163 (`SUM(amount_usdc) WHERE confirmed_at IS NOT NULL`) |
| Promotion conditional on `balance >= MIN_DEPOSIT_USDC` | scheduler.py:164 (`tier_promoted = total_balance >= min_deposit`) |
| `UPDATE users SET access_tier` only inside `if tier_promoted` branch | scheduler.py:165–170 |
| Below-threshold case logs and skips                  | scheduler.py:177–184 (`else: logger.info(... "Tier 3 not granted" ...)`) |
| User notified that Tier 3 is NOT unlocked yet        | scheduler.py:209–213 |
| Promotion + balance read in same DB transaction      | scheduler.py:137 `async with conn.transaction()` wraps the whole block, so the SUM and the UPDATE are atomic with the deposit insert |

The `UPDATE users SET access_tier = GREATEST(access_tier, 3)` is reached
only on the `tier_promoted` branch. There is no other code path in
`watch_deposits` that mutates `access_tier`. A dust deposit (below
`MIN_DEPOSIT_USDC` cumulative) credits the ledger but does NOT touch
`access_tier`, and the user is messaged accordingly.

### Verdict — C3: PASS

- Cumulative balance query exists and runs before the tier update. ✅
- Promotion is strictly gated by `total_balance >= MIN_DEPOSIT_USDC`. ✅
- Below-threshold case logs (`"deposit credited but below MIN_DEPOSIT_USDC"`)
  and skips — no silent promotion. ✅
- Read + update are inside the same `conn.transaction()`, so a concurrent
  dust deposit cannot race the gate. ✅

---

## Out of scope

Per the task brief, this re-verify only covers C1, C2, C3. The following
were NOT re-evaluated in this pass and the prior PR #853 verdict on them
stands until a separate audit is requested:

- Stability score recomputation (Phases 1–8).
- Other criticals, high-severity, or backlog items from PR #853.
- Any code outside `domain/risk/`, `bot/handlers/setup.py`,
  `migrations/004_deposit_log_index.sql`, and the Tier 3 block in
  `scheduler.py`.

No source files were modified during this re-verify. The only artifact
written is this report.

---

## Final verdict

`C1 ✅ C2 ✅ C3 ✅ — SENTINEL PASS. PR #852 approved for merge.`

NEXT GATE: WARP🔹CMD reviews PR #852 and decides merge.
