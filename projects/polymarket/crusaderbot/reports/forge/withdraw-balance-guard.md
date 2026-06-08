# WARP-96 — Multi-User Wallet System Verification + Withdrawal Overdraft Fix

Role: WARP•R00T
Branch: WARP/withdraw-balance-guard
Validation Tier: MAJOR (financial — capital-exit path, multi-user fund isolation)
Claim Level: NARROW INTEGRATION (one CRITICAL fix + full-path audit; paper-verified, live path unchanged)
Validation Target: deposit → withdrawal → live-trade across backend + both frontends (WebTrader + Telegram)
Not in Scope: changing trading execution logic, ENABLE_LIVE_TRADING / SCORER_ACTIVE / ORCHESTRATOR_ACTIVE, kill_switch, Kelly/risk constants, encrypted_key handling
Suggested Next Step: WARP🔹CMD merge decision (MAJOR financial), then the prioritized hardening backlog in §6

---

## 1. What was built

A full verification pass of the multi-user wallet system (deposit, withdrawal,
live trade — backend + WebTrader + Telegram), validated against Polymarket's
actual requirements via the `web3-polymarket` skill. It surfaced **one CRITICAL
bug, now fixed**, plus a prioritized backlog of lower-severity findings.

**CRITICAL — withdrawal overdraft (FIXED):** the WebTrader API endpoint
`POST /wallet/withdraw` (`webtrader/backend/router.py:1665`) validated only the
minimum amount and address format — it never checked `balance_usdc >= amount`.
The shared chokepoint `create_withdrawal_request` debited unconditionally, the
ledger `_post_in_conn` has no non-negative guard, and there is no DB CHECK
constraint. A user could request more than they hold → balance goes negative →
settlement sends from the **pooled master wallet** that holds *every* user's
custody funds (i.e. one user could drain others). The Telegram flow had a
client-snapshot check; the WebTrader frontend had a bypassable client-side
check; neither was enforced server-side at the data layer.

Fix: an **atomic, row-locked** balance guard inside `create_withdrawal_request`
— the single chokepoint both surfaces call — so no caller (present or future)
can overdraft.

## 2. Current system architecture (verified)

```
DEPOSIT   user → per-user EOA deposit_address → watch_deposits (120s, conf-depth 32,
          idempotent) → ledger T_DEPOSIT credit → wallets.balance_usdc       [VERIFIED OK]

WITHDRAW  WebTrader API / Telegram → create_withdrawal_request
          → [NEW] FOR UPDATE balance guard: refuse if balance < amount
          → INSERT withdrawals + atomic ledger debit
          → approve → _settle_withdrawal → custody.transfer_usdc (EOA/Safe)   [FIXED]

LIVE      get_clob_client() (integrations/clob/, pysdk) signs with
TRADE     signature_type=2 GNOSIS_SAFE + funder; USDC.e (0x2791Bca…) collateral;
          gate Cap-0 balance>0 + Cap-1 position≤%balance + step-8 deploy cap    [VERIFIED OK]
```

Per-user fund isolation rests on the ledger `balance_usdc` + the gate's balance
caps on entry and (now) the overdraft guard on exit.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/wallet/withdrawals.py` — atomic `FOR UPDATE` overdraft guard in `create_withdrawal_request`
- `projects/polymarket/crusaderbot/tests/test_wallet_withdraw_flow.py` — SQL-aware balance mock + 2 overdraft tests
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `state/CHANGELOG.md` — state sync

## 4. What is working (verified this pass)

- Backend wallet/trade suite: **830 passed, 12 skipped** (the 4 `clob_pysdk` fails = optional `polymarket-client` module absent in sandbox; 10 collection errors = missing optional deps — all pre-existing, CI has the full stack).
- Live-order path correctly wires `signature_type=2` (GNOSIS_SAFE) + `funder` (`integrations/clob/__init__.py:188`, `adapter.py:473`) — matches Polymarket's Safe-proxy requirement; USDC.e collateral matches the skill.
- Deposit watcher: idempotent, reorg-safe, confirmation-depth crediting (WARP-94, just shipped).
- Trade entry: balance-gated (gate Cap 0/1 + step-8 deployment cap) — multi-user isolation holds.
- Withdrawal overdraft: now refused atomically — 28 withdraw tests pass (incl. 2 new), ruff clean.

## 5. Known issues (backlog — see §6 for priority)

- **MEDIUM (dead code / landmine):** `integrations/polymarket.py` still carries the legacy v1 live-order path (`_build_clob_client`/`prepare_live_order`/`submit_live_order`) built with **no `signature_type`/`funder`** (would sign as EOA — wrong maker for a Safe-funded account). No active caller (the live path uses `get_clob_client`), but `domain/execution/order.py`'s docstring still references it (stale). Recommend deletion + docstring fix.
- **LOW:** WebTrader live-activation has no confirmation timeout (Telegram enforces 10s); approval-mode (auto/manual) not surfaced in the WebTrader withdraw UI; several frontend `.catch()` blocks swallow errors silently (no retry/empty states); no incoming-deposit polling (manual refresh only).
- **LOW (defense-in-depth):** no DB CHECK `balance_usdc >= 0`; the new app-level guard covers the withdrawal path, but a DB constraint would harden every debit path.

## 6. What is next (prioritized recommendations)

1. **(this PR)** Ship the withdrawal overdraft fix — MAJOR, financial.
2. **MEDIUM:** delete the orphaned legacy CLOB live-order path in `integrations/polymarket.py` + fix the stale `order.py` docstring (removes a wrong-maker landmine).
3. **LOW-MED:** add DB CHECK `balance_usdc >= 0` (migration) as defense-in-depth across all debit paths.
4. **LOW:** WebTrader UX parity — surface approval-mode, add an activation timeout, replace silent `.catch()` swallows with retry/empty states, add lightweight deposit-detection polling/SSE.
5. **Operator/live:** before any live cutover, confirm `POLYMARKET_FUNDER_ADDRESS` = the master Safe proxy and that the Safe is approved to the CTF Exchange (Polymarket sets this at proxy creation); WARP-74 already proved build+sign+POST+accept on the real broker (allow_fills=false).

Validation Handoff (NEXT PRIORITY):
```
WARP🔹CMD merge decision required (MAJOR, financial — capital-exit path).
Source: projects/polymarket/crusaderbot/reports/forge/withdraw-balance-guard.md
Tier: MAJOR
```
