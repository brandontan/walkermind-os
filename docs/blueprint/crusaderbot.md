# CrusaderBot — Multi-User Auto-Trade Blueprint v3

**Status:** v3.2 LOCKED — CrusaderBot auto-trade pivot target architecture
**Version:** 3.2
**Last Updated:** 2026-05-23 15:30 Asia/Jakarta
**Owner:** Bayue Walker (Mr. Walker)
**Project Path (target):** `projects/polymarket/crusaderbot/`
**Authority:** This blueprint is target architecture intent. Code truth defines current reality. AGENTS.md remains highest authority.

---

## 1. Identity & Vision

### What CrusaderBot is

CrusaderBot is a **multi-user, autonomous trading service for Polymarket**, controlled via Telegram. Users configure strategy preferences, risk profile, and capital allocation. The bot scans markets continuously, executes trades when signals match, manages exits per strategy or user-defined TP/SL, and auto-redeems winning positions. Users never type a buy/sell command — they manage configuration, the bot manages execution.

### What CrusaderBot is NOT

- Not a manual trading interface
- Not a chat-based trade entry tool
- Not a signal-broadcast-only service
- Not an open-public bot at launch (closed beta first)
- Not a non-custodial product at launch (custodial-light, transparent)

### Niche positioning

**UX-niche, hybrid auto-trade.**

- Entry: always automatic (per strategy + risk gate)
- Exit: user-overridable via TP/SL setting; otherwise strategy default; otherwise hold-to-resolve
- Force-close: emergency override available per-position

### Access Tiers

> **Implementation note (v3.2):** The `access_tier` column (Tier 1–4) was dropped in migration 044 (WARP-51). The running system uses `users.role` (RBAC) as the access control mechanism. The tier descriptions below represent functional intent; the code truth is role-based.

| Tier | Name | Role (code truth) | Access | Gate |
|---|---|---|---|---|
| **Tier 1** | Browse | `user` (default) | Read markets, view docs, paper mode (no config) | Auto on /start |
| **Tier 2** | Community allowlisted | `user` + operator flag | Configure strategy + paper trade | Operator adds to allowlist |
| **Tier 3** | Funded beta | `user` + deposit confirmed | Paper auto-trade active, deposit confirmed | Min deposit met |
| **Tier 4** | Live auto-trade | `admin` / explicit approval | Real money execution | All activation guards SET + operator approval |

Access control is enforced via `users.role` at runtime. `access_tier` field does not exist in the schema. Legal/compliance is an **MVP operating guard** (not a build blocker). Controlled community beta gate is sufficient for Phase 1–beta.

### Core principles

1. **Risk-first** — risk gate is hard-wired in code, not configurable bypass
2. **Paper-default** — live mode requires multi-gate activation; default routes to paper
3. **Multi-user isolation** — every action scoped to user/account/wallet, no cross-tenant leak
4. **Custodial transparent** — users deposit USDC to managed wallet pool, sub-account ledger per user, withdraw always available
5. **Audit everything** — append-only audit log, separate DB, every privileged action recorded
6. **Replace, never append (state files)** — repo truth always reflects NOW, not history of changes


---

## 1b. Blueprint vs Code — Deliberate Divergences (v3.2)

The following are confirmed divergences from blueprint intent, validated by WARP•SENTINEL audits. These are **code truth** — the blueprint intent was superseded by implementation decisions.

| Blueprint intent | Code reality | Decision | Reference |
|---|---|---|---|
| `access_tier` column (Tier 1–4) | Dropped; `users.role` RBAC used | Deliberate — simpler, no schema drift | migration 044, WARP-51 |
| `copy_targets` table | `copy_trade_tasks` (canonical execution table) | Deliberate — schema rename for clarity | migration 009+, WARP-57/58/59 |
| Audit log physically-separate DB | Single-DB `audit_log` table (migration 002) | Gap — documented, deferred | SENTINEL audit 2026-05-23 |
| Wallet plane: KMS vault, hot/cold/HD per-user | Custodial-light single pool | Partial — per blueprint phasing; full wallet plane deferred | §7 phasing note |
| `5m/15m` timeframe discriminator on Confluence Scalper | Not implemented (Gamma API does not expose reliable duration field) | Deliberate — UI copy updated, crypto-only eligibility gate retained | WARP-61 post-review |

These divergences are stable. Do not "fix" them without explicit WARP🔹CMD decision.

---
## 2. System Architecture

### High-level flow

```
User (Telegram)
       ↓
Edge Gateway (FastAPI)
       ↓
       ├── Identity Plane (auth, session, user/account/wallet)
       ├── Trading Plane (signal → risk → execution)
       └── Admin/Ops Plane (operator dashboard, kill switch)
       ↓
Strategy Registry (pluggable strategies)
       ↓
Risk Gate (hard-wired, locked constants)
       ↓
Execution Engine (planner, signer, CLOB client)
       ↓
Polymarket CLOB API + Polygon Exchange Contract
       ↓
Wallet Plane (separated for security: vault + signer + hot/cold pool)
       ↓
Persistence (Postgres + Redis + InfluxDB)
       ↓
Observability (logs + metrics + alerts + audit log)
```

