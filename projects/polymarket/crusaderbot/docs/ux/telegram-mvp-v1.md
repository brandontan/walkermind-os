# CrusaderBot Telegram MVP UX Blueprint

**Version:** MVP v1  
**Platform:** Telegram Bot only  
**Web Dashboard:** Later roadmap, not included in MVP implementation  
**Product Mode:** Full-auto trading bot  
**Manual Trading:** Not supported  
**Primary UX Style:** Hierarchy Tree Terminal UI  
**Owner:** Mr. Walker  
**Prepared for:** CrusaderBot implementation lane

---

## 1. MVP Objective

CrusaderBot MVP must let a user understand, configure, start, and monitor a full-auto Polymarket trading bot from Telegram without needing a web dashboard.

The MVP goal is:

> User can go from `/start` to a running paper-mode automation setup in under 3 minutes.

The bot must feel like:

- A premium Telegram trading terminal
- Simple enough for a beginner
- Safe enough for autonomous trading
- Clear enough that the user always understands what the bot is doing

---

## 2. Hard Product Decisions

### 2.1 Telegram Only

MVP is Telegram-only.

The UX, navigation, onboarding, and monitoring flows must be designed for Telegram first.

Web dashboard is deferred.

### 2.2 Full Auto Only

CrusaderBot MVP is a full-auto bot.

Users do not manually place trades.

Not allowed in MVP:

- Manual Buy YES
- Manual Buy NO
- Manual order entry
- Manual position sizing per market
- Market detail execution buttons
- Manual trade confirmation flows

Allowed:

- Configure automation
- Configure risk
- Configure capital allocation
- Add wallet address for copy wallet
- Pause/resume automation
- Monitor markets
- Monitor portfolio
- View notifications
- View trade lifecycle events

### 2.3 Auto Trade and Copy Wallet Are Separate

Auto Trade and Copy Wallet are different products.

```text
🤖 Auto Trade
└── Bot trades using internal strategy engine

👥 Copy Wallet
└── Bot mirrors target wallet address activity
```

Do not mix Signal Following, copy trading, and auto trading.

For MVP:

- `Signal Following` is not part of Auto Trade.
- Copy Wallet only means target wallet address copying.
- No social trader marketplace.
- No signal provider marketplace.

### 2.4 Markets Are Intelligence Only

Markets are not an execution surface.

Markets are used for:

- Trending discovery
- AI insights
- Watchlist
- Sentiment
- Bot exposure visibility
- Opportunity monitoring

Markets must not include manual trade buttons.

---

## 3. MVP Information Architecture

```text
🏠 Dashboard
│
├── 🤖 Auto Trade
│   ├── 🚀 Quick Start
│   ├── 🛠 Configure
│   ├── 📊 Strategy Status
│   └── ⏯ Pause / Resume
│
├── 👥 Copy Wallet
│   ├── ➕ Add Wallet
│   ├── 👛 Active Wallets
│   └── ⏯ Pause / Resume
│
├── 💼 Portfolio
│   ├── 💰 Balance
│   ├── 📌 Positions
│   ├── 📜 History
│   └── 💹 Performance
│
├── 📈 Markets
│   ├── 🔥 Trending
│   ├── 🆕 New Markets
│   ├── 🧠 AI Insights
│   ├── ⭐ Watchlist
│   └── 🔎 Search
│
├── ⚙️ Settings
│   ├── 🔄 Trading Mode
│   ├── 🛡 Risk Controls
│   ├── 🔔 Notifications
│   ├── 👤 Account
│   └── 🧪 Advanced
│
└── ❓ Help
    ├── 🚀 Quick Start Guide
    ├── 🤖 How Auto Trade Works
    ├── 👥 How Copy Wallet Works
    ├── 🛡 Risk & Safety
    ├── 💬 FAQ
    └── 🆘 Support
```

---

## 4. Visual Language

### 4.1 Hierarchy Tree Style

All major Telegram messages must use hierarchy tree formatting.

Default pattern:

```text
SECTION TITLE
│
├── Group
│   └── Value
│
├── Group
│   ├── Label
│   │   └── Value
│   └── Label
│       └── Value
│
└── Choose an action:
```

### 4.2 Tree Characters

Use:

```text
│
├──
└──
```

### 4.3 Screen Density Rule

Each screen should have:

```text
4–5 main sections max
3 child items per section max
```

If more detail is needed, split into submenu.

### 4.4 Status Language

```text
🟢 Running
🟡 Pending
🔴 Disabled
⏸ Paused
🔒 Locked
📝 Paper Trading
💸 Live Trading
```

### 4.5 Positive / Negative

```text
📈 +$2.40
📉 -$0.80
```

Avoid panic wording on losses.

Bad:

```text
LOSING MONEY
```

Good:

```text
Risk protection active
```

---

## 5. Emoji System

Emoji meanings must stay consistent.

```text
🏠 = Dashboard / Home
🤖 = Auto Trade
👥 = Copy Wallet
💼 = Portfolio
📈 = Markets
⚙️ = Settings
❓ = Help

🚀 = Quick Start
🛠 = Configure
📊 = Status / Analytics
⚠ = Warning
🛡 = Risk / Protection
💰 = Capital / Money
⚖️ = Risk level
🧠 = AI / Strategy
⏯ = Pause / Resume
📜 = History
📌 = Positions
🔄 = Refresh
🏠 = Home
⬅ = Back
❌ = Cancel
✅ = Confirm
```

No random emoji substitutions.

---

## 6. Navigation Rules

### 6.1 Global Navigation Buttons

```text
⬅ Back
🏠 Home
🔄 Refresh
❌ Cancel
✅ Confirm
```

Meaning:

