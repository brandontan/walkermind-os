# WARP•FORGE Report — webtrader-wallet-withdraw

Branch: WARP/R00T-webtrader-wallet
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: WebTrader wallet withdraw UI + POST /wallet/withdraw API endpoint
Not in Scope: on-chain signing, admin UI, real USDC transfer, paper→live activation

---

## 1. What was built

Full paper-mode withdrawal flow for WebTrader (browser client):

- `POST /wallet/withdraw` FastAPI endpoint with amount + EVM address validation
- `requestWithdrawal()` method wired into the `makeApi()` factory
- `WithdrawModal` replaced from a non-functional stub to a full 3-step modal:
  - Step 1: Amount input with 25%/50%/100%/Max quick-fill buttons, min $5 guard
  - Step 2: Destination EVM address input with `0x[0-9a-fA-F]{40}` client validation
  - Step 3: Confirm summary (amount, short address, approval note)
  - Submitting / Success / Error terminal states
  - Paper mode warning banner shown throughout (non-blocking — queues for admin same as Telegram)
- `WalletPage.tsx` wired: `onWithdraw={api.requestWithdrawal}`, `onSuccess` auto-closes modal and reloads wallet balance

---

## 2. Current system architecture

```
WalletPage.tsx
  └─ WithdrawModal (amount → address → confirm → submit → success/error)
       └─ api.requestWithdrawal(amount, address)
            └─ POST /api/web/wallet/withdraw
                 └─ wallet/withdrawals.py
                      ├─ create_withdrawal_request() — atomic INSERT + debit_in_conn(T_WITHDRAW)
                      └─ get_approval_mode() — reads system_settings.withdrawal_approval_mode
```

Approval flow is identical to Telegram bot: admin receives Telegram notification, approves/rejects via `/admin withdrawals` panel. Rejection refunds via `credit_in_conn(T_ADJUSTMENT)`.

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — added `POST /wallet/withdraw` endpoint (lines ~1001–1048)
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` — `WithdrawRequest` + `WithdrawResponse` (already in prior session)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` — `requestWithdrawal()` method + `WithdrawRequest`/`WithdrawResponse` TS interfaces
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/WithdrawModal.tsx` — full 3-step replace (was stub)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/WalletPage.tsx` — wired `onWithdraw` + `onSuccess` props

---

## 4. What is working

- Amount validation: min $5 USDC, max = available balance, floatparse safe
- EVM address validation: client-side regex + server-side regex double guard
- API layer: `POST /wallet/withdraw` delegates to existing `wallet/withdrawals.py` functions (already tested in PR #1371)
- Paper mode: shows warning banner but is fully functional — queues withdrawal for admin same as Telegram bot
- Success state: displays truncated withdrawal ID + pending status
- Error state: surfaces server error message + Retry button
- Balance reload: `onSuccess` auto-reloads wallet state so ledger entry + balance debit are visible immediately
- Quick-fill buttons: 25%/50%/100%/Max for amount step

---

## 5. Known issues

- No backend integration tests for the new endpoint (Telegram bot tests cover `create_withdrawal_request` directly; endpoint tested manually)
- Paper mode balance debit shows immediately but on-chain transfer will never fire (correct — paper only, by design)

---

## 6. What is next

- WARP🔹CMD: review + merge WARP/R00T-webtrader-wallet PR
- Migration 057 must be applied to Supabase before deploy (already applied — PR #1371 confirmed this)
- Fly.io redeploy to ship the new endpoint + updated frontend bundle
- Continue Lane 3 (copy-trade scanner F-HIGH-2 follow-up) + Lane 4 (on-chain signing skeleton) per WARP🔹CMD direction

Suggested Next Step: WARP🔹CMD review + merge + fly deploy WARP/R00T-webtrader-wallet.
