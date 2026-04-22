# CrusaderBot Blueprint - V.2

## Directory Tree ✅

Status: fixed for blueprint use Scope: target blueprint structure, not current repo tree 1:1

```text
crusaderbot/
├── .env.example
├── .gitignore
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── README.md
├── CHANGELOG.md
│
├── docs/
│   ├── blueprint/
│   ├── operator/
│   ├── api/
│   └── runbooks/
│
├── reports/
│   ├── forge/
│   ├── sentinel/
│   └── briefer/
│
├── scripts/
│   ├── local/
│   ├── deploy/
│   └── maintenance/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── runtime/
│   └── fixtures/
│
├── archive/
│   ├── legacy/
│   ├── deprecated/
│   └── migration_notes/
│
└── src/
    └── crusaderbot/
        ├── __init__.py
        ├── main.py
        │
        ├── app/
        │   ├── app.py
        │   ├── bootstrap/
        │   │   ├── config_loader.py
        │   │   ├── dependency_wiring.py
        │   │   ├── runtime_startup.py
        │   │   └── health_bootstrap.py
        │   └── runtime/
        │       ├── lifecycle.py
        │       ├── scheduler.py
        │       ├── mode_manager.py
        │       └── system_state.py
        │
        ├── config/
        │   ├── settings.py
        │   ├── constants.py
        │   ├── logging_config.py
        │   ├── security_config.py
        │   ├── telegram_config.py
        │   ├── polymarket_config.py
        │   ├── database_config.py
        │   └── cache_config.py
        │
        ├── surfaces/
        │   ├── telegram/
        │   │   ├── bot.py
        │   │   ├── dispatcher.py
        │   │   ├── router.py
        │   │   ├── middlewares/
        │   │   ├── handlers/
        │   │   │   ├── public/
        │   │   │   ├── operator/
        │   │   │   ├── admin/
        │   │   │   └── common/
        │   │   ├── keyboards/
        │   │   │   ├── public/
        │   │   │   ├── operator/
        │   │   │   ├── admin/
        │   │   │   └── common/
        │   │   ├── states/
        │   │   ├── filters/
        │   │   └── utils/
        │   │
        │   ├── web/
        │   │   ├── dashboard/
        │   │   ├── public_api/
        │   │   └── auth_pages/
        │   │
        │   └── admin/
        │       ├── monitor/
        │       ├── moderation/
        │       └── ops/
        │
        ├── domain/
        │   ├── trading/
        │   │   ├── execution/
        │   │   ├── orders/
        │   │   ├── positions/
        │   │   ├── portfolio/
        │   │   └── settlement/
        │   ├── markets/
        │   │   ├── discovery/
        │   │   ├── catalog/
        │   │   ├── scoring/
        │   │   └── filters/
        │   ├── strategy/
        │   ├── risk/
        │   ├── accounts/
        │   └── wallet_control/
        │
        ├── integrations/
        │   ├── polymarket/
        │   │   ├── clob/
        │   │   ├── gamma/
        │   │   ├── proxy_wallet/
        │   │   └── auth/
        │   ├── telegram_api/
        │   ├── wallets/
        │   └── intelligence/
        │
        └── platform/
            ├── storage/
            ├── cache/
            ├── monitoring/
            ├── logging/
            ├── auth/
            └── jobs/
```

### Direction preserved

- Telegram-first
- Polymarket-native
- non-custodial by design
- clear public/operator/admin boundary
- clear split between surfaces, domain, integrations, platform

### Notes

- This is blueprint structure.
- This is not current repo truth.
- Public command baseline and current rollout posture must still be documented separately from this target tree.

## Bot Architecture ✅

Status: fixed for blueprint use Scope: target product architecture, not current rollout posture

### Product identity anchor

CrusaderBot is a non-custodial, Telegram-first trading bot for Polymarket. It is designed to let users retain control of funds while the system handles signal processing, execution orchestration, monitoring, and policy enforcement through Polymarket proxy-wallet and CLOB-based flows.

### Architecture principles

- non-custodial by design
- Telegram-first control surface
- Polymarket-native market + execution path
- explicit separation between control surfaces, trading domain, integrations, and platform support
- explicit public / operator / admin boundary
- execution automation without custody transfer
- intelligence informs decisions but does not replace execution or risk authority

### Layer model

#### 1. Control Surface Layer

Purpose: where users and operators interact with CrusaderBot.

Components:

- Telegram public surface
- Telegram operator surface
- Telegram admin surface
- web dashboard surface
- admin monitoring surface

Responsibilities:

- onboarding entry points
- account-link guidance
- command routing
- callback routing
- control presentation
- status/result presentation
- public/operator/admin access separation

#### 2. Application Runtime Layer

Purpose: bootstraps and orchestrates the live system lifecycle.

Components:

- app bootstrap
- dependency wiring
- lifecycle manager
- mode manager
- scheduler
- runtime state manager

Responsibilities:

- startup and shutdown
- environment/config loading
- feature wiring
- runtime mode switching
- background loop coordination
- health/readiness coordination

#### 3. Trading Domain Layer

Purpose: the business core of CrusaderBot.

Components:

- execution engine
- order manager
- trade executor
- fill tracker
- position manager
- portfolio state
- settlement logic
- strategy manager
- allocation logic
- market policy and filtering
- risk manager and kill switch
- account/profile state
- wallet-control boundary

Responsibilities:

- signal-to-order decision flow
- order lifecycle management
- position tracking
- portfolio and exposure control
- strategy selection and allocation
- market eligibility policy
- risk enforcement
- account and preference policy application

#### 4. Market Data Layer

Purpose: retrieves and normalizes Polymarket market-state inputs used by discovery, scoring, and decision logic.

Components:

- Gamma market catalog client
- market discovery adapters
- market metadata normalization
- liquidity / volume / resolution-window readers

Responsibilities:

- market metadata retrieval
- market discovery and filtering
- read-side normalization
- scoring inputs for strategy and risk layers

#### 5. Execution & Wallet Authorization Layer

Purpose: handles the authenticated non-custodial path from approved decision to market execution.

Components:

- CLOB client
- execution gateway
- proxy-wallet service/client
- signing/auth exchange
- authorization/session exchange

Responsibilities:

- order submission/cancellation
- execution reconciliation
- wallet authorization handling
- authenticated session exchange
- signature / auth boundary enforcement
- non-custodial execution path enforcement

#### 6. Intelligence Layer

Purpose: enriches decision quality without becoming the custody, execution, or risk authority.

Components:

- Falcon integration
- market-context enrichment
- external feed adapters

Responsibilities:

- signal enrichment
- confidence/context enrichment
- ranking/prioritization input
- research-side intelligence only

#### 7. Platform Support Layer

Purpose: provides runtime services needed to operate the system safely.

Components:

- config
- storage/repositories
- cache
- monitoring
- health checks
- metrics/tracing
- logging
- auth/session controls
- operator permission controls
- jobs/background workers

Responsibilities:

- observability
- persistence
- cache/session state
- permissioning
- runtime diagnostics
- background processing
- operational safety support

### Primary execution flow

1. User interacts through Telegram.
2. Control surface validates route and access boundary.
3. Application runtime resolves dependencies and current operating mode.
4. Trading domain evaluates strategy, policy, and risk eligibility.
5. Market data layer provides normalized Polymarket market context.
6. Intelligence layer may enrich signal/context.
7. Account and authorization boundary is checked before execution.
8. Execution & wallet authorization layer executes through authenticated non-custodial flow.
9. Trading domain reconciles positions, portfolio, and risk state.
10. Control surface returns status/result back to user or operator.
11. Platform layer records logs, metrics, and health signals.

### Boundary rules

- user funds remain under user control
- CrusaderBot orchestrates execution, not custody
- Telegram is the primary control surface, not the custody layer
- market data and execution are separate concerns
- Polymarket integration is the execution venue, not the strategy brain
- intelligence can inform decisions but must not replace risk controls
- admin/operator controls remain separate from public-safe user surfaces
- admin scope is for monitoring, moderation, operational safety, and system control — not exchange-style financial custody

### What this architecture is not

- not an exchange
- not a custodial wallet platform
- not a generic AI bot shell
- not a paper-only product definition
- not a claim of current production-capital readiness

### Blueprint note

This architecture describes the intended CrusaderBot product shape. Current repo truth and current rollout posture must be documented separately from this target architecture.

## Project Overview ✅

Status: fixed for blueprint use Scope: product identity and product direction, not current rollout posture

### Core definition

CrusaderBot is a non-custodial, high-performance trading bot for Polymarket. It is designed to execute trading workflows through Telegram while allowing users to retain control of their own funds. The system uses Polymarket-native proxy-wallet and CLOB-based execution flows to support secure, gasless trading without turning CrusaderBot into a custodial platform.

### Product identity

- non-custodial by design
- Telegram-first control surface
- Polymarket-native trading workflow
- user retains fund control
- execution orchestration without custody transfer
- designed for fast, high-signal decision and execution loops

### What CrusaderBot does

CrusaderBot helps users interact with Polymarket through a structured Telegram-driven trading experience. It handles market context gathering, signal enrichment, trade orchestration, execution routing, monitoring, and risk policy enforcement. It is intended to reduce execution friction while preserving user control over funds and authorization boundaries.

### Core operating model

1. User interacts through Telegram.
2. CrusaderBot interprets command, context, and policy.
3. Market and signal context are evaluated.
4. Risk and account rules are applied.
5. Authorized execution is routed through Polymarket-native flows.
6. Results, status, and controls are returned through Telegram and supporting surfaces.

### Non-custodial boundary

CrusaderBot does not exist to hold user funds. Its role is to orchestrate trading workflows, not to become the custody layer. The wallet / proxy-wallet / signing boundary is a core part of the product definition, not an implementation detail.

### Product direction

CrusaderBot is aimed at becoming a Telegram-first, non-custodial Polymarket trading system with:

- clear execution controls
- strong risk boundaries
- rich monitoring and operator visibility
- fast Polymarket-native execution handling
- scalable user/account architecture

### What Project Overview is not

- not a paper-only product definition
- not a generic AI bot description
- not a custodial exchange-style platform
- not a claim that current rollout posture equals final product shape
- not a claim of current production-capital readiness

### Separation note

Project Overview defines what CrusaderBot is. Current repo truth defines what is live, merged, or currently exposed. Those two must remain related, but they must not be collapsed into the same statement.

## Telegram Structure ✅

Status: fixed for blueprint use Scope: target Telegram product structure, not current command/runtime truth

### Telegram role in CrusaderBot

Telegram is the primary control surface of CrusaderBot. It is where users onboard, inspect status, configure trading behavior, review outcomes, and trigger authorized actions. It is not the custody layer.

### Telegram structure principles

- Telegram-first, not Telegram-only
- non-custodial wording must stay explicit
- public, operator, and admin paths must remain separate
- account authorization must be visible before execution-capable controls
- read-side status and write-side execution actions must be distinguishable
- operator/admin power must not leak into public-safe UX
- Telegram should feel like a control console, not an exchange wallet app

### Surface map

#### 1. Public Entry Surface

Purpose: first-contact and public-safe orientation.

Includes:

- /start
- /help
- /status
- /paper
- /about
- /risk\_info
- /account
- /link

Responsibilities:

- onboarding entry
- current status overview
- product explanation
- risk explanation
- account-link guidance
- safe fallback/help routing

#### 2. Account & Authorization Surface

Purpose: establish user identity, account state, and execution authorization boundary.

Includes:

- account summary
- link / relink flow
- authorization status
- wallet/proxy-wallet guidance
- permissions / readiness checks

Responsibilities:

- show whether account is linked
- explain execution readiness
- expose non-custodial boundary clearly
- gate execution-capable controls until authorization is valid

#### 3. Trading Control Surface

Purpose: user-facing controls for trading behavior and execution posture.

Includes:

- mode selection
- start / pause / stop controls
- strategy profile controls
- capital/risk policy inputs
- category/market filters
- execution preference controls

Responsibilities:

- configure how CrusaderBot trades
- expose risk boundaries before activation
- separate policy setting from actual custody/auth flow

#### 4. Portfolio & Position Surface

Purpose: show what the system is doing and what exposure exists.

Includes:

- open positions
- closed positions
- pending orders
- portfolio summary
- market-specific position details

Responsibilities:

- show exposure and outcome state
- make active decisions inspectable
- let user understand execution outcomes without turning Telegram into a brokerage ledger UI

#### 5. Analytics & Notification Surface

Purpose: help the user interpret performance, signals, and system behavior.

Includes:

- performance summaries
- signal analytics
- category performance
- risk analytics
- notification preferences
- summary schedule/history

Responsibilities:

- make the bot explainable
- show confidence and performance trends
- expose operational feedback loops

#### 6. Operator Surface

Purpose: restricted operational controls beyond the public-safe layer.

Includes:

- operator risk controls
- market controls
- metrics and health controls
- strategy overrides
- manual trade/control actions where permitted

Responsibilities:

- support controlled runtime operations
- expose deeper controls only to authorized operator roles
- remain clearly separate from the public-safe surface

#### 7. Admin / Ops Surface

Purpose: restricted system-level monitoring, moderation, and operational safety.

Includes:

- monitor dashboards
- moderation tools
- broadcast / announcements
- report access
- operational safety controls

Responsibilities:

- system visibility
- moderation and support workflows
- operational control and incident response

### Telegram navigation model

1. Entry point
2. Identity/account state check
3. Public-safe overview
4. Authorization-aware branching
5. Trading control / portfolio / analytics branches
6. Restricted operator/admin branches only when role allows

### Telegram execution rule

Any execution-capable path must come after:

- identity resolution
- account-link state check
- authorization readiness check
- policy/risk eligibility check

### UX wording rules

- use "control" language, not custody language
- use "link" / "authorize" language, not exchange-style deposit custody language
- keep non-custodial boundary visible in wallet/account areas
- keep operator/admin actions visually distinct from user paths
- do not describe Telegram as monitor-only
- do not imply unrestricted full autonomy without user-controlled boundaries

### What Telegram structure is not

- not a custodial wallet app
- not a broker-style exchange terminal
- not an admin-heavy finance platform
- not a monitor-only shell
- not a statement of current merged command truth

### Blueprint note

Telegram Structure defines the intended Telegram product shape. Current repo command truth and current rollout posture must be documented separately from this target structure.

### Telegram treeview model

```text
TELEGRAM
│
├── Public Entry Surface
│   │
│   ├── /start
│   │   ├── New User
│   │   │   ├── Welcome
│   │   │   ├── Product Overview
│   │   │   ├── Terms / Consent
│   │   │   ├── Account Status Check
│   │   │   ├── Link / Authorization Guidance
│   │   │   └── Continue to Main Control
│   │   │
│   │   └── Existing User
│   │       ├── Account Status Summary
│   │       ├── Bot Status Summary
│   │       └── Continue to Main Control
│   │
│   ├── /help
│   ├── /status
│   ├── /paper
│   ├── /about
│   ├── /risk_info
│   ├── /account
│   └── /link
│
├── Main Control Surface
│   │
│   ├── Dashboard
│   │   ├── Portfolio Summary
│   │   ├── Bot Status
│   │   ├── Open Exposure Snapshot
│   │   ├── Recent Activity
│   │   └── Alerts / Important Notices
│   │
│   ├── Trading Controls
│   │   ├── Mode Selection
│   │   ├── Start / Pause / Stop
│   │   ├── Strategy Profile
│   │   ├── Risk Policy
│   │   ├── Market / Category Filters
│   │   └── Execution Preferences
│   │
│   ├── Portfolio & Positions
│   │   ├── Open Positions
│   │   ├── Closed Positions
│   │   ├── Pending Orders
│   │   └── Position Detail
│   │
│   ├── Analytics
│   │   ├── Performance Summary
│   │   ├── Signal Analytics
│   │   ├── Category Performance
│   │   ├── Risk Analytics
│   │   └── Notification History
│   │
│   └── Account & Authorization
│       ├── Account Summary
│       ├── Link / Relink Account
│       ├── Authorization Readiness
│       ├── Wallet / Proxy-Wallet Guidance
│       └── Permissions / Eligibility State
│
├── Execution-Capable Path
│   │
│   ├── Identity Resolved
│   ├── Account Linked
│   ├── Authorization Ready
│   ├── Policy / Risk Eligible
│   └── Execution Allowed
│
├── Operator Surface
│   │
│   ├── Operator Risk Controls
│   ├── Market Controls
│   ├── Strategy Overrides
│   ├── Metrics / Health Views
│   └── Manual Runtime Controls
│
└── Admin / Ops Surface
    │
    ├── Monitor Dashboard
    ├── Moderation Tools
    ├── Broadcast / Announcement Tools
    ├── Reports Access
    └── Operational Safety Controls
```

### Treeview intent note

This treeview is a Telegram product-shape map. It shows surface hierarchy and control flow. It does not define current merged commands one-to-one. It also does not imply custodial wallet behavior or exchange-style deposit custody.

## Command Surface ✅

Status: fixed for blueprint use\
Scope: target Telegram command model, not current merged command truth

### Command surface role

Command Surface defines how CrusaderBot exposes user, operator, and admin capabilities through Telegram commands. It exists to make the product understandable, controllable, and safe. It must reflect a Telegram-first control model without turning Telegram into a custodial wallet app or exchange terminal.

### Design principles

- Telegram is a control plane, not an execution plane
- the bot receives intent, not raw manual trading instructions
- heavy lifting happens in backend services and domain/integration layers
- commands must be understandable, discoverable, and single-purpose
- public-safe commands must stay separate from execution-capable commands
- account and authorization commands must appear before execution-capable commands
- operator/admin controls must never leak into public-safe discovery paths
- read-side commands and write-side commands must be distinguishable
- command names should reinforce non-custodial wording

### What command surface is / is not

#### Command surface is

- a control interface for bot automation
- a status and observability window
- a configuration entry point
- a notification delivery channel
- an emergency control panel
- a support/help gateway

#### Command surface is not

- a manual trading terminal
- a custodial wallet interface
- a real-time market data terminal
- a charting / TA platform
- an order-book viewer
- the primary auth mechanism for sensitive operations

### Role model

- **User**: end user of CrusaderBot
- **Moderator**: support-facing limited review role
- **Operator**: technical/runtime control role
- **Admin**: platform operations role
- **Super Admin**: owner-level system authority

### Command classes

#### 1. Public-safe commands

Purpose: orientation, education, and status without privileged control.