```text
⬅ Back     = previous screen
🏠 Home    = Dashboard
🔄 Refresh = reload current screen
❌ Cancel  = exit current flow
✅ Confirm = execute decision
```

### 6.2 Back Behavior

Back always returns to the previous screen in the current navigation stack.

Example:

```text
Dashboard
→ Auto Trade
→ Configure
→ Risk
```

Back resolves as:

```text
Risk → Configure
Configure → Auto Trade
Auto Trade → Dashboard
```

### 6.3 Home Behavior

Home always returns to Dashboard.

### 6.4 Refresh Behavior

Refresh reloads the current context.

Examples:

```text
💼 Portfolio / Positions
🔄 Refresh = reload positions
```

```text
📊 Market Details / BTC
🔄 Refresh = reload that market
```

```text
👥 Copy Wallet / Wallet 0x123
🔄 Refresh = reload that wallet
```

### 6.5 Cancel Behavior

Cancel only appears inside flows.

Cancel exits the flow and returns to the parent surface.

Example:

```text
🤖 Auto Trade / Configure / Review
❌ Cancel → 🤖 Auto Trade Home
```

---

## 7. Keyboard Design System

Telegram UX rule:

> Message = information. Keyboard = action.

### 7.1 Keyboard Types

```text
1. 🏠 Main Navigation
2. 📂 Sub Navigation
3. ⚡ Action Keyboard
4. ⚠ Confirmation Keyboard
```

### 7.2 Main Navigation Keyboard

Used on Dashboard.

Always 2 columns.

```text
🤖 Auto Trade      👥 Copy Wallet
💼 Portfolio       📈 Markets
⚙️ Settings        ❓ Help
🔄 Refresh         🏠 Home
```

Rules:

- Max 8 buttons
- No destructive actions
- 2-column layout
- Same ordering everywhere

### 7.3 Sub Navigation Keyboard

Used on submenu home screens.

Formula:

```text
action       action
action       action
⬅ Back      🏠 Home
```

Example:

```text
🚀 Quick Start     🛠 Configure
📊 Status          ⏯ Pause
⬅ Back             🏠 Home
```

### 7.4 Action Keyboard

Used after notifications or detail screens.

Formula:

```text
Primary action
Secondary action
Escape action
```

Example:

```text
💼 Portfolio
📊 Market Details
🏠 Dashboard
```

### 7.5 Confirmation Keyboard

Safe actions:

```text
✅ Confirm
❌ Cancel
```

Dangerous actions:

```text
❌ Cancel
🗑 Remove Wallet
```

Cancel first for destructive actions.

### 7.6 Button Priority

Top-left is highest priority.

Examples:

```text
🚀 Quick Start = top-left
🛠 Configure = top-right
```

### 7.7 Button Count

Ideal:

```text
4–8 buttons
```

Absolute max:

```text
10 buttons
```

If more than 10 buttons are needed, split the screen.

---

## 8. Dashboard MVP

### 8.1 Dashboard Default

```text
🏠 Dashboard
│
├── 🤖 Bot Status
│   └── 🟢 Running
│
├── 💹 Today
│   ├── PnL
│   │   └── 📈 +$2.40
│   └── Trades
│       └── 3
│
├── 🤖 Auto Trade
│   └── ⚡ Momentum
│
├── 👥 Copy Wallet
│   └── 2 Active
│
└── 💼 Portfolio
    └── $112.40
```

Keyboard:

```text
🤖 Auto Trade      👥 Copy Wallet
💼 Portfolio       📈 Markets
⚙️ Settings        ❓ Help
🔄 Refresh         🏠 Home
```

### 8.2 New User Dashboard

```text
🏠 Dashboard
│
├── 👋 Welcome
│   └── Your bot is not configured yet
│
├── 🚀 Quick Start
│   └── Recommended for beginners
│
├── 🤖 Auto Trade
│   └── Not Configured
│
├── 👥 Copy Wallet
│   └── Not Configured
│
└── Ready to begin?
```

Keyboard:

```text
🚀 Quick Start
🛠 Configure
❓ Learn More
```

### 8.3 Paused Dashboard

```text
🏠 Dashboard
│
├── 🤖 Bot Status
│   ├── State
│   │   └── ⏸ Paused
│   └── Reason
│       └── Manual Pause
│
├── 💹 Today
│   └── 📈 +$2.40
│
└── Action Required
    └── Resume trading to continue
```

Keyboard:

```text
▶ Resume Bot
⚙️ Settings
🏠 Home
```

### 8.4 Risk Alert Dashboard

```text
🏠 Dashboard
│
├── ⚠ Risk Alert
│   └── Daily drawdown nearing limit
│
├── 🤖 Bot Protection
│   └── Auto pause may trigger
│
├── 💼 Portfolio
│   └── Review open positions
│
└── Recommended Action
    └── Adjust risk settings
```

Keyboard:

```text
🛡 Risk Controls
💼 Portfolio
🏠 Home
```

---

## 9. Auto Trade MVP

### 9.1 Purpose

Auto Trade is the autonomous strategy engine.

It trades using internal strategies.

It is not copy trading.

It is not manual trading.

### 9.2 Auto Trade Home

```text
🤖 Auto Trade
│
├── Status
│   └── 🟢 Running
│
├── Active Strategy
│   └── ⚡ Momentum
│
├── Configuration
│   ├── 💰 Capital
│   │   └── $100
│   ├── ⚖️ Risk
│   │   └── 🟡 Balanced
│   └── 📝 Mode
│       └── Paper Trading
│
├── Performance
│   ├── 📈 PnL Today
│   │   └── +$2.40
│   ├── 🔥 Executions
│   │   └── 3
│   └── 🎯 Win Rate
│       └── 67%
│
└── Choose an action:
```

Keyboard:

