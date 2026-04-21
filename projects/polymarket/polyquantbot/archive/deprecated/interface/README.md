# Deprecated Interface Telegram Path Archive

This folder archives the deprecated `projects/polymarket/polyquantbot/interface` Telegram presentation implementation.

## Active source of truth

- `projects/polymarket/polyquantbot/telegram/view_handler.py`
- `projects/polymarket/polyquantbot/telegram/ui_formatter.py`

## Compatibility layer retained

- `projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
- `projects/polymarket/polyquantbot/interface/ui_formatter.py`

The interface-path files above are now thin import shims only, retained to avoid import breakage while removing duplicate Telegram UX implementation logic.

## Archived snapshot

- `projects/polymarket/polyquantbot/archive/deprecated/interface/telegram_legacy_20260421/`
