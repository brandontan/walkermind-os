# WARP-70 — Dynamic Capital from Risk Profile

Issue: #1290
Branch: WARP/warp70-dynamic-capital
Role: WARP•FORGE
Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: Auto Trade capital derived from `balance × risk_fraction` in `bot/handlers/mvp/autotrade.py:_read_state`
Not in Scope: messages_mvp render signatures, dispatcher, DB schema, `_flow()` wizard working value, notification balance line

## 1. What was built

Auto Trade screen capital is no longer the hardcoded `$100`. `_read_state()` now
reads the user's wallet balance and risk profile and derives capital as
`balance × risk_fraction`:

- 🟢 safe → 0.25
- 🟡 balanced → 0.50
- 🔴 aggressive → 0.80

Example: balance `$949.06`, balanced → capital `$474.53`. When balance is `0`
(new user, no deposit), capital falls back to `_DEFAULT_CAPITAL = 100.0`.
The risk label shown on the Auto Trade home is now sourced from the stored
`risk_profile` setting instead of always defaulting to "🟡 Balanced".

## 2. Current system architecture

`show_home()` → `_read_state(user)` → `_users.fetch_balance()` +
`_users.fetch_settings()` (existing helpers, no new DB access) → derived
`capital` + `risk` → `mvp.render_autotrade_home(...)`. No call-site or
keyboard changes; render signature unchanged.

## 3. Files created / modified

- Modified: `projects/polymarket/crusaderbot/bot/handlers/mvp/autotrade.py`
- Created: `projects/polymarket/crusaderbot/reports/forge/warp70-dynamic-capital.md`
- Updated: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Updated: `projects/polymarket/crusaderbot/state/WORKTODO.md`
- Updated: `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- `_RISK_CAPITAL_FRACTIONS` + `_DEFAULT_RISK_KEY` + `_RISK_LABELS` constants added.
- `_read_state()` derives `capital = round(balance × fraction, 2)`; `0` balance → `$100` fallback.
- Unknown / null `risk_profile` defaults to balanced (0.50) and "🟡 Balanced" label.
- `py_compile` clean on the modified file.

## 5. Known issues

- Full `pytest tests/` not exercised in this remote container — runtime deps
  (`asyncpg`, `python-telegram-bot`, cryptography Rust chain) unsatisfiable here,
  same posture as WARP-58/59/60/61. CI / WARP🔹CMD should run
  `pytest tests/ -v --tb=short` before merge.
- `_flow()` wizard default capital left at `_DEFAULT_CAPITAL` fallback — `_flow()`
  is synchronous with no DB/balance access; deriving balance there is out of the
  single-file MINOR scope. `do_start()` notification balance line not added (would
  require a `messages_mvp` signature change, outside the single-file constraint).

## 6. What is next

- WARP🔹CMD review + merge (issue marks "langsung merge saat PR masuk").
- Fly.io redeploy so the running bot pod imports the updated handler.

## Suggested Next Step

WARP🔹CMD review required. Tier: MINOR. No migration.
Source: projects/polymarket/crusaderbot/reports/forge/warp70-dynamic-capital.md