```text
🚀 Quick Start     🛠 Configure
📊 Status          ⏯ Pause
⬅ Back             🏠 Home
```

### 9.3 Quick Start

```text
🚀 Quick Start
│
├── Recommended Setup
│   ├── 🧠 Strategy
│   │   └── ⚡ Momentum
│   ├── ⚖️ Risk
│   │   └── 🟡 Balanced
│   ├── 💰 Capital
│   │   └── $100
│   └── 📝 Mode
│       └── Paper Trading
│
└── Ready to begin?
```

Keyboard:

```text
✅ Start Recommended
🛠 Customize
⬅ Back
```

### 9.4 Configure Wizard

#### Step 1 — Strategy

```text
🤖 Auto Trade / Configure / Strategy
│
├── ⚡ Momentum
│   └── Fast trend following
│
├── 📊 Mean Reversion
│   └── Buy pullbacks
│
└── 🧪 Smart Hybrid
    └── Mixed adaptive mode
```

Keyboard:

```text
⚡ Momentum
📊 Mean Reversion
🧪 Smart Hybrid
⬅ Back
```

#### Step 2 — Capital

```text
🤖 Auto Trade / Configure / Capital
│
├── Current Allocation
│   └── $100
│
└── Choose allocation:
```

Keyboard:

```text
$25       $50
$100      $250
✏️ Custom
⬅ Back
```

#### Step 3 — Risk

```text
🤖 Auto Trade / Configure / Risk
│
├── 🟢 Safe
│   └── Lower risk • fewer trades
│
├── 🟡 Balanced
│   └── Recommended
│
└── 🔴 Aggressive
    └── Higher volatility
```

Keyboard:

```text
🟢 Safe
🟡 Balanced
🔴 Aggressive
⬅ Back
```

#### Step 4 — Review

```text
🤖 Auto Trade / Configure / Review
│
├── 🧠 Strategy
│   └── ⚡ Momentum
│
├── 💰 Capital
│   └── $100
│
├── ⚖️ Risk
│   └── 🟡 Balanced
│
├── 📝 Mode
│   └── Paper Trading
│
└── Looks good?
```

Keyboard:

```text
▶ Start Auto Trade
🛠 Edit Setup
❌ Cancel
```

### 9.5 Strategy Status

```text
📊 Strategy Status
│
├── Strategy
│   ├── Name
│   │   └── ⚡ Momentum
│   ├── Status
│   │   └── 🟢 Running
│   ├── Capital
│   │   └── $100
│   ├── PnL Today
│   │   └── 📈 +$2.40
│   └── Trades
│       └── 3
│
└── Select an action:
```

Keyboard:

```text
⏸ Pause
⚙️ Edit
📊 Stats
🏠 Home
```

### 9.6 Pause Auto Trade

```text
⏸ Pause Auto Trade
│
├── Effect
│   ├── New trades
│   │   └── Stopped
│   └── Open positions
│       └── Remain active
│
└── Confirm pause?
```

Keyboard:

```text
✅ Pause Bot
❌ Cancel
```

### 9.7 Resume Auto Trade

```text
▶ Resume Auto Trade
│
├── Effect
│   ├── Market monitoring
│   │   └── Resumed
│   └── Trade execution
│       └── Enabled
│
└── Continue trading?
```

Keyboard:

```text
✅ Resume Bot
❌ Cancel
```

---

## 10. Copy Wallet MVP

### 10.1 Purpose

Copy Wallet mirrors target wallet address activity.

It does not follow generic signals.

It does not follow social profiles.

It does not manually trade.

### 10.2 Copy Wallet Home

```text
👥 Copy Wallet
│
├── Status
│   └── 🟢 Running
│
├── Active Wallets
│   └── 2 Following
│
├── Allocation
│   └── $100
│
└── Choose an action:
```

Keyboard:

```text
➕ Add Wallet      👛 Active Wallets
⏯ Pause           🛡 Risk
⬅ Back            🏠 Home
```

### 10.3 Add Wallet

```text
➕ Add Wallet
│
├── Step 1
│   └── Paste wallet address
│
└── Example
    └── 0x123...abc
```

Keyboard:

```text
⬅ Back
🏠 Home
```

### 10.4 Wallet Verification

After user pastes address:

```text
👥 Wallet Review
│
├── Address
│   └── 0x12...ab9
│
├── Activity
│   └── 🟢 Active
│
├── Recent Trades
│   └── 14
│
└── Risk
    └── 🟡 Moderate
```

Keyboard:

```text
✅ Continue
❌ Cancel
```

### 10.5 Wallet Configuration

```text
⚙️ Wallet Configuration
│
├── Wallet
│   └── 0x12...ab9
│
├── Allocation
│   └── $100
│
├── Risk
│   └── 🟡 Balanced
│
└── Copy Mode
    └── Mirror Trades
```

Keyboard:

```text
▶ Start Copying
🛠 Edit
❌ Cancel
```

### 10.6 Active Wallets

```text
👛 Active Wallets
│
├── Wallet #1
│   ├── Address
│   │   └── 0x12...ab9
│   ├── Status
│   │   └── 🟢 Running
│   ├── Allocation
│   │   └── $100
│   ├── PnL Today
│   │   └── 📈 +$1.80
│   └── Trades Copied
│       └── 5
│
└── Select an action:
```

Keyboard:

```text
⏸ Pause Wallet
⚙️ Edit Wallet
📊 Stats
🏠 Home
```

### 10.7 Pause Copy Wallet

```text
⏸ Pause Copy Wallet
│
├── Effect
│   ├── New copied trades
│   │   └── Stopped
│   └── Existing positions
│       └── Stay active
│
└── Confirm pause?
```

Keyboard:

```text
✅ Pause Copying
❌ Cancel
```

