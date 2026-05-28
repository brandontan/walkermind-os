# WARP•R00T FORGE REPORT — settings-email-linked-state

Branch: `WARP/ROOT/settings-email-linked-state`
Role: WARP•R00T (self-validated)
Validation Tier: **STANDARD** (user-facing WebTrader behavior, no trading-safety surface)
Claim Level: NARROW INTEGRATION
Validation Target: WebTrader Settings shows persistent email-link state instead of re-showing the link form after refresh.
Not in Scope: changing the link/auth flow itself; Telegram-link block (already persisted via getLinkTelegramStatus).
Suggested Next Step: WARP🔹CMD review + merge.

---

## 1. What was built

Bug (owner-reported, screenshots): after linking an email in WebTrader Settings,
a refresh **re-showed the "Link Email" form** instead of showing the linked
email. Root cause: the linked state was only transient React state
(`linkSuccess`), reset to `false` on reload — the page never read whether the
account already had an email persisted.

Fix:
- `GET /api/web/me` now returns persisted identity: `email`, `username`,
  `telegram_linked`. Synthetic tombstone emails (`merged-*@telegram.local`,
  from the reverse-link merge) are excluded → surfaced as `email=null`.
- WebTrader Settings fetches `/me` in its load(), renders a persistent
  **"Email — connected: <email>"** row, and shows the link form **only when no
  real email is linked**. After a successful link it refreshes identity so the
  connected row shows and the form stays hidden across refreshes. Username row
  now prefers the real `username`.

## 2. Current system architecture

Settings identity now mirrors the same persisted-state pattern already used for
the Telegram-link block (`getLinkTelegramStatus`): email-linked state comes from
the DB via `/me`, not from ephemeral client state.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` (get_me returns email/username/telegram_linked; tombstone exclusion)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` (getMe + MeResponse)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/SettingsPage.tsx` (persistent Email row; link form gated on no-email; refresh after link)
- `projects/polymarket/crusaderbot/tests/test_account_link.py` (+2 get_me pins)

Created:
- `projects/polymarket/crusaderbot/reports/forge/settings-email-linked-state.md`

## 4. What is working

- After linking, refresh keeps the "Email — connected" row; the link form does not reappear.
- Tombstoned merge accounts never show a fake `@telegram.local` email.
- 17 account/identity tests pass; full suite green; ruff + py_compile + tsc + vite build clean.

## 5. Known issues

- "Email — connected" row reflects link state on the 30s Settings poll / next load (no users-table SSE trigger) — instant after the user's own link action via the post-link refresh.

## 6. What is next

WARP🔹CMD review + merge → Fly auto-deploy.