Includes:

- /start
- /help
- /status
- /paper
- /about
- /risk\_info

#### 2. Account & authorization commands

Purpose: identity, account state, and execution readiness.

Includes:

- /account
- /link
- /authorize
- /permissions

#### 3. Trading control commands

Purpose: user-facing controls over trading behavior.

Includes:

- /mode
- /control
- /strategy
- /risk
- /filters
- /preferences

#### 4. Portfolio & position commands

Purpose: inspect exposure and outcome state.

Includes:

- /portfolio
- /positions
- /orders
- /exposure

#### 5. Analytics commands

Purpose: interpret performance and operational behavior.

Includes:

- /analytics
- /performance
- /signals
- /notifications

#### 6. Operator commands

Purpose: restricted runtime controls beyond standard user controls.

Includes:

- /operator\_risk
- /markets
- /metrics
- /health
- /trade
- /override

#### 7. Admin / ops commands

Purpose: restricted system-level monitoring and safety controls.

Includes:

- /admin
- /monitor
- /moderate
- /broadcast
- /reports

### Command policy model

Each command family should define:

- **role**: who can access it
- **rate limit**: how often it may be called
- **confirmation**: whether confirmation is required
- **elevated auth**: whether 2FA / step-up auth is required
- **destructive flag**: whether it can change state or trigger emergency behavior

### Command behavior model

#### Read-side commands

These commands show status, state, context, and explanation. Examples:

- /status
- /about
- /risk\_info
- /portfolio
- /positions
- /analytics
- /metrics
- /health

#### Control commands

These commands change system behavior or policy. Examples:

- /link
- /authorize
- /mode
- /control
- /strategy
- /risk
- /filters
- /preferences
- /override

#### Execution-capable commands

These commands may lead to order-routing or execution-relevant outcomes. Examples:

- /trade
- /control
- /risk
- /strategy

Execution-capable commands must never bypass:

- identity resolution
- account-link state
- authorization readiness
- policy/risk eligibility

### Naming rules

- use product language, not infra language
- prefer one clear noun or verb per command
- keep public-safe commands easy to discover
- keep operator/admin commands explicit and separate
- avoid exchange-custody wording such as deposit/withdraw as primary command framing
- prefer authorize/link/control language over custody language

### Discovery rules

- public help must show only public-safe and account-safe commands
- execution-capable commands should appear only after account and authorization readiness is established
- operator/admin commands must not appear in standard public onboarding/help paths
- deep control commands should be reachable through structured navigation, not noisy top-level sprawl

### Command surface view model

```text
COMMAND SURFACE
│
├── PUBLIC-SAFE
│   ├── /start       → entry point, onboarding, safe routing
│   ├── /help        → help and discoverability
│   ├── /status      → quick system/account status
│   ├── /paper       → rollout / posture explanation
│   ├── /about       → product explanation
│   └── /risk_info   → risk explanation, read-only
│
├── ACCOUNT & AUTHORIZATION
│   ├── /account     → account summary
│   ├── /link        → link / relink account flow
│   ├── /authorize   → authorization readiness
│   └── /permissions → eligibility and permission state
│
├── TRADING CONTROLS
│   ├── /mode        → choose operating mode
│   ├── /control     → start / pause / stop controls
│   ├── /strategy    → strategy profile controls
│   ├── /risk        → risk policy controls
│   ├── /filters     → market/category controls
│   └── /preferences → trading preferences
│
├── PORTFOLIO & POSITIONS
│   ├── /portfolio   → portfolio snapshot
│   ├── /positions   → open / closed positions
│   ├── /orders      → pending / recent orders
│   └── /exposure    → exposure visibility
│
├── ANALYTICS
│   ├── /analytics   → analytics home
│   ├── /performance → performance summaries
│   ├── /signals     → signal analytics
│   └── /notifications → notification config/history
│
├── OPERATOR
│   ├── /operator_risk → runtime risk controls
│   ├── /markets       → market controls
│   ├── /metrics       → metrics and observability
│   ├── /health        → runtime health
│   ├── /trade         → controlled runtime intervention
│   └── /override      → restricted override controls
│
└── ADMIN / OPS
    ├── /admin       → admin home
    ├── /monitor     → monitor access
    ├── /moderate    → moderation tools
    ├── /broadcast   → announcement tools
    └── /reports     → reports and audit access
```

### Easy-to-read command policy view

```text
CATEGORY 1 — PUBLIC-SAFE
Command       Purpose                         Role        Confirm   Elevated Auth
/start        Entry point                     None        No        No
/help         Help menu                       None        No        No
/status       Quick status                    User        No        No
/paper        Rollout posture explanation     None/User   No        No
/about        About CrusaderBot               None        No        No
/risk_info    Risk explanation                None/User   No        No

CATEGORY 2 — ACCOUNT & AUTHORIZATION
Command       Purpose                         Role        Confirm   Elevated Auth
/account      Account summary                 User        No        No
/link         Link / relink account           User        Yes       Step-up if sensitive
/authorize    Authorization readiness         User        No        Step-up if sensitive
/permissions  Permission / eligibility state  User        No        No

CATEGORY 3 — TRADING CONTROLS
Command       Purpose                         Role        Confirm   Elevated Auth
/mode         Change operating mode           User        Yes       No
/control      Start / pause / stop behavior   User        Yes       Step-up for destructive actions
/strategy     Strategy profile control        User        Yes       No
/risk         Risk policy control             User        Yes       Step-up when materially increasing risk
/filters      Market/category filtering       User        No        No
/preferences  Trading preferences             User        No        No

CATEGORY 4 — PORTFOLIO & POSITIONS
Command       Purpose                         Role        Confirm   Elevated Auth
/portfolio    Portfolio snapshot              User        No        No
/positions    Position visibility             User        No        No
/orders       Pending/recent order state      User        No        No
/exposure     Exposure visibility             User        No        No

CATEGORY 5 — ANALYTICS
Command       Purpose                         Role        Confirm   Elevated Auth
/analytics    Analytics home                  User        No        No
/performance  Performance summaries           User        No        No
/signals      Signal analytics                User        No        No
/notifications Notification config/history    User        No        No

CATEGORY 6 — OPERATOR / ADMIN
Command       Purpose                         Role        Confirm   Elevated Auth
/operator_risk Runtime risk control           Operator    Yes       Yes
/markets      Runtime market control          Operator    Yes       Yes
/metrics      Metrics / observability         Operator    No        No
/health       Runtime health                  Operator    No        No
/trade        Controlled intervention         Operator    Yes       Yes
/override     Restricted override             Operator    Yes       Yes
/admin        Admin home                      Admin+      No        Yes
/monitor      Monitor access                  Admin+      No        Yes
/moderate     Moderation tools                Moderator+  Yes       Yes
/broadcast    Announcement tools              Admin+      Yes       Yes
/reports      Reports / audit access          Admin+      No        Yes
```

### Suggested command map

```text
COMMAND SURFACE MAP
│
├── Public-safe
│   ├── /start
│   ├── /help
│   ├── /status
│   ├── /paper
│   ├── /about
│   └── /risk_info
│
├── Account & Authorization
│   ├── /account
│   ├── /link
│   ├── /authorize
│   └── /permissions
│
├── Trading Controls
│   ├── /mode
│   ├── /control
│   ├── /strategy
│   ├── /risk
│   ├── /filters
│   └── /preferences
│
├── Portfolio & Positions
│   ├── /portfolio
│   ├── /positions
│   ├── /orders
│   └── /exposure
│
├── Analytics
│   ├── /analytics
│   ├── /performance
│   ├── /signals
│   └── /notifications
│
├── Operator
│   ├── /operator_risk
│   ├── /markets
│   ├── /metrics
│   ├── /health
│   ├── /trade
│   └── /override
│
└── Admin / Ops
    ├── /admin
    ├── /monitor
    ├── /moderate
    ├── /broadcast
    └── /reports
```

### What Command Surface is not

- not a statement that all listed commands are currently merged
- not a custodial wallet command model
- not an admin-first control plane
- not a promise that every control is top-level forever
- not a claim of unrestricted live-trading readiness

### Separation note

Command Surface defines the intended Telegram command model for CrusaderBot. Current repo command truth must still be documented separately from this blueprint target.



## User Flow ✅

Status: fixed for blueprint use\
Scope: target onboarding and lifecycle flow, not current merged runtime flow

### User flow role

User Flow defines how a person moves from first contact to active use of CrusaderBot. It must make the product understandable, safe, non-custodial, and reversible. It must also support resuming partially completed setup without forcing users to restart from zero.

### Design principles

- progressive disclosure
- safety first
- clear exit points
- zero ambiguity
- compliance-ready structure
- non-custodial wording must remain explicit
- Telegram handles guidance and control, not sensitive custody operations

### Core suggestions applied from reference review

- keep **Discovery** as a real stage, because entry attribution and routing matter
- keep **Welcome before commitment**, so value proposition is clear before asking for consent
- keep **Legal / risk disclosure before activation**
- keep **resume-by-stage routing** for incomplete users
- keep **paper preview / familiarization before live authorization**
- replace custodial-looking **wallet generate / import / deposit** flows with **account link / authorization / readiness** flows
- keep **clear cancel and resume** at every stage
- keep **jurisdiction / policy checks** as capability, without making Telegram the full compliance engine

### Stage model

#### Stage 0 — Discovery

Purpose: capture source, context, and routing state before onboarding begins.

Inputs:

- direct bot link
- referral link
- QR code / campaign link
- Telegram search
- group mention / channel handoff

System actions:

- capture Telegram metadata
- detect existing vs new user
- parse referral / attribution context if present
- log discovery source
- perform initial policy / jurisdiction flags if available
- route user to the correct next stage or resume stage

#### Stage 1 — Welcome & Introduction

Purpose: explain what CrusaderBot is before asking for commitment.

Outputs:

- product explanation
- non-custodial positioning
- Telegram-first control model explanation
- quick preview of how CrusaderBot works
- explicit ability to continue, skip high-level intro, or exit

#### Stage 2 — Legal & Risk Disclosure

Purpose: establish informed use before any activation-capable setup.

Outputs:

- terms acknowledgement
- risk disclosure acknowledgement
- boundary explanation
- jurisdiction / policy gating where needed

#### Stage 3 — Account Setup

Purpose: establish basic user profile and operating preferences.

Outputs:

- account record
- language / locale preference
- timezone preference
- notification baseline
- resumable setup state

#### Stage 4 — Security & Access Setup

Purpose: protect sensitive control paths before deeper configuration.

Outputs:

- PIN / step-up auth setup
- optional 2FA path
- recovery / re-entry method
- elevated-auth readiness for sensitive actions

#### Stage 5 — Account Link & Authorization

Purpose: establish the non-custodial execution boundary.

Outputs:

- account-link guidance
- authorization readiness state
- wallet / proxy-wallet boundary explanation
- permissions state
- no raw key / seed / signing-through-chat behavior

#### Stage 6 — Trading Configuration

Purpose: let the user define how CrusaderBot should behave.

Outputs:

- mode selection
- strategy profile
- risk policy
- market/category filters
- preferences and operating controls

#### Stage 7 — Preview / Familiarization

Purpose: build confidence before activation-capable usage.

Outputs:

- preview of dashboards and controls
- example status / analytics views
- paper-preview or safe familiarization path
- confirmation that user understands the control model

#### Stage 8 — Readiness Check

Purpose: confirm the system is actually ready before activation.

Outputs:

- identity resolved
- account linked
- authorization ready
- policy/risk valid
- notification and control readiness
- unresolved blockers surfaced clearly

#### Stage 9 — Activation

Purpose: explicit opt-in to active bot operation.

Outputs:

- final review
- explicit confirmation
- start in chosen operating mode
- first active status delivered back to the user

#### Stage 10 — Post-Activation Guidance

Purpose: help the user understand what happens after activation.

Outputs:

- first-use guidance
- status interpretation tips
- how to pause / stop / change settings
- how to inspect positions / analytics
- feedback and support entry points

### Routing logic

- new user → Stage 0 to Stage 10 in order
- partial user → resume at the saved incomplete stage
- active user → route directly to Main Control Surface
- banned/restricted user → show policy-restricted message and no privileged flow
- missing authorization → route to Account Link & Authorization
- not-ready configuration → route to Readiness Check blockers

### Lifecycle branches

#### Branch A — New user path

Discovery → Welcome → Legal → Account → Security → Link/Authorize → Configure → Preview → Readiness → Activation → Guidance

#### Branch B — Returning incomplete user

/start → detect saved state → resume exact stage → continue forward

#### Branch C — Active user

/start → status summary → Main Control Surface

#### Branch D — Restricted user

/start → policy/restriction message → support/help branch only

### User flow treeview model

```text
USER FLOW
│
├── STAGE 0 — DISCOVERY
│   ├── Entry source captured
│   ├── Telegram metadata captured
│   ├── Existing vs new user check
│   ├── Referral / attribution parsed
│   ├── Initial policy / jurisdiction flags
│   └── Route to next appropriate stage
│
├── STAGE 1 — WELCOME & INTRODUCTION
│   ├── Welcome greeting
│   ├── What CrusaderBot is
│   ├── Non-custodial explanation
│   ├── Telegram control model explanation
│   └── Continue / Skip Intro / Cancel
│
├── STAGE 2 — LEGAL & RISK
│   ├── Terms acknowledgement
│   ├── Risk disclosure acknowledgement
│   ├── Boundary explanation
│   └── Policy gating if needed
│
├── STAGE 3 — ACCOUNT SETUP
│   ├── Profile setup
│   ├── Language / locale
│   ├── Timezone
│   └── Notification baseline
│
├── STAGE 4 — SECURITY & ACCESS
│   ├── PIN / step-up auth
│   ├── Optional 2FA
│   ├── Recovery method
│   └── Sensitive-action readiness
│
├── STAGE 5 — ACCOUNT LINK & AUTHORIZATION
│   ├── Link / relink guidance
│   ├── Authorization readiness
│   ├── Wallet / proxy-wallet boundary
│   └── Permissions state
│
├── STAGE 6 — TRADING CONFIGURATION
│   ├── Mode selection
│   ├── Strategy profile
│   ├── Risk policy
│   ├── Market/category filters
│   └── Preferences
│
├── STAGE 7 — PREVIEW / FAMILIARIZATION
│   ├── Control preview
│   ├── Status preview
│   ├── Analytics preview
│   └── Safe familiarization path
│
├── STAGE 8 — READINESS CHECK
│   ├── Identity resolved
│   ├── Account linked
│   ├── Authorization ready
│   ├── Policy/risk valid
│   └── Blockers shown clearly
│
├── STAGE 9 — ACTIVATION
│   ├── Final review
│   ├── Explicit opt-in
│   ├── Bot enters active mode
│   └── Initial active status shown
│
└── STAGE 10 — POST-ACTIVATION GUIDANCE
    ├── First-use guidance
    ├── Pause / stop guidance
    ├── Positions / analytics guidance
    └── Support / feedback path
```

### Easy-to-read stage view

```text
STAGE   NAME                         PURPOSE
0       Discovery                    Find source, identify user, route correctly
1       Welcome                      Explain CrusaderBot before asking commitment
2       Legal & Risk                 Informed acknowledgement before activation
3       Account Setup                Basic profile and preference setup
4       Security & Access            Sensitive-control protection
5       Account Link & Authorization Non-custodial readiness boundary
6       Trading Configuration        Define mode, strategy, risk, filters
7       Preview / Familiarization    Build confidence before activation
8       Readiness Check              Confirm blockers are cleared
9       Activation                   Explicit opt-in to active use
10      Post-Activation Guidance     Help user understand live behavior
```

### Flow rules

- user can cancel at any stage
- setup state must be resumable
- risky or destructive transitions require explicit confirmation
- sensitive actions require elevated auth where appropriate
- no private key display in Telegram
- no seed phrase input in Telegram chat
- no raw signing flow in Telegram chat
- no forced progression through dark-pattern onboarding

### What User Flow is not

- not a custodial deposit funnel
- not a generic exchange signup flow
- not a statement that every stage is currently merged
- not a requirement that every step be handled only inside Telegram
- not a claim that current rollout posture already equals final onboarding shape

### Separation note

User Flow defines the intended CrusaderBot onboarding and lifecycle experience. Current repo truth and current rollout posture must still be documented separately from this blueprint target.



## Control Dashboard Structure ✅

Status: fixed for blueprint use\
Scope: target Telegram dashboard structure, not current merged UI/runtime truth

### Dashboard role

Control Dashboard is the primary summary view inside Telegram. It exists to help users understand bot state, exposure, activity, health, and next actions in a fast, mobile-native format. It must feel like a control console, not a brokerage terminal or custodial wallet screen.

### Design principles

- glanceable
- actionable
- layered
- Telegram-native
- real-time but cached
- critical information in the first fold
- every anomaly should have a next action
- no dead-end summary blocks

### Core suggestions applied from reference review

- keep a **glanceable first screen** so bot health is understandable in under a few seconds
- keep **layered navigation** from summary → category dashboard → detail → raw evidence/logs
- keep **manual refresh with visible timestamp**, instead of noisy auto-refresh
- keep **inline keyboard action bar** for fast movement between dashboard branches
- keep **state-dependent blocks** so paused/halted/blocked states change the dashboard clearly
- keep **alerts & notices as conditional block**, not permanent clutter
- replace custody-looking wallet emphasis with **account / authorization readiness** wording where possible
- keep markdown/text-grid friendly layout for Telegram mobile readability

### Dashboard hierarchy model

#### L1 — Main Dashboard

Purpose: summary overview shown first.

Shows:

- bot status
- mode
- uptime / state freshness
- portfolio snapshot
- active position snapshot
- today activity
- system health
- alerts / notices
- action bar

#### L2 — Category Dashboards

Purpose: focused category views launched from the main dashboard.

Includes:

- Bot Status dashboard
- Portfolio dashboard
- Positions dashboard
- Performance / Analytics dashboard
- System Health dashboard
- Strategy / Controls dashboard
- Alerts dashboard
- Account / Authorization dashboard

#### L3 — Detail Views

Purpose: drill-down screens for one selected block or metric.

Examples:

- engine/runtime detail
- balance/exposure detail
- position detail
- metric detail
- service detail
- alert detail

#### L4 — Raw Evidence / Logs

Purpose: operator/admin or deep-inspection evidence view.

Examples:

- raw event stream
- trade log
- notification history
- runtime health log
- audit / report links