---

## 11. Markets MVP

### 11.1 Purpose

Markets are intelligence-only.

Markets must not allow manual trading.

### 11.2 Markets Home

```text
📈 Markets
│
├── 🔥 Trending
│   └── Most active markets
│
├── 🆕 New Markets
│   └── Fresh opportunities
│
├── 🧠 AI Insights
│   └── High-confidence setups
│
├── ⭐ Watchlist
│   └── Saved markets
│
└── 🔎 Search
    └── Find any market
```

Keyboard:

```text
🔥 Trending      🆕 New
🧠 AI Insights   ⭐ Watchlist
🔎 Search        🏠 Home
```

### 11.3 Trending Markets

```text
🔥 Trending Markets
│
├── 1️⃣ BTC > 120k by Dec?
│   ├── Price
│   │   └── YES 42¢ • NO 58¢
│   ├── Volume
│   │   └── 🔥 High
│   └── Sentiment
│       └── 🟢 Bullish
│
├── 2️⃣ Trump 2028?
│   ├── Price
│   │   └── YES 61¢ • NO 39¢
│   ├── Volume
│   │   └── ⚡ Medium
│   └── Sentiment
│       └── 🟡 Neutral
│
└── Select a market:
```

Keyboard:

```text
1️⃣ BTC > 120k
2️⃣ Trump 2028
🔄 Refresh
🏠 Home
```

### 11.4 Market Detail

No manual trade buttons.

```text
📊 Market Details
│
├── Market
│   └── BTC > 120k by Dec?
│
├── Market Price
│   ├── YES
│   │   └── 42¢
│   └── NO
│       └── 58¢
│
├── Sentiment
│   └── 🟢 Bullish
│
├── AI Confidence
│   └── 81%
│
├── Bot Exposure
│   └── No active position
│
└── Available Actions
    └── Monitor • Watch • Auto
```

Keyboard:

```text
🤖 Auto Strategy
⭐ Add Watchlist
📊 Similar Markets
⬅ Back
```

### 11.5 AI Insights

```text
🧠 AI Insights
│
├── Market
│   └── BTC > 120k by Dec?
│
├── Confidence
│   └── 81%
│
├── Reason
│   └── Momentum + volume strength
│
└── Bot Exposure
    └── No active position
```

Keyboard:

```text
📊 View Market
⭐ Watchlist
⬅ Back
```

### 11.6 Search

```text
🔎 Search Markets
│
└── Send a keyword
    └── Example: BTC, Trump, ETH
```

Keyboard:

```text
⬅ Back
🏠 Home
```

---

## 12. Portfolio MVP

### 12.1 Portfolio Home

```text
💼 Portfolio
│
├── 💰 Balance
│   └── $112.40
│
├── 💹 Today
│   ├── PnL
│   │   └── 📈 +$4.20
│   ├── Trades
│   │   └── 3
│   └── Win Rate
│       └── 67%
│
├── 📌 Open Positions
│   └── 2 Active
│
└── Choose an action:
```

Keyboard:

```text
📌 Positions       📜 History
💹 Performance     💰 Balance
⬅ Back             🏠 Home
```

### 12.2 Positions

```text
📌 Open Positions
│
├── 1️⃣ BTC > 120k
│   ├── Side
│   │   └── 🟢 YES
│   └── PnL
│       └── +$1.30
│
├── 2️⃣ Trump 2028
│   ├── Side
│   │   └── 🔴 NO
│   └── PnL
│       └── -$0.40
│
└── Select a position:
```

Keyboard:

```text
1️⃣ BTC > 120k
2️⃣ Trump 2028
🔄 Refresh
🏠 Home
```

### 12.3 Position Detail

No manual close if runtime does not support user-initiated close safely.

If close is supported by existing safe paper/live path, show confirmation.

```text
📌 Position Details
│
├── Market
│   └── BTC > 120k?
│
├── Side
│   └── 🟢 YES
│
├── Entry
│   └── 42¢
│
├── Current
│   └── 51¢
│
├── PnL
│   └── +$1.30
│
└── Status
    └── 🟢 Open
```

Keyboard:

```text
📊 View Market
🔄 Refresh
⬅ Back
```

### 12.4 History

```text
📜 Trade History
│
├── Today
│   └── 3 Trades
│
├── This Week
│   └── 21 Trades
│
└── Choose range:
```

Keyboard:

```text
📅 Today
📆 This Week
🗂 All Time
⬅ Back
```

### 12.5 Performance

```text
💹 Performance
│
├── Today
│   └── 📈 +$4.20
│
├── 7 Days
│   └── 📈 +$12.10
│
├── Win Rate
│   └── 67%
│
└── Trades
    └── 21
```

Keyboard:

```text
📊 Weekly
📈 Monthly
⬅ Back
```

### 12.6 Balance

```text
💰 Balance
│
├── Available
│   └── $112.40
│
├── Allocated
│   └── $40.00
│
└── Free Capital
    └── $72.40
```

Keyboard:

```text
🔄 Refresh
⬅ Back
🏠 Home
```

---

## 13. Settings MVP

### 13.1 Settings Home

```text
⚙️ Settings
│
├── 🔄 Trading Mode
│   └── Paper Trading
│
├── 🛡 Risk Controls
│   └── Daily protections
│
├── 🔔 Notifications
│   └── Trade alerts enabled
│
├── 👥 Copy Wallet
│   └── Wallet mirroring settings
│
├── 👤 Account
│   └── Wallet & profile
│
└── 🧪 Advanced
    └── Power user settings
```

Keyboard:

```text
🔄 Trading Mode   🛡 Risk
🔔 Notifications  👥 Copy Wallet
👤 Account        🧪 Advanced
⬅ Back            🏠 Home
```