### Three-plane separation

| Plane | Responsibility |
|---|---|
| **Identity** | User auth, session management, user/account/wallet ownership, access tier |
| **Trading** | Signal generation, risk gate, execution, position lifecycle, settlement, redeem |
| **Admin/Ops** | Operator dashboard, kill switch, monitoring, manual interventions, audit review |

Privilege escalation requires explicit cross-plane authorization. No silent bypass.

### Wallet plane — separated

The wallet plane is architecturally isolated from trading plane:

- **Wallet vault** — encrypted secrets at rest (KMS-backed if possible)
- **Signing service** — isolated process with separate permissions; signs orders for the pooled hot wallet
- **Hot wallet pool** — operational liquidity for active trading
- **Cold wallet** — long-term storage; manual move to hot when needed
- **On-chain reader** — read-only Polygon access for balance, allowance, deposit detection

If the trading plane is compromised, attacker still must break the wallet plane boundary before any signing occurs.

---

## 3. User Journey

```
STAGE 1 — ONBOARDING (5 min)
  /start
    → Welcome message + features overview
    → [Generate Wallet] | [Import Wallet]
    → If Generate: HD-derive new wallet for user, show address
    → If Import: paste private key OR WalletConnect (Phase 2)
    → Access Tier 1 = Browse-only (read markets, view docs, paper mode)

STAGE 2 — ALLOWLIST (operator gate)
  Operator adds user to community allowlist
    → Access Tier 2 = Community allowlisted (can configure, paper trade)

STAGE 3 — DEPOSIT (1 min)
  Menu: 💰 Wallet → Deposit
    → Show user's HD-derived USDC deposit address (Polygon)
    → QR code + tap-to-copy
    → Min deposit: $50
    → Bot watches chain for incoming USDC
    → On confirmation: auto-credit sub-account ledger, sweep to hot pool
    → Access Tier 3 = Funded beta (can activate auto-trade, paper first)

STAGE 4 — STRATEGY CONFIG (2-5 min)
  Menu: 🤖 Auto-Trade Setup
    → Pick strategy (or combine via Hybrid)
    → Pick risk profile (Conservative / Balanced / Aggressive)
    → Set market filters (categories + blacklist)
    → Set capital allocation (% slider)
    → Trade Setting (TP/SL defaults)

STAGE 5 — ACTIVATION
  Toggle Auto-Trade ON
    → Confirmation dialog: "I understand risk, real money at stake"
    → 2FA via Telegram (one-time setup, persistent thereafter)
    → Access Tier 4 = Live auto-trade enabled (all activation guards SET + operator approval)
    → Bot now scans markets per user's strategy
    → User receives push notifications on trades

STAGE 6 — MONITORING (passive)
  Menu: 📊 Dashboard, 📈 Positions, 📋 Activity, 📅 P&L Calendar
  Per-position controls: 🛑 Force Close button
  Trade Setting: TP/SL adjustable globally
  Emergency: 🚨 Pause / Pause+Close / Lock Account
```

---

## 4. Strategy Engine

### Strategy Registry

Pluggable architecture. Each strategy is a module implementing `BaseStrategy` interface:

```python
class BaseStrategy:
    name: str
    version: str
    risk_profile_compatibility: list[str]  # which user profiles can use this

    async def scan(self, market_filters: MarketFilters, user_context: UserContext) -> list[SignalCandidate]
    async def evaluate_exit(self, position: Position) -> ExitDecision
    def default_tp_sl(self) -> tuple[float, float]
```

### Strategies (launch order)

#### Domain strategies (registered in `domain/strategy/registry.py`)

| # | Strategy | Preset key | Status | Risk profiles | Description |
|---|---|---|---|---|---|
| 1 | **Copy Trade** | `whale_mirror`, `hybrid` | ✅ Built + registered | all | User picks wallets to mirror; bot replicates entries size-scaled to bankroll |
| 2 | **Signal Following** | `signal_sniper`, `hybrid`, `trend_breakout`, `contrarian` | ✅ Built + registered | all | Operator-curated signal feed; bot executes published signals |
| 3 | **Momentum Reversal** | `contrarian` | ✅ Built + registered | balanced, aggressive, custom | Price + volume momentum reversal detection |
| 4 | **Confluence Scalper** | `confluence_scalper` ("Crypto Scalper") | ✅ Built + registered | balanced, aggressive, custom | Multi-signal confluence on crypto markets. **Crypto-only eligibility gate:** BTC/ETH/SOL/XRP/DOGE/BNB/HYPE |

#### Lib strategies (loaded via `lib/strategies/` — `lib_strategy_runner.py`)