### Entry paths

Primary entry paths should stay aligned with the broader Telegram structure. Recommended dashboard entry paths:

- Main Control Surface
- /status
- /portfolio
- /analytics
- Home / Dashboard button in inline navigation

Optional future alias:

- /dashboard

### Refresh policy

- auto-refresh: disabled by default
- manual refresh available
- cache TTL should be explicit
- stale indicator must be visible, for example: "Updated 12s ago"
- refresh calls must be rate-limited
- critical state changes may still push notifications proactively

### Main dashboard block model

#### Header

Shows:

- CrusaderBot label
- user handle / identity label
- updated timestamp
- optional mode/state badge

#### Block 1 — Bot Status

Critical at-a-glance state.

Shows:

- current state (active / paused / halted / blocked)
- mode
- uptime or session duration
- high-level health score / readiness label

#### Block 2 — Portfolio Snapshot

Quick financial/exposure overview.

Shows:

- total value
- available capital / usable balance
- deployed / invested amount
- today P&L or equivalent session performance

#### Block 3 — Active Positions

Quick exposure snapshot.

Shows:

- open positions count
- pending orders count
- short rolling win-rate or outcome quality signal
- optional net exposure summary

#### Block 4 — Today Activity

What the bot has done recently.

Shows:

- signals analyzed
- executed actions / trades
- rejected actions count
- last action timestamp

#### Block 5 — System Health

Dependency and runtime health snapshot.

Shows:

- Polymarket connectivity
- intelligence provider status
- account / authorization readiness
- storage / runtime health

#### Block 6 — Alerts & Notices

Conditional attention area.

Shows only when needed:

- active alerts
- risk threshold proximity
- unresolved readiness blockers
- required user actions
- policy or system warnings

#### Action Bar

Inline keyboard navigation.

Recommended actions:

- Control
- Portfolio
- Positions
- Performance
- Strategy
- Alerts
- Account
- Refresh

### State-dependent behavior

#### If bot is paused

- show pause reason
- show resume availability or resume time
- swap primary action to Resume

#### If bot is halted / blocked

- show high-visibility warning banner
- replace primary actions with safe recovery/support actions
- surface reason clearly before any further controls

#### If account is not authorized

- surface authorization blocker prominently
- replace execution-oriented actions with Link / Authorize guidance

#### If there are no active positions

- keep portfolio view compact
- highlight configuration, readiness, or activation guidance instead of empty trading noise

### Dashboard treeview model

```text
CONTROL DASHBOARD
│
├── L1 — MAIN DASHBOARD
│   │
│   ├── Header
│   │   ├── CrusaderBot label
│   │   ├── User identity label
│   │   ├── Updated timestamp
│   │   └── Mode / state badge
│   │
│   ├── Block 1 — Bot Status
│   ├── Block 2 — Portfolio Snapshot
│   ├── Block 3 — Active Positions
│   ├── Block 4 — Today Activity
│   ├── Block 5 — System Health
│   ├── Block 6 — Alerts & Notices (conditional)
│   └── Action Bar
│
├── L2 — CATEGORY DASHBOARDS
│   ├── Bot Status
│   ├── Portfolio
│   ├── Positions
│   ├── Performance / Analytics
│   ├── System Health
│   ├── Strategy / Controls
│   ├── Alerts
│   └── Account / Authorization
│
├── L3 — DETAIL VIEWS
│   ├── Engine / Runtime Detail
│   ├── Balance / Exposure Detail
│   ├── Position Detail
│   ├── Metric Detail
│   ├── Service Detail
│   └── Alert Detail
│
└── L4 — RAW EVIDENCE / LOGS
    ├── Trade Log
    ├── Event Stream
    ├── Notification History
    ├── Runtime Health Log
    └── Audit / Reports
```

### Easy-to-read layout view

```text
[HEADER]
CrusaderBot Dashboard
@username | Updated 12s ago | Mode: Balanced

[BLOCK 1: BOT STATUS]
Status     : ACTIVE
Mode       : Balanced
Uptime     : 2d 14h
Health     : Healthy

[BLOCK 2: PORTFOLIO SNAPSHOT]
Total Value : $X
Available   : $X
Deployed    : $X
Today P&L   : +$X / -$X

[BLOCK 3: ACTIVE POSITIONS]
Open        : X
Pending     : X
Win Rate    : X%
Exposure    : X%

[BLOCK 4: TODAY ACTIVITY]
Signals     : X analyzed
Executed    : X
Rejected    : X
Last Action : HH:MM UTC

[BLOCK 5: SYSTEM HEALTH]
Polymarket  : Online
Falcon      : Online
Authorization : Ready / Not Ready
Storage     : Healthy

[BLOCK 6: ALERTS & NOTICES]
Only shown when needed

[ACTION BAR]
[Control] [Portfolio] [Positions] [Performance]
[Strategy] [Alerts] [Account] [Refresh]
```

### Telegram formatting rules

- optimize for mobile viewport first
- prefer text-grid / markdown-friendly blocks
- avoid dense wide tables
- use inline keyboards for movement, not long command memorization
- keep first screen readable without scroll where possible
- visual hierarchy should be status → exposure → activity → health → actions

### What Control Dashboard Structure is not

- not a brokerage terminal
- not a real-time charting screen
- not an order-book viewer
- not a custodial wallet page
- not a statement that /dashboard is already a fixed merged command
- not a claim that every L3/L4 view is currently shipped

### Separation note

Control Dashboard Structure defines the intended Telegram dashboard shape for CrusaderBot. Current repo truth and current rollout posture must still be documented separately from this blueprint target.



## Visual Presentation Standard ✅

Status: fixed for blueprint use\
Scope: presentation standard for all blueprint sections already locked

### Style goals

- premium but still text-first
- easy to scan on mobile
- Telegram-friendly monospace / text-grid look
- icon-assisted visual hierarchy
- readable without relying on colors alone
- safe for markdown/text rendering

### Global view rules

- use ASCII/text-grid blocks for main views
- use icons to create light color and hierarchy
- keep titles, blocks, and dividers visually distinct
- optimize for narrow/mobile viewport first
- prefer summary-first layout
- keep each block actionable or clearly informative
- avoid dense wide tables unless converted to stacked text-grid form

### Icon language

- 🦅 brand / CrusaderBot
- 👤 user / account
- 🤖 bot / runtime
- ⚙️ control / settings
- 🔐 auth / security
- 🛡️ risk / boundary
- 📊 portfolio / analytics
- 📂 positions / lists
- 🌐 integrations / external connectivity
- 🧠 intelligence / signal
- 🏥 health / monitoring
- 🚨 alerts / critical notice
- 🔄 refresh / resume / retry
- ✅ ready / healthy
- ⚠️ attention / caution
- ❌ blocked / invalid

### Content hierarchy rule

Every major blueprint section should be readable in this order:

1. title / identity
2. purpose
3. core blocks or layer map
4. flow / hierarchy / treeview
5. boundary / notes

### Premium view patch — Directory Tree

```text
╔══════════════════════════════════════════════════════════════════════╗
║                        🦅 CRUSADERBOT TREE                          ║
╚══════════════════════════════════════════════════════════════════════╝

crusaderbot/
│
├── 📄 .env.example
├── 📄 pyproject.toml
├── 📄 requirements.txt
├── 📄 Dockerfile
├── 📄 README.md
├── 📄 CHANGELOG.md
│
├── 📁 docs/
├── 📁 reports/
├── 📁 scripts/
├── 📁 tests/
├── 📁 archive/
└── 📁 src/
    └── 📁 crusaderbot/
        ├── 📄 main.py
        ├── 📁 app/
        ├── 📁 config/
        ├── 📁 surfaces/
        ├── 📁 domain/
        ├── 📁 integrations/
        └── 📁 platform/
```

```text
[IDENTITY]
🦅 Telegram-first
🌐 Polymarket-native
🛡️ Non-custodial by design

[CORE SHAPE]
📱 surfaces/     → user interaction
🧠 domain/       → business logic
🔌 integrations/ → external connections
🏗️ platform/     → runtime support
```

### Premium view patch — Bot Architecture

```text
╔══════════════════════════════════════════════════════════════════════╗
║                     🏗️ BOT ARCHITECTURE OVERVIEW                    ║
╚══════════════════════════════════════════════════════════════════════╝

┌──────────────────────────────┐
│ 📱 1. CONTROL SURFACE LAYER  │
│ Telegram / Web / Admin       │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ ⚙️ 2. APPLICATION RUNTIME     │
│ Bootstrap / Lifecycle / Mode │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 🧠 3. TRADING DOMAIN LAYER   │
│ Strategy / Risk / Execution  │
└───────┬───────────┬──────────┘
        ▼           ▼
┌──────────────┐ ┌──────────────────────────────┐
│ 📡 4. MARKET │ │ 🔐 5. EXECUTION & AUTH LAYER │
│ DATA LAYER   │ │ CLOB / Proxy Wallet / Auth   │
└──────┬───────┘ └──────────────┬───────────────┘
       ▼                        ▼
┌──────────────────────────────┐
│ 🧠 6. INTELLIGENCE LAYER     │
│ Falcon / Context / Signals   │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 🏥 7. PLATFORM SUPPORT       │
│ Storage / Monitoring / Logs  │
└──────────────────────────────┘
```

### Premium view patch — Project Overview

```text
╔══════════════════════════════════════════════════════════════════════╗
║                      🦅 PROJECT OVERVIEW                            ║
╚══════════════════════════════════════════════════════════════════════╝

CrusaderBot is a non-custodial, high-performance trading bot for Polymarket.

[CORE IDENTITY]
📱 Telegram-first control surface
🌐 Polymarket-native trading workflow
🛡️ User retains control of funds
🔐 Proxy-wallet + CLOB-based execution
⚡ High-performance orchestration

[BOUNDARY]
✅ non-custodial
✅ execution orchestration
✅ user-controlled authorization

❌ not a custodial exchange
❌ not a generic AI bot shell
❌ not a paper-only product definition
```

### Premium view patch — Telegram Structure

```text
╔══════════════════════════════════════════════════════════════════════╗
║                    📱 TELEGRAM STRUCTURE MAP                        ║
╚══════════════════════════════════════════════════════════════════════╝

TELEGRAM
│
├── 🚪 Public Entry Surface
│   ├── /start
│   ├── /help
│   ├── /status
│   ├── /paper
│   ├── /about
│   ├── /risk_info
│   ├── /account
│   └── /link
│
├── 🎛️ Main Control Surface
│   ├── Dashboard
│   ├── Trading Controls
│   ├── Portfolio & Positions
│   ├── Analytics
│   └── Account & Authorization
│
├── 🔐 Execution-Capable Path
│   ├── Identity Resolved
│   ├── Account Linked
│   ├── Authorization Ready
│   ├── Policy / Risk Eligible
│   └── Execution Allowed
│
├── 🛠️ Operator Surface
└── 👑 Admin / Ops Surface
```

### Premium view patch — Command Surface

```text
╔══════════════════════════════════════════════════════════════════════╗
║                      ⌨️ COMMAND SURFACE MAP                         ║
╚══════════════════════════════════════════════════════════════════════╝

├── 🚪 Public-safe
│   ├── /start
│   ├── /help
│   ├── /status
│   ├── /paper
│   ├── /about
│   └── /risk_info
│
├── 👤 Account & Authorization
│   ├── /account
│   ├── /link
│   ├── /authorize
│   └── /permissions
│
├── ⚙️ Trading Controls
│   ├── /mode
│   ├── /control
│   ├── /strategy
│   ├── /risk
│   ├── /filters
│   └── /preferences
│
├── 📊 Portfolio & Positions
├── 📈 Analytics
├── 🛠️ Operator
└── 👑 Admin / Ops
```

```text
[EXECUTION GATE]
🔐 identity resolved
🔗 account linked
✅ authorization ready
🛡️ policy/risk eligible
▶️ execution allowed
```

### Premium view patch — User Flow

```text
╔══════════════════════════════════════════════════════════════════════╗
║                        👤 USER FLOW MAP                             ║
╚══════════════════════════════════════════════════════════════════════╝

0️⃣ Discovery
   ↓
1️⃣ Welcome & Introduction
   ↓
2️⃣ Legal & Risk
   ↓
3️⃣ Account Setup
   ↓
4️⃣ Security & Access
   ↓
5️⃣ Account Link & Authorization
   ↓
6️⃣ Trading Configuration
   ↓
7️⃣ Preview / Familiarization
   ↓
8️⃣ Readiness Check
   ↓
9️⃣ Activation
   ↓
🔟 Post-Activation Guidance
```

```text
[FLOW BRANCHES]
🆕 New user        → full onboarding path
⏸️ Incomplete user → resume exact saved stage
✅ Active user      → route to Main Control Surface
🚫 Restricted user  → support/help only
```

### Premium view patch — Control Dashboard Structure

```text
╔══════════════════════════════════════════════════════════════════════╗
║                    🦅 CRUSADERBOT DASHBOARD                         ║
╚══════════════════════════════════════════════════════════════════════╝

👤 @username                     🕒 Updated 12s ago

┌────────────────────────────────────────────────────────────────────┐
│ 🤖 BOT STATUS                                                     │
│ Status     : ACTIVE ✅                                            │
│ Mode       : Balanced 🟡                                          │
│ Uptime     : 2d 14h 23m                                           │
│ Health     : Healthy (98/100) 🟢                                  │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 💰 PORTFOLIO SNAPSHOT                                             │
│ Total Value : $1,250.50                                           │
│ Available   : $450.20                                             │
│ Deployed    : $800.30                                             │
│ Today P&L   : +$45.20 (+3.7%) 🟢                                  │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 📂 ACTIVE POSITIONS                                               │
│ Open        : 3 positions                                         │
│ Pending     : 1 order                                             │
│ Win Rate    : 68.5% (30d)                                         │
│ Exposure    : 42%                                                 │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🔍 TODAY ACTIVITY                                                 │
│ Signals     : 47 analyzed                                         │
│ Executed    : 5 trades                                            │
│ Rejected    : 42                                                  │
│ Last Action : 14:23 UTC                                           │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🏥 SYSTEM HEALTH                                                  │
│ Polymarket    : Online (42ms) 🟢                                  │
│ Falcon        : Online (128ms) 🟢                                 │
│ Authorization : Ready 🟢                                          │
│ Storage       : Healthy 🟢                                        │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🚨 ALERTS & NOTICES                                               │
│ 1 active alert                                                    │
│ • Daily loss approaching limit (80% used)                        │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[🤖 Control] [📊 Portfolio] [📂 Positions] [📈 Performance]
[⚙️ Strategy] [🚨 Alerts] [👤 Account] [🔄 Refresh]
```

### Wording correction rule

- prefer **Account** or **Authorization** over **Wallet** in primary Telegram surfaces
- keep non-custodial boundary visible in summary and health views
- every major view should surface a next action when state is blocked / paused / not ready

### Blueprint note

These premium view models are presentation references for the already fixed blueprint sections. They do not replace current repo truth, current runtime truth, or current merged command truth.



## Operator / Admin Flow ✅

Status: fixed for blueprint use\
Scope: target restricted operations flow, not current merged admin/runtime truth

### Role of operator / admin flow

Operator / Admin Flow defines how restricted operational users access monitoring, moderation, system safety, and controlled runtime actions inside CrusaderBot. It must preserve strict separation from the public-safe user surface. It must also avoid drifting into an exchange-style custodial operations console.

### Core principles

- restricted by role, not discoverable from public-safe help paths
- monitoring first, control second
- safety actions require explicit confirmation
- destructive actions require elevated auth
- operator controls are narrower than admin controls
- moderator paths focus on support/moderation, not runtime control
- no custodial fund-management posture in the primary ops surface

### Role hierarchy

- **User 👤** → end-user surface only
- **Moderator 🔰** → support and moderation only
- **Operator ⚙️** → technical/runtime control role
- **Admin 🛡️** → operations and system visibility role
- **Super Admin 👑** → owner-level authority and emergency controls

### Access model

#### Moderator 🔰

Allowed:

- moderation tools
- support workflows
- limited user/account inspection
- announcement assistance where permitted

Not allowed:

- runtime trade controls
- system-wide overrides
- owner-level config
- sensitive financial/custodial actions

#### Operator ⚙️

Allowed:

- runtime health views
- metrics and service inspection
- market/runtime controls
- controlled overrides and incident response actions

Not allowed:

- owner-level role management
- unrestricted system-wide authority
- exchange-style financial control center behavior

#### Admin 🛡️

Allowed:

- system visibility
- monitor/dashboard access
- moderation oversight
- reports/audit access
- approved operational safety controls

Not allowed:

- owner-only role transfer and deepest emergency authority

#### Super Admin 👑

Allowed:

- full authority over admin/operator configuration
- emergency stop / critical override controls
- owner-level system governance

### Flow stages

#### Stage A — Restricted Entry

Entry command examples:

- /admin
- /monitor
- /moderate
- /reports

System behavior:

- resolve identity
- verify role
- verify elevated auth when needed
- deny with safe message if unauthorized

#### Stage B — Role Verification

Possible outcomes:

- not authorized → access denied
- moderator verified → moderation branch
- operator verified → operator branch
- admin verified → admin branch
- super admin verified → full ops branch

#### Stage C — Main Restricted Dashboard

Show a role-appropriate dashboard with:

- current system state
- active alerts
- permitted actions only
- no leakage of higher-role actions

#### Stage D — Focused Branch Access

Role branches:

- Moderation / support branch
- Operator runtime branch
- Admin monitor branch
- Super admin emergency/config branch

#### Stage E — Confirmed Action Path

For any destructive or sensitive action:

- show reason/context
- show impact clearly
- require explicit confirmation
- require elevated auth when applicable
- log action for audit

#### Stage F — Audit & Return

After action or inspection:

- show result/status
- show next safe actions
- preserve audit trace
- return to role dashboard or related detail screen

### Operator branches

#### Operator Runtime Branch

Purpose: controlled runtime management.

Includes:

- runtime risk controls
- market controls
- metrics / health inspection
- controlled override actions
- incident triage tools

#### Operator Monitoring Branch

Purpose: runtime visibility.

Includes:

- service health
- processing backlog
- execution anomalies
- alert feed
- dependency readiness

### Admin branches

#### Admin Monitor Branch

Purpose: system-wide monitoring and visibility.

Includes:

- global dashboard
- alert overview
- user/account anomaly visibility
- service readiness overview
- report access

