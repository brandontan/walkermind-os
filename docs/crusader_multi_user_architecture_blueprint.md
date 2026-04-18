# Crusader — Multi-User Architecture Blueprint v1

## 1. Tujuan Sistem

Crusader adalah bot trading prediction market **multi-user** yang dirancang untuk berjalan dengan arsitektur berikut:

    User (Telegram/Web)
           ↓
    Crusader Bot (Telegram)
           ↓
    Crusader Backend (FastAPI)
           ↓
    Polymarket CLOB API
           ↓
    Polymarket Exchange Contract (On-Chain Settlement)
           ↓
    User Proxy Wallet (Polygon)

Crusader bukan sekadar bot Telegram. Ini adalah **trading system** yang memiliki:

- interface layer untuk user
- backend control plane untuk orchestration
- signal/risk/execution core
- Polymarket integration layer
- settlement awareness
- wallet ownership mapping per user

### Fungsi utama

- menerima interaksi user dari Telegram dan Web
- menampilkan market, signal, posisi, PnL, dan status risiko
- membangun signal trading dari model-vs-market edge
- menerapkan risk engine sebelum order boleh lewat
- mengelola order lifecycle sampai fill, settlement, dan resolve
- menjaga isolasi data, wallet, order, dan notifikasi **per user**

### Prinsip desain

1. **Risk-first** — trade bagus tetap ditolak bila risk limit breach
2. **Modular** — interface, backend, signal, risk, execution, wallet dipisah
3. **Model-vs-market** — entry berasal dari gap antara keyakinan model dan harga market
4. **Auditability** — semua keputusan penting harus bisa ditelusuri
5. **Extensible** — mudah ditambah strategy baru, source baru, dan exchange baru
6. **Multi-user isolation** — semua resource user harus terisolasi dengan aman

---

## 2. Core Logic

### 2.1 Decision Core

Bot bekerja berdasarkan rantai keputusan berikut:

1. ambil market + harga + candles + trade flow + optional narrative signal
2. bangun feature set
3. estimasi `p_model`
4. hitung:
   - `edge = p_model - p_market`
   - `EV = p·b - (1-p)`
   - `z-score` mispricing
   - confidence / bias-adjusted probability
5. cek semua hard risk rule
6. tentukan sizing dengan fractional Kelly
7. submit order atau paper trade
8. monitor posisi sampai exit / resolve

### 2.2 Hard Rules

- hanya entry bila **EV > 0**
- hanya entry bila **edge > minimum threshold**
- sizing pakai **fractional Kelly**, bukan full Kelly
- stop new trades bila **MDD > 8%**
- total correlated exposure **< 40% bankroll**
- size di-scale dengan volatility regime
- semua aktivitas trading harus di-scope ke **user/account/wallet**

---

## 3. High-Level System Architecture

Arsitektur resmi Crusader:

    User (Telegram/Web)
           ↓
    Crusader Bot (Telegram)
           ↓
    Crusader Backend (FastAPI)
           ↓
    Polymarket CLOB API
           ↓
    Polymarket Exchange Contract (On-Chain Settlement)
           ↓
    User Proxy Wallet (Polygon)

### 3.1 User Layer

Entry point user berasal dari:

- Telegram
- Web interface

User melakukan:

- connect account
- lihat market
- lihat signal / rekomendasi
- submit command
- monitor posisi dan PnL
- trigger action manual bila dibutuhkan

### 3.2 Crusader Bot (Telegram)

Lapisan conversational interface.

Tugas:

- menerima command user
- menampilkan market/signal/portfolio/risk state
- mengirim alert, fill update, resolve update
- menjadi gateway UX utama untuk Telegram

Contoh command:

- `/start`
- `/markets`
- `/signal`
- `/positions`
- `/risk`
- `/buy`
- `/sell`
- `/close`
- `/status`

### 3.3 Crusader Backend (FastAPI)

Ini adalah core application layer.

Tugas:

- auth/session handling
- orchestration logic
- signal generation
- risk approval
- order planning
- execution routing
- portfolio tracking
- monitoring
- API bridge ke Polymarket
- multi-user access control
- audit logging

### 3.4 Polymarket CLOB API

Orderbook / trading gateway off-chain.

Tugas:

- market discovery
- book / price query
- order submission
- order status tracking
- fills dan trading state

### 3.5 Polymarket Exchange Contract