### 13.2 Trading Mode

```text
🔄 Trading Mode
│
├── Current Mode
│   └── 📝 Paper Trading
│
├── 📝 Paper Mode
│   └── Safe simulation
│
└── 💸 Live Mode
    └── Real capital execution
```

Keyboard:

```text
📝 Paper Mode
💸 Live Mode
⬅ Back
```

### 13.3 Live Mode Safety Gate

```text
⚠ Live Trading
│
├── Warning
│   └── Real funds will be used
│
├── Current Status
│   └── 🔒 Disabled
│
├── Requirement
│   └── Manual confirmation required
│
└── Recommendation
    └── Use Paper Mode first
```

Keyboard:

```text
🔐 Request Access
⬅ Back
```

### 13.4 Risk Controls

```text
🛡 Risk Controls
│
├── Daily Loss Limit
│   └── $20
│
├── Max Position Size
│   └── 10%
│
├── Concurrent Trades
│   └── 3 Max
│
└── Auto Pause
    └── 🟢 Enabled
```

Keyboard:

```text
💸 Loss Limit
📊 Position Size
🔢 Trade Limits
⏸ Auto Pause
⬅ Back
```

### 13.5 Notifications

```text
🔔 Notifications
│
├── Trade Opened
│   └── 🟢 Enabled
│
├── Trade Closed
│   └── 🟢 Enabled
│
├── Risk Alerts
│   └── 🟢 Enabled
│
├── Daily Summary
│   └── 🟢 Enabled
│
└── Market Alerts
    └── 🔴 Disabled
```

Keyboard:

```text
📈 Trades
⚠ Risk Alerts
📅 Daily Summary
🔕 Quiet Mode
⬅ Back
```

### 13.6 Account

```text
👤 Account
│
├── Wallet
│   └── Connected
│
├── Mode
│   └── 📝 Paper Trading
│
├── API Status
│   └── 🟢 Healthy
│
└── Subscription
    └── MVP
```

Keyboard:

```text
🔗 Wallet
📄 Export Data
🔒 Security
⬅ Back
```

### 13.7 Advanced

```text
🧪 Advanced
│
├── Strategy Logs
│   └── View execution logs
│
├── Debug Mode
│   └── 🔴 Disabled
│
├── Data Refresh
│   └── Real-time
│
└── System Health
    └── 🟢 Operational
```

Keyboard:

```text
📜 Logs
🛠 Debug
💓 Health
⬅ Back
```

---

## 14. Help and Onboarding MVP

### 14.1 Help Home

```text
❓ Help
│
├── 🚀 Quick Start Guide
│   └── Get started in under 2 minutes
│
├── 🤖 How Auto Trade Works
│   └── Learn how automation works
│
├── 👥 How Copy Wallet Works
│   └── Mirror wallet activity
│
├── 🛡 Risk & Safety
│   └── Understand protections
│
├── 💬 FAQ
│   └── Common questions
│
└── 🆘 Support
    └── Need help?
```

Keyboard:

```text
🚀 Quick Start    🤖 Auto Trade
👥 Copy Wallet    🛡 Safety
💬 FAQ            🆘 Support
🏠 Home
```

### 14.2 Quick Start Guide

```text
🚀 Quick Start Guide
│
├── Step 1
│   └── Configure Auto Trade
│
├── Step 2
│   └── Choose risk & capital
│
├── Step 3
│   └── Start in Paper Mode
│
├── Step 4
│   └── Monitor performance
│
└── Recommendation
    └── Use Paper Mode first
```

Keyboard:

```text
🤖 Setup Auto Trade
👥 Setup Copy Wallet
⬅ Back
🏠 Home
```

### 14.3 How Auto Trade Works

```text
🤖 How Auto Trade Works
│
├── Purpose
│   └── Bot trades automatically
│
├── Decision Engine
│   └── Strategy-based execution
│
├── You Control
│   ├── 💰 Capital
│   ├── ⚖️ Risk
│   └── 🧠 Strategy
│
├── Bot Controls
│   └── Market execution
│
└── Safety
    └── Risk protections enabled
```

Keyboard:

```text
🛡 Safety
🚀 Quick Start
⬅ Back
```

### 14.4 How Copy Wallet Works

```text
👥 How Copy Wallet Works
│
├── Purpose
│   └── Mirror target wallet activity
│
├── What Happens
│   └── Trades may be copied automatically
│
├── You Control
│   ├── 💰 Allocation
│   ├── ⚖️ Risk
│   └── Wallet selection
│
├── Important
│   └── Past performance ≠ future results
│
└── Recommendation
    └── Start small
```

Keyboard:

```text
➕ Add Wallet
🛡 Safety
⬅ Back
```

### 14.5 Risk & Safety

```text
🛡 Risk & Safety
│
├── Paper Mode
│   └── Practice without real funds
│
├── Daily Loss Limit
│   └── Bot protection available
│
├── Auto Pause
│   └── Risk protection can stop trading
│
├── Copy Wallet Risk
│   └── Wallets can underperform
│
└── Reminder
    └── Never risk more than you can afford
```

Keyboard:

```text
🔄 Trading Mode
🛡 Risk Controls
⬅ Back
```

### 14.6 FAQ

```text
💬 FAQ
│
├── 🤖 Is trading automatic?
│
├── 📝 What is Paper Mode?
│
├── 💸 Can I lose money?
│
├── 👥 How does Copy Wallet work?
│
└── 🔒 Is my wallet safe?
```

Keyboard:

```text
1️⃣ Auto Trade
2️⃣ Paper Mode
3️⃣ Risk
4️⃣ Copy Wallet
⬅ Back
```

### 14.7 Support