#### Admin Moderation Branch

Purpose: support and moderation workflows.

Includes:

- user search / account state
- restriction / flag review
- support case handling
- broadcast / notices where allowed

#### Super Admin Emergency Branch

Purpose: highest-impact safety controls.

Includes:

- emergency halt / kill-switch path
- role management
- critical configuration approval
- severe incident response

### Operator / admin treeview model

```text
OPERATOR / ADMIN FLOW
│
├── RESTRICTED ENTRY
│   ├── /admin
│   ├── /monitor
│   ├── /moderate
│   └── /reports
│
├── ROLE VERIFICATION
│   ├── ❌ Not Authorized → Safe denial
│   ├── 🔰 Moderator Verified → Moderation Branch
│   ├── ⚙️ Operator Verified → Operator Branch
│   ├── 🛡️ Admin Verified → Admin Branch
│   └── 👑 Super Admin Verified → Full Ops Branch
│
├── MAIN RESTRICTED DASHBOARD
│   ├── system state snapshot
│   ├── alert overview
│   ├── role-allowed actions only
│   └── audit-safe navigation
│
├── MODERATOR BRANCH
│   ├── support tools
│   ├── moderation tools
│   └── limited user/account inspection
│
├── OPERATOR BRANCH
│   ├── runtime controls
│   ├── market/runtime controls
│   ├── metrics / health
│   └── controlled overrides
│
├── ADMIN BRANCH
│   ├── monitor dashboard
│   ├── anomaly visibility
│   ├── reports / audit access
│   └── moderation oversight
│
├── SUPER ADMIN BRANCH
│   ├── emergency controls
│   ├── role management
│   ├── critical config approval
│   └── severe incident response
│
└── CONFIRMED ACTION PATH
    ├── context shown clearly
    ├── confirmation required
    ├── elevated auth if needed
    ├── audit log written
    └── result returned safely
```

### Premium restricted dashboard view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                     👑 ADMIN / OPS DASHBOARD                        ║
╚══════════════════════════════════════════════════════════════════════╝

👤 @operator_name                 🕒 Updated 10s ago
🔐 Role: Admin 🛡️                🚨 Active Alerts: 3

┌────────────────────────────────────────────────────────────────────┐
│ 🏥 SYSTEM STATUS                                                  │
│ Runtime     : Healthy ✅                                          │
│ Alerts      : 3 active ⚠️                                         │
│ Dependencies: Ready ✅                                            │
│ Mode        : Normal Operations                                   │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 📊 GLOBAL VISIBILITY                                               │
│ Active Users   : 1,250                                             │
│ Active Bots    : 987                                               │
│ Paused Bots    : 145                                               │
│ Blocked States : 12                                                │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🧠 RUNTIME / EXECUTION HEALTH                                      │
│ Queue Health  : Stable ✅                                          │
│ Signal Flow   : Healthy ✅                                         │
│ Risk Gates    : Healthy ✅                                         │
│ Execution Path: Online ✅                                          │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🚨 ALERTS & INCIDENTS                                              │
│ 3 active alerts                                                    │
│ • Daily loss threshold approached                                  │
│ • 2 users blocked by authorization readiness                       │
│ • 1 dependency latency spike                                       │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[📊 Monitor] [🔍 Reports] [🔰 Moderate] [⚙️ Runtime]
[🚨 Alerts] [📢 Broadcast] [🔄 Refresh] [🛑 Emergency]
```

### Easy-to-read role matrix

```text
ROLE          PRIMARY PURPOSE                 CAN CONTROL RUNTIME   CAN MODERATE   CAN EMERGENCY
User          end-user bot control           No                    No             No
Moderator     support / moderation           No                    Yes            No
Operator      runtime inspection/control     Yes (limited)         No             Limited
Admin         ops visibility + safety        Yes (approved scope)  Yes            Limited
Super Admin   owner-level authority          Yes                   Yes            Yes
```

### Restricted action rules

- any destructive action requires confirmation
- emergency actions require elevated auth
- role escalation must never happen through Telegram convenience alone
- unauthorized users must receive safe denial without leaking internals
- every restricted action must be audit-logged
- operator/admin screens must show only actions valid for that role

### What Operator / Admin Flow is not

- not a public-facing surface
- not a custodial financial back office
- not an exchange-style treasury console
- not a statement that all admin commands are currently merged
- not permission to expose restricted commands in public help flows

### Separation note

Operator / Admin Flow defines the intended restricted operations model for CrusaderBot. Current repo truth and current runtime/admin implementation must still be documented separately from this blueprint target.



## Portfolio / Positions Structure ✅

Status: fixed for blueprint use\
Scope: target portfolio and position model, not current merged runtime/storage truth

### Role of portfolio / positions structure

Portfolio / Positions Structure defines how CrusaderBot represents a user's economic footprint, active exposure, derived balances, and historical trade state. It must preserve non-custodial truth, deterministic P&L, and a clear distinction between display views and authoritative state. It must also keep Telegram readable and safe without turning the bot into a brokerage ledger terminal.

### Core principles

- source-of-truth separation
- portfolio as aggregate root
- position as first-class entity
- deterministic P&L
- immutable trade history
- Telegram is read-only by default for positions
- emergency close is a separate controlled flow
- display layer must never be treated as authoritative truth

### Core suggestions applied from reference review

- keep **Portfolio** as the top-level aggregate root for one user
- keep **Balance** as a computed projection, not a standalone mutable source of truth
- keep **Position** separate from **Order**, **Fill**, and **Trade**
- keep continuous reconciliation between on-chain and off-chain derived state
- keep position lifecycle explicit and visible
- keep realized vs unrealized P&L clearly separated
- keep Telegram position surfaces read-only except controlled emergency paths
- keep historical correction through compensating records, not deletion

### Domain hierarchy

#### Aggregate root

- **Portfolio** → one per user

#### Child / derived layers

- **Balance** → current liquid and encumbered fund projection
- **Positions** → active and historical economic commitments
- **Orders** → open / pending execution intents
- **Fills** → execution fragments tied to orders/positions
- **Trades** → immutable execution records / historical footprint
- **Ledger / Events** → audit and reconciliation evidence

### Entity model

#### 1. Portfolio

Purpose: top-level aggregate representing a user's total economic footprint.

Core identity:

- portfolio\_id
- user\_id
- wallet\_address
- created\_at

Core state:

- status
- base currency
- reconciliation status
- last reconciled timestamp

Derived aggregate metrics:

- total value
- available balance
- invested amount
- unrealized P&L
- realized P&L today
- realized P&L total
- open positions count
- pending orders count

#### 2. Balance

Purpose: point-in-time view of liquid and encumbered funds.

Important rule:

- balance is a projection from portfolio + orders + positions
- balance is not the primary mutable source of truth

Typical components:

- available funds
- pending deposit / pending withdrawal state if applicable in the broader system model
- locked in orders
- locked in positions
- on-chain balance snapshot
- drift amount

#### 3. Position

Purpose: economic commitment to a specific market outcome.

Identity:

- position\_id
- portfolio\_id
- market\_id
- outcome / side
- token\_id

Market context snapshot:

- market question
- category
- resolution timestamp
- condition id

State:

- opening / open / closing / closed / liquidated
- shares held
- average entry price
- current mark price
- cost basis
- current value

Position behavior:

- aggregates multiple fills
- tracks lifecycle explicitly
- acts as the accountable unit of exposure

#### 4. Order / Fill / Trade

Purpose: execution history and lifecycle evidence.

Rules:

- order ≠ fill ≠ trade ≠ position
- fills can accumulate into one position
- trades are immutable historical records
- corrections happen via compensating entries, not deletion

### Source-of-truth model

#### Authoritative truth

- on-chain state is authoritative for balances and final position ownership

#### Operational truth

- off-chain state is a derived, optimized runtime/display model

#### Reconciliation rule

- display and runtime views must reconcile against authoritative state
- drift must be detected and surfaced
- stale or drifted data must never be silently presented as final truth

### P&L model

- realized and unrealized P&L must be clearly separated
- fees must be accounted for explicitly
- calculation rules must be deterministic across all views
- summary views and detail views must agree on the same math

### Telegram surface model

#### Portfolio surface

Purpose: summary of economic footprint.

Shows:

- total value
- available balance
- deployed / invested amount
- unrealized P&L
- realized P&L summary
- reconciliation status

#### Positions surface

Purpose: current and historical exposure visibility.

Shows:

- open positions
- pending orders
- recently closed positions
- position state / side / entry / current value / P&L

#### Position detail surface

Purpose: drill-down into one selected market exposure.

Shows:

- market question
- side / outcome
- shares held
- entry price
- current price
- current value
- realized/unrealized P&L
- order/fill history summary
- resolution context

### Interaction rules

- users do not manually mutate positions through chat
- users inspect positions through Telegram
- the bot engine remains the primary mutator of position state
- emergency close is a separate controlled path
- destructive position-affecting actions require confirmation and elevated checks where appropriate

### Portfolio / positions treeview model

```text
PORTFOLIO / POSITIONS STRUCTURE
│
├── PORTFOLIO (Aggregate Root)
│   ├── identity
│   ├── state
│   ├── reconciliation status
│   └── derived aggregate metrics
│
├── BALANCE (Derived Projection)
│   ├── available funds
│   ├── pending state
│   ├── locked in orders
│   ├── locked in positions
│   ├── on-chain snapshot
│   └── drift amount
│
├── POSITIONS (Exposure List)
│   ├── Open Positions
│   ├── Closing Positions
│   ├── Closed Positions
│   └── Liquidated / exceptional states
│
├── POSITION DETAIL
│   ├── market context
│   ├── entry state
│   ├── mark/current state
│   ├── value / P&L state
│   └── lifecycle state
│
├── ORDERS
│   ├── pending orders
│   ├── active orders
│   ├── canceled orders
│   └── order history
│
├── FILLS
│   ├── partial fills
│   ├── complete fills
│   └── fill aggregation into position
│
├── TRADES
│   ├── immutable trade records
│   ├── correction via compensating entries
│   └── audit-safe history
│
└── RECONCILIATION / LEDGER
    ├── on-chain truth check
    ├── off-chain derived state
    ├── drift detection
    └── audit/event trail
```

### Premium portfolio summary view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                    📊 PORTFOLIO OVERVIEW                            ║
╚══════════════════════════════════════════════════════════════════════╝

👤 @username                     🕒 Updated 10s ago
🔐 Reconciliation: IN SYNC ✅

┌────────────────────────────────────────────────────────────────────┐
│ 💰 BALANCE SNAPSHOT                                               │
│ Total Value     : $1,250.50 USDC                                  │
│ Available       : $450.20                                         │
│ Deployed        : $800.30                                         │
│ Locked in Orders: $120.00                                         │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 📈 P&L SUMMARY                                                    │
│ Unrealized P&L : +$32.10                                          │
│ Realized Today : +$45.20                                          │
│ Realized Total : +$310.40                                         │
│ Fees           : -$8.50                                           │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 📂 EXPOSURE SUMMARY                                               │
│ Open Positions : 3                                                │
│ Pending Orders : 1                                                │
│ Net Exposure   : 42%                                              │
│ Largest Bucket : Politics                                         │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[📂 Positions] [🧾 Orders] [📈 Performance] [🔄 Refresh]
```

### Premium positions list view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                     📂 OPEN POSITIONS                               ║
╚══════════════════════════════════════════════════════════════════════╝

[POSITION 1]
🧠 Market      : Will BTC exceed $100k by Dec 31?
🎯 Side        : YES
📦 Shares      : 100
💵 Avg Entry   : 0.45
📍 Mark Price  : 0.52
💰 Current Val : $52.00
📈 Unrealized  : +$7.00 (+15.6%) 🟢
🕒 Resolves    : 2026-12-31

[POSITION 2]
🧠 Market      : Will candidate X win election Y?
🎯 Side        : NO
📦 Shares      : 80
💵 Avg Entry   : 0.38
📍 Mark Price  : 0.34
💰 Current Val : $27.20
📉 Unrealized  : -$3.20 (-10.5%) ⚠️
🕒 Resolves    : 2026-11-04

[ACTION BAR]
[🔍 Detail] [🧾 Orders] [📊 Portfolio] [🔄 Refresh]
```

### Premium position detail view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                     🔍 POSITION DETAIL                              ║
╚══════════════════════════════════════════════════════════════════════╝

🧠 Market       : Will BTC exceed $100k by Dec 31?
🎯 Side         : YES
🗂️ Category     : Crypto
🕒 Resolves     : 2026-12-31
🔖 Status       : OPEN ✅

┌────────────────────────────────────────────────────────────────────┐
│ 📦 POSITION STATE                                                 │
│ Shares Held    : 100                                              │
│ Avg Entry      : 0.45                                             │
│ Mark Price     : 0.52                                             │
│ Cost Basis     : $45.00                                           │
│ Current Value  : $52.00                                           │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 📈 P&L BREAKDOWN                                                  │
│ Unrealized P&L : +$7.00                                           │
│ Realized P&L   : $0.00                                            │
│ Fees           : -$0.40                                           │
│ Net P&L        : +$6.60                                           │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🧾 EXECUTION HISTORY                                              │
│ Orders        : 2                                                 │
│ Fills         : 3                                                 │
│ Last Fill     : 2026-04-20 09:14 UTC                              │
│ Lifecycle     : OPENING → OPEN                                    │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[📂 Back to Positions] [🧾 Orders] [📊 Portfolio] [🔄 Refresh]
```

### Easy-to-read entity relationship view

```text
PORTFOLIO (1 per user)
├── BALANCE   → derived state
├── POSITIONS → exposure list
│   └── POSITION
│       ├── ORDERS
│       ├── FILLS
│       └── TRADES
└── LEDGER / RECONCILIATION
```

### View rules

- portfolio view should summarize first, not overwhelm with raw history
- positions view should prioritize active exposure before historical detail
- position detail should explain state, not only list numbers
- balance and P&L figures must align with the same calculation model everywhere
- Telegram views remain read-oriented; mutation paths stay separate and controlled
- reconciliation status should be visible when relevant

### What Portfolio / Positions Structure is not

- not a custodial wallet ledger
- not a manual trading terminal
- not a raw exchange position blotter
- not a statement that every position field is already shipped in repo truth
- not permission for manual position mutation through public Telegram chat

### Separation note

Portfolio / Positions Structure defines the intended exposure and portfolio model for CrusaderBot. Current repo truth and current runtime/storage implementation must still be documented separately from this blueprint target.



## Analytics / Performance Structure ✅

Status: fixed for blueprint use\
Scope: target analytics and performance model, not current merged analytics/runtime truth

### Role of analytics / performance structure

Analytics / Performance Structure defines how CrusaderBot measures, explains, and presents outcomes, risk, activity quality, signal quality, and system health over time. It must prioritize truth over vanity, preserve reproducibility, and stay readable for Telegram users without hiding important downside information.

### Core principles

- truth over vanity
- attribution-driven
- comparable over time
- user-literate
- audit-ready
- deterministic P&L definitions
- display views must not silently diverge from source calculations

### Core suggestions applied from reference review

- keep analytics domain split into **Return**, **Risk**, **Activity**, **Signal Quality**, and **System Health**
- keep **Realized P&L**, **Unrealized P&L**, and **Total P&L** separate and explicit
- keep **ROI**, **TWR**, and **MWR** distinct because they answer different questions
- show drawdown and downside metrics prominently, not only wins
- make every displayed number reproducible and versionable
- use progressive disclosure so simple users see summary first while advanced users can drill down deeper
- keep fees, slippage, failed trades, and rejected signals inside the truth model

### Analytics domain hierarchy

#### 1. Return Metrics

Purpose: measure economic outcome across time windows.

Core metrics:

- Realized P&L
- Unrealized P&L
- Total P&L
- ROI
- TWR
- MWR / IRR
- Annualized Return

Derived metrics:

- best day / week / month
- worst day / week / month
- winning / losing streaks

#### 2. Risk Metrics

Purpose: show downside, stability, and exposure quality.

Core metrics:

- max drawdown
- current drawdown
- volatility
- Sharpe / risk-adjusted return
- VaR / CVaR where applicable
- exposure concentration
- category concentration
- policy-limit proximity

#### 3. Activity Metrics

Purpose: show how the system behaves operationally.

Core metrics:

- signals analyzed
- trades executed
- trades rejected
- trade velocity
- fill rate
- average hold time
- order completion quality

#### 4. Signal Quality Metrics

Purpose: measure whether the decision layer is good, not only whether P&L happened.

Core metrics:

- confidence vs outcome
- hit rate
- edge realization quality
- Falcon contribution / attribution
- false positive / false negative profile
- execution quality vs signal quality separation

#### 5. System Health Metrics

Purpose: show whether the runtime environment is healthy enough to trust the numbers and flow.

Core metrics:

- latency
- uptime
- dependency health
- reconciliation freshness
- error rate
- alert frequency
- data staleness / lag

### Metric definition model

#### Realized P&L

Definition:

- sum of exit proceeds minus cost basis minus fees for closed positions

Use:

- historical performance windows
- today / 7D / 30D / 90D / YTD / all-time summaries

#### Unrealized P&L

Definition:

- mark-to-market gain/loss on open positions

Use:

- current open exposure understanding
- must carry liquidity/slippage caveat

#### Total P&L

Definition:

- realized + unrealized

Use:

- headline summary number

#### ROI

Definition:

- P&L as a percentage of invested capital / deposits

Use:

- simple user-facing performance interpretation

#### TWR

Definition:

- time-weighted return independent of deposit/withdraw timing

Use:

- fair comparison across users and periods

#### MWR / IRR

Definition:

- money-weighted return based on actual timing of user cash flows

Use:

- user-specific return experience

### Time windows

Recommended windows:

- Today
- 7D
- 30D
- 90D
- YTD
- All-time

Rules:

- not every metric must be meaningful on every window
- annualized metrics should be suppressed or caveated when data history is too short
- all windows must use clearly frozen definitions

### Attribution model

Analytics should separate at least these sources:

- signal quality
- execution quality
- market drift / noise
- fees / slippage
- risk gate impact
- Falcon / intelligence contribution where measurable

### Telegram analytics surface model

#### Analytics summary surface

Purpose: show user-literate performance overview first.

Shows:

- headline total P&L
- realized vs unrealized split
- ROI / TWR summary
- drawdown summary
- recent activity summary
- alert or caveat note if data is stale or drifted

#### Performance detail surface

