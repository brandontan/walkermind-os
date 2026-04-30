# telegram_menu_truth_fix_20260406

## 1. What was built
- Completed a Telegram menu-truth correctness pass focused on operator-facing live menu identity and content routing for home/system/status, wallet, positions, exposure, trade, pnl, performance, market/markets, settings, control, notifications, mode, auto-trade, refresh/summary, and empty/sparse states.
- Implemented distinct menu contracts so positions/exposure and pnl/performance no longer render as near-duplicates.
- Removed wrong-context block bleed by tightening final-renderer block gating: exposure no longer inherits position/market cards by default; wallet and trade no longer display exposure summaries unless explicitly supplied in their own contract.
- Fixed pnl-facing binding so active-position state and unrealized vs realized composition are reflected from the normalized payload path used by callback/refresh/edit-menu rendering.
- Added ref metadata dedup safeguards so cards do not display duplicated reference labels when fallback title text already includes a ref fragment.

## 2. Design principles
- **Truth over style:** menu identity is defined by purpose-specific data contracts first, then rendered in shared visual grammar.
- **View isolation:** cards only render in menus where they are context-valid; no implicit reuse across unrelated menu types.
- **Parity across entry paths:** callback payload normalization and `render_view` contracts are aligned so command/callback/edit/refresh paths converge on the same menu truth.
- **Sparse-safe behavior:** empty/sparse payload handling keeps each menu’s identity distinct (positions empty != exposure empty, pnl sparse != performance sparse).
- **Metadata hygiene:** market labels remain title/question/name-first and ref metadata is secondary + deduplicated per card.

## 3. Files changed
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/ui_formatter.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`
- `/workspace/walker-ai-team/projects/polymarket/polyquantbot/reports/forge/telegram_menu_truth_fix_20260406.md`
- `/workspace/walker-ai-team/PROJECT_STATE.md`

## 4. Before/after improvement summary
- **Full menu truth audit:**
  - Before: multiple menus shared overly broad block append behavior, causing identity drift and repeated payload meaning.
  - After: explicit mode-to-block contracts enforce purpose-specific composition.
- **Positions vs exposure separation:**
  - Before: both screens were dominated by similar position+market content.
  - After: positions focuses on position card and active position details; exposure focuses on aggregate exposure posture and concentration summary.
- **PnL vs performance separation:**
  - Before: both screens read as generalized pnl/drawdown summaries.
  - After: pnl highlights realized/unrealized + active-position movement state; performance highlights scorecard metrics (trades/win-rate/drawdown).
- **Trade and wallet isolation fix:**
  - Before: these menus could inherit unrelated aggregate exposure meaning.
  - After: trade is position/action context; wallet is account-capital context; neither receives generic exposure block bleed.
- **Live pnl binding/update correctness fix:**
  - Before: normalized callback payload lacked strong position-derived unrealized propagation in menu summary paths.
  - After: callback payload now includes normalized open positions + unrealized aggregation; view payload derivation computes total/unrealized/realized consistently.
- **Callback/command/refresh parity:**
  - Before: equivalent actions could diverge via payload shape assumptions.
  - After: `view_handler` derives primary position + totals from list-based and count-based payloads, preserving menu truth across entry paths.
- **Market label + ref dedup:**
  - Before: fallback title and explicit ref line could duplicate reference context.
  - After: per-card dedup avoids extra ref line if label already carries the same ref fragment.
- **Empty/sparse menu correctness:**
  - Before: sparse fallback messaging could blur menu identity.
  - After: positions/exposure/pnl each emit menu-specific empty-state guidance.
- **No logic-layer drift:**
  - Confirmed UI-only scope: no strategy/risk/execution/infra/websocket/async behavior changes.

## 5. Issues
- Real Telegram screenshot capture is not available in this Codex environment.
- External `market_context` endpoint remains unreachable from this container, so checks use safe fallback rendering and warning logs.
- Async pytest plugin is unavailable in this environment, so callback parity evidence was gathered through direct async render/callback harness scripts.

## 6. Next
- SENTINEL validation required for telegram-menu-truth-fix-20260406 before merge.
Source: projects/polymarket/polyquantbot/reports/forge/telegram_menu_truth_fix_20260406.md