```text
🆘 Support
│
├── Help Center
│   └── Common troubleshooting
│
├── Report Issue
│   └── Found a problem?
│
└── Status
    └── 🟢 Systems Operational
```

Keyboard:

```text
🐞 Report Issue
💬 FAQ
🏠 Home
```

---

## 15. Notification UX MVP

### 15.1 Notification Classes

```text
1. 🤖 Bot Status
2. 📈 Trade Lifecycle
3. 👥 Copy Wallet Events
4. ⚠ Risk Alerts
5. 💰 Profit Milestones
6. 📅 Daily Summary
```

### 15.2 Bot Started

```text
🤖 Auto Trade Started
│
├── Strategy
│   └── ⚡ Momentum
│
├── Capital
│   └── $100
│
├── Risk
│   └── 🟡 Balanced
│
└── Status
    └── 🟢 Running
```

Keyboard:

```text
💼 Portfolio
🏠 Dashboard
```

### 15.3 Bot Waiting Reassurance

```text
🤖 Auto Trade Started
│
├── Status
│   └── 🟢 Running
│
├── What happens next
│   └── Bot monitors opportunities automatically
│
└── Note
    └── First trade may take time
```

### 15.4 Trade Opened

```text
📈 Trade Opened
│
├── Market
│   └── BTC > 120k by Dec?
│
├── Position
│   └── 🟢 YES
│
├── Strategy
│   └── ⚡ Momentum
│
├── Entry
│   └── 42¢
│
├── Size
│   └── $10
│
└── Reason
    └── High confidence setup
```

Keyboard:

```text
💼 Portfolio
📊 View Market
```

### 15.5 First Trade Opened

```text
🎉 First Trade Opened
│
├── Nice start
│   └── Your bot placed its first trade
│
├── Market
│   └── BTC > 120k?
│
└── Status
    └── Monitoring performance
```

Keyboard:

```text
💼 Portfolio
🏠 Dashboard
```

### 15.6 Trade Closed — Profit

```text
🎯 Trade Closed
│
├── Market
│   └── BTC > 120k?
│
├── Result
│   └── 📈 +$2.40
│
├── Exit Reason
│   └── Profit target reached
│
└── Portfolio Balance
    └── $112.40
```

Keyboard:

```text
💼 Portfolio
📜 Trade History
```

### 15.7 Trade Closed — Loss

```text
📉 Trade Closed
│
├── Market
│   └── Trump 2028?
│
├── Result
│   └── -$0.80
│
├── Exit Reason
│   └── Risk protection triggered
│
└── Portfolio Status
    └── Stable
```

### 15.8 Wallet Trade Copied

```text
👥 Wallet Trade Copied
│
├── Wallet
│   └── 0x12...ab9
│
├── Market
│   └── ETH > 10k?
│
├── Position
│   └── 🟢 YES
│
├── Size
│   └── $8
│
└── Copy Mode
    └── Proportional
```

Keyboard:

```text
👥 Copy Wallet
💼 Portfolio
```

### 15.9 Drawdown Warning

```text
⚠ Risk Alert
│
├── Daily Loss
│   └── $16 / $20
│
├── Protection
│   └── Auto pause nearing
│
└── Recommendation
    └── Review exposure
```

Keyboard:

```text
🛡 Risk Controls
💼 Portfolio
```

### 15.10 Auto Pause Triggered

```text
🛡 Safety Protection Activated
│
├── Trigger
│   └── Daily loss limit reached
│
├── Auto Trade
│   └── ⏸ Paused
│
├── Open Positions
│   └── Still monitored
│
└── Action Needed
    └── Review settings
```

Keyboard:

```text
🛡 Risk Controls
▶ Resume Later
```

### 15.11 Daily Summary

```text
📅 Daily Summary
│
├── Portfolio
│   └── $112.40
│
├── Today PnL
│   └── 📈 +$4.20
│
├── Trades
│   └── 3 completed
│
├── Win Rate
│   └── 67%
│
├── Best Trade
│   └── BTC > 120k (+$2.40)
│
└── Bot Status
    └── 🟢 Running
```

Keyboard:

```text
💼 Portfolio
🏠 Dashboard
```

### 15.12 Notification Frequency Rules

Instant:

```text
✅ Trade opened
✅ Trade closed
✅ Risk alert
✅ Bot pause/resume
✅ Wallet copied
```

Daily:

```text
📅 Summary
🎉 Milestones
```

Never spam:

```text
❌ Every price movement
❌ Every signal detected
❌ Market noise
```

---

## 16. Empty States

### 16.1 No Positions

```text
📌 Open Positions
│
├── Status
│   └── No active positions
│
└── Note
    └── Your bot will trade when opportunities appear
```

Keyboard:

```text
🤖 Auto Trade
👥 Copy Wallet
🏠 Home
```

### 16.2 No Trade History

```text
📜 Trade History
│
├── Status
│   └── No trades yet
│
└── Note
    └── Start automation to build history
```

Keyboard:

```text
🚀 Quick Start
🏠 Home
```

### 16.3 No Active Wallets

```text
👛 Active Wallets
│
├── Status
│   └── No wallets added
│
└── Next Step
    └── Add a wallet address to start copying
```

Keyboard:

```text
➕ Add Wallet
🏠 Home
```

### 16.4 No Watchlist

```text
⭐ Watchlist
│
├── Status
│   └── No markets saved
│
└── Tip
    └── Add markets from AI Insights or Trending
```

Keyboard:

```text
🧠 AI Insights
🔥 Trending
🏠 Home
```

---

## 17. Loading and Sync States

### 17.1 Generic Loading

```text
⏳ Loading
│
└── Fetching data...
```

### 17.2 Portfolio Sync

```text
🔄 Syncing
│
└── Updating portfolio data...
```

### 17.3 Market Sync

