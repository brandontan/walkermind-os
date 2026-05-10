# WARP•SENTINEL REPORT — phase5bc-preset-dashboard

Validation Tier: MAJOR (PR #925) + STANDARD focused audit (PR #926, explicit WARP🔹CMD request)
Claim Level (PR #925): NARROW INTEGRATION
Validation Target: PR #925 — strategy preset system (Phase 5C); PR #926 — dashboard hierarchy redesign (Phase 5B)
Not in Scope: Live trading activation, CLOB adapter, execution path, strategy engine, Phase 5D customization
Source Reports:
- projects/polymarket/crusaderbot/reports/forge/crusaderbot-phase5c-presets.md
- projects/polymarket/crusaderbot/reports/forge/crusaderbot-phase5b-dashboard.md
Audit Date: 2026-05-10 Asia/Jakarta

---

## PHASE 0 — PRE-TEST (SENTINEL BLOCKERS)

| Check | Result |
|---|---|
| Forge report at correct path (PR #925) | PASS — `reports/forge/crusaderbot-phase5c-presets.md` present, all 6 sections confirmed |
| Forge report at correct path (PR #926) | PASS — `reports/forge/crusaderbot-phase5b-dashboard.md` present, all 6 sections confirmed |
| `PROJECT_STATE.md` updated (PR #925 branch) | PASS — Last Updated 2026-05-09 22:00, Phase 5C in [IN PROGRESS] |
| No `phase*/` folders or imports | PASS — zero phase-prefix folders in any changed file |
| Domain structure correct | PASS — `domain/preset/` new module follows locked domain layout |
| Hard delete policy | PASS — no files deleted; migration is additive only |
| Implementation evidence for critical layers | PASS — `_on_activate` live guard, import-time validation, 30 hermetic tests |

**Phase 0: ALL CHECKS PASS — proceeding to validation phases.**

---

## TEST ENVIRONMENT

- Validation method: diff-level code audit (PR #925 and #926 vs shared base `6dcc1a75`)
- All file patches reviewed in full
- Activation guard grep performed across all changed files
- Test functions enumerated and mapped to requirements
- No live DB or Telegram session required for NARROW INTEGRATION claim

---

## PHASE 1 — FUNCTIONAL TESTING (PR #925)

### 1a. Preset Definitions

| Check | Result | Evidence |
|---|---|---|
| 5 presets defined | PASS | `domain/preset/presets.py`: `PRESETS` dict has 5 keys |
| PRESET_ORDER matches spec | PASS | `PRESET_ORDER = ("whale_mirror","signal_sniper","hybrid","value_hunter","full_auto")` |
| Recommended = whale_mirror | PASS | `RECOMMENDED_PRESET = "whale_mirror"` |
| Strategies use canonical keys | PASS | Only `copy_trade`, `signal`, `value` used across all presets |
| `get_preset()` returns None for unknown key | PASS | `PRESETS.get(key)` fallback; `test_get_preset_unknown_returns_none` |

### 1b. Import-Time Validation

| Check | Result | Evidence |
|---|---|---|
| `capital_pct >= 1.0` rejected | PASS | `__post_init__`: `not 0.0 < self.capital_pct < 1.0` raises ValueError |
| `max_position_pct > MAX_POSITION_PCT` rejected | PASS | `not 0.0 < self.max_position_pct <= MAX_POSITION_PCT` raises ValueError |
| `tp_pct` and `sl_pct` range-checked | PASS | `not 0.0 < self.tp_pct <= 1.0` and `sl_pct` same |
| Empty strategies rejected | PASS | `if not self.strategies: raise ValueError` |
| `test_preset_validation_rejects_oversize_capital` | PASS | `capital_pct=1.5` raises ValueError |
| `test_preset_validation_rejects_position_over_cap` | PASS | `max_position_pct=0.5` raises ValueError |

### 1c. Picker and Confirmation Card

| Check | Result | Evidence |
|---|---|---|
| Picker renders 5 rows in canonical order | PASS | `test_picker_keyboard_has_one_row_per_preset_with_recommended_marker` |
| ⭐ on first row (whale_mirror) | PASS | `assert "⭐" in labels[0]` |
| Callback data per row = `preset:pick:{key}` | PASS | `assert cbs == [f"preset:pick:{k}" for k in PRESET_ORDER]` |
| Confirm card shows all 6 values | PASS | `test_pick_renders_confirmation_with_all_values` |
| Confirm keyboard: activate / customize / back | PASS | `test_confirm_keyboard_carries_preset_key` asserts 3 callbacks |

### 1d. Activation (Paper)

| Check | Result | Evidence |
|---|---|---|
| `update_settings()` called once with all 6 kwargs | PASS | `upd_settings.assert_awaited_once()` + `kwargs` asserted for all 6 fields |
| `set_auto_trade(uid, True)` called | PASS | `set_auto.assert_awaited_once_with(uid, True)` |
| `set_paused(uid, False)` called | PASS | `set_p.assert_awaited_once_with(uid, False)` |
| Status card rendered after activation | PASS | `assert any("activated" in r for r in replies)` |

### 1e. Pause / Resume / Stop / Switch

| Check | Result | Evidence |
|---|---|---|
| Pause flips `paused=True`, re-renders status | PASS | `test_pause_persists_and_renders_paused_card` |
| Resume flips `paused=False`, re-renders status | PASS | `test_resume_persists_and_renders_running_card` |
| Stop clears `active_preset=None`, `max_position_pct=None`, `auto_trade_on=False` | PASS | `test_stop_yes_clears_preset_and_stops` asserts all 3 writes |
| Switch clears preset, re-shows picker | PASS | `test_switch_yes_clears_preset_and_shows_picker` asserts all 3 writes |
| Stop/Switch require confirmation step | PASS | `test_stop_intent_shows_confirmation`, `test_switch_intent_shows_confirmation` |
| Status keyboard swaps pause/resume button | PASS | `test_status_keyboard_swaps_pause_resume` |

### 1f. setup_root Routing

| Check | Result | Evidence |
|---|---|---|
| active_preset set → status card | PASS | `test_setup_root_routes_to_status_when_preset_active` |
| active_preset None → picker | PASS | `test_setup_root_routes_to_picker_when_no_preset` |

---

## PHASE 2 — PIPELINE END-TO-END

No pipeline or strategy execution path is modified by PR #925 or #926. Preset activation writes `user_settings` and flips `users.auto_trade_on` only. The trading scheduler reads these fields on its own cycle. **PASS — no pipeline bypass risk.**

---

## PHASE 3 — FAILURE MODES

| Failure Mode | Handling | Result |
|---|---|---|
| Unknown preset key on activate | Returns "❌ Unknown preset." via `_reply` | PASS |
| Unknown preset key on pick | Returns "❌ Unknown preset." via `_reply` | PASS |
| Status card fallback when no preset | Routes to picker | PASS |
| Live mode activation attempt | Returns explanatory message, zero DB writes | PASS |
| Tier 1 user attempts picker | `_ensure_tier2` returns False, alert shown | PASS |
| ctx.user_data None | `if ctx.user_data:` guard before pop | PASS |
| Callback with len(parts) < 2 | Early return guard before action dispatch | PASS |
| `get_user_by_telegram_id` returns None (PR #926) | Existing-user check is None-safe | PASS |
| `_fetch_stats` pool acquire (PR #926) | Uses `async with pool.acquire()` — connection auto-released | PASS |
| CONCERN — no transaction wrapper on 3 sequential activate writes | `update_settings` → `set_auto_trade` → `set_paused` are not atomic. If `set_auto_trade` fails after `update_settings` succeeds, settings are updated but auto_trade_on remains False. Paper mode only; risk is cosmetic inconsistency, not capital loss. | CONCERN (non-blocking) |

---

## PHASE 4 — ASYNC SAFETY

| Check | Result | Evidence |
|---|---|---|
| `asyncio` only — no `threading` imports | PASS | No `threading` import in any changed file |
| `pool.acquire()` used as context manager throughout | PASS | All DB reads use `async with pool.acquire()` |
| No shared mutable module-level state introduced | PASS | `PRESETS` and `PRESET_ORDER` are frozen/immutable at import |
| `Preset` dataclass is `frozen=True` | PASS | `@dataclass(frozen=True)` on `Preset` |
| No race condition on preset switch/stop | PASS — per-user scoped DB writes; no cross-user state | PASS |
| `_FakePool` in tests uses `async with` correctly | PASS — nested `__aenter__`/`__aexit__` implemented | PASS |

---

## PHASE 5 — RISK RULES IN CODE

| Risk Rule | Value | Verified | Result |
|---|---|---|---|
| Kelly fraction — no `capital_pct = 1.0` | Max is 0.80 (full_auto) | `test_presets_capital_under_full_kelly`: all presets `0 < x < 1` | PASS |
| Max position cap — `max_position_pct <= 0.10` | Max is 0.10 (full_auto, at cap) | `test_presets_obey_hard_position_cap`: all presets `<= MAX_POSITION_PCT` | PASS |
| `MAX_POSITION_PCT` imported from `domain/risk/constants` | Yes — `from ..risk.constants import MAX_POSITION_PCT` | Import in `domain/preset/presets.py` | PASS |
| Risk constants NOT modified | PASS | No edits in `domain/risk/` | PASS |
| Live trading guard (paper-only activate) | `if s.get("trading_mode") == "live": return` | `presets.py:_on_activate` | PASS |
| `test_activate_blocked_in_live_mode`: all 3 writes not awaited | PASS | `upd_settings.assert_not_awaited()` + `set_auto.assert_not_awaited()` + `set_p.assert_not_awaited()` | PASS |
| ENABLE_LIVE_TRADING not read or mutated | PASS — absent from all code files | grep scan across all 12 PR #925 files | PASS |
| USE_REAL_CLOB not read or mutated | PASS — absent from all code files | grep scan | PASS |
| EXECUTION_PATH_VALIDATED not read or mutated | PASS — absent from all code files | grep scan | PASS |
| CAPITAL_MODE_CONFIRMED not read or mutated | PASS — absent from all code files | grep scan | PASS |

---

## PHASE 6 — LATENCY

Preset surface is configuration-write only. No latency-sensitive execution path touched.

| Path | Verdict |
|---|---|
| Preset activation | 1 `update_settings` + 1 `set_auto_trade` + 1 `set_paused` — 3 sequential DB writes, well within 500ms budget |
| Status card render | 1 `get_settings_for` + 1 `get_balance` + 1 `daily_pnl` + 1 pool query for open count |
| No hot path (signal ingest / execution / order submission) modified | PASS |

**PASS — no latency concerns for NARROW INTEGRATION claim.**

---

## PHASE 7 — INFRA (Redis / PostgreSQL / Telegram)

| Component | Check | Result |
|---|---|---|
| PostgreSQL | Migration 016 additive, idempotent (`IF NOT EXISTS`) | PASS |
| PostgreSQL | No new tables; 2 nullable columns + 1 partial index on existing table | PASS |
| Redis | Not touched | PASS |
| Telegram | Bot handlers add `/preset` command and `^preset:` callback | PASS |
| Telegram | Tier gate enforced before any response | PASS |

---

## PHASE 8 — TELEGRAM ALERT EVENTS

PR #925 does not introduce Telegram alert events (not a monitoring/infra lane). The bot surface changes are UX handlers, not alert pipelines. No new `notify_operator` calls introduced.
**Out of scope for NARROW INTEGRATION claim — PASS.**

---

## PR #926 FOCUSED AUDIT (STANDARD)

### Dashboard Data Fetch

| Check | Result | Evidence |
|---|---|---|
| `_fetch_stats` uses single `pool.acquire()` for 4 queries | PASS | `async with pool.acquire() as conn: pos = await conn.fetchrow(...); trades = ...; pnl = ...; sett = ...` — all within one connection |
| All queries are read-only SELECT | PASS | No INSERT/UPDATE in `_fetch_stats` |
| All queries indexed by `user_id` | PASS | `WHERE user_id = $1` on all 4 queries |
| No new tables or schema changes | PASS | Only existing `positions`, `ledger`, `user_settings` tables used |
| `dashboard_nav_cb` trades sub-handler uses `pool.acquire()` | PASS — `async with pool.acquire() as conn` |
| CONCERN — `_fetch_stats` 4 queries not in READ TRANSACTION | Reads are not serializable; dashboard may show momentarily inconsistent data. Acceptable for display-only. | CONCERN (non-blocking) |

### /start Routing

| Check | Result | Evidence |
|---|---|---|
| Existing Tier 2+ users → dashboard | PASS | `if existing is not None and has_tier(user["access_tier"], Tier.ALLOWLISTED): await dashboard(update, ctx); return` |
| New users → onboarding welcome | PASS | `existing = None` → falls through to tier_label / welcome text |
| Tier 1 browse users → onboarding | PASS | `has_tier(Tier.ALLOWLISTED)` is False for Tier 1 → falls through |
| `audit.write` fires for ALL /start calls | PASS (improvement) | Moved before early-return; previously only fired for new users |
| `get_user_by_telegram_id` is existing accessor | PASS | Imported from `...users`; not a new function |
| Wallet creation logic unchanged | PASS | `if wallet is None: create_wallet_for_user` path preserved |

### Activation Guards (PR #926)

| Guard | Result | Evidence |
|---|---|---|
| ENABLE_LIVE_TRADING | PASS — not present in any PR #926 code diff | |
| USE_REAL_CLOB | PASS | |
| EXECUTION_PATH_VALIDATED | PASS | |
| CAPITAL_MODE_CONFIRMED | PASS | |
| Comment deletion in `autotrade_toggle_cb` | PASS — 6 lines of explanatory comments removed; functional `autotrade_toggle_pending_confirm` call preserved | `dashboard.py` diff |

### No Trading Logic Touched

| Check | Result | Evidence |
|---|---|---|
| `autotrade_toggle_cb` functional logic preserved | PASS | Diff shows only comment deletion, not logic deletion |
| `close_position_cb` unchanged | PASS | Not in PR #926 diff |
| `positions()`, `activity()` unchanged | PASS | Not in PR #926 diff |
| No imports from `domain/execution/`, `integrations/clob/`, `integrations/polymarket.py` | PASS | Only `database`, `users`, `wallet.*`, `keyboards` imports in changed files |

---

## CROSS-PR CONFLICT ANALYSIS

| File | PR #925 Change | PR #926 Change | Conflict Risk |
|---|---|---|---|
| `bot/dispatcher.py` | Adds `preset:` callback handler after `setup_callback` (hunk at ~line 94) | Adds `dashboard:` callback handler after `settings_callback` (hunk at ~line 101) | LOW — different line ranges, non-overlapping hunks |
| `bot/keyboards/__init__.py` | No change (PR #925 creates new `bot/keyboards/presets.py`) | Adds `dashboard_nav()` function | NO CONFLICT |
| `bot/handlers/dashboard.py` | No change | Full rewrite | NO CONFLICT |
| `bot/handlers/setup.py` | Modified (adds `setup_root` routing + `setup_legacy_root`) | Not in PR #926 | NO CONFLICT |
| `state/PROJECT_STATE.md` | Updated (5C in progress) | Updated (5B added) | NEEDS REBASE — states will diverge; WARP🔹CMD to merge sequentially |

**GitHub `mergeable_state: clean` on both PRs (shared base `6dcc1a75`). If #925 merges first, #926 dispatcher.py hunk will apply cleanly — different context lines. Low risk.**

---

## STABILITY SCORE

### PR #925 (MAJOR)

| Domain | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20% | 19/20 | Frozen dataclass, import-time validation, locked domain layout, clean separation. Minor: 3 sequential activate writes not in transaction. |
| Functional | 20% | 19/20 | 30 hermetic tests, all flows verified via mock await assertions. Minor: `_preset_status_text` not independently tested (exercised via `show_preset_status` path). |
| Failure modes | 20% | 17/20 | Live guard verified. Unknown preset handled. Tier gate enforced. Missing: no retry/backoff on `update_settings` / `set_auto_trade` DB calls; no test for pool acquisition failure. |
| Risk rules | 20% | 20/20 | All 4 activation guards absent from code. MAX_POSITION_PCT enforced at import time. No full Kelly. Risk constants untouched. Live guard verified by dedicated test. |
| Infra + Telegram | 10% | 8/10 | Migration idempotent, additive. Telegram handlers gated correctly. No Telegram alert pipeline added (out of scope). |
| Latency | 10% | 9/10 | Config write path well within budget. No hot path touched. |
| **Total** | **100%** | **92/100** | |

### PR #926 (STANDARD — focused audit)

| Domain | Weight | Score | Notes |
|---|---|---|---|
| Dashboard data fetch | 25% | 23/25 | Single connection for 4 queries. All reads indexed. Minor: not in READ TRANSACTION (display-only, acceptable). |
| /start routing | 25% | 24/25 | Correct routing for all 3 cases. Audit write improvement. Minor: no automated test for routing branch. |
| Activation guards untouched | 25% | 25/25 | All 4 guards absent. Comment deletion confirmed cosmetic. |
| No trading logic touched | 25% | 25/25 | Zero execution/risk imports added. All trading callbacks preserved. |
| **Total** | **100%** | **97/100** | |

---

## CRITICAL ISSUES

**PR #925:** None found.

**PR #926:** None found.

No single critical issue in either PR. No BLOCKED verdict triggered.

---

## GO-LIVE STATUS

### PR #925 — WARP/CRUSADERBOT-PHASE5C-PRESETS

**VERDICT: APPROVED**

Score: 92/100. Zero critical issues. All MAJOR audit phases pass.

Rationale:
- Activation guards (4/4) completely absent from all code files — no live trading bypass path exists.
- Live guard in `_on_activate` enforced and verified by dedicated test with `assert_not_awaited()` on all 3 DB writes.
- Preset values comply with `MAX_POSITION_PCT` (0.10 hard cap) and no-full-Kelly rule, enforced at Python import time via `__post_init__`.
- Migration 016 is additive and idempotent — safe to apply to any database state.
- 30 hermetic tests with full mock isolation; no real DB or API calls.
- Zero edits in `domain/execution/`, `integrations/clob/`, `integrations/polymarket.py`.

Score rationale for deductions:
- -1 Architecture: 3 sequential activate writes (update_settings / set_auto_trade / set_paused) not in a transaction. Partial failure could leave settings updated with auto_trade_on=False. Paper mode only — no capital at risk. Acceptable.
- -1 Functional: `_preset_status_text` not unit-tested directly (covered implicitly via status card render tests).
- -3 Failure modes: No retry/backoff on DB writes in the activate flow; no test for pool acquisition failure in status card.

**WARP🔹CMD: safe to merge PR #925 to main.**

### PR #926 — claude/dashboard-hierarchy-redesign-TwPJB

**VERDICT: APPROVED (with branch name flag)**

Score: 97/100. Zero critical issues. All STANDARD focused audit items pass.

Rationale:
- No trading logic, risk gates, or activation guards touched.
- Dashboard data fetch uses existing accessors; single DB connection for 4 grouped queries.
- /start routing correct for all 3 user states (new, Tier 1, existing Tier 2+).
- Activation confirmation flow (`autotrade_toggle_pending_confirm`) preserved.

**BRANCH NAME NON-COMPLIANCE:** Branch is `claude/dashboard-hierarchy-redesign-TwPJB` (auto-generated). Declared WARP branch is `WARP/CRUSADERBOT-PHASE5B-DASHBOARD`. Per CLAUDE.md: WARP•SENTINEL never blocks on branch name alone. Flag to WARP🔹CMD for resolution at merge (rebase or squash-merge onto `WARP/CRUSADERBOT-PHASE5B-DASHBOARD` before the merge commit if policy requires).

**WARP🔹CMD: safe to merge PR #926 to main. Resolve branch name posture at merge.**

---

## FIX RECOMMENDATIONS (priority ordered)

### Critical (0)

None.

### High (1 — non-blocking, address before Phase 5D)

1. **PR #925 — Activate write atomicity** (`bot/handlers/presets.py:_on_activate`)
   Wrap `update_settings` + `set_auto_trade` + `set_paused` in a single DB transaction or use a combined helper that writes all fields (including `auto_trade_on` and `paused`) in one atomic call. Relevant in live mode when Phase 5D extends preset activation to live. Not required before merge; required before live activation is re-evaluated.

### Medium (2 — address in Phase 5D lane)

2. **PR #925 — DB write retry** (`bot/handlers/presets.py:_on_activate`, `_on_stop_yes`, `_on_switch_yes`)
   `update_settings`, `set_auto_trade`, `set_paused` calls have no retry/backoff on transient DB errors. Add consistent retry posture (3 attempts, exponential backoff) before any live-mode gate is opened.

3. **PR #926 — Automated test for /start routing** (`bot/handlers/onboarding.py:start_handler`)
   The `existing is not None and has_tier(...)` routing branch has no automated coverage. Add a test that mocks `get_user_by_telegram_id` returning a user record and verifies `dashboard()` is called instead of the onboarding text.

### Low (2 — deferred)

4. **PR #926 — Extra DB round-trip on /start for existing users** (`bot/handlers/onboarding.py`)
   `get_user_by_telegram_id` + `upsert_user` = 2 queries per /start. Consider a single `upsert_user_returning_created_flag` pattern to eliminate the extra round-trip.

5. **PR #925 — `_preset_status_text` standalone test**
   Currently exercised only indirectly through show_preset_status and _on_activate. Add one direct test asserting STOPPED/PAUSED/RUNNING strings for the three state paths.

---

## DEFERRED BACKLOG

The following items are inherited from prior SENTINEL reports and remain deferred:

- `[DEFERRED]` Concurrent HALF_OPEN trial race in CircuitBreaker (Phase 4E, P2)
- `[DEFERRED]` CLOB circuit-open alert text uses plain markdown rather than MarkdownV2 (P2)
- `[DEFERRED]` Ops dashboard CLOB circuit card lacks SSE/WS push refresh (enhancement)
- `[DEFERRED]` `integrations/polymarket.py _build_clob_client()` dead code cleanup

None of the above are impacted by PR #925 or PR #926.

---

## TELEGRAM PREVIEW

### Alert format (existing, unchanged by these PRs)

```
⚠️  [SENTINEL] Phase 5C preset system validated.
Score: 92/100 | Verdict: APPROVED
Critical Issues: 0
Next: WARP🔹CMD merge decision on PR #925 + PR #926
```

### Dashboard Auto-Trade section (PR #926, new format)

```
🤖 Auto-Trade
├─ Status: ✅ ACTIVE
├─ Preset: Copy Trade, Signal
├─ Risk: 🟡 Balanced
└─ Mode: 📝 Paper
```

### Preset Status Card (PR #925, new surface)

```
🐋 Whale Mirror — 🟢 Safe
State: ✅ RUNNING

Live stats
├ Balance        : $250.00
├ Today's P&L    : $+12.50
└ Open positions : 2

Active config
├ Capital        : 50%
├ TP / SL        : +20% / -10%
└ Max position   : 5%

[✏️ Edit] [🔄 Switch] [⏸ Pause] [🛑 Stop]
```

