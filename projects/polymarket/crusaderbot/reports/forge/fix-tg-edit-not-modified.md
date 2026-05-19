# WARP•FORGE REPORT — fix-tg-edit-not-modified

**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Telegram inline-edit handlers in bot/handlers/setup.py and bot/handlers/settings.py
**Not in Scope:** Other bot handlers, webtrader, scheduler, DB layer
**Suggested Next Step:** WARP🔹CMD review → merge

---

## 1. What was built

Added targeted `BadRequest` "not modified" guard to all `edit_reply_markup` call sites in `bot/handlers/setup.py` and one in `bot/handlers/settings.py`.

Previously: `set_risk` used a bare `except BadRequest: pass` that swallowed ALL BadRequest errors. Four other `edit_reply_markup` calls had no guard at all and would surface uncaught tracebacks on double-tap.

Fix applied: every `edit_reply_markup` call is now wrapped in:
```python
try:
    await q.message.edit_reply_markup(...)
except BadRequest as e:
    if "not modified" not in str(e).lower():
        raise
```

This suppresses the benign no-op case and re-raises genuine errors (e.g. message deleted, bot kicked).

---

## 2. Current system architecture

Unchanged. Handler layer only — no DB, no scheduler, no core pipeline touched.

---

## 3. Files created / modified

- `projects/polymarket/crusaderbot/bot/handlers/setup.py` — added not-modified guard to: `setup_callback` (menu sub), `set_strategy`, `set_risk`, `set_category`, `set_mode`
- `projects/polymarket/crusaderbot/bot/handlers/settings.py` — added not-modified guard to `autoredeem` redeem_set block

---

## 4. What is working

- `set_risk`: double-tap no longer logs BadRequest; genuine errors still surface
- `set_strategy`, `set_category`, `set_mode`, `setup_callback:menu`: same guard applied
- `settings.py:autoredeem`: same guard applied
- `settings.py:_render_hub` (line 128): already had "Message is not modified" check — no change needed
- compileall: clean

---

## 5. Known issues

None.

---

## 6. What is next

WARP🔹CMD review required. Tier: MINOR.