| Strategy class | Enabled | Preset mapping | Notes |
|---|---|---|---|
| `TrendBreakoutStrategy` | ✅ | `trend_breakout` | Trend + breakout confirmation |
| `MomentumStrategy` | ✅ | `contrarian` | Momentum signals |
| `ValueInvestorStrategy` | ✅ | `value_hunter`, `full_auto` | EV model — Phase 7+ but class exists |
| `ExpirationTimingStrategy` | ✅ | — | Expiry-based entry timing |
| `PairArbStrategy` | ✅ | — | Pair arbitrage |
| `EnsembleStrategy` | ✅ | — | Multi-strategy ensemble |
| `WhaleTrackingStrategy` | ⏸ Deferred | — | Requires external prob.trade API |
| `sentiment` / `logic_arb` / `market_making` / `weather_arb` | 🔲 | — | Present in lib, not in ENABLED_STRATEGIES |

#### Presets (user-facing, `bot/presets.py`)

| Preset key | Name | Strategy backing | Risk label |
|---|---|---|---|
| `whale_mirror` | 🐋 Whale Mirror | copy_trade | Safe 🟢 |
| `signal_sniper` | 📡 Signal Sniper | signal_following | Safe 🟢 |
| `hybrid` | 🐋📡 Hybrid | copy_trade + signal | Balanced 🟡 |
| `value_hunter` | 🎯 Value Hunter | value (lib) | Advanced 🟡 |
| `confluence_scalper` | 🚀 Crypto Scalper | confluence_scalper | Balanced 🟡 |
| `trend_breakout` | 📈 Trend Breakout | signal_following (lib TrendBreakout) | Balanced 🟡 |
| `contrarian` | 🔄 Contrarian | signal_following (lib Momentum) | Balanced 🟡 |
| `full_auto` | 🚀 Full Auto | copy_trade + signal + value | Aggressive 🔴 |

> **Note:** `confluence_scalper` runs in Full Auto scan with crypto-eligibility gate. `value_hunter` and `full_auto` map to `value` strategy which is Phase 7+ deferred at risk gate level (STRATEGY_AVAILABILITY in constants.py gates execution to `balanced`/`aggressive`/`custom` only).

**Deferred (not built):**
- Arbitrage — Phase 9
- True Hybrid weighted allocator — Phase 8

 Value/momentum model deferred until historical data validates.

---

## 5. Telegram Menu Structure

> **Implementation note (v3.2):** The Telegram UI uses `ReplyKeyboardMarkup` (persistent bottom bar) for primary navigation and `InlineKeyboardMarkup` for contextual actions within screens. The old 10-item tree menu was replaced in WARP-65/66/67/68 with a 5-button state-aware bottom bar.

### Persistent Bottom Bar (ReplyKeyboardMarkup — all screens)

```
[ 📊 Dashboard    ]  [ 💼 Portfolio / 💼 Trades (N) ]
[ 🤖 Setup Auto   ]  [ ⚙️ Settings                  ]  ← label changes by state
[ 🤖 Auto Mode    ]     (if auto_trade_on)
[ ▶️ Resume       ]     (if paused)
[       ❓ Help        ]
```

State-aware labels (`keyboards/__init__.py → main_menu_keyboard()`):
- `auto_label`: `"▶️ Resume"` if paused · `"🤖 Auto Mode"` if active · `"🤖 Setup Auto"` otherwise
- `portfolio_label`: `"💼 Trades (N)"` if open positions > 0 · `"💼 Portfolio"` otherwise

### Screen map

```
📊 Dashboard
  ├── Balance, PnL today, open count, auto status, last scan
  └── [Open Positions →] (inline button)

💼 Portfolio / Trades
  ├── Positions list (paginated 3/page, Prev/Next)
  └── Per-position: entry price, size, unrealized PnL, Force Close

🤖 Auto Trade (Setup Auto / Auto Mode / Resume)
  ├── Screen 03 — Preset Picker (8 presets shown)
  ├── Screen 04 — Preset Confirm
  ├── Screen 04b — Active Preset Status (if already running)
  ├── Risk Profile submenu (Conservative / Balanced / Aggressive / Custom)
  └── Toggle ON/OFF

⚙️ Settings
  ├── Auto-Redeem Mode (Instant / Hourly)
  ├── Notifications
  ├── Risk Profile
  └── Capital / TP / SL overrides

❓ Help
  └── Feature explanations, FAQ, contact
```

**UX principles:**
- Max 2-3 taps to any action
- Emergency pause always reachable via Auto Mode screen toggle
- Persistent keyboard never disappears (is_persistent=True)
- Inline confirmations on irreversible actions (force close, toggle off)

## 6. Risk System

### Hard-wired constants

