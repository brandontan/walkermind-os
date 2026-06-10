# SENTINEL — live-notify-parity

Branch: WARP/root-live-notify-parity @ 952c7fd
Source: projects/polymarket/crusaderbot/reports/forge/live-notify-parity.md
Tier: MAJOR | Claim: NARROW INTEGRATION (live entry/close user-visibility side effects only)
Date: 2026-06-11 Asia/Jakarta | Validator: WARP•SENTINEL (inline, WARP•R00T lane)

## Environment

- Repo: /home/user/walkermind-os, branch verified via `git rev-parse` = WARP/root-live-notify-parity (matches declared)
- dev environment — infra warn-only, risk ENFORCED
- Diff base: origin/main...HEAD — 6 files, exactly the declared set (live.py, notifier.py, new test file, forge report, PROJECT_STATE.md, CHANGELOG.md)

## Test Plan

- Phase 0: report existence + 6 sections + metadata; PROJECT_STATE timestamp; declared file set
- Phase 1: diff discipline — call-site placement vs money path, byte-unchanged guard/risk surfaces
- Phase 2: fail-soft proof — wrapper load-bearing, writer contract never-raise
- Phase 3: break attempts — targeted tests, pin-test authenticity, full suite, ruff
- Phase 4: risk-constant + guard integrity grep on runtime diff

## Findings

### Phase 0 — Pre-test

- Forge report present with all 6 sections + Tier/Claim/Target/Not-in-Scope/Suggested-Next metadata (reports/forge/live-notify-parity.md:7-47) — PASS
- PROJECT_STATE.md `Last Updated : 2026-06-11 05:22` full timestamp, Status carries the lane — PASS
- No `phase*/` folders introduced; diff confined to 6 declared files (`git diff --stat`) — PASS

### Phase 1 — Diff discipline

- (a) execute(): broker submit at domain/execution/live.py:325; atomic persist (orders update + positions insert + ledger.debit_in_conn) at live.py:382-409; audit live_open at live.py:420-428. The ONLY in-body hunk starts at the notify swap live.py:429-453 — strictly after persist + audit. Diff hunk headers prove zero body changes before old line 423 — PASS
- Module-level additions (imports live.py:28-29, `_notifier = TradeNotifier()` at live.py:47) are side-effect-free: TradeNotifier is stateless with no `__init__` (services/trade_notifications/notifier.py:185-188); full suite import proves no cycle — PASS
- (b) close_position(): snapshot at live.py:652 strictly after finalize transaction (live.py:621-641) + audit live_close (live.py:642-647). Early return #1 not-claimed at live.py:518-522 and early return #2 finalize-lost at live.py:629-637 both precede the snapshot line — neither can reach it — PASS
- (c) assert_live_guards (live.py:60), slippage, order building, ledger calls, risk imports: untouched. `git diff --stat` on domain/risk/, order.py, slippage.py, paper.py, exit_watcher.py = 0 lines — byte-unchanged — PASS
- (d) notifier.py diff is the single header hunk (notifier.py:215-220); paper branch literal `📋  TRADE OPENED` is byte-identical to the removed literal — paper rendering unchanged, pinned by test — PASS
- `import html` removal safe: zero remaining `html.` usages in live.py (grep) — PASS
- Entry card price = `limit_price` (live.py:442), same value persisted as positions.entry_price (live.py:396,401 — $6 param) — parity claim verified — PASS

### Phase 2 — Fail-soft proof

- Wrapper live.py:435-453: `except Exception` → `logger.error` → falls through to unconditional return at live.py:454. Never re-raises. Correctly does NOT catch asyncio.CancelledError (BaseException) — cancellation hygiene intact — PASS
- Wrapper is LOAD-BEARING, not decoration: `await notifications_enabled_by_telegram_id(...)` at notifier.py:628 sits OUTSIDE both internal try/except blocks (notifier.py:612-624 guards prefs routing; notifier.py:638-648 guards TG send). notify_entry's `await self._send(...)` at notifier.py:247 is unguarded. A DB blip at notifier.py:628 propagates `_send` → `notify_entry` → execute() — after capital moved — unless caught at live.py:435-453 — PASS
- write_snapshot contract: try opens as FIRST statement at services/portfolio_snapshots.py:114 (even `get_pool()` at :115 inside); `except Exception` → WARNING → `return None` at portfolio_snapshots.py:139-143. Bare await at live.py:652 provably cannot raise — PASS
- Paper-close parity reference real: domain/execution/paper.py:151 calls the identical `write_snapshot(position["user_id"])` — PASS