Purpose: focused return and risk view.

Shows:

- realized P&L by window
- unrealized P&L
- total P&L
- ROI / TWR / MWR
- drawdown / Sharpe / volatility

#### Signal quality surface

Purpose: determine whether the bot is making good decisions.

Shows:

- confidence vs outcome
- hit rate
- executed vs rejected signal profile
- edge realization quality
- attribution notes

#### System health analytics surface

Purpose: determine whether the analytics and runtime can be trusted.

Shows:

- dependency health
- freshness / lag
- reconciliation status
- errors / alert counts
- uptime / latency summary

### Progressive disclosure model

#### Level 1 — Beginner view

Shows:

- total P&L
- realized today
- unrealized now
- win rate
- current drawdown

#### Level 2 — Intermediate view

Shows:

- ROI
- category performance
- activity counts
- average hold time
- rejected-signal reasons

#### Level 3 — Advanced view

Shows:

- TWR / MWR
- Sharpe
- VaR / CVaR if enabled
- confidence calibration
- execution attribution
- methodology / calculation notes

### Analytics / performance treeview model

```text
ANALYTICS / PERFORMANCE STRUCTURE
│
├── RETURN METRICS
│   ├── Realized P&L
│   ├── Unrealized P&L
│   ├── Total P&L
│   ├── ROI
│   ├── TWR
│   ├── MWR / IRR
│   └── Annualized Return
│
├── RISK METRICS
│   ├── Max Drawdown
│   ├── Current Drawdown
│   ├── Volatility
│   ├── Sharpe / Risk-adjusted Return
│   ├── VaR / CVaR
│   └── Exposure Concentration
│
├── ACTIVITY METRICS
│   ├── Signals Analyzed
│   ├── Trades Executed
│   ├── Trades Rejected
│   ├── Trade Velocity
│   ├── Fill Rate
│   └── Average Hold Time
│
├── SIGNAL QUALITY
│   ├── Confidence vs Outcome
│   ├── Hit Rate
│   ├── Edge Realization
│   ├── Rejection Profile
│   └── Falcon Contribution
│
└── SYSTEM HEALTH
    ├── Latency
    ├── Uptime
    ├── Dependency Health
    ├── Reconciliation Freshness
    ├── Error Rate
    └── Alert Frequency
```

### Premium analytics summary view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                  📈 ANALYTICS / PERFORMANCE                         ║
╚══════════════════════════════════════════════════════════════════════╝

👤 @username                     🕒 Updated 15s ago
🧾 Metrics Version: v1           🔐 Reproducible: Yes

┌────────────────────────────────────────────────────────────────────┐
│ 💰 RETURN SUMMARY                                                  │
│ Realized P&L   : +$45.20                                           │
│ Unrealized P&L : +$32.10                                           │
│ Total P&L      : +$77.30 🟢                                        │
│ ROI            : +6.1%                                             │
│ TWR            : +4.8%                                             │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🛡️ RISK SUMMARY                                                   │
│ Max Drawdown   : -3.2%                                             │
│ Current DD     : -0.8%                                             │
│ Volatility     : Moderate                                          │
│ Sharpe         : 1.24                                              │
│ Limit Proximity: Healthy ✅                                        │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🔍 ACTIVITY SUMMARY                                                │
│ Signals Analyzed : 47                                              │
│ Executed Trades  : 5                                               │
│ Rejected Signals : 42                                              │
│ Avg Hold Time    : 14h                                             │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🧠 SIGNAL QUALITY                                                  │
│ Hit Rate        : 68.5%                                            │
│ Confidence Fit  : Stable ✅                                        │
│ Edge Realization: Good                                             │
│ Falcon Impact   : Positive                                         │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🏥 SYSTEM HEALTH                                                   │
│ Data Freshness   : 12s                                             │
│ Dependencies     : Healthy ✅                                      │
│ Reconciliation   : In Sync ✅                                      │
│ Error Rate       : Low                                             │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[💰 Returns] [🛡️ Risk] [🔍 Activity] [🧠 Signals]
[🏥 Health] [📂 Portfolio] [🔄 Refresh]
```

### Premium performance detail view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                    💰 RETURN DETAIL                                 ║
╚══════════════════════════════════════════════════════════════════════╝

[WINDOW]
Today | 7D | 30D | 90D | YTD | All-time

┌────────────────────────────────────────────────────────────────────┐
│ Realized P&L    : +$45.20                                          │
│ Unrealized P&L  : +$32.10                                          │
│ Total P&L       : +$77.30                                          │
│ Fees            : -$8.50                                           │
│ Slippage Impact : -$2.10                                           │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ ROI             : +6.1%                                            │
│ TWR             : +4.8%                                            │
│ MWR / IRR       : +5.3%                                            │
│ Annualized      : +18.4%                                           │
└────────────────────────────────────────────────────────────────────┘

[NOTES]
- Unrealized values are mark-to-market estimates
- Actual close value may differ due to liquidity/slippage
```

### Premium signal quality view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                    🧠 SIGNAL QUALITY                                ║
╚══════════════════════════════════════════════════════════════════════╝

┌────────────────────────────────────────────────────────────────────┐
│ Hit Rate          : 68.5%                                          │
│ Confidence vs Win : Well-calibrated                                │
│ Rejected Signals  : 42                                             │
│ False Positives   : 4                                              │
│ False Negatives   : 7                                              │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ Edge Realization   : Strong                                        │
│ Execution Quality  : Stable                                        │
│ Falcon Contribution: Positive                                      │
│ Drift vs Market    : Within expected range                         │
└────────────────────────────────────────────────────────────────────┘
```

### Easy-to-read analytics level view

```text
LEVEL 1 — SIMPLE
- Total P&L
- Realized / Unrealized
- Win Rate
- Current Drawdown

LEVEL 2 — INTERMEDIATE
- ROI
- Category Performance
- Activity Counts
- Average Hold Time
- Rejection Reasons

LEVEL 3 — ADVANCED
- TWR / MWR
- Sharpe
- VaR / CVaR
- Confidence Calibration
- Attribution / Methodology
```

### Display rules

- downside metrics must not be hidden below gains
- stale or drifted data must be labeled clearly
- every headline number must be reproducible
- methodology/version note should be available for advanced users
- summary screens should stay simple; complexity appears only on drill-down
- analytics should separate skill, execution quality, and market noise where possible

### What Analytics / Performance Structure is not

- not a vanity leaderboard
- not a marketing-only stats page
- not a promise that all advanced metrics are already shipped
- not permission to hide drawdowns or fees
- not a substitute for portfolio source-of-truth reconciliation

### Separation note

Analytics / Performance Structure defines the intended measurement and explanation model for CrusaderBot. Current repo truth and current analytics implementation must still be documented separately from this blueprint target.



## Signal / Intelligence Structure ✅

Status: fixed for blueprint use\
Scope: target signal and intelligence model, not current merged runtime/model truth

### Role of signal / intelligence structure

Signal / Intelligence Structure defines how CrusaderBot ingests market context, builds intelligence, produces signal objects, and passes them downstream without collapsing the boundary between intelligence and execution. It must stay read-side by design, evidence-based, auditable, and time-aware. It must also preserve the rule that a signal is a proposal, not an instruction.

### Core principles

- signal ≠ trade
- evidence-based confidence
- Falcon as primary, not sole
- edge over prediction
- decision auditability
- time-aware intelligence
- read-side intelligence must stay separate from write-side execution

### Core suggestions applied from reference review

- keep a hard boundary between **signal production** and **trade execution**
- keep **Falcon** as primary intelligence source, but never as a single point of truth or failure
- make **edge detection** the core objective, not generic prediction for its own sake
- require every signal to carry **confidence**, **evidence context**, and **TTL**
- keep the pipeline replayable for audit and forensics
- keep input quality requirements explicit, especially for Polymarket market state
- keep downstream consumers separate: trading, risk, analytics, and alerts each consume intelligence differently

### Intelligence domain hierarchy

#### 1. Input Layer

Purpose: collect raw inputs needed to build market intelligence.

Core sources:

- Polymarket market data
- Falcon API
- news/context feeds
- social/context feeds
- historical market and outcome data

#### 2. Processing Pipeline

Purpose: transform raw inputs into scored, ranked, and filtered intelligence.

Pipeline stages:

- collect
- normalize
- enrich
- score
- rank
- filter
- emit

#### 3. Output Layer

Purpose: emit reusable signal objects with audit-safe reasoning.

Core outputs:

- signal object
- confidence score
- edge / EV summary
- TTL / freshness state
- evidence bundle
- audit trail

#### 4. Downstream Consumers

Purpose: consume intelligence without confusing it for execution authority.

Consumers:

- trading engine
- risk engine
- analytics
- alert system

### Input source model

#### Source 1 — Polymarket market data

Purpose: current market state and microstructure.

Core fields:

- market metadata
- current yes/no prices
- last trade / mid price / spread
- liquidity state
- volume state
- short historical series

Quality rules:

- price freshness must stay tight
- volume freshness must be bounded
- prices must stay in valid probability range
- yes/no consistency must be checked
- critical fields cannot be missing

#### Source 2 — Falcon intelligence

Purpose: primary AI-derived probability and context layer.

Rules:

- on-demand per market
- short-lived cache
- timeout-bounded
- retry with backoff
- fallback path required

Expected outputs:

- predicted probability
- confidence / confidence band
- supporting rationale or evidence summary
- versioned response contract

#### Source 3 — Contextual enrichment

Purpose: strengthen or weaken a signal with surrounding evidence.

Examples:

- news / narrative context
- social momentum or anomaly context
- historical regime comparisons
- market-category or event-type priors

### Signal object model

A signal should carry at minimum:

- market identity
- question / category context
- market-implied probability
- model probability
- edge
- expected value summary
- confidence score
- evidence summary
- TTL / emitted\_at / expires\_at
- reason for rejection or weakness when applicable
- version / provenance metadata

### Processing model

#### Collect

Pull market state, call Falcon, and retrieve contextual data.

#### Normalize

Convert inputs into a common schema with consistent timestamps and units.

#### Enrich

Add category priors, market microstructure context, time-to-resolution context, and supporting evidence annotations.

#### Score

Compute:

- model probability
- market implied probability
- edge
- expected value
- confidence
- signal strength

#### Rank

Order candidate signals by attractiveness after confidence and edge adjustments.

#### Filter

Reject or downgrade signals that are:

- stale
- low-confidence
- weakly evidenced
- below minimum edge
- below liquidity/safety thresholds
- too close to resolution without sufficient safety margin

#### Emit

Produce signal objects ready for downstream use, with audit-safe metadata attached.

### Signal decision rules

- signal is a proposal, not a trade instruction
- significant edge is required before downstream action is even considered
- edge must exceed fees, slippage, and safety margin
- stale signals must never be executed
- single-source signals should be marked weak or rejected
- near-resolution markets should be weighted conservatively
- rejection reasons must be logged explicitly

### Confidence model

Confidence should be based on:

- strength of Falcon output
- agreement or disagreement with market microstructure
- breadth of supporting evidence
- freshness of underlying data
- time to resolution
- signal stability across recent updates

Confidence should not be:

- purely opaque
- purely narrative
- purely single-source

### Edge model

The intelligence goal is mispricing detection.

Core view:

- market implied probability = p\_market
- model probability = p\_model
- edge = p\_model - p\_market

Meaning:

- positive edge alone is not enough
- the edge must still survive fees, slippage, risk policy, and safety margin before downstream action is justified

### Time-awareness model

Every signal should carry:

- emitted timestamp
- expiry timestamp / TTL
- last refresh timestamp
- time-to-resolution awareness

Rules:

- stale signals expire automatically
- near-resolution signals are stricter
- low-freshness inputs degrade or invalidate confidence

### Downstream consumer model

#### Trading engine

Uses signals as candidates, not orders.

#### Risk engine

Checks whether candidate signals are even eligible for exposure.

#### Analytics

Measures hit rate, calibration, attribution, and realized quality of signals over time.

#### Alert system

Notifies users/operators about high-signal events, degraded signal quality, or rejected opportunities where helpful.

### Signal / intelligence treeview model

```text
SIGNAL / INTELLIGENCE STRUCTURE
│
├── INPUT LAYER
│   ├── Polymarket market data
│   ├── Falcon API
│   ├── News/context feeds
│   ├── Social/context feeds
│   └── Historical data
│
├── PROCESSING PIPELINE
│   ├── Collect
│   ├── Normalize
│   ├── Enrich
│   ├── Score
│   ├── Rank
│   ├── Filter
│   └── Emit
│
├── OUTPUT LAYER
│   ├── Signal object
│   ├── Confidence score
│   ├── Edge / EV summary
│   ├── TTL / freshness state
│   ├── Evidence bundle
│   └── Audit trail
│
└── DOWNSTREAM CONSUMERS
    ├── Trading engine
    ├── Risk engine
    ├── Analytics
    └── Alert system
```

### Premium signal overview view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                   🧠 SIGNAL / INTELLIGENCE                          ║
╚══════════════════════════════════════════════════════════════════════╝

🦅 Primary Intel : Falcon
🕒 Freshness     : 18s
🔐 Mode          : Read-side only

┌────────────────────────────────────────────────────────────────────┐
│ 🌐 INPUT STATUS                                                   │
│ Market Data    : Healthy ✅                                       │
│ Falcon API     : Available ✅                                     │
│ News Context   : Partial ⚠️                                       │
│ Social Context : Available ✅                                     │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🎯 SIGNAL STATE                                                   │
│ p_market      : 0.41                                              │
│ p_model       : 0.52                                              │
│ Edge          : +0.11                                             │
│ EV Summary    : Positive                                          │
│ Confidence    : Strong ✅                                          │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🛡️ SAFETY / FILTER STATUS                                         │
│ TTL            : Valid                                             │
│ Freshness      : Valid                                             │
│ Evidence Breadth: Multi-source ✅                                  │
│ Resolution Risk: Acceptable                                        │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 📝 AUDIT TRAIL                                                    │
│ Signal ID      : SIG-2026-04-22-001                               │
│ Version        : intel-v1                                          │
│ Emitted At     : 2026-04-22 15:24 UTC                              │
│ Rejection Cause: None                                              │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[🧠 Detail] [📊 Analytics] [🛡️ Risk View] [🔄 Refresh]
```

### Premium signal detail view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                      🔍 SIGNAL DETAIL                              ║
╚══════════════════════════════════════════════════════════════════════╝

🧠 Market        : Will BTC exceed $100k by Dec 31?
🗂️ Category      : Crypto
🕒 Resolves      : 2026-12-31
🔖 Signal Status : EMITTED ✅

┌────────────────────────────────────────────────────────────────────┐
│ 🎯 PROBABILITY MODEL                                              │
│ p_market      : 0.41                                              │
│ p_model       : 0.52                                              │
│ Edge          : +0.11                                             │
│ EV Summary    : Positive                                          │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🧾 EVIDENCE SUMMARY                                                │
│ Falcon Output  : Strong                                           │
│ Market Context : Supportive                                       │
│ Social Context : Mild positive                                    │
│ Data Freshness : 18s                                              │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🛡️ FILTER / TTL STATE                                             │
│ TTL            : 5m                                               │
│ Expires At     : 2026-04-22 15:29 UTC                              │
│ Resolution Risk: Low                                              │
│ Weakness Flag  : None                                             │
└────────────────────────────────────────────────────────────────────┘

[NOTES]
- This signal is a proposal, not an execution instruction
- Downstream trading and risk layers decide whether it can act
```

### Easy-to-read intelligence level view

```text
LEVEL 1 — SIMPLE
- Current signal strength
- Confidence
- Freshness
- Edge summary

LEVEL 2 — INTERMEDIATE
- p_market vs p_model
- EV summary
- evidence breadth
- TTL / resolution sensitivity