```python
# domain/risk/constants.py — code-level, NOT YAML, NOT overridable
KELLY_FRACTION = 0.25
MAX_POSITION_PCT = 0.10
MAX_CORRELATED_EXPOSURE = 0.40
MAX_CONCURRENT_TRADES = 5
DAILY_LOSS_HARD_STOP = -2_000.0
MAX_DRAWDOWN_HALT = 0.08
MIN_LIQUIDITY = 10_000.0
MIN_EDGE_BPS = 200
SIGNAL_STALE_SECONDS = 14400       # 4h
DEDUP_WINDOW_SECONDS = 300
MAX_MARKET_IMPACT_PCT = 0.05       # max 5% of visible depth per order
MAX_SLIPPAGE_PCT = 0.03            # live path only
SLIPPAGE_GUARD_PCT = 0.05          # hard pre-submission fence, live path only
```

> **Note:** `MIN_NET_EDGE_VS_COSTS_BPS` is not a separate constant — cost check is gate step 13 (`cost_check`). `SIGNAL_STALE_SECONDS` (4h) replaces blueprint mention of stale signal protection.

These constants are PR-protected. Cannot be overridden by config or runtime flag.

### Risk profile presets

```
PROFILE         | CONSERVATIVE   | BALANCED       | AGGRESSIVE     | CUSTOM
----------------|----------------|----------------|----------------|------------------
Kelly fraction  | 0.10           | 0.20           | 0.25 (cap)     | 0.20 (floor)
Max position %  | 3%             | 6%             | 10%            | 6% (floor)
Max concurrent  | 3              | 5              | 5              | 5
Daily loss stop | -$200          | -$500          | -$1000         | -$500 (floor)
Min edge req    | 4% (400bps)    | 3% (300bps)    | 2% (200bps)    | 3% (floor)
Min liquidity   | $20k           | $15k           | $10k           | $15k (floor)
Max time-to-res | 7 days         | 30 days        | 90 days        | 30 days (floor)
Strategies      | Copy+Signal    | Copy+Signal    | All allowed    | user-configured
```

> **Implementation note:** `custom` profile floor values = `balanced`. User sets `capital_pct`, `tp_pct`, `sl_pct` in `user_settings`. Risk gate falls back to balanced floor until custom values are confirmed. Auto-rebalance timing is not implemented as a separate scheduler — exit watcher runs per scheduler tick.

**Strategy compatibility fix:** All profiles support Copy Trade + Signal Following at launch (Phase 3).
Value/Mispricing and Momentum only unlock at Phase 7+ when the model is validated.
"Conservative / Value only" was a design drift — Value strategy doesn't exist at Phase 3 launch.

**Effective limit rule (precedence):**
```
effective_limit = most_restrictive(
    SYSTEM_HARD_CONSTANT,   # e.g. DAILY_LOSS_HARD_STOP = -$2000
    profile_cap,            # e.g. Conservative = -$200 or -5% of bankroll
    user_lower_override     # user can set lower, never higher than profile
)
```
Example: Conservative profile cap = -$200. System hard cap = -$2000.
Effective = -$200 (most restrictive wins). User cannot override upward past profile.

User profiles can only restrict downward. Hard ceiling = system constants.

### Risk gate flow

```
trade_intent
  ↓
[1]  kill_switch_check        → if active: REJECT_HALT
  ↓
[2]  tenant_scope_check       → user/account/wallet ownership verified
  ↓
[3]  live_mode_check          → if not LIVE: route to paper
  ↓
[4]  capital_mode_check       → CAPITAL_MODE_CONFIRMED set + receipt valid
  ↓
[5]  daily_loss_check         → daily PnL > -$2k → REJECT_HALT
  ↓
[6]  drawdown_check           → MDD > 8% → REJECT_HALT
  ↓
[7]  exposure_check           → user exposure ≤ 10%, correlated ≤ 40%
  ↓
[8]  liquidity_check          → orderbook depth ≥ $10k at intended size
  ↓
[9]  signal_validity_check    → EV > 0, edge > threshold, signal not stale
  ↓
[10] sizing_check             → fractional Kelly α=0.25, max position 10%
  ↓
[11] dedup_check              → idempotency key not seen in 5min window
  ↓
[12] concurrent_trade_check   → user has < 5 open
  ↓
[13] cost_check               → fees + slippage est ≤ expected_edge
  ↓
APPROVED → execution
```

Every step returns `(approved: bool, reason: str)`. Every rejection logged to audit. No silent throws.

### TP/SL evaluation (per-position)

After entry, position carries snapshot values:

```
position.applied_tp_pct       # snapshot at entry
position.applied_sl_pct       # snapshot at entry
position.exit_reason          # enum: manual, tp_hit, sl_hit, strategy_exit, resolution
```

Exit watcher worker evaluates priority order each tick:

```
1. position.user_force_close_intent → execute close immediately
2. position.applied_tp_pct hit       → close at TP
3. position.applied_sl_pct hit       → close at SL
4. strategy.evaluate_exit(position)  → if exit signal, close
5. otherwise → hold (until resolution)
```