```text
🔄 Syncing
│
└── Updating market intelligence...
```

### 17.4 Wallet Verification

```text
⏳ Verifying Wallet
│
└── Checking recent activity...
```

---

## 18. Error States

### 18.1 API Error

```text
⚠ Temporary Issue
│
├── Status
│   └── Data unavailable
│
└── Action
    └── Try refresh in a moment
```

Keyboard:

```text
🔄 Refresh
🏠 Home
```

### 18.2 Invalid Wallet Address

```text
⚠ Invalid Wallet Address
│
├── Expected Format
│   └── 0x... wallet address
│
└── Action
    └── Paste a valid address
```

Keyboard:

```text
⬅ Back
🏠 Home
```

### 18.3 Bot Paused

```text
⏸ Bot Paused
│
├── New Trades
│   └── Stopped
│
└── Existing Positions
    └── Still monitored
```

Keyboard:

```text
▶ Resume Bot
🏠 Home
```

### 18.4 Live Mode Locked

```text
🔒 Live Mode Locked
│
├── Status
│   └── Not enabled
│
└── Requirement
    └── Owner activation required
```

Keyboard:

```text
📝 Paper Mode
🏠 Home
```

---

## 19. User Journeys

### 19.1 New User Golden Path

```text
/start
│
├── 🚀 Quick Start
├── 🤖 Auto Trade / Quick Start
├── Choose Strategy
├── Choose Capital
├── Choose Risk
├── ✅ Confirm
├── ▶ Start Auto Trade
├── 🤖 Auto Trade Started
├── 🏠 Dashboard
└── 🔔 First Trade Notification
```

### 19.2 Curious User

```text
/start
│
├── 👀 Explore First
├── 📈 Markets
├── 🧠 AI Insights
├── ❓ Help
├── 🤖 How Auto Trade Works
└── 🚀 Quick Start
```

### 19.3 Copy Wallet User

```text
Dashboard
│
├── 👥 Copy Wallet
├── ➕ Add Wallet
├── Paste Address
├── Wallet Verification
├── Configure Allocation
├── Configure Risk
├── Review
└── ▶ Start Copying
```

### 19.4 Passive Daily User

```text
Open Telegram
│
├── Daily Summary
├── Dashboard
├── Portfolio
└── Exit
```

### 19.5 Losing Day User

```text
⚠ Risk Alert
│
├── Portfolio
├── Risk Controls
└── Auto Pause
```

---

## 20. Callback Architecture

### 20.1 Callback Naming Convention

Use predictable callback IDs.

Format:

```text
surface:action
surface:section:action
surface:flow:step:action
```

Examples:

```text
dashboard:home
dashboard:refresh

auto:home
auto:quick_start
auto:configure
auto:configure:strategy
auto:configure:capital
auto:configure:risk
auto:configure:review
auto:start
auto:pause
auto:resume

copy:home
copy:add_wallet
copy:wallet:verify
copy:wallet:configure
copy:wallet:start
copy:wallets
copy:pause
copy:resume

portfolio:home
portfolio:positions
portfolio:history
portfolio:performance
portfolio:balance

markets:home
markets:trending
markets:new
markets:insights
markets:watchlist
markets:search
markets:detail

settings:home
settings:mode
settings:risk
settings:notifications
settings:account
settings:advanced

help:home
help:quick_start
help:auto
help:copy_wallet
help:safety
help:faq
help:support
```

### 20.2 Navigation Stack

Store per-user navigation stack.

Suggested structure:

```json
{
  "user_id": "telegram_user_id",
  "stack": [
    "dashboard:home",
    "auto:home",
    "auto:configure:strategy"
  ],
  "updated_at": "timestamp"
}
```

### 20.3 Flow State

Store wizard state separately.

Auto Trade setup:

```json
{
  "user_id": "telegram_user_id",
  "flow": "auto_configure",
  "step": "risk",
  "data": {
    "strategy": "momentum",
    "capital": 100,
    "risk": "balanced"
  }
}
```

Copy Wallet setup:

```json
{
  "user_id": "telegram_user_id",
  "flow": "copy_wallet_add",
  "step": "configure",
  "data": {
    "wallet": "0x12...ab9",
    "allocation": 100,
    "risk": "balanced",
    "copy_mode": "mirror"
  }
}
```

---

## 21. Suggested Telegram Handler Map

```text
bot/handlers/dashboard.py
bot/handlers/auto_trade.py
bot/handlers/copy_wallet.py
bot/handlers/portfolio.py
bot/handlers/markets.py
bot/handlers/settings.py
bot/handlers/help.py
bot/handlers/navigation.py
bot/handlers/onboarding.py
bot/handlers/notifications.py
```

Keyboard modules:

```text
bot/keyboards/main.py
bot/keyboards/auto_trade.py
bot/keyboards/copy_wallet.py
bot/keyboards/portfolio.py
bot/keyboards/markets.py
bot/keyboards/settings.py
bot/keyboards/help.py
bot/keyboards/navigation.py
```

Message renderers:

```text
bot/renderers/dashboard.py
bot/renderers/auto_trade.py
bot/renderers/copy_wallet.py
bot/renderers/portfolio.py
bot/renderers/markets.py
bot/renderers/settings.py
bot/renderers/help.py
bot/renderers/notifications.py
```

Shared UI helpers:

```text
bot/ui/tree.py
bot/ui/formatters.py
bot/ui/buttons.py
bot/ui/states.py
```

---

## 22. Data Model MVP

This is conceptual and should be mapped to current repo schema.

### 22.1 User Settings

```text
user_settings
├── user_id
├── trading_mode
├── notifications_enabled
├── daily_summary_enabled
├── risk_alerts_enabled
├── created_at
└── updated_at
```

