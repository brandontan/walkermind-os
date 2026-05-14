# Forge Report — public-status-landing-page

- Branch: warp/build-public-status-landing-page
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: Public landing/status page on `/` and `/health` contract stability.
- Not in Scope: Trading logic, risk constants, capital logic, activation guard state changes, CLOB/order execution, Telegram behavior.

## Changes
- Replaced root `/` response in `main.py` from JSON heartbeat to read-only public HTML landing page.
- Landing page renders dark mobile-first card layout with Server Status, Health, Runtime, Activation Guards.
- Added `/health` link CTA and paper-trading/not-financial-advice disclaimer.
- Health data is sourced from existing `api.health` route contract; unavailable values render as N/A.
- Added targeted tests for `/` HTML contract and `/health` machine-readable JSON contract.

## Validation
- `python3 -m py_compile projects/polymarket/crusaderbot/main.py projects/polymarket/crusaderbot/tests/test_public_landing.py`
- `pytest -q projects/polymarket/crusaderbot/tests/test_public_landing.py`
- `pytest -q projects/polymarket/crusaderbot/tests/test_health.py projects/polymarket/crusaderbot/tests/test_api_ops.py`

## Safety Notes
- Activation guard values unchanged (OFF / NOT SET posture retained).
- `/health` machine-readable behavior preserved.
- No trading/runtime safety path modifications.
