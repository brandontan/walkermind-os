# Telegram Menu Scope Hardening - Founder Handoff

## 1. Executive summary
`telegram-menu-scope-hardening-20260407` is validated at repository/worktree level.
SENTINEL verdict is **APPROVED** with a **88/100** score, and **no critical blockers found**.

This supports a merge decision from a code-validation perspective, while keeping external runtime confirmation explicitly separate.

## 2. What changed
- `/start` numeric placeholder crash hardening was applied so malformed/placeholder numeric values no longer hard-crash the Telegram home/dashboard render path.
- Home callback live-path hardening was applied so malformed shared-state payloads do not break callback render flow.
- Root menu parity was maintained across reply and inline navigation contracts.
- Market-scope persistence was added for `all_markets_enabled`, enabled categories, and selection type across re-init/restart context.
- Category inference hardening was added for weak-metadata/uncategorized paths with deterministic fallback behavior.
- Blocked-scope guard was preserved so downstream processing is blocked when active scope is invalid (e.g., All Markets OFF with zero enabled categories).

## 3. What SENTINEL validated
- Actual `/start` execution path is stable under normal and malformed placeholder payload conditions.
- Home callback execution path is stable, including edit-message fallback behavior.
- Root menu actions function through normalized routing.
- Placeholder/malformed payloads do not crash the Telegram render paths tested.
- Scope persistence and restore behavior validated in runtime checks.
- Scope gate is enforced before ingest/signals when scope is blocked.
- No critical blocker remains in repo/worktree validation for this increment.

## 4. Remaining external caveats
- Railway/live deployment behavior is an external verification layer and is separate from repo/worktree validation.
- External market-context endpoint warnings may still appear in the validation container when upstream network access is unavailable.
- Live-device Telegram confirmation remains separate from local container validation where direct device proof is required.

## 5. Decision options
A. Proceed to COMMANDER merge decision now
B. Run BRIEFER-supported operational rollout note while waiting for Railway stability
C. Hold merge until live Railway confirmation is observed

## 6. Recommendation
**Recommend A**: proceed to COMMANDER merge decision now, because repository/worktree validation is APPROVED (88/100, no critical blockers), while explicitly tracking Railway/live-device confirmation as external post-validation assurance.