Settlement layer on-chain.

Tugas:

- settlement final
- contract-level exchange interaction
- enforce asset state on-chain

### 3.6 User Proxy Wallet (Polygon)

Wallet eksekusi user.

Tugas:

- menampung asset / position ownership
- source of funds
- final on-chain state reference
- signing / delegated execution path sesuai model integrasi

---

## 4. Main Subsystems

Karena Crusader adalah multi-user system, backend diposisikan sebagai otak sistem, sementara Telegram Bot dan Web menjadi interface layer.

### 4.1 Interface Layer

Tugas:

- menerima interaksi user dari Telegram dan Web
- meneruskan request ke backend
- menampilkan response, alert, trade status, portfolio state

Komponen utama:

- `telegram_bot`
- `web_app`
- `notification_router`
- `session_manager`

### 4.2 Data Ingestion Layer

Tugas:

- mengambil data dari sumber eksternal
- menormalisasi format data
- memberi timestamp konsisten
- menyimpan snapshot ke storage/caching

Komponen:

- `markets_fetcher`
- `candles_fetcher`
- `trades_fetcher`
- `social_fetcher`
- `scheduler`
- `normalizer`

### 4.3 Storage Layer

Tugas:

- menyimpan state sistem dan historinya
- menyediakan query cepat untuk signal / risk / monitoring
- menjaga ownership dan isolasi data per user

Pemisahan storage:

- **raw storage**
- **processed storage**
- **state storage**
- **analytics storage**

### 4.4 Feature Engineering Layer

Feature groups:

- price features
- market quality features
- flow features
- model features
- portfolio context features

### 4.5 Signal Engine

Submodules:

- Probability Model
- Edge Engine
- Regime Filter
- Strategy Selector

### 4.6 Risk Engine

Submodules:

- Sizing Engine
- Exposure Engine
- Drawdown Guard
- Tail Risk Guard
- Trade Approval Gate
- User Limits

### 4.7 Execution Engine

Submodules:

- Order Planner
- Order Router
- Fill Handler
- Exit Manager
- Settlement Tracker
- Execution Guard

### 4.8 Portfolio Engine

Fungsi:

- open position registry
- avg entry calculation
- mark-to-market PnL
- realized PnL
- exposure aggregation
- bankroll update
- performance attribution by strategy
- per-user portfolio isolation

### 4.9 Monitoring & Observability

Monitor categories:

- system health
- trading health
- strategy health
- risk health
- user/account anomalies

---