### 22.2 Auto Trade Config

```text
auto_trade_configs
├── user_id
├── enabled
├── strategy
├── capital_allocation
├── risk_level
├── mode
├── created_at
└── updated_at
```

### 22.3 Copy Wallet Config

```text
copy_wallet_configs
├── id
├── user_id
├── wallet_address
├── enabled
├── allocation
├── risk_level
├── copy_mode
├── verification_status
├── created_at
└── updated_at
```

### 22.4 Navigation State

```text
telegram_navigation_state
├── user_id
├── stack_json
├── current_screen
├── updated_at
```

### 22.5 Flow State

```text
telegram_flow_state
├── user_id
├── flow_name
├── step
├── payload_json
├── created_at
└── updated_at
```

---

## 23. Safety and Guardrails

### 23.1 MVP Trading Mode

Default mode must be Paper Trading.

Live trading must remain locked unless explicit owner activation exists.

### 23.2 Live Mode

Live Mode screen may exist for awareness, but must not enable live execution.

It should show:

```text
🔒 Disabled
Manual confirmation required
Use Paper Mode first
```

### 23.3 Risk Controls

Risk settings UI must not bypass backend risk constants.

UI must reflect backend truth.

### 23.4 No Manual Execution

No Telegram button should directly place manual trades.

Allowed execution triggers:

- Auto Trade engine
- Copy Wallet mirroring engine
- Existing safe runtime automation path

### 23.5 Destructive Actions

Dangerous operations must use confirmation screen.

Examples:

- Remove wallet
- Pause all automation
- Disable notifications
- Request live mode access

---

## 24. Implementation Scope

### 24.1 MVP In Scope

```text
✅ Telegram hierarchy UI
✅ Dashboard redesign
✅ Auto Trade menu
✅ Copy Wallet menu
✅ Portfolio menu
✅ Markets intelligence menu
✅ Settings menu
✅ Help menu
✅ Navigation stack
✅ Keyboard consistency
✅ Notification templates
✅ Empty/loading/error states
```

### 24.2 MVP Out of Scope

```text
❌ Web dashboard
❌ Manual trading
❌ Manual Buy YES / NO
❌ Strategy marketplace
❌ Copy signal providers
❌ Social trader marketplace
❌ Advanced charts
❌ Premium analytics
❌ Live trading activation
```

---

## 25. Validation Plan

### 25.1 UX Validation

Check:

```text
✅ Every screen uses hierarchy tree format
✅ Every screen has Back or Home
✅ No manual trade buttons exist
✅ Auto Trade and Copy Wallet are separated
✅ Markets are intelligence-only
✅ Copy Wallet asks for target wallet address
✅ Keyboard layout follows system rules
✅ Empty/loading/error states exist
```

### 25.2 Safety Validation

Check:

```text
✅ Live mode remains locked
✅ No execution guard bypass
✅ No risk constant changes
✅ No manual trade path introduced
✅ Paper mode remains default
```

### 25.3 Technical Validation

Check:

```text
✅ Callback IDs are deterministic
✅ Handler imports resolve
✅ Navigation stack works
✅ Flow state survives multi-step wizard
✅ All keyboards render correctly
✅ Telegram message length safe
✅ Existing tests pass
```

---

## 26. Definition of Done

MVP UX implementation is done when:

```text
✅ Dashboard uses hierarchy tree terminal style
✅ Auto Trade flow works end-to-end in Telegram
✅ Copy Wallet flow accepts and verifies wallet address
✅ Portfolio screens render current data
✅ Markets screens are intelligence-only
✅ Settings screens render and do not bypass safety
✅ Help screens explain full-auto behavior clearly
✅ Notifications use hierarchy tree style
✅ Navigation Back/Home/Refresh works consistently
✅ No manual trading UI exists
✅ Live mode remains locked
✅ Report and state files updated
```

---

## 27. Recommended Implementation Lane

Suggested branch:

```text
WARP/telegram-mvp-ux
```

Validation Tier:

```text
STANDARD
```

Claim Level:

```text
NARROW INTEGRATION
```

Scope:

```text
Telegram UI/menu/copy/navigation only.
No execution logic.
No live guards.
No capital/risk backend behavior changes.
```

Suggested report path:

```text
projects/polymarket/crusaderbot/reports/forge/telegram-mvp-ux.md
```

---

## 28. Suggested Build Order

### Phase 1 — Foundation

```text
1. UI tree renderer helpers
2. Keyboard design system
3. Navigation stack
4. Dashboard compact MVP
```

### Phase 2 — Core Product Surfaces

```text
5. Auto Trade screens
6. Copy Wallet screens
7. Portfolio screens
8. Markets intelligence screens
```

### Phase 3 — Trust and Retention

```text
9. Settings screens
10. Help screens
11. Notification templates
12. Empty/loading/error states
```

### Phase 4 — QA

```text
13. Callback audit
14. Journey test
15. Safety guard audit
16. Final Telegram preview
```

---

## 29. Post-MVP Roadmap

Later, not MVP:

```text
📊 Web dashboard
📈 Advanced analytics
🧠 Strategy marketplace
👥 Wallet leaderboard
🧾 Export reports
📉 Chart images
🔔 Advanced alert filters
🧪 A/B tested onboarding
💎 Premium insights
```

---

## 30. Final MVP Verdict

```text
MVP UX READY FOR IMPLEMENTATION
```

CrusaderBot Telegram MVP is ready to move from UX blueprint to implementation with the following fixed identity:

```text
🤖 Auto Trade
= autonomous strategy engine

👥 Copy Wallet
= target wallet address mirroring

📈 Markets
= intelligence only

💼 Portfolio
= monitoring only

⚙️ Settings
= safety and control

❓ Help
= trust and onboarding
```