User can update TP/SL in `Trade Setting` for **future entries** — does not affect open positions.

---

## 7. Wallet Plane

### Custodial-transparent model

Users deposit USDC to a **pooled hot wallet** managed by CrusaderBot. Each user has a virtual sub-account in DB with their own balance, P&L, position registry. Withdrawals always available (subject to security checks).

**Trade-off acknowledged:**
- ✅ Same risk profile as "delegated signer non-custodial"
- ✅ Cleaner compliance (clearly labeled custodial)
- ✅ Better UX (instant trade, instant deposit/withdraw)
- ✅ Faster to launch
- ⚠️ Operator carries on-chain custody risk → need proper hot/cold split, ToS, insurance posture

### Wallet model — MVP (Phase 1–beta: custodial-light only)

**Single model for MVP. No mixing.**

- **HD-derived deposit address per user** — 1 master seed (cold-stored) → deterministic per-user deposit address via HD derivation path
- User sends USDC to their unique address → bot detects transfer on-chain → sweeps to pooled hot wallet → credits user's internal sub-account ledger
- All trading executed from pooled hot wallet on user's behalf
- User never touches private keys

**Deferred to later phase (explicitly NOT MVP):**
- Wallet import (paste private key) → Phase later
- WalletConnect / non-custodial signing → Phase later

Rationale: Mixing three wallet models in MVP creates security surface complexity and UX confusion. Start with one clean model, validate, then expand.

### Hot/cold split

| Wallet | Purpose | Capital % |
|---|---|---|
| **Hot pool** | Operational trading | 20-40% of total custody |
| **Warm reserve** | Buffer for redeems, withdraws | 30-40% |
| **Cold storage** | Long-term safe keep | 30-50% |

Auto-rebalance triggered when hot pool drops below threshold.

### On-chain reader