## 5. Directory Tree

    crusaderbot/
    ├── README.md
    ├── pyproject.toml
    ├── requirements.txt
    ├── .env.example
    ├── .gitignore
    │
    ├── client/
    │   ├── telegram/
    │   │   ├── __init__.py
    │   │   ├── bot.py                      # Main Telegram bot instance
    │   │   ├── config.py                   # Telegram token, webhook config, admins
    │   │   ├── helpers.py                  # Telegram-specific helper utilities
    │   │   ├── handlers/
    │   │   │   ├── __init__.py
    │   │   │   ├── auth.py                 # /start, /connect_wallet, /disconnect_wallet
    │   │   │   ├── markets.py              # /markets, /watchlist
    │   │   │   ├── signals.py              # /signal, /recommendation
    │   │   │   ├── trading.py              # /buy, /sell, /cancel, /close
    │   │   │   ├── portfolio.py            # /balance, /positions, /pnl, /history
    │   │   │   ├── settings.py             # /mode, /limits, /notifications
    │   │   │   ├── account.py              # /profile, /wallet, /permissions
    │   │   │   ├── notifications.py        # Alert commands / subscriptions
    │   │   │   ├── admin.py                # Operator/admin-only commands
    │   │   │   └── utils.py                # Lightweight handler helpers only
    │   │   ├── middlewares/
    │   │   │   ├── __init__.py
    │   │   │   ├── auth.py                 # Session and identity validation
    │   │   │   ├── tenant_context.py       # Inject user/tenant context into request scope
    │   │   │   ├── permissions.py          # RBAC checks
    │   │   │   ├── rate_limit.py           # Flood control per user/chat
    │   │   │   └── error_handler.py        # Graceful error responses
    │   │   ├── keyboards/
    │   │   │   ├── main.py
    │   │   │   ├── trading.py
    │   │   │   ├── portfolio.py
    │   │   │   ├── settings.py
    │   │   │   └── account.py
    │   │   ├── states/
    │   │   │   ├── __init__.py
    │   │   │   ├── auth_states.py
    │   │   │   ├── trade_states.py
    │   │   │   ├── settings_states.py
    │   │   │   └── wallet_states.py
    │   │   ├── templates/
    │   │   │   ├── welcome.md
    │   │   │   ├── order_confirm.md
    │   │   │   ├── portfolio.md
    │   │   │   ├── signal.md
    │   │   │   ├── wallet_status.md
    │   │   │   └── error.md
    │   │   └── notifications/
    │   │       ├── __init__.py
    │   │       ├── trade_alerts.py
    │   │       ├── fill_alerts.py
    │   │       ├── pnl_alerts.py
    │   │       ├── risk_alerts.py
    │   │       └── system_alerts.py
    │   │
    │   └── web/
    │       ├── __init__.py
    │       ├── app.py
    │       ├── routes/
    │       ├── templates/
    │       └── static/
    │
    ├── server/
    │   ├── __init__.py
    │   ├── main.py                        # FastAPI entrypoint
    │   ├── config.py
    │   ├── dependencies.py
    │   │
    │   ├── api/
    │   │   ├── __init__.py
    │   │   ├── telegram_webhook.py
    │   │   ├── auth.py
    │   │   ├── users.py
    │   │   ├── accounts.py
    │   │   ├── wallets.py
    │   │   ├── markets.py
    │   │   ├── signals.py
    │   │   ├── orders.py
    │   │   ├── positions.py
    │   │   ├── portfolio.py
    │   │   ├── risk.py
    │   │   ├── settings.py
    │   │   ├── notifications.py
    │   │   ├── admin.py
    │   │   └── health.py
    │   │
    │   ├── services/
    │   │   ├── __init__.py
    │   │   ├── auth_service.py
    │   │   ├── user_service.py
    │   │   ├── account_service.py
    │   │   ├── wallet_service.py
    │   │   ├── market_service.py
    │   │   ├── signal_service.py
    │   │   ├── order_service.py
    │   │   ├── execution_service.py
    │   │   ├── portfolio_service.py
    │   │   ├── risk_service.py
    │   │   ├── settings_service.py
    │   │   ├── notification_service.py
    │   │   ├── permission_service.py
    │   │   └── audit_service.py
    │   │
    │   ├── core/
    │   │   ├── __init__.py
    │   │   ├── signal_engine.py
    │   │   ├── ev_engine.py
    │   │   ├── edge_engine.py
    │   │   ├── pricing_engine.py
    │   │   ├── strategy_router.py
    │   │   ├── explainers.py
    │   │   └── tenancy.py                # tenant/user scoping helpers
    │   │
    │   ├── risk/
    │   │   ├── __init__.py
    │   │   ├── sizing.py
    │   │   ├── kelly.py
    │   │   ├── exposure.py
    │   │   ├── correlation.py
    │   │   ├── drawdown.py
    │   │   ├── var.py
    │   │   ├── cvar.py
    │   │   ├── trade_gate.py
    │   │   └── user_limits.py            # per-user / per-tier limits
    │   │
    │   ├── execution/
    │   │   ├── __init__.py
    │   │   ├── order_planner.py
    │   │   ├── order_router.py
    │   │   ├── fill_handler.py
    │   │   ├── settlement_tracker.py
    │   │   ├── slippage.py
    │   │   └── execution_guard.py        # duplicate order / race prevention
    │   │
    │   ├── integrations/
    │   │   ├── __init__.py
    │   │   ├── polymarket/
    │   │   │   ├── __init__.py
    │   │   │   ├── clob_client.py
    │   │   │   ├── markets_client.py
    │   │   │   ├── orders_client.py
    │   │   │   ├── trades_client.py
    │   │   │   └── exchange_contract.py
    │   │   └── polygon/
    │   │       ├── __init__.py
    │   │       ├── wallet_client.py
    │   │       ├── signer.py
    │   │       ├── balances.py
    │   │       ├── allowances.py
    │   │       └── proxy_wallet.py
    │   │
    │   ├── portfolio/
    │   │   ├── __init__.py
    │   │   ├── positions.py
    │   │   ├── bankroll.py
    │   │   ├── pnl.py
    │   │   ├── exposure_aggregator.py
    │   │   ├── reconciliation.py
    │   │   └── user_portfolio_scope.py   # enforce portfolio isolation per user
    │   │
    │   ├── storage/
    │   │   ├── __init__.py
    │   │   ├── db.py
    │   │   ├── session.py
    │   │   ├── models/
    │   │   │   ├── user.py
    │   │   │   ├── account.py
    │   │   │   ├── wallet.py
    │   │   │   ├── user_settings.py
    │   │   │   ├── market.py
    │   │   │   ├── signal.py
    │   │   │   ├── order.py
    │   │   │   ├── fill.py
    │   │   │   ├── position.py
    │   │   │   ├── portfolio_snapshot.py
    │   │   │   ├── risk_decision.py
    │   │   │   ├── notification_subscription.py
    │   │   │   ├── audit_log.py
    │   │   │   └── idempotency_key.py
    │   │   ├── repositories/
    │   │   │   ├── user_repository.py
    │   │   │   ├── account_repository.py
    │   │   │   ├── wallet_repository.py
    │   │   │   ├── order_repository.py
    │   │   │   ├── position_repository.py
    │   │   │   ├── signal_repository.py
    │   │   │   ├── portfolio_repository.py
    │   │   │   ├── settings_repository.py
    │   │   │   ├── notification_repository.py
    │   │   │   └── audit_repository.py
    │   │   └── migrations/
    │   │
    │   ├── schemas/
    │   │   ├── __init__.py
    │   │   ├── auth.py
    │   │   ├── user.py
    │   │   ├── account.py
    │   │   ├── wallet.py
    │   │   ├── market.py
    │   │   ├── signal.py
    │   │   ├── order.py
    │   │   ├── portfolio.py
    │   │   ├── risk.py
    │   │   ├── settings.py
    │   │   └── notification.py
    │   │
    │   ├── workers/
    │   │   ├── __init__.py
    │   │   ├── scheduler.py
    │   │   ├── market_sync.py
    │   │   ├── signal_runner.py
    │   │   ├── order_monitor.py
    │   │   ├── settlement_monitor.py
    │   │   ├── risk_monitor.py
    │   │   ├── portfolio_reconciler.py
    │   │   └── notification_dispatcher.py
    │   │
    │   └── utils/
    │       ├── __init__.py
    │       ├── logging.py
    │       ├── time.py
    │       ├── ids.py
    │       ├── crypto.py
    │       └── exceptions.py
    │
    ├── configs/
    │   ├── app.yaml
    │   ├── trading.yaml
    │   ├── risk.yaml
    │   ├── telegram.yaml
    │   ├── wallet.yaml
    │   ├── polymarket.yaml
    │   ├── notifications.yaml
    │   └── tiers.yaml                # user tiers / permissions / limits
    │
    ├── tests/
    │   ├── unit/
    │   ├── integration/
    │   ├── multiuser/
    │   └── e2e/
    │
    ├── scripts/
    │   ├── run_bot.py
    │   ├── run_api.py
    │   ├── run_worker.py
    │   ├── migrate.py
    │   └── seed_admin.py
    │
    └── docs/
        ├── architecture.md
        ├── api_spec.md
        ├── telegram_flow.md
        ├── wallet_flow.md
        ├── multiuser_model.md
        └── risk_rules.md