LEVEL 3 — ADVANCED
- source attribution
- calibration notes
- rejection causes
- versioned audit metadata
- replayable input bundle
```

### Display rules

- signal screens must not imply automatic execution authority
- confidence must be explained, not shown as magic
- stale or degraded inputs must be labeled clearly
- edge and confidence must appear together, not separately misleading
- evidence breadth should be visible when relevant
- reasoning should stay concise in summary view and expand only on drill-down

### What Signal / Intelligence Structure is not

- not a manual trade ticket
- not a promise that Falcon alone decides trades
- not a statement that every input source is required at all times
- not permission to blur read-side intelligence with write-side execution
- not a claim that all advanced attribution logic is already shipped

### Separation note

Signal / Intelligence Structure defines the intended intelligence model for CrusaderBot. Current repo truth and current runtime/model implementation must still be documented separately from this blueprint target.



## Risk Engine Structure ✅

Status: fixed for blueprint use\
Scope: target risk-engine model, not current merged runtime/risk truth

### Role of risk engine structure

Risk Engine Structure defines how CrusaderBot evaluates whether a candidate action is safe enough to proceed. It must remain non-negotiable, deterministic, fail-closed, and independently authoritative over trade proposals. It must also protect the system across position, portfolio, loss, velocity, concentration, liquidity, time, quality, system, and operational risk dimensions.

### Core principles

- risk engine is non-negotiable
- defense in depth
- fail-closed by default
- deterministic and auditable
- circuit-breaker mindset
- user-configurable within hard bounds
- no public/user bypass path
- override, if ever allowed, must remain heavily restricted

### Core suggestions applied from reference review

- keep risk as a layered engine, not a single threshold check
- keep separate dimensions for position, portfolio, loss, velocity, concentration, liquidity, time, quality, system, and operational risk
- keep distinct engine zones: limits registry, gates, circuit breakers, exposure controller, and monitors/audit
- keep missing data, stale data, or unknown state as automatic rejection conditions
- keep every rejection and every limit change versioned and logged
- keep circuit-breaker responses graduated: warn → throttle → halt
- allow user configuration only inside platform-enforced ceilings
- make loosening safety slower than tightening safety

### Risk dimensions taxonomy

#### 1. Position Risk

Controls:

- max capital per single position
- max shares per market
- max concentration in one outcome

#### 2. Portfolio Risk

Controls:

- total exposure cap
- max open positions count
- minimum available capital reserve

#### 3. Loss Risk

Controls:

- per-trade loss tolerance
- daily loss limit
- max drawdown tolerance

#### 4. Velocity Risk

Controls:

- max trades per hour
- max trades per day
- minimum trade interval

#### 5. Concentration Risk

Controls:

- max exposure per category
- max exposure per event
- max correlation cluster weight

#### 6. Liquidity Risk

Controls:

- minimum market liquidity threshold
- max position as percentage of market depth
- slippage tolerance

#### 7. Time Risk

Controls:

- minimum time to resolution
- maximum time to resolution where applicable
- near-resolution throttling / rejection

#### 8. Quality Risk

Controls:

- minimum signal confidence
- minimum edge threshold
- maximum signal age

#### 9. System Risk

Controls:

- API error rate tolerance
- data staleness threshold
- reconciliation drift threshold

#### 10. Operational Risk

Controls:

- wallet / balance sanity
- network health
- execution-environment sanity
- external dependency safety state

### Risk engine domain map

#### 1. Limits Registry

Purpose: authoritative source of all active risk ceilings, floors, and policy versions.

Includes:

- per-trade limits
- per-day limits
- portfolio/global limits
- user-configured limits within bounds
- platform hard ceilings
- version metadata

#### 2. Gates

Purpose: explicit go/no-go checks at multiple stages.

Includes:

- pre-trade gate
- post-signal gate
- execution gate

#### 3. Circuit Breakers

Purpose: automatically reduce or stop activity under abnormal conditions.

Includes:

- daily loss breaker
- drawdown breaker
- error-rate breaker
- stale-data breaker
- dependency-health breaker

#### 4. Exposure Controller

Purpose: keep position sizing and portfolio concentration inside acceptable bounds.

Includes:

- position sizing controller
- concentration controller
- correlation controller
- reserve-capital controller

#### 5. Monitors & Audit

Purpose: make risk state visible and replayable.

Includes:

- real-time risk dashboard
- alert stream
- rejection log
- limit-change audit trail
- breaker state history

### Decision pipeline

#### Step 1 — Candidate intake

Receive candidate action from downstream of signal/intelligence.

#### Step 2 — Limit registry resolution

Load effective user + platform risk policy set and current version.

#### Step 3 — Gate checks

Run staged checks across:

- quality
- time
- liquidity
- position size
- portfolio exposure
- velocity
- system health
- operational sanity

#### Step 4 — Exposure calculation

Compute current and post-trade exposure state:

- single-position impact
- category/event concentration
- cluster correlation
- reserve-capital impact

#### Step 5 — Circuit-breaker evaluation

Check whether warning, throttle, or halt conditions are already active or should be triggered.

#### Step 6 — Decision output

Return one of:

- APPROVE
- REJECT
- THROTTLE
- HALT\_REQUIRED

#### Step 7 — Audit write

Persist decision, rule path, effective limits version, and rejection cause.

### Fail-closed rules

- missing data = no trade
- stale limits = no trade
- unknown state = unsafe state
- unresolved reconciliation drift = reject or halt depending on severity
- broken dependency health = throttle or halt
- circuit breaker active = block affected actions until reset conditions are met

### Circuit-breaker model

#### Warning state

Use when risk is rising but activity can continue carefully.

Examples:

- loss nearing daily limit
- elevated error rate
- mild data staleness

#### Throttle state

Use when activity must be slowed or narrowed.

Examples:

- repeated near-limit behavior
- degraded liquidity environment
- rising anomaly density

#### Halt state

Use when continued trading is unsafe.

Examples:

- daily loss breach
- max drawdown breach
- severe data staleness
- severe reconciliation drift
- execution environment instability

Rules:

- halt requires manual/controlled reset
- cooldown period may apply before restart
- all breaker trips must be logged and visible

### User-configurable limits model

Users may configure selected limits, but only within platform-imposed ceilings.

Rules:

- users may tighten limits freely
- users may not disable hard safety limits
- tightening applies immediately
- loosening may require cooldown / confirmation / elevated checks
- platform ceilings always win over user preferences

### Risk state outputs

Risk engine should expose at minimum:

- current risk mode
- active warnings
- active throttles
- active breaker states
- current exposure summary
- limit proximity summary
- last rejection reason
- effective risk-policy version

### Telegram risk surface model

#### Risk summary surface

Purpose: show high-level safety state.

Shows:

- risk mode
- daily loss usage
- drawdown state
- exposure usage
- active warnings / breakers
- current policy version or mode label

#### Risk detail surface

Purpose: show why the engine would approve or reject candidates.

Shows:

- dimension-by-dimension status
- current thresholds / proximity
- last rejection causes
- throttle / halt reasons
- configuration bounds

#### Risk controls surface

Purpose: allow safe user/operator tightening or review of limits.

Shows:

- user-settable limits
- platform ceilings
- pending cooldowns
- confirmation requirements for sensitive changes

### Risk engine treeview model

```text
RISK ENGINE STRUCTURE
│
├── LIMITS REGISTRY
│   ├── per-trade limits
│   ├── per-day limits
│   ├── portfolio/global limits
│   ├── user-configured limits
│   ├── platform ceilings
│   └── version metadata
│
├── GATES
│   ├── pre-trade gate
│   ├── post-signal gate
│   └── execution gate
│
├── CIRCUIT BREAKERS
│   ├── daily loss breaker
│   ├── drawdown breaker
│   ├── error-rate breaker
│   ├── stale-data breaker
│   └── dependency-health breaker
│
├── EXPOSURE CONTROLLER
│   ├── position sizing
│   ├── concentration control
│   ├── correlation control
│   └── reserve-capital control
│
└── MONITORS & AUDIT
    ├── risk dashboard
    ├── alert stream
    ├── rejection log
    ├── limit change audit
    └── breaker state history
```

### Premium risk overview view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                        🛡️ RISK ENGINE                               ║
╚══════════════════════════════════════════════════════════════════════╝

🕒 Updated 10s ago               🔐 Policy Version: risk-v3
⚙️ Mode: NORMAL                  🚨 Active Breakers: 0

┌────────────────────────────────────────────────────────────────────┐
│ 📏 LIMIT USAGE                                                     │
│ Position Cap     : 42% used                                        │
│ Portfolio Cap    : 58% used                                        │
│ Daily Loss Limit : 24% used                                        │
│ Velocity Limit   : 12% used                                        │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🧭 GATE STATUS                                                     │
│ Quality Gate    : Pass ✅                                          │
│ Liquidity Gate  : Pass ✅                                          │
│ Time Gate       : Pass ✅                                          │
│ System Gate     : Pass ✅                                          │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 📊 EXPOSURE CONTROL                                                │
│ Open Positions  : 3                                                │
│ Category Risk   : Balanced                                         │
│ Correlation Risk: Moderate                                         │
│ Reserve Capital : Healthy ✅                                       │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🚨 BREAKER STATE                                                   │
│ Warning Level   : None                                             │
│ Throttle State  : Inactive                                         │
│ Halt State      : Inactive                                         │
│ Last Rejection  : None                                             │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[🛡️ Detail] [📊 Exposure] [⚙️ Limits] [🔄 Refresh]
```

### Premium risk detail view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                        🔍 RISK DETAIL                               ║
╚══════════════════════════════════════════════════════════════════════╝

[DIMENSIONS]
Position Risk      : Pass ✅
Portfolio Risk     : Pass ✅
Loss Risk          : Pass ✅
Velocity Risk      : Pass ✅
Concentration Risk : Warning ⚠️
Liquidity Risk     : Pass ✅
Time Risk          : Pass ✅
Quality Risk       : Pass ✅
System Risk        : Pass ✅
Operational Risk   : Pass ✅

[LAST REJECTION]
Reason        : None
Last Event    : 2026-04-22 14:50 UTC

[BREAKER POLICY]
Warn          : Near-threshold behavior
Throttle      : Repeated degradation
Halt          : Unsafe system or hard breach
```

### Easy-to-read risk control levels

```text
LEVEL 1 — SIMPLE
- risk mode
- daily loss usage
- exposure usage
- active warnings

LEVEL 2 — INTERMEDIATE
- per-dimension gate status
- concentration / liquidity / time checks
- last rejection reasons
- breaker proximity

LEVEL 3 — ADVANCED
- policy versioning
- platform ceilings vs user limits
- breaker history
- audit/replay trail
- limit-change methodology
```

### Display rules

- risk state must be visible before aggressive control paths
- rejection reasons should be concise in summary and detailed on drill-down
- warning/throttle/halt states must be visually distinct
- user-visible controls must not imply that hard safety limits can be disabled
- limit usage should show proximity, not only raw thresholds
- stale or unknown risk state must be labeled unsafe

### What Risk Engine Structure is not

- not an optional advisory layer
- not a user-bypassable settings panel
- not a promise that all breaker types are currently shipped
- not permission to hide hard rejections behind vague messaging
- not a substitute for execution-side safety checks

### Separation note

Risk Engine Structure defines the intended safety and control model for CrusaderBot. Current repo truth and current runtime/risk implementation must still be documented separately from this blueprint target.



## Execution Engine Structure ✅

Status: fixed for blueprint use  
Scope: target execution-engine model, not current merged runtime/execution truth

### Role of execution engine structure
Execution Engine Structure defines the last-mile path from an already-approved trade intent into venue submission, fill tracking, settlement awareness, and reconciliation.
It must never decide whether to trade.
It only decides how to execute safely, observably, and idempotently.

### Core principles
- execution is the last mile
- idempotency is mandatory
- atomicity at the boundary
- observable at every hop
- settlement is separate from submission
- execution quality is measured
- no execution path may bypass prior risk approval

### Core suggestions applied from reference review
- keep execution downstream of signal and risk only
- keep intake, planning, pre-submit validation, submission, tracking, settlement, and reconciliation as distinct stages
- keep every order keyed by deterministic idempotency key
- keep partial fills explicit, never implicit
- keep venue submission, fill lifecycle, and settlement as different phases with different timeout/retry policies
- keep downstream emission to portfolio, notifications, analytics, and audit

### Execution engine hierarchy

#### 1. Intake Queue
Purpose: accept approved trade intents from the risk engine.

Includes:
- approved trade intent intake
- prioritization
- deduplication
- idempotency enforcement

#### 2. Planner
Purpose: translate approved intent into concrete order plan.

Includes:
- pricing model
- size translation
- order type choice
- split strategy
- venue routing choice

#### 3. Submitter
Purpose: perform the actual venue call safely.

Includes:
- venue adapter
- signer/auth bridge
- retry logic
- submission tracing

#### 4. Tracker
Purpose: monitor lifecycle until terminal order state.

Includes:
- state machine
- fill tracking
- timeout handling
- cancellation / expiry handling

#### 5. Settler & Reconciler
Purpose: confirm settlement-related state and align off-chain views with authoritative truth.

Includes:
- settlement confirmation awareness
- ledger update
- reconciliation check
- drift alert generation

#### 6. Downstream Emitters
Purpose: publish execution outcomes to system consumers.

Includes:
- portfolio updates
- notification events
- analytics events
- audit log writes

### Execution pipeline — 7 stages

#### Stage 1 — Intake
Input: approved trade intent from risk engine.
Output: enqueued execution task.

#### Stage 2 — Planning
Input: execution task.
Output: concrete order plan.

#### Stage 3 — Pre-submit validation
Input: order plan.
Output: validated order plan.

Checks include:
- stale deadline check
- idempotency check
- venue sanity
- auth/session readiness
- final boundary validation

#### Stage 4 — Submission
Input: validated order plan.
Output: venue acknowledgment / submitted order.

#### Stage 5 — Tracking
Input: submitted order.
Output: terminal order state.

Terminal states may include:
- FILLED
- CANCELLED
- EXPIRED
- REJECTED
- PARTIALLY_FILLED then terminal follow-up

#### Stage 6 — Settlement
Input: terminal order state.
Output: settled trade record or settlement-aware completion state.

#### Stage 7 — Reconciliation
Input: settlement-aware completion state.
Output: reconciled trade or drift alert.

### Intake contract model
An approved trade intent should carry at minimum:
- intent identity
- originating signal reference
- user / portfolio scope
- deterministic idempotency key
- action type
- market / outcome / side
- target size or amount
- acceptable price bounds
- slippage tolerance
- time in force
- deadline
- partial-fill policy
- urgency / priority hints

### Execution decision rules
- execution engine never decides whether to trade
- no intake without prior risk approval
- retry must never create double execution
- unknown submission state must be reconciled, not assumed
- partial fills must be reflected explicitly in state
- internal transitions must be transactional from our side
- every external call must carry trace and latency visibility

### Execution quality model
Track at minimum:
- slippage per order
- fill rate per strategy
- latency per venue call
- rejection rate
- timeout rate
- fee and cost impact

### Failure handling model
Examples:
- duplicate intent → reject safely
- submission timeout → resolve via idempotent retry / status query
- partial fill stall → track, timeout, or cancel per policy
- reconciliation drift → alert and hold affected state as unresolved
- excessive order failures → breaker/escalation path

### Execution engine treeview model

```text
EXECUTION ENGINE STRUCTURE
│
├── INTAKE QUEUE
│   ├── approved intents
│   ├── prioritization
│   ├── dedup
│   └── idempotency
│
├── PLANNER
│   ├── pricing model
│   ├── size translation
│   ├── order type
│   ├── split strategy
│   └── routing
│
├── PRE-SUBMIT VALIDATION
│   ├── deadline check
│   ├── auth/session readiness
│   ├── venue sanity
│   └── final boundary checks
│
├── SUBMITTER
│   ├── venue adapter
│   ├── signer/auth bridge
│   ├── retry logic
│   └── submission trace
│
├── TRACKER
│   ├── lifecycle state machine
│   ├── fills
│   ├── timeouts
│   └── cancellations / expiry
│
├── SETTLER & RECONCILER
│   ├── settlement awareness
│   ├── ledger update
│   ├── reconciliation
│   └── drift alerts
│
└── DOWNSTREAM EMITTERS
    ├── portfolio
    ├── notifications
    ├── analytics
    └── audit log
```

### Premium execution overview view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                     ⚙️ EXECUTION ENGINE                              ║
╚══════════════════════════════════════════════════════════════════════╝

🕒 Updated 8s ago                🔐 Idempotency: ENFORCED
🌐 Venue: Polymarket CLOB        🧾 Trace ID: EXE-2026-04-22-001

┌────────────────────────────────────────────────────────────────────┐
│ 📥 INTAKE STATUS                                                  │
│ Approved Intents : 3                                              │
│ Queue State      : Healthy ✅                                     │
│ Duplicate Guard  : Active ✅                                      │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🧭 PLANNING / SUBMIT                                               │
│ Order Plan      : Ready ✅                                         │
│ Pre-submit Gate : Pass ✅                                          │
│ Venue Submit    : Acknowledged ✅                                  │
│ Latency         : 412ms                                            │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 📡 TRACKING / SETTLEMENT                                           │
│ Lifecycle State : PARTIALLY_FILLED                                 │
│ Fill Progress   : 60%                                              │
│ Timeout Policy  : Active                                           │
│ Settlement View : Pending                                          │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 📝 RECONCILIATION / OUTPUT                                         │
│ Reconciliation : In Progress                                       │
│ Drift Alert     : None                                             │
│ Portfolio Sync  : Ready                                            │
│ Audit Write     : Success ✅                                       │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[⚙️ Detail] [📂 Orders] [📊 Portfolio] [🔄 Refresh]
```

### Premium execution detail view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                     🔍 EXECUTION DETAIL                             ║
╚══════════════════════════════════════════════════════════════════════╝

Intent ID       : INT-2026-04-22-991
Signal ID       : SIG-2026-04-22-554
Market          : Will BTC exceed $100k by Dec 31?
Side            : BUY YES
Idempotency Key : idem_9c2a...

[PIPELINE]
Intake          : Pass ✅
Planning        : Complete ✅
Pre-submit      : Pass ✅
Submission      : Ack ✅
Tracking        : Active
Settlement      : Pending
Reconciliation  : Waiting

[QUALITY]
Slippage        : 7 bps
Fill Rate       : 60%
Venue Latency   : 412ms
Cost Impact     : Within policy ✅
```

### What Execution Engine Structure is not
- not a risk engine replacement
- not a signal decision engine
- not permission for raw manual order entry through Telegram
- not a claim that settlement is owned entirely by our platform
- not a statement that every venue fallback path is already shipped

### Separation note
Execution Engine Structure defines the intended last-mile execution model for CrusaderBot.
Current repo truth and current runtime/execution implementation must still be documented separately from this blueprint target.

## Polymarket Integration Structure ✅

Status: fixed for blueprint use  
Scope: target Polymarket integration model, not current merged adapter/runtime truth

### Role of Polymarket integration structure
Polymarket Integration Structure defines how CrusaderBot connects to Polymarket as an external venue and data dependency.
It must isolate venue concerns behind adapters and a unified gateway.
It must also preserve the rule that on-chain truth is authoritative while off-chain surfaces are optimized views.

### Core principles
- Polymarket is the venue, not the product
- multi-surface awareness
- on-chain is truth, off-chain is view
- graceful degradation
- signed, never custodial
- rate-aware and cost-aware
- adapter isolation over tight coupling

### Core suggestions applied from reference review
- treat CLOB, Gamma, on-chain, WebSocket, and data APIs as different surfaces with different roles
- route each operation through a Polymarket gateway / facade
- keep fallback, retry, circuit breaking, caching, and rate-limiting in the integration layer
- keep CLOB for trading, Gamma for discovery/metadata, on-chain for authoritative balances/positions/settlement awareness
- keep signing and credentials out of Telegram and out of unsafe surfaces

### Integration surfaces

#### 1. CLOB API
Purpose: primary trading surface.

Used for:
- order placement
- cancellation
- orderbook queries
- fill tracking
- execution state

#### 2. Gamma API
Purpose: market discovery and metadata.

Used for:
- market catalog
- event metadata
- question/category context
- discovery inputs

#### 3. On-chain contract / Polygon RPC
Purpose: authoritative settlement and ownership-aware truth.

Used for:
- balances
- positions ownership
- settlement reference
- authorization / allowance / delegation awareness

#### 4. WebSocket stream
Purpose: real-time updates.

Used for:
- orderbook changes
- price updates
- near-real-time venue state

#### 5. Data API / historical reads
Purpose: historical analytics and auxiliary data.

Used for:
- time-series analysis
- volume/stat history
- analytics enrichment

### Polymarket gateway model
The integration layer should expose a unified gateway that:
- routes to the correct surface for each use case
- applies retry / backoff / breaker policies
- applies cache and TTL rules
- normalizes errors and response contracts
- emits observability signals

### Adapter model
Under the gateway, keep dedicated adapters for:
- CLOB adapter
- Gamma adapter
- On-chain adapter
- WebSocket adapter
- Data adapter

Supporting cross-cutting components:
- auth manager
- nonce manager
- rate limiter
- retry engine
- request cache
- circuit breaker
- metrics collector
- gas oracle where relevant

### Truth model
- balances, positions, and settlement-related truth are on-chain authoritative
- orderbook and market metadata are off-chain acceptable views
- discrepancies trigger reconciliation and alerting, not silent mutation

### Degradation model
Examples:
- Gamma down → use cached last-known metadata where policy allows
- CLOB degraded → trading path may throttle or halt
- RPC down → rotate or fail over to backup RPC
- multiple critical surfaces down → circuit break and notify ops/users appropriately

### CLOB auth / signing model
CLOB trading integration should assume:
- signed EIP-712 style auth path
- API key / secret / passphrase lifecycle derived from authorized wallet flow
- idempotency client-side keys / hashes
- secrets stored in secure backend boundary only

### Polymarket integration treeview model

```text
POLYMARKET INTEGRATION STRUCTURE
│
├── POLYMARKET GATEWAY (Facade)
│   ├── route by operation
│   ├── retry / breaker / fallback
│   ├── normalization
│   └── observability hooks
│
├── CLOB SURFACE
│   ├── order placement
│   ├── cancellation
│   ├── orderbook
│   └── fills / execution state
│
├── GAMMA SURFACE
│   ├── market discovery
│   ├── metadata
│   ├── event context
│   └── catalog queries
│
├── ON-CHAIN SURFACE
│   ├── balances
│   ├── positions ownership
│   ├── settlement reference
│   └── authorization/delegation truth
│
├── WEBSOCKET SURFACE
│   ├── realtime price updates
│   ├── orderbook updates
│   └── stream events
│
├── DATA SURFACE
│   ├── historical series
│   ├── stats / volume
│   └── analytics reads
│
└── SUPPORTING COMPONENTS
    ├── auth manager
    ├── nonce manager
    ├── rate limiter
    ├── retry engine
    ├── request cache
    ├── circuit breaker
    └── metrics collector
