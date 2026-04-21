# Telegram UX 01 — Refine Onboarding and Command Copy

Date: 2026-04-21 15:21 (Asia/Jakarta)
Branch: feature/refine-telegram-onboarding-and-public-ux-copy
Project Root: projects/polymarket/polyquantbot/

## 1. What was changed

- Refined `/help` copy to be scan-first in Telegram with clearer command intent and explicit public paper-beta safety boundaries.
- Refined `/status` copy into structured sections (Runtime, Safety, Paper metrics) to reduce wall-of-text behavior while preserving truthful paper-only posture.
- Refined `/start` session-success, session-rejected, and temporary backend-error replies to be clearer, calmer, and next-step oriented.
- Refined onboarding/session lifecycle fallback replies for not-onboarded, onboarded, already-linked, activated, activation-rejected, onboarding-rejected, and identity/runtime temporary errors.
- Refined unknown-command reply formatting to be friendlier and action-oriented, while preserving no live trading / no manual trade-entry constraints.

## 2. Files modified (full repo-root paths)

- projects/polymarket/polyquantbot/client/telegram/dispatcher.py
- projects/polymarket/polyquantbot/client/telegram/handlers/auth.py
- projects/polymarket/polyquantbot/client/telegram/runtime.py
- projects/polymarket/polyquantbot/reports/forge/telegram_ux_01_refine-onboarding-command-copy.md
- PROJECT_STATE.md

## 3. Validation Tier / Claim Level / Validation Target / Not in Scope / Suggested Next

Validation Tier   : MINOR
Claim Level       : FOUNDATION
Validation Target : Telegram onboarding and command UX copy surfaces for `/start`, `/help`, `/status`, unknown-command, and user-facing fallback/error responses
Not in Scope      : runtime activation/deploy/webhook changes, command-routing logic changes, live-trading enablement, production-capital readiness, wallet lifecycle expansion
Suggested Next    : COMMANDER review