---

## 6. Bot Structure by Runtime Role

### 6.1 User Layer

Entry point resmi Crusader:

- Telegram user
- Web user

User capability:

- browse market
- lihat signal
- approve trade flow
- pantau posisi
- lihat risk exposure
- receive alert

### 6.2 Crusader Bot (Telegram)

Ini adalah interaction bot.

Fungsi utama:

- command interface
- quick trade action
- push notification
- conversational access ke backend

Bot ini **tidak menyimpan decision truth utama**. Semua keputusan final tetap di backend.

### 6.3 Crusader Backend (FastAPI)

Ini adalah core control plane.

Fungsi utama:

- request validation
- user/session management
- strategy orchestration
- signal generation
- risk approval
- execution coordination
- portfolio truth
- audit logging
- notification dispatch

### 6.4 Polymarket CLOB Integration Layer

Tugas:

- query market / orderbook
- submit order
- track order status
- ingest trade updates

### 6.5 Exchange Contract Layer

Tugas:

- observe settlement state
- map exchange activity ke on-chain result
- reconcile off-chain execution vs on-chain settlement

### 6.6 User Proxy Wallet Layer (Polygon)

Tugas:

- represent user funds / positions
- support execution and settlement path
- track balances and allowances
- become final ownership state

---

## 7. Main Runtime Flows