```

### Premium integration overview view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                 🌐 POLYMARKET INTEGRATION                           ║
╚══════════════════════════════════════════════════════════════════════╝

🌐 Venue Model   : External dependency
🔐 Signing Model : Authorized, non-custodial
🧭 Gateway Mode  : Unified facade

┌────────────────────────────────────────────────────────────────────┐
│ ⚙️ SURFACE STATUS                                                  │
│ CLOB API      : Online ✅                                          │
│ Gamma API     : Online ✅                                          │
│ On-chain RPC  : Healthy ✅                                         │
│ WebSocket     : Connected ✅                                       │
│ Data API      : Degraded ⚠️                                        │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🧠 ROUTING MODEL                                                   │
│ Trading        : CLOB                                              │
│ Discovery      : Gamma                                             │
│ Truth Check    : On-chain                                           │
│ Realtime Feed  : WebSocket                                          │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🛡️ SAFETY                                                          │
│ Retry Engine   : Active ✅                                         │
│ Cache / TTL    : Enforced ✅                                       │
│ Circuit Breaker: Armed ✅                                          │
│ Drift Alerting : Enabled ✅                                        │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[🌐 Detail] [📡 Health] [🔐 Auth] [🔄 Refresh]
```

### What Polymarket Integration Structure is not
- not product identity by itself
- not permission to couple business logic directly to venue clients
- not a claim that off-chain views are authoritative over on-chain truth
- not a custodial signing model
- not a statement that all surface fallbacks are already implemented

### Separation note
Polymarket Integration Structure defines the intended venue-integration model for CrusaderBot.
Current repo truth and current adapter/runtime implementation must still be documented separately from this blueprint target.

## Account / Authorization / Non-Custodial Wallet Flow ✅

Status: fixed for blueprint use  
Scope: target identity, wallet, and authorization model, not current merged auth/runtime truth

### Role of account / authorization / wallet flow
This structure defines who the user is, what wallet they own, and what the platform is authorized to do on their behalf.
It must preserve non-custodial boundaries, separate identity from wallet ownership from authorization scope, and ensure Telegram alone is never the authority for funds.

### Core principles
- non-custodial by design
- identity ≠ wallet ≠ authorization
- Telegram is not an auth authority for funds
- private keys never transit unsafe surfaces
- scoped, time-bound authorizations
- revocation is always available
- auditability at every boundary

### Layer model

#### Layer 1 — Identity
Question answered: who is accessing the bot?

Components:
- Telegram identity
- platform user ID
- session state
- MFA state
- trust / security state

Source of truth:
- platform database

Authority:
- Telegram auth + platform session

#### Layer 2 — Wallet
Question answered: what on-chain entity do they own?

Components:
- EVM wallet address
- wallet type
- ownership proof via signature challenge
- link state and linkage metadata

Source of truth:
- Polygon chain

Authority:
- cryptographic ownership proof

#### Layer 3 — Authorization
Question answered: what can the platform do on their behalf?

Components:
- scope
- limits
- expiry
- revocation state
- authorization mechanism

Source of truth:
- on-chain for chain-governed parts
- platform metadata store for off-chain metadata

Authority:
- user wallet signature

### Identity entity model
Core attributes should include:
- platform user ID
- Telegram ID
- lifecycle status
- creation / last-active timestamps
- Telegram bindings and optional recovery email
- session state
- PIN / 2FA / recovery state
- trust score / failed auth / lockout state

Hard rules:
- one platform identity per Telegram ID
- identity never stores private keys or seed material
- identity mutation must be audited
- deletion should be tombstone-style, not blind hard delete

### Authentication tier model

#### Tier 0 — Anonymous
Allowed:
- /start
- /help
- /about
- public-safe legal/about surfaces

Blocked:
- any privileged or account-specific action

#### Tier 1 — Telegram-authenticated
Allowed:
- read-only operations
- configuration view
- account discovery

Blocked:
- financial-state mutation
- trade authorization
- wallet-sensitive changes

#### Tier 2 — PIN-verified
Allowed:
- strategy changes
- risk setting changes
- sensitive control updates within policy

Blocked:
- wallet link/unlink
- authorization change without stronger proof

#### Tier 3 — Step-up verified (2FA / wallet-signature path)
Allowed:
- wallet-sensitive changes
- authorization grant / revoke flows
- high-sensitivity account actions
- material safety actions where required

Rule:
- Telegram session by itself is never enough for fund authority

### Authorization model
Every authorization should define:
- scope of allowed actions
- monetary / frequency limits
- expiry
- revocation state
- mechanism used
- actor / trace metadata

Rules:
- authorization is delegated, not custodial
- user may revoke via Telegram, web, or primary on-chain path
- platform insolvency must not threaten user funds
- default duration should be short and explicit
- renewal should be active, not passive

### Account / authorization flow stages

#### 1. Identity established
User enters through Telegram and a platform identity/session is created.

#### 2. Security state established
PIN / 2FA / recovery readiness is configured.

#### 3. Wallet ownership proof
User proves control of wallet via cryptographic challenge.

#### 4. Authorization grant
User authorizes limited platform capabilities with explicit scope, limits, and expiry.

#### 5. Readiness confirmation
System confirms whether execution-capable controls are permitted.

#### 6. Revocation / renewal
User can renew, tighten, or revoke authorization from multiple safe channels.

### Account / authorization treeview model

```text
ACCOUNT / AUTHORIZATION / WALLET FLOW
│
├── IDENTITY LAYER
│   ├── Telegram identity
│   ├── platform user ID
│   ├── session state
│   ├── MFA state
│   └── trust/security state
│
├── WALLET LAYER
│   ├── EVM address
│   ├── wallet type
│   ├── ownership proof
│   └── link state
│
├── AUTHORIZATION LAYER
│   ├── scope
│   ├── limits
│   ├── expiry
│   ├── revocation state
│   └── authorization mechanism
│
├── AUTHENTICATION TIERS
│   ├── Tier 0 — Anonymous
│   ├── Tier 1 — Telegram-authenticated
│   ├── Tier 2 — PIN-verified
│   └── Tier 3 — Step-up verified
│
└── FLOW STATES
    ├── identity established
    ├── security established
    ├── wallet ownership proven
    ├── authorization granted
    ├── readiness confirmed
    └── revoke / renew path
```

### Premium account / authorization overview view

```text
╔══════════════════════════════════════════════════════════════════════╗
║            🔐 ACCOUNT / AUTHORIZATION / WALLET                      ║
╚══════════════════════════════════════════════════════════════════════╝

👤 Identity Tier : Tier 2 (PIN-verified)
🌐 Wallet State  : Linked ✅
🔏 Authorization : ACTIVE

┌────────────────────────────────────────────────────────────────────┐
│ 👤 IDENTITY                                                        │
│ Telegram ID   : Linked                                             │
│ Session State : Active ✅                                          │
│ MFA State     : Ready                                              │
│ Trust Score   : Normal                                             │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🌐 WALLET                                                          │
│ Wallet Type   : EOA                                                │
│ Ownership     : Verified ✅                                        │
│ Link State    : Active                                             │
│ Primary Chain : Polygon                                            │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🔐 AUTHORIZATION                                                   │
│ Scope         : Trade + Read                                       │
│ Daily Cap      : Active                                            │
│ Expiry         : 2026-04-29 15:00 UTC                              │
│ Revocation     : Available ✅                                      │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[👤 Detail] [🌐 Wallet] [🔐 Authorize] [🛑 Revoke]
```

### Display rules
- never display private key or seed phrase
- never imply Telegram login equals wallet control
- sensitive changes require step-up auth or wallet signature path
- authorization scope, limits, and expiry must be visible
- revocation path must always be obvious

### What Account / Authorization / Wallet Flow is not
- not a custodial wallet system
- not a raw key import flow through chat
- not permission for Telegram-only authority over funds
- not a claim that every auth mechanism is already shipped
- not a replacement for on-chain sovereignty

### Separation note
Account / Authorization / Non-Custodial Wallet Flow defines the intended identity and delegation boundary for CrusaderBot.
Current repo truth and current auth/runtime implementation must still be documented separately from this blueprint target.

## Monitoring / Alerts / Observability Structure ✅

Status: fixed for blueprint use  
Scope: target observability model, not current merged monitoring/runtime truth

### Role of monitoring / alerts / observability structure
This structure defines how CrusaderBot observes itself, explains incidents, and exposes trustworthy health information to operators and curated status to users.
It must unify metrics, logs, traces, events, and health into one coherent story.
It must also keep alerts actionable and privacy-preserving.

### Core principles
- observability is a product feature
- three pillars, one story
- alert on symptoms, investigate causes
- structured over free-form
- retention by tier
- privacy-preserving
- operator-first, user-aware

### Observability hierarchy

#### 1. Metrics
Numeric time-series for trend, alerting, and dashboards.

#### 2. Logs
Structured contextual records explaining what happened.

#### 3. Traces
Causal path across components using correlation IDs.

#### 4. Events
Semantic domain events for replay, notification, and audit.

#### 5. Health
Service/status representation for operators and users.

#### 6. Processing Layer
Cross-cutting enrichment, correlation, aggregation, and anomaly detection.

#### 7. Outputs
- alerting
- dashboards
- status page
- audit log
- SIEM/security pipeline

### Metrics pillar model
Metric types:
- counter
- gauge
- histogram
- summary

Rules:
- typed, low-cardinality by default
- avoid high-cardinality labels like raw user IDs on hot metrics
- consistent naming convention by domain/subject/unit
- service/environment/version labels standardized

### Metrics domains
At minimum, metrics should cover:
- user & session
- bot state
- signal pipeline
- risk engine
- execution
- portfolio
- notification delivery
- dependency health

### Alerting model
Alerts should:
- target user-visible impact or real operator action need
- avoid noisy non-actionable spam
- map to clear severity and owner
- include correlation / trace context

Examples of alert-worthy symptoms:
- execution failure spikes
- reconciliation drift
- stale data
- breaker trips
- degraded external dependency
- security/auth anomalies

### User vs operator observability boundary

#### User-facing observability
Curated, minimal, explanatory.

Examples:
- bot health summary
- system status badge
- relevant incident notice
- authorization readiness
- last update timestamp

#### Operator-facing observability
Full diagnostic depth.

Examples:
- dashboards
- logs/traces
- alert feed
- incident timeline
- correlation by trace/request IDs

### Monitoring / observability treeview model

```text
MONITORING / ALERTS / OBSERVABILITY
│
├── METRICS
│   ├── counters
│   ├── gauges
│   ├── histograms
│   └── summaries
│
├── LOGS
│   ├── structured runtime logs
│   ├── audit logs
│   └── contextual error logs
│
├── TRACES
│   ├── request traces
│   ├── execution traces
│   └── cross-service correlation
│
├── EVENTS
│   ├── domain events
│   ├── notification triggers
│   └── incident events
│
├── HEALTH
│   ├── service health
│   ├── dependency health
│   ├── readiness/liveness
│   └── user-facing status
│
├── PROCESSING LAYER
│   ├── enrichment
│   ├── correlation
│   ├── aggregation
│   └── anomaly detection
│
└── OUTPUTS
    ├── alerting
    ├── dashboards
    ├── status page
    ├── audit log
    └── SIEM/security
```

### Premium observability overview view

```text
╔══════════════════════════════════════════════════════════════════════╗
║              🏥 MONITORING / OBSERVABILITY                          ║
╚══════════════════════════════════════════════════════════════════════╝

🕒 Updated 6s ago                🔗 Correlation IDs: Active
👤 User View  : Curated          ⚙️ Operator View : Full

┌────────────────────────────────────────────────────────────────────┐
│ 📏 METRICS                                                        │
│ Signal Latency  : Healthy ✅                                      │
│ Risk Decisions  : Stable ✅                                       │
│ Execution Errors: Low                                             │
│ Reconcile Drift : None                                            │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🧾 LOGS / EVENTS                                                  │
│ Structured Logs : Enabled ✅                                      │
│ Audit Trail     : Enabled ✅                                      │
│ Event Pipeline  : Healthy ✅                                      │
│ Trace Coverage  : Good                                            │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🚨 ALERTING                                                       │
│ Active Alerts   : 2                                               │
│ Noise Level     : Controlled ✅                                   │
│ Escalation Path : Ready                                           │
│ User Impact     : Low                                             │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[🏥 Health] [🚨 Alerts] [🧾 Audit] [🔄 Refresh]
```

### Display rules
- health must be visible to users in a curated form
- operators get full depth, users get relevant trust signals only
- every alert should imply a next action
- structured logs/events beat free-form blobs
- secrets and PII must be redacted or hashed by default

### What Monitoring / Observability Structure is not
- not ops-only hidden plumbing
- not permission to spam alerts for every metric wobble
- not a free-form logging dump
- not a claim that every telemetry backend is already deployed
- not a substitute for reconciliation or safety controls themselves

### Separation note
Monitoring / Alerts / Observability Structure defines the intended trust and visibility model for CrusaderBot.
Current repo truth and current monitoring/runtime implementation must still be documented separately from this blueprint target.

## Data / Storage / Reconciliation Structure ✅

Status: fixed for blueprint use  
Scope: target data, storage, and reconciliation model, not current merged persistence/runtime truth

### Role of data / storage / reconciliation structure
This structure defines how CrusaderBot stores transactional state, time-series data, caches, events, archives, and secrets while continuously reconciling off-chain projections against on-chain authoritative truth.
It must preserve correctness on the write path, speed on the read path, immutable history, and continuous drift detection.

### Core principles
- on-chain is truth, off-chain is derived
- write-path vs read-path separation
- polyglot persistence, purposeful
- immutable history, mutable views
- reconciliation is continuous
- schema evolution is a process
- privacy and retention by design

### Data domain hierarchy
Major domains include:
- identity
- wallet & authorization
- portfolio
- signal / AI
- execution
- risk
- observability

Examples of records:
- users / sessions / MFA
- wallets / wallet_links / authorizations
- portfolios / balances / positions / fills / trades / ledger entries
- signals / inputs / responses / decisions / outcomes
- orders / order events / settlement records / reconciliation log
- limits / snapshots / breaches / circuit trips
- metrics / events log / audit log / status snapshots

### Storage topology

#### 1. PostgreSQL — transactional core
Use for:
- users
- portfolios
- positions
- orders
- trades
- authorizations

#### 2. TimescaleDB — time-series / metrics / market data
Use for:
- prices
- volumes
- metrics
- signal scores
- latencies

#### 3. Redis — cache / sessions / queues
Use for:
- sessions
- rate-limit counters
- market cache
- queue state

#### 4. Message bus
Use for:
- domain events
- task queues
- notification streams

#### 5. Cold archive / object storage
Use for:
- audit archives
- exports
- compliance retention

#### 6. Vault / secrets store
Use for:
- API keys
- signing credentials
- encryption keys

#### 7. Search / observability index
Use for:
- structured logs
- searchable audit/events
- operational search surfaces

### Data classification model
Critical financial data should have:
- strong encryption at rest
- append-only mutation patterns where required
- continuous backup / archival posture
- strict RBAC and audited access
- long retention window

### Reconciliation model

#### Authoritative side
- on-chain balances, positions, settlements

#### Derived side
- database projections
- summary tables
- caches
- analytics views

#### Loop behavior
- reconciliation runs continuously, not as rare batch only
- detect drift before user-visible impact when possible
- alert on discrepancies
- repair via corrective entries / projection rebuilds, not silent mutation of history

### CQRS-like boundary
- write path optimized for correctness and transactional integrity
- read path optimized for fast dashboards, summaries, and Telegram surfaces
- deliberate denormalization is acceptable in read models
- historical truth remains replayable from immutable sources

### Storage / reconciliation treeview model

```text
DATA / STORAGE / RECONCILIATION
│
├── DATA DOMAINS
│   ├── identity
│   ├── wallet & authorization
│   ├── portfolio
│   ├── signal / AI
│   ├── execution
│   ├── risk
│   └── observability
│
├── STORAGE TOPOLOGY
│   ├── PostgreSQL (transactional core)
│   ├── TimescaleDB (time-series)
│   ├── Redis (cache / sessions / queues)
│   ├── Message Bus (events / tasks)
│   ├── Object Storage (cold archive)
│   ├── Vault (secrets)
│   └── Search / Observability index
│
├── HISTORY MODEL
│   ├── immutable events
│   ├── immutable trades / audit logs
│   ├── mutable projections
│   └── replay support
│
└── RECONCILIATION LOOP
    ├── on-chain truth check
    ├── drift detection
    ├── alerting
    ├── corrective projection update
    └── audit evidence
```

