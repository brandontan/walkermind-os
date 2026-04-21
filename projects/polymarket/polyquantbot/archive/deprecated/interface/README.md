# Deprecated Interface Telegram Path Archive

This folder archives deprecated Telegram-facing files that previously lived under
`projects/polymarket/polyquantbot/interface`.

## Active source of truth

- `projects/polymarket/polyquantbot/telegram/view_handler.py`
- `projects/polymarket/polyquantbot/telegram/ui_formatter.py`

## Compatibility shims retained (transitional)

- `projects/polymarket/polyquantbot/interface/telegram/__init__.py`
- `projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
- `projects/polymarket/polyquantbot/interface/ui_formatter.py`

These files are intentionally thin import shims only, retained to avoid import breakage while duplicate Telegram implementation logic remains archived.

## Archived legacy snapshot

- `projects/polymarket/polyquantbot/archive/deprecated/interface/telegram_legacy_20260421/__init__.py`
- `projects/polymarket/polyquantbot/archive/deprecated/interface/telegram_legacy_20260421/view_handler.py`
- `projects/polymarket/polyquantbot/archive/deprecated/interface/telegram_legacy_20260421/ui_formatter.py`