### 7.1 User Interaction Flow

    User (Telegram/Web)
    → request action / command
    → Crusader Bot or Web UI
    → FastAPI backend
    → backend validates request
    → backend returns data / signal / trade result
    → response shown to user

### 7.2 Market Discovery Flow

    Scheduler
    → fetch market metadata
    → normalize
    → store snapshot
    → apply liquidity/time filters
    → update watchlist

### 7.3 Signal Generation Flow

    Watchlist
    → fetch latest candles/trades/social
    → build features
    → run probability model
    → calculate edge + EV + z-score
    → apply regime filters
    → create signal candidates

### 7.4 Trade Approval Flow

    Signal candidate
    → compute raw size
    → apply fractional Kelly
    → check exposure caps
    → check MDD / VaR / CVaR
    → approve / reduce / block
    → write decision log

### 7.5 Execution Flow

    Approved trade
    → plan order in backend
    → route order to Polymarket CLOB API
    → receive order status / fill / partial fill
    → track exchange state
    → observe settlement path via exchange contract
    → update user proxy wallet state (Polygon)
    → update positions and bankroll
    → monitor exit condition

### 7.6 Position Lifecycle Flow

    Open position
    → monitor mark price
    → monitor signal validity
    → monitor time-to-resolution
    → exit / resolve
    → settle PnL
    → archive position history

---

## 8. Recommended Initial Database Tables

Karena Crusader adalah **multi-user system**, database harus memisahkan dengan jelas:

- user identity
- account ownership
- wallet mapping
- user settings
- orders/positions per user
- notifications per user
- audit trail per user

### Identity & access tables

- `users`
- `accounts`
- `user_sessions`
- `user_roles`
- `permissions`

### Wallet tables

- `wallets`
- `wallet_links`
- `wallet_balances`
- `wallet_allowances`
- `proxy_wallet_mappings`

### Market & signal tables

- `markets`
- `market_outcomes`
- `candles`
- `trades`
- `social_events`
- `watchlist`
- `feature_snapshots`
- `signal_snapshots`

### Trading tables

- `orders`
- `fills`
- `positions`
- `position_events`
- `risk_decisions`
- `idempotency_keys`

### Portfolio tables

- `portfolio_snapshots`
- `bankroll_snapshots`
- `pnl_snapshots`
- `exposure_snapshots`

### User preference & notification tables

- `user_settings`
- `notification_subscriptions`
- `notification_events`

### Audit & system tables

- `audit_logs`
- `system_alerts`
- `job_runs`

### Important isolation rule

Setiap tabel yang berhubungan dengan aktivitas user wajib bisa di-scope minimal dengan salah satu dari ini:

- `user_id`
- `account_id`
- `wallet_id`

Tidak boleh ada query order/position/portfolio yang membaca data lintas user tanpa scope eksplisit admin.

---

## 9. Configuration Design

Config harus dipisah dari code.

### `trading.yaml`

- allowed markets
- max open positions
- minimum volume
- time-to-resolution filters
- paper/live mode

### `risk.yaml`

- max single position %
- max cluster exposure %
- max correlated exposure %
- MDD stop threshold
- daily loss stop
- Kelly fraction alpha
- slippage tolerance

### `tiers.yaml`

- user tiers
- permissions
- risk limits
- product access
- rate limits

### Strategy configs

- edge threshold
- EV threshold
- z-score threshold
- momentum windows
- feature weights
- cooldown rules

---

## 10. Logging & Audit Requirements

Karena sistem multi-user, semua action penting harus tercatat dengan konteks identitas.

### Mandatory logs

- fetch start/end
- normalized record count
- feature build result
- model output per candidate
- edge/EV per candidate
- risk decision reason
- order request/response
- fill update
- position state transition
- exit reason
- resolved trade summary
- wallet link/unlink event
- permissions change
- admin override event

### Audit fields minimal

- timestamp
- request_id
- idempotency_key
- user_id
- account_id
- wallet_id
- telegram_user_id / session ref bila relevan
- market_id / condition_id / token_id
- model version
- strategy name
- signal score
- risk status
- order id
- operator mode (paper/live)
- actor_role (user/admin/system)