### Premium storage overview view

```text
╔══════════════════════════════════════════════════════════════════════╗
║           🗄️ DATA / STORAGE / RECONCILIATION                        ║
╚══════════════════════════════════════════════════════════════════════╝

🔐 Truth Model   : On-chain authoritative
⚙️ Read Model    : Derived / optimized
🕒 Reconcile Loop: Continuous

┌────────────────────────────────────────────────────────────────────┐
│ 🧾 TRANSACTIONAL CORE                                              │
│ PostgreSQL     : Healthy ✅                                        │
│ Critical Data  : Encrypted                                         │
│ Append History : Enforced ✅                                       │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 📈 TIME-SERIES / CACHE                                             │
│ TimescaleDB   : Healthy ✅                                         │
│ Redis         : Healthy ✅                                         │
│ Queue State   : Stable ✅                                          │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🔄 RECONCILIATION                                                  │
│ Drift State    : None                                              │
│ Last Sync      : 12s ago                                           │
│ Alerting       : Armed ✅                                          │
│ Projection View: Fresh ✅                                          │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[🧾 Domains] [🗄️ Storage] [🔄 Reconcile] [🔐 Secrets]
```

### What Data / Storage / Reconciliation Structure is not
- not a single-database worldview
- not permission to treat cache as source of truth
- not permission to overwrite immutable history silently
- not a claim that every storage engine is already deployed
- not a substitute for runtime ownership / isolation checks

### Separation note
Data / Storage / Reconciliation Structure defines the intended persistence and truth model for CrusaderBot.
Current repo truth and current persistence/runtime implementation must still be documented separately from this blueprint target.

## Runtime Modes / State Machine ✅

Status: fixed for blueprint use  
Scope: target runtime-state model, not current merged state-machine truth

### Role of runtime modes / state machine
This structure defines how CrusaderBot expresses platform, tenant, user, and engine runtime states explicitly.
It must ensure that state is visible, hierarchical, fail-safe, and auditable.
It must also ensure that higher-level constraints propagate downward and cannot be bypassed by lower-level components.

### Core principles
- state is explicit, never implied
- transitions are intentional
- fail-safe defaults
- hierarchical and composable
- observable transitions
- reversible where possible
- time-aware transitions

### Hierarchical state model
State exists at four levels:
- system-level
- tenant-level
- user-level
- engine-level

Effective permission rule:
- action allowed only if all four levels allow it
- any higher-level denial blocks lower-level activity

### System-level states

#### OPERATIONAL
Meaning:
- normal operation
- all features available within lower-level rules

#### DEGRADED
Meaning:
- partial functionality
- core operation may continue
- non-essential features restricted

#### READ_ONLY
Meaning:
- no new mutations
- observability and read paths only

#### MAINTENANCE
Meaning:
- planned downtime / upgrade posture
- user-facing functionality heavily restricted

#### EMERGENCY_HALT
Meaning:
- critical incident posture
- trading globally frozen
- exit requires explicit controlled recovery

### Lower-level blueprint states

#### Tenant-level
Examples:
- operational
- maintenance window
- restricted region / restricted segment

#### User-level
Examples:
- ready
- active
- paused
- throttled
- blocked
- halted

#### Engine-level
Examples:
- signal ready / degraded / halted
- risk ready / breaker tripped
- execution ready / throttled / halted

### Transition model
Every transition should define:
- trigger
- guard conditions
- actor
- effect / side effects
- emitted event
- audit log record

Examples:
- operational → degraded on health breach
- operational → read_only for controlled safety mode
- operational → maintenance for planned work
- operational → emergency_halt on critical incident
- paused → active on controlled resume
- active → halted on unresolved unsafe condition

### State-machine treeview model

```text
RUNTIME MODES / STATE MACHINE
│
├── SYSTEM-LEVEL STATE
│   ├── OPERATIONAL
│   ├── DEGRADED
│   ├── READ_ONLY
│   ├── MAINTENANCE
│   └── EMERGENCY_HALT
│
├── TENANT-LEVEL STATE
│   ├── operational
│   ├── maintenance
│   └── restricted segment modes
│
├── USER-LEVEL STATE
│   ├── ready
│   ├── active
│   ├── paused
│   ├── throttled
│   ├── blocked
│   └── halted
│
└── ENGINE-LEVEL STATE
    ├── signal state
    ├── risk state
    ├── execution state
    └── monitoring state
```

### Premium runtime state overview view

```text
╔══════════════════════════════════════════════════════════════════════╗
║                ⚙️ RUNTIME MODES / STATE MACHINE                     ║
╚══════════════════════════════════════════════════════════════════════╝

🌐 System State : OPERATIONAL ✅
🏢 Tenant State : OPERATIONAL ✅
👤 User State   : ACTIVE ✅
⚙️ Engine State : SIGNAL:READY | RISK:READY | EXEC:READY

┌────────────────────────────────────────────────────────────────────┐
│ 🧭 PERMISSION RESOLUTION                                           │
│ System Allows : Yes                                                │
│ Tenant Allows : Yes                                                │
│ User Allows   : Yes                                                │
│ Engine Allows : Yes                                                │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🔄 TRANSITION MODEL                                                │
│ Trigger       : explicit only                                      │
│ Guards        : required                                           │
│ Side Effects  : emitted                                            │
│ Audit Trail   : enabled ✅                                         │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[⚙️ Detail] [🧾 Transitions] [🚨 State Alerts] [🔄 Refresh]
```

### Display rules
- unknown state must resolve to safe blocked/halted behavior
- state labels must be visible to users where relevant
- no silent transition
- soft stop and hard stop must be clearly different
- restart from critical halt requires explicit controlled action

### What Runtime Modes / State Machine is not
- not a hidden backend-only concept
- not permission for implicit in-between states
- not a claim that every lower-level machine is fully implemented now
- not permission for lower layers to override higher-level halts
- not a substitute for risk and execution guards

### Separation note
Runtime Modes / State Machine defines the intended lifecycle-control model for CrusaderBot.
Current repo truth and current runtime state implementation must still be documented separately from this blueprint target.

## Notification / Reporting Structure ✅

Status: fixed for blueprint use  
Scope: target notification and reporting model, not current merged delivery/runtime truth

### Role of notification / reporting structure
This structure defines how CrusaderBot communicates event-driven updates, scheduled reports, and operator/admin broadcasts to users and operators.
It must ensure that notifications are useful, channel-appropriate, suppressible when safe, and non-suppressible when critical.
It must also treat reports as reproducible data products, not ad-hoc prose.

### Core principles
- signal, not noise
- right channel for right message
- user owns their notification graph
- critical channel is non-negotiable
- structured templates, consistent voice
- deliverability is a first-class concern
- reports are data products

### Communication domain hierarchy

#### 1. Notifications
Event-driven messages.

Examples:
- trade notifications
- position notifications
- risk notifications
- security notifications
- system notifications

#### 2. Reports
Scheduled summaries.

Examples:
- daily
- weekly
- monthly
- tax / YTD
- custom on-demand reports

#### 3. Broadcasts
Admin-driven communication.

Examples:
- product updates
- policy changes
- maintenance / incidents
- administrative notices

#### 4. Delivery Pipeline
Channels and retries.

Channels:
- Telegram
- Email
- Webhook
- status page for broad incidents where appropriate

### Notification category model
Core categories may include:
- trading
- position
- risk
- portfolio
- bot_state
- security
- account
- compliance
- system
- reports
- support

Rules:
- some categories are suppressible
- some are partially suppressible
- security/compliance-critical categories are non-suppressible

### Severity model

#### CRITICAL
Immediate awareness required.
Delivery:
- instant
- cross-channel fan-out as needed
- non-suppressible

#### HIGH
Material event, likely needs action.
Delivery:
- instant on primary channel
- limited suppression where allowed

#### MEDIUM
Informational but meaningful.
Delivery:
- instant or batched per user preference

#### LOW
Routine / digest-friendly.
Delivery:
- digest by default

#### TRACE
Verbose / debug.
Delivery:
- opt-in only

### User preference model
Users should control:
- category subscriptions
- delivery frequency
- quiet hours
- preferred channels
- digest vs instant behavior where allowed

Hard rule:
- non-critical notifications are user-controlled
- critical security/compliance/safety messages are not suppressible

### Deliverability model
- transient failure → retry
- persistent failure → dead-letter / failure record
- delivery receipts tracked
- broken channel state visible to user/operator
- templates versioned and localizable

### Reporting model
Reports should be:
- deterministic from source-of-truth data
- methodology-versioned
- reproducible on demand
- exportable in standard formats
- separated from raw operational alerts

### Notification / reporting treeview model

```text
NOTIFICATION / REPORTING STRUCTURE
│
├── NOTIFICATIONS
│   ├── trading
│   ├── position
│   ├── risk
│   ├── portfolio
│   ├── bot_state
│   ├── security
│   ├── account
│   ├── compliance
│   └── system
│
├── REPORTS
│   ├── daily
│   ├── weekly
│   ├── monthly
│   ├── tax / YTD
│   └── custom
│
├── BROADCASTS
│   ├── product updates
│   ├── policy changes
│   ├── incidents
│   └── admin notices
│
└── DELIVERY PIPELINE
    ├── Telegram
    ├── Email
    ├── Webhook
    ├── retry engine
    ├── dead-letter handling
    └── delivery receipts
```

### Premium notification overview view

```text
╔══════════════════════════════════════════════════════════════════════╗
║               🔔 NOTIFICATION / REPORTING                           ║
╚══════════════════════════════════════════════════════════════════════╝

👤 Preference Model : User-controlled
🚨 Critical Path    : Non-suppressible
🧾 Reports          : Deterministic

┌────────────────────────────────────────────────────────────────────┐
│ 🔔 CATEGORY STATUS                                                 │
│ Trading       : ON                                                 │
│ Risk          : ON                                                 │
│ Security      : ON (forced critical)                               │
│ Product       : OFF                                                │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 📡 DELIVERY PIPELINE                                               │
│ Telegram      : Healthy ✅                                         │
│ Email         : Healthy ✅                                         │
│ Webhook       : Optional                                           │
│ Retry Engine  : Active ✅                                          │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 🧾 REPORTING                                                       │
│ Daily Summary  : Enabled                                           │
│ Weekly Report  : Enabled                                           │
│ Methodology    : Versioned ✅                                      │
│ Export Path    : Available                                         │
└────────────────────────────────────────────────────────────────────┘

[ACTION BAR]
[🔔 Preferences] [🧾 Reports] [📡 Delivery] [🔄 Refresh]
```

### Event routing rules
Examples:
- trade opened / filled / closed → trading or position category
- trade rejected → high-priority trading/risk event
- breaker trip / risk breach → risk category, partial suppression only
- login / auth / wallet-link change → security category, non-suppressible
- maintenance / degradation / incident → system category, partial suppression only

### Display rules
- no spammy FYI flood
- critical events must be clearly labeled
- templates should stay structured and consistent
- user preference controls must be visible and understandable
- report generation must be reproducible, not hand-written guesswork

### What Notification / Reporting Structure is not
- not a marketing blast engine first
- not permission to suppress critical safety/security/legal notices
- not a claim that every delivery channel is already live
- not a free-form string system with no template/version control
- not a substitute for observability or audit systems themselves

### Separation note
Notification / Reporting Structure defines the intended communication model for CrusaderBot.
Current repo truth and current delivery/runtime implementation must still be documented separately from this blueprint target.



## System Pipeline Summary / Final Master Map ✅

Status: fixed for blueprint use  
Scope: final closure section for blueprint consistency, not current repo/runtime truth

### Why this section exists
This closing section does not introduce new components.
It exists to:
- show the whole system, not isolated parts
- lock wording consistency across the blueprint
- define one canonical section order
- define the line between blueprint scope and implementation scope

### Canonical blueprint section order

#### Part I — Foundations
1. Project Overview
2. Directory Tree
3. Bot Architecture
4. Telegram Structure
5. Command Surface
6. User Flow
7. Operator / Admin Flow

#### Part II — Product Surfaces & Domain Views
8. Control Dashboard Structure
9. Portfolio / Positions Structure
10. Analytics / Performance Structure
11. Signal / Intelligence Structure

#### Part III — Operational Core
12. Risk Engine Structure
13. Execution Engine Structure
14. Polymarket Integration Structure
15. Account / Authorization / Non-Custodial Wallet Flow

#### Part IV — Cross-Cutting System Layers
16. Monitoring / Alerts / Observability Structure
17. Data / Storage / Reconciliation Structure
18. Runtime Modes / State Machine
19. Notification / Reporting Structure
20. Visual Presentation Standard

#### Part V — Closure
21. System Pipeline Summary / Final Master Map

### Canonical terms used across blueprint

#### Product and subsystem terms
- **CrusaderBot** = the platform as a whole
- **Bot** = per-user autonomous trading instance
- **Engine** = internal subsystem such as signal, risk, or execution
- **Venue** = external marketplace, especially Polymarket
- **Signal** = proposal generated by intelligence layer
- **Intent** = risk-approved trade proposal
- **Order** = concrete instruction sent to the venue
- **Fill** = partial or full match of an order
- **Trade** = execution-complete economic record with settlement awareness where applicable
- **Position** = aggregated exposure to one market outcome
- **Portfolio** = aggregate of user balances, positions, and derived value state

#### Canonical control verbs
- **START** = transition user bot into active operation
- **PAUSE** = stop new trades, continue monitoring
- **RESUME** = exit pause and return to active operation
- **HALT** = stop all activity, hold positions, require explicit controlled recovery
- **EMERGENCY_STOP** = high-severity halt path under critical safety conditions
- **KILL** = terminal shutdown / re-init required, restricted to highest authority only

#### Canonical roles
- **USER 👤** = end user of CrusaderBot
- **MODERATOR 🔰** = support / moderation role
- **OPERATOR ⚙️** = technical operations role
- **ADMIN 🛡️** = platform operations and safety role
- **SUPER ADMIN 👑** = highest routine system authority inside blueprint

#### Canonical severity levels
- **CRITICAL** = immediate awareness mandatory; non-suppressible
- **HIGH** = material; partial suppression only where policy allows
- **MEDIUM** = meaningful; user-configurable where safe
- **LOW** = routine; digest by default
- **TRACE** = verbose; opt-in only

#### Canonical time-in-force terms
- **IOC** = immediate-or-cancel
- **GTC** = good-till-cancelled
- **GTD** = good-till-date

#### Canonical authentication tiers
- **TIER 0 — ANONYMOUS** = no identity established
- **TIER 1 — TG_AUTHENTICATED** = Telegram session established
- **TIER 2 — PIN_VERIFIED** = step-up via PIN within valid window
- **TIER 3 — STEP_UP_VERIFIED** = high-sensitivity verification path, such as 2FA and/or wallet-signature flow where required

### Final master system map

```text
╔════════════════════════════════════════════════════════════════════════════════╗
║                 🦅 CRUSADERBOT FINAL MASTER MAP                                ║
╚════════════════════════════════════════════════════════════════════════════════╝

┌──────────────────────────────────────────────────────────────────────────────┐
│                               USER SURFACES                                  │
│                                                                              │
│  Telegram (primary)   │   Status / Health Surface   │   Email / Reports      │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         GATEWAY & CONTROL PLANE                              │
│                                                                              │
│  Command Surface → Middleware → Router → Handler                            │
│  Identity / Auth / Rate Limit / Logging / Role Boundary                     │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          APPLICATION SERVICES                                │
│                                                                              │
│  Dashboard  │  Portfolio  │  Analytics  │  Strategy  │  Wallet/Auth         │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                            CORE ENGINE LAYER                                 │
│                                                                              │
│  SIGNAL ENGINE → RISK ENGINE → EXECUTION ENGINE → SETTLEMENT / RECON        │
└──────────────┬───────────────────┬───────────────────┬───────────────────────┘
               │                   │                   │
               ▼                   ▼                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        INTEGRATION & TRUTH / DATA PLANE                      │
│                                                                              │
│  Polymarket Gateway  │  Falcon / Intelligence  │  On-chain Truth            │
│  Storage / Reconcile │  Auth / Authorization   │  Observability             │
└──────────────────────────────────────────────────────────────────────────────┘

CROSS-CUTTING RAILS
- Runtime Modes / State Machine constrain all lower layers
- Monitoring / Alerts / Observability spans every hop
- Notification / Reporting consumes events from all major domains
- Data / Storage / Reconciliation preserves history and truth boundaries
```

### Canonical end-to-end pipeline

```text
USER INTENT
→ Command Surface
→ Identity / Authorization boundary
→ Signal / Intelligence
→ Risk Engine
→ Execution Engine
→ Polymarket Venue
→ Fill / Settlement awareness
→ Reconciliation
→ Portfolio / Analytics / Notifications / Audit
```

### Cross-section consistency rules
- **Signal** always means proposal, never venue instruction
- **Intent** always means risk-approved trade proposal
- **Execution** always starts after risk approval
- **On-chain truth** always wins over off-chain projection for balances, positions, and settlement-relevant state
- **Telegram** is always a control surface, never the custody authority
- **Risk engine** is always non-optional and fail-closed
- **Observability** is always cross-cutting, not bolted on
- **Reports** are always deterministic data products, not hand-written summaries

### Blueprint done line
This blueprint covers:
- product identity and philosophy
- user/operator/admin surfaces
- domain structures
- intelligence, risk, execution, and integration boundaries
- data/storage/reconciliation model
- runtime state model
- observability and communication model
- canonical wording and canonical section order

This blueprint does not cover:
- current merged repo truth
- exact implementation status
- exact endpoint contracts
- exact database schema/migrations
- secrets, credentials, or key material
- production-capital readiness claims
- legal/compliance documents in full
- deployment-specific runbooks in operational detail

### Blueprint-to-implementation boundary
Belongs to blueprint:
- shape
- boundaries
- flows
- roles
- states
- canonical terminology

Belongs to implementation:
- exact code paths
- exact APIs
- exact storage schema
- exact thresholds/constants in runtime
- deployment topology details
- environment variables and secret handling specifics

### Final closure note
This section is the single closure layer for the blueprint.
It exists to keep every previous section aligned to one system story.
It does not replace repo truth, runtime truth, or current implementation truth.