Read-only Polygon access for:
- Deposit detection (watch USDC transfers to user addresses)
- Balance verification (cross-check internal ledger vs on-chain)
- Allowance tracking (user's CLOB allowance status)

---

## 8. Auto-Trade Engine

### Scheduler architecture

```
┌─────────────────────────────────────────────────────┐
│  AUTO-TRADE SCHEDULER (per-user execution loop)     │
│                                                     │
│  For each user with auto_trade_enabled = true:      │
│    1. Load user config (strategies, risk, filters) │
│    2. Get markets matching filters                  │
│    3. For each matching market:                     │
│       a. Run user's active strategies               │
│       b. Aggregate signal candidates                │
│       c. For each candidate:                        │
│          - Risk gate check                          │
│          - If approved → queue execution            │
│    4. Process exit watcher for open positions       │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  EXECUTION QUEUE (per-user, FIFO)                   │
│                                                     │
│  - Plans order → signs → submits to Polymarket CLOB │
│  - Watches fills → updates position registry        │
│  - Notifies user via Telegram                       │
│  - Records audit log                                │
└─────────────────────────────────────────────────────┘
```

### Signal scan frequency

| Activity | Frequency | Mechanism |
|---|---|---|
| Market metadata refresh | 5 min | Polling Polymarket API |
| Signal generation per user | 1-5 min | Polling (per user's strategy cadence) |
| Open position tracking | Real-time | WebSocket subscription per market |
| Resolution monitoring | 1 min | Polling Polymarket API |

### Concurrent execution safeguards

When multiple users trigger same signal on same market:

- **Per-user execution lock** (no double-execute for same user)
- **Per-market size aggregation** (track total bot exposure to a market)
- **Stagger execution** to reduce orderbook impact (jitter 0-3s)
- **Stale signal protection** — re-validate edge before execution; if edge gone, skip
- **Backpressure** — if API rate-limited, drop oldest stale signals first

### Execution pipeline

```
Signal generated
  ↓
Per-user filter (does user's strategy match this signal?)
  ↓
Per-user risk gate (13-step gate from §6)
  ↓
Sizing calculation (per user's bankroll + risk profile)
  ↓
Execution queue (per user, FIFO)
  ↓
Stale signal re-validation (edge still present?)
  ↓
Order place → Polymarket CLOB
  ↓
Fill watch → position registry update
  ↓
User push notification (Telegram)
  ↓
Audit log entry
```

---

## 9. Auto-Redeem System

### User-configurable mode

Settings menu:
```
⚙️ Settings → Auto-Redeem Mode
├── Mode: [Instant] [Hourly]   ← default Hourly
└── Info: "Instant uses more gas. Hourly batches redeems for lower cost."
```

### Behavior

| Mode | Trigger | Gas profile |
|---|---|---|
| **Instant** | Resolution detected → immediate redeem | Higher cost (1 tx per redeem) |
| **Hourly** | Resolution → queue → batch every hour | Lower cost (sequential or batched if contract supports) |

### Implementation

```
auto_redeem_instant_worker
  - Subscribes to Polymarket resolution events
  - For users with mode=Instant: immediate redeem
  - Gas cap protection: if gas > 100 gwei, queue to next hourly batch

auto_redeem_hourly_worker
  - Cron every hour
  - Aggregates pending redeems for users with mode=Hourly
  - Submits batched redeems (or sequential within hour)
  - Updates internal ledger on confirmation
  - Notifies users via Telegram
```

### Loser positions

Markets resolve with user position on losing side: no redeem needed (token worthless). Bot marks position closed in internal ledger, records final P&L, notifies user.

---

## 10. Fee & Referral System

### Fee model (build now, activate later)

**Activation guard:** `FEE_COLLECTION_ENABLED = false` at launch. All accounting paths execute, but fee amount = $0. Owner flips guard when ready.

### Trading fee structure

```
User entry $100
  ↓
Bot calculates fee: $100 × 0.01 = $1.00
  ↓
If FEE_COLLECTION_ENABLED:
  - Bot places order $99.00 (effective entry)
  - $1.00 deducted from user sub-account
  - Of that $1.00:
    - $0.80 → admin fee wallet
    - $0.20 → referrer wallet (if user was referred)
  - If no referrer: $1.00 → admin fee wallet
If NOT FEE_COLLECTION_ENABLED:
  - Bot places full $100 entry
  - $0 deducted, $0 distributed
  - All accounting still logged for audit
```

**No exit fee.** User-friendly, no double-charge.

### Referral system (Phase 1 build)

```
Each user gets unique referral code/link
Referred user trade → 20% of fees forever (or capped period)

Referral attribution:
- Stored at user creation: user.referrer_user_id
- Attribution applies to ALL future trades from referred user
- Settled to referrer wallet monthly (or on-demand)
- Tracked per-trade in audit log
```

### Fee transparency

- **Pre-trade preview:** "Entry $100 (incl. $1 fee). Net entry $99."
- **Per-trade record** in Activity history
- **Daily/weekly summary** in Dashboard
- **Referral earnings** visible in Referrals menu

---

## 11. Database Schema

### Identity & access (5 tables)
```
users (id, telegram_user_id, status, access_tier, referrer_user_id, created_at, ...)
sub_accounts (id, user_id, custodial_balance_usdc, ...)
sessions (id, user_id, expires_at, revoked_at, ...)
```

### Audit log — physical separation (security boundary)

Audit log is NOT a table in the main app DB. It is a **physically separate DB / schema** with strict access controls:

```
audit_db (separate Postgres instance or schema):
  audit_log (id, ts, user_id, actor_role, action, payload, ...)

Access rules:
  - App service account: INSERT only — no UPDATE, no DELETE
  - Admin read account: SELECT only — separate credentials
  - No ORM model with update/delete methods
  - Retention policy: minimum 2 years, immutable
  - Backup: separate backup job, separate destination

audit_log schema:
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid()
  ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
  user_id     UUID        (nullable — system actions have no user)
  actor_role  VARCHAR(20) NOT NULL   -- user/system/operator/admin
  action      VARCHAR(100) NOT NULL
  payload     JSONB       DEFAULT '{}'
  ip_hash     VARCHAR(64)            -- hashed IP for forensics
  session_id  UUID                   -- which session triggered this
```

Rationale: If audit log is in same DB with same service account, a compromised app can delete its own trail. Physical separation + write-only service account enforces append-only guarantee.

### Main app tables — Identity & access

### Wallet & money (4 tables)
```
deposits (id, user_id, tx_hash, amount, confirmed_at, ...)
withdrawals (id, user_id, tx_hash, amount, status, ...)
ledger_entries (id, sub_account_id, type, amount, ref_id, ts, ...)
proxy_wallet_pool (id, label, address, hot_or_cold, ...)
```

### Trading (6 tables)
```
markets (id, condition_id, slug, status, resolution_at, ...)
orders (id, sub_account_id, market_id, side, size, price, status, idempotency_key, ...)
fills (id, order_id, fill_price, fill_size, fee, ts, ...)
positions (id, sub_account_id, market_id, side, size, avg_entry, applied_tp_pct, applied_sl_pct, exit_reason, ...)
risk_decisions (id, intent_id, decision, reason, payload, ts, ...)
idempotency_keys (key, user_id, action, created_at, expires_at, ...)
```

### Strategy & config (5 tables)
```
user_strategies (id, user_id, strategy_type, weight, enabled, params_json, ...)
user_risk_profile (user_id, profile_name, custom_overrides, updated_at, ...)
user_market_filters (id, user_id, filter_type, filter_value, ...)
user_trade_settings (user_id, default_tp_pct, default_sl_pct, use_strategy_default, per_strategy_overrides, ...)
auto_trade_state (user_id, enabled, paused_at, paused_reason, started_at, ...)
strategy_definitions (id, name, version, params_schema, status, ...)
```

### Copy-trade (3 tables)
```
copy_targets (id, user_id, target_wallet_address, scale_factor, status, ...)
copy_trade_events (id, copy_target_id, source_tx_hash, mirrored_order_id, ...)
wallet_leaderboard (address, win_rate, total_volume, pnl_30d, ...)
```

### Signal feeds (3 tables)
```
signal_feeds (id, name, operator_id, status, subscriber_count, ...)
signal_publications (id, feed_id, market_id, signal_type, payload, published_at, ...)
user_signal_subscriptions (id, user_id, feed_id, subscribed_at, ...)
```

### Portfolio (2 tables)
```
portfolio_snapshots (id, sub_account_id, total_value, exposure, mdd, ts, ...)
pnl_daily (id, sub_account_id, date, realized, unrealized, fees, ...)
```

### Fee & referrals (3 tables)
```
fee_records (id, trade_id, user_id, fee_amount, admin_share, referrer_share, referrer_user_id, ts, ...)
referral_links (id, user_id, code, created_at, ...)
referral_earnings (id, referrer_user_id, referred_user_id, amount, source_trade_id, settled_at, ...)
```

### Ops (3 tables)
```
system_alerts (id, severity, type, message, resolved_at, ...)
job_runs (id, job_name, status, started_at, finished_at, error, ...)
kill_switch_history (id, action, actor_id, reason, ts, ...)
```

**Total: ~34 tables.** Scope-bound, ownership-isolated, audit-trailed.

---

## 12. Activation Guards

System has multiple guards that must be set before live operations:

| Guard | Owner | Purpose |
|---|---|---|
| `EXECUTION_PATH_VALIDATED` | Engineering | Real CLOB end-to-end runtime validated |
| `CAPITAL_MODE_CONFIRMED` | Operator | Operator receipt flow active |
| `ENABLE_LIVE_TRADING` | Owner | Final guard — live trades enabled |
| `RISK_CONTROLS_VALIDATED` | SENTINEL | Risk gate hardening passed |
| `SECURITY_HARDENING_VALIDATED` | SENTINEL | Security hardening passed |
| `FEE_COLLECTION_ENABLED` | Owner | Fee charging active |
| `REFERRAL_PAYOUT_ENABLED` | Owner | Referral settlement active |
| `AUTO_REDEEM_ENABLED` | Engineering | Auto-redeem worker active |

Guards are **default OFF**. Each requires explicit enable + audit trail. No guard can be set without owner+commander acknowledgment.

---

## 13. Roadmap

### Phase numbering — migration note

This blueprint uses fresh phase numbering (Phase 0–11) for the CrusaderBot v3 auto-trade pivot. This is a **new product roadmap**, distinct from the legacy numbering in repo state files (which used Phase 1–10 / Priority 1–9 for the paper-beta build path completed in PR #840).

Repo-truth alignment:
- Legacy `ROADMAP.md` phases (1–10) + Priority 9 (9.1, 9.2, 9.3) = COMPLETE per merged state
- This blueprint's Phase 0–11 = NEW build roadmap for auto-trade CrusaderBot
- When this blueprint is committed as `docs/blueprint/crusaderbot.md`, ROADMAP.md must be updated to reflect the new phase structure
- AGENTS.md phase numbering normalization rule (max `.9` sub-phase) applies to new phases
- No new work should reference old Priority 9.x numbering — those are historical completion markers only

### **Phase 0 — Owner gates** (1 week)
Pre-build decisions required:

**Hard gates (must decide before Phase 1 build starts):**
- Polymarket ToS review — multi-tenant operator allowed?
- Community beta access gate — who gets Tier 2 allowlist? how invited?
- Capital ceiling for beta — per-user cap + total cap
- Operator liability posture (ToS language, loss policy, disclaimer)

**MVP operating guards (decide before beta launch, not before build):**
- Jurisdiction operating posture — which users you actively market to (not a build blocker, an ops decision)
- Tax reporting intent — will you provide trade summaries? (implement if needed, not a prerequisite)
- Insurance approach — self-insured or on-chain coverage? (risk management decision, not a build gate)

Note: Legal/compliance is downgraded from hard build blocker to MVP operating guard. Controlled community beta with explicit ToS and small capital ceiling is a reasonable operating posture for Phase 1–beta. Full compliance review is recommended before open beta (Phase 11).

### **Phase 1 — Project restructure** (1 week, MINOR)
- `git mv` `polyquantbot/` → `crusaderbot/`
- Update PROJECT_REGISTRY.md
- Update PROJECT_ROOT in all configs
- Restructure to v3 layout
- Verify tests + imports
- SENTINEL: spot-check, no live impact

### **Phase 2 — Wallet & deposit foundation** (2 weeks, MAJOR)
- HD wallet derivation per user
- Wallet vault (KMS-backed encryption)
- Deposit detection (Polygon chain watcher)
- Internal ledger system
- Sub-account model
- Withdraw flow (manual approval gate initially)

### **Phase 3 — Strategy registry + 2 strategies** (3 weeks, MAJOR)
- BaseStrategy interface
- StrategyRegistry boundary
- Implement Copy-Trade strategy
- Implement Signal Following strategy
- Per-user signal scan loop
- Per-user execution queue

### **Phase 4 — Real CLOB execution** (2 weeks, MAJOR)
- Replace MockClobClient in production path
- Real signer service (isolated process)
- Order place/fill/cancel/settle flow
- E2E live test (1 wallet, $100 cap)
- SENTINEL APPROVED required

### **Phase 5 — Telegram auto-trade UX** (2 weeks, MAJOR)
- Onboarding flow (wallet generate/import)
- Strategy setup menus
- Risk profile presets
- Trade Setting (TP/SL)
- Auto-trade toggle with 2FA
- Position monitor + alerts
- Force-close per-position
- Emergency menu

### **Phase 6 — Fee & referral system** (1 week, STANDARD)
- Fee accounting tables + logic
- Referral tracking + attribution
- FEE_COLLECTION_ENABLED guard (default OFF)
- REFERRAL_PAYOUT_ENABLED guard (default OFF)
- Pre-trade fee preview UI
- Referral menu UI

### **Phase 7 — Auto-redeem system** (1 week, STANDARD)
- Resolution event detection
- Instant redeem worker
- Hourly batch redeem worker
- User mode setting (Instant/Hourly)
- Gas cap protection
- Audit log integration

### **Phase 8 — Multi-user isolation live audit** (1 week, MAJOR)
- 2-3 sub-accounts live test, $100 each
- Concurrent execution stress test
- Cross-user leak audit
- SENTINEL APPROVED required

### **Phase 9 — Operations & monitoring** (1 week, STANDARD)
- Operator dashboard
- Prometheus + Grafana
- Audit log review tools
- Incident runbook
- Kill switch drill

### **Phase 10 — Closed beta** (3 weeks, controlled)
- Whitelist 5-10 users
- Each capped at $200-500
- Daily monitoring
- Iterate UX based on feedback
- Validate strategy performance

### **Phase 11 — Open beta + scale** (owner gate)
- Activate fee collection
- Activate referral payouts
- Marketing push
- Add Value/Mispricing strategy (Phase 7+ work)
- Add Momentum strategy
- Web dashboard

**Total realistic timeline: 13-15 weeks Phase 1 → Phase 10**, faster if Phase 0 cleared promptly.

---

## 14. Owner-Level Decisions Outstanding

These are not engineering decisions. They block Phase 0 closure:

**Hard gates (before Phase 1):**
1. **Polymarket ToS posture** — multi-tenant operator allowed under their terms?
2. **Community beta cohort sizing** — how many users in Tier 2 allowlist?
3. **Capital ceiling per user (beta)** — $100 / $500 / $1000?
4. **Total beta capital ceiling** — $1k / $5k / $10k?
5. **Operator liability ToS** — what does the disclaimer say? what's the loss policy?

**MVP operating guards (before beta launch):**
6. **Jurisdiction operating posture** — passive (accept whoever finds it) or active whitelist?
7. **Insurance approach** — self-insured or on-chain coverage?
8. **Tax reporting intent** — will you provide trade summaries to users?
9. **Referral economics activation timing** — at beta start or at open beta?

**Access tier management:**
10. **Allowlist mechanism** — operator adds Tier 2 users manually via admin command, or invite-link based?

---

## 15. Out of Scope (v3)

Explicitly excluded from this blueprint:

- Open public launch from day one (closed beta first)
- Manual buy/sell command interface
- Web frontend at launch (later phase)
- Non-custodial signing for retail users (custodial-light first)
- Multi-exchange support (Polymarket only)
- Live trading without all activation guards SET
- Strategy that bypasses risk gate
- Per-user custom strategies (DSL or scripting) — beyond template parameters

---

## 16. Reference

- **AGENTS.md** — master rules, single source of truth
- **PROJECT_REGISTRY.md** — active project list
- **{PROJECT_ROOT}/state/PROJECT_STATE.md** — operational truth
- **{PROJECT_ROOT}/state/ROADMAP.md** — milestone truth
- **docs/crusader_multi_user_architecture_blueprint.md** — original blueprint v1 (superseded by this document)
- **docs/blueprint/crusaderbot.md** — this blueprint v3 (target architecture)

---

**End of Blueprint v3.**

---

## Version History

| Version | Date | Changes |
|---|---|---|
| v3.0 | 2026-05-01 | Initial multi-user auto-trade blueprint |
| v3.1 | 2026-05-03 | LOCKED — CrusaderBot pivot target; risk constants, activation guards, fee/referral model |
| v3.2 | 2026-05-23 | Full code sync: tier section (RBAC), strategy table rebuilt (domain + lib + presets), main menu updated to ReplyKeyboard bottom bar, risk constants synced to code, custom profile added, deliberate divergences documented |