### Multi-user audit principle

- user biasa hanya bisa lihat log yang terkait resource miliknya
- admin access ke audit log harus explicit dan tercatat
- semua privileged action wajib bikin audit trail

---

## 11. Safety & Failure Handling

### Hard stop conditions

- stale market data
- missing price source
- bankroll desync
- position book mismatch
- MDD breach
- excessive order failures
- unresolved critical exception in execution loop
- duplicate order intent for same user/action/idempotency key
- cross-user data leakage detected

### Recovery mechanisms

- safe mode fallback
- auto-disable live execution
- replay recent events from storage
- manual reconcile job
- restart from persisted portfolio state
- force wallet/account resync per user

### Multi-user safety requirements

- semua request harus resolve ke tenant/user context dulu
- setiap service wajib enforce ownership check
- setiap order write harus pakai idempotency key
- notifikasi harus difilter per subscriber/user
- admin path dipisah dan diaudit

---

## 12. Minimum Viable Version (MVP)

Tujuan MVP:

- Telegram bot aktif
- FastAPI backend aktif
- multi-user auth/session jalan
- wallet connection per user jalan
- market scan berjalan
- hitung signal dasar
- apply risk per user
- paper trade end-to-end per user
- monitor PnL dan drawdown per user

### MVP Scope

- Crusader Bot via Telegram
- optional basic web dashboard
- FastAPI backend as central control plane
- Polymarket only
- rules-based probability model
- value/mispricing strategy only
- paper execution only
- daily/near-real-time scheduling
- per-user wallet linking
- per-user settings & notification preferences
- simple dashboard/logging

### MVP Modules

- Telegram auth/account flow
- user/account/wallet models
- market fetcher
- feature builder
- probability model v1
- edge + EV engine
- risk gate per user
- paper broker
- portfolio tracker per user
- audit logging
- notification dispatcher

---

## 13. Phase Roadmap

### Phase 1 — Foundation

- repo structure
- configs
- identity/user/account/wallet mapping
- ingestion pipeline
- normalized schema
- watchlist engine
- paper portfolio state per user

### Phase 2 — Signal Core

- rules-based model
- edge/EV engine
- mispricing filters
- risk gate
- paper execution loop
- per-user order/position flow

### Phase 3 — Monitoring & Backtest

- backtesting engine
- PnL reporting
- MDD/Sharpe/Sortino tracking
- anomaly alerts
- audit tools

### Phase 4 — Intelligence Upgrade

- social/narrative integration
- Bayesian updater
- event model
- smart-money flow features

### Phase 5 — Portfolio Expansion

- multi-strategy sleeves
- regime switching
- cluster risk model
- live execution readiness

---

## 14. Recommended Strategy Order

Jangan mulai dari strategi terlalu banyak.

Urutan terbaik:

1. **value / mispricing**
2. **momentum confirmation**
3. **event / narrative**
4. **flow-following**
5. **mean reversion**

Alasan:

- value/mispricing paling dekat dengan formula inti
- momentum bisa jadi filter tambahan
- event/narrative perlu data quality lebih tinggi
- flow-following dan mean reversion lebih sensitif pada microstructure

---

## 15. Final Summary

Crusader v1 sebaiknya dibangun sebagai:

- **multi-user Telegram-first prediction market trading bot**
- **FastAPI-centered backend architecture**
- **Polymarket CLOB execution gateway**
- **on-chain settlement aware system**
- **proxy-wallet-based user execution model**
- **risk-first modular trading backend**
- **strict user isolation and auditability**

Blueprint inti resmi:

    User (Telegram/Web)
           ↓
    Crusader Bot (Telegram)
           ↓
    Crusader Backend (FastAPI)
           ↓
    Polymarket CLOB API
           ↓
    Polymarket Exchange Contract (On-Chain Settlement)
           ↓
    User Proxy Wallet (Polygon)

Decision flow internal tetap:

    Data → Features → Probability Model → Edge/EV → Risk Gate → Execution → Portfolio → Monitoring

Karena Crusader adalah multi-user, maka fondasi non-negotiable adalah:

- user/account/wallet separation
- portfolio isolation per user
- ownership checks di semua service
- idempotent execution flow
- audit trail untuk semua action sensitif
- notification delivery yang scoped per user