### Phase 3 — Break attempts

- Targeted: 103 passed in 1.03s (test_live_notify_parity 7, test_live_execution_rewire 38, test_trade_notifications 16, test_notifications_gate 5, test_live_gate_hardening 37) — PASS
- Pin authenticity: tests/test_live_notify_parity.py:227-238 mocks `_notifier.notify_entry` with `side_effect=RuntimeError("prefs DB blip")` and byte-asserts the full execute() result dict (test:233). Without the live.py wrapper the mocked exception would crash `_run_execute` — a real pin, confirmed against the code-level escape path above — PASS
- Legacy bare send gone: test:221-225 asserts `send.assert_not_awaited()` — PASS
- Snapshot pins: finalized close snapshots once with USER_ID (test:241-246); unclaimed close skips (test:248-253) — PASS
- Header pins: live header renders (test:278-281); paper byte-unchanged (test:283-286) — PASS
- Full suite: **3409 passed, 11 skipped in 52.61s** — exact claim match (3402 baseline + 7 new, zero regressions) — PASS
- ruff: All checks passed on live.py, notifier.py, test_live_notify_parity.py — PASS

### Phase 4 — Risk-constant + guard integrity

- Runtime diff grep for risk/constants, ENABLE_LIVE_TRADING, Kelly, kill_switch, drawdown, MAX_POSITION, assert_live_guards: 3 hits, ALL unchanged context lines (live.py import block :44 and audit payload :428 surrounding the hunks). ZERO added/removed lines touch any risk token — PASS
- No new awaits before broker submission (first changed body line is post-audit live.py:429) — PASS

## Critical Issues

None found.

## Stability Score

| Area | Weight | Score | Evidence |
| --- | --- | --- | --- |
| Architecture | 20 | 20 | Placement exactly per claim; narrow integration respected; stateless singleton safe (live.py:47, notifier.py:185) |
| Functional | 20 | 20 | 7 hermetic pins + 103 targeted + 3409 full suite green; call kwargs match notify_entry signature (notifier.py:190-207) |
| Failure modes | 20 | 19 | Wrapper proven load-bearing (notifier.py:628 escape path); writer never raises; −1: finalize-lost snapshot-skip (live.py:636) proven by control flow only, no direct test pin |
| Risk | 20 | 20 | Zero risk-token diff lines; guard/risk files byte-unchanged (0 diff lines); no new pre-submit awaits |
| Infra + TG | 10 | 10 | TG card + AlertCenter mirror + prefs routing verified in _send (notifier.py:599-626); header parity pinned |
| Latency | 10 | 9 | Notify strictly post-money-path; same sequential-await shape as the replaced legacy send; −1: prefs DB read + web mirror add bounded post-trade latency before execute() returns |

**Total: 98/100 — Critical: 0**

## GO-LIVE Verdict

**APPROVED** — score 98 >= 85, zero critical issues. The declared claim survives adversarial review: the notify swap cannot precede or perturb the money path, the fail-soft wrapper is demonstrably load-bearing against a real escape path, the snapshot is unreachable from both degraded close paths, and the guard/risk surface is byte-identical to origin/main.

## Fix Recommendations

1. LOW — add a test pinning the finalize-lost path (live.py:629-637) skips the snapshot, mirroring the unclaimed pin at test:248-253. Control-flow proof is sound today; a pin protects against future refactor reordering.
2. LOW — consider hoisting the notifier.py:628 legacy prefs read inside a guard within `_send` itself in a future lane, making `_send` fully self-contained never-raise; the live.py call-site wrapper would then become defense-in-depth instead of the sole barrier.

NEXT GATE: Return to WARP•R00T for merge decision (full-bypass authority per owner directive 2026-06-05).
