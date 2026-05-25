"""Centralized callback prefixes, emoji tokens, and layout rules.

Single source of truth for all keyboard callback_data prefixes.
Every keyboard builder in this package MUST use these constants
instead of hardcoded strings. This prevents prefix drift and
makes dispatcher registration auditable.

Layout rules (from telegram-keyboard-design skill):
- Max 2 buttons per row horizontally
- Max 5 rows visible without scrolling
- Buttons at least 30-40px tall (auto by Telegram)
- Labels max 20 characters
- Always include Back/Home escape hatch
"""
from __future__ import annotations

# ── Navigation (global, handled by dispatcher group=-1) ──────────
NAV       = "nav"
NAV_HOME  = "nav:home"
NAV_BACK  = "nav:back"
NAV_REFRESH = "nav:refresh"
NAV_CANCEL = "nav:cancel"
NAV_NOOP  = "nav:noop"

# ── Domain prefixes (each maps to one dispatcher handler) ────────
MENU        = "menu"          # top-level menu routing
DASHBOARD   = "dashboard"     # dashboard sub-actions
AUTO        = "auto"          # auto-trade surface
PRESET      = "preset"        # preset picker/confirm/status
CUSTOMIZE   = "customize"     # customize wizard
PORTFOLIO   = "portfolio"     # portfolio surface
POSITIONS   = "positions"     # position actions (close, detail)
TRADES      = "trades"        # trade history
SETTINGS    = "settings"      # settings hub
EMERGENCY   = "emergency"     # emergency actions
WALLET      = "wallet"        # wallet actions
ADMIN       = "admin"         # admin/operator
OPS         = "ops"           # ops dashboard
COPY        = "copy"          # copy-trade wizard
SIGNAL      = "signal"        # signal following
ONBOARD     = "onboard"       # onboarding flow
MARKET      = "market"        # market card
INSIGHTS    = "insights"      # PnL insights
CHART       = "chart"         # portfolio chart

# ── Risk tier grouping (for preset picker progressive disclosure) ─
# Only contains presets in VISIBLE_PRESET_ORDER. Hidden presets must not
# appear here — showing a tier button that leads to an empty list confuses users.
RISK_TIERS = {
    "🟢 Safe": ["close_sweep"],
}

# ── Standard emoji tokens ────────────────────────────────────────
E_BACK    = "⬅"
E_HOME    = "🏠"
E_REFRESH = "🔄"
E_CANCEL  = "❌"
E_CONFIRM = "✅"
E_PAUSE   = "⏸"
E_RESUME  = "▶"
E_STOP    = "🛑"
E_EDIT    = "🛠"
E_SWITCH  = "🔄"
E_SAFE    = "🟢"
E_BALANCED = "🟡"
E_AGGRESSIVE = "🔴"

# ── Layout constraints ───────────────────────────────────────────
MAX_COLS = 2
MAX_ROWS = 5
MAX_LABEL_CHARS = 20
