"""CrusaderBot Keyboard Module — v2 Redesign.

Architecture:
  _constants.py  — Callback prefixes, emoji tokens, layout rules
  _common.py     — Shared helpers (buttons, rows, grid, pagination)
  main_menu.py   — ReplyKeyboardMarkup (persistent bottom bar)
  dashboard.py   — Dashboard inline keyboards
  autotrade.py   — Auto-trade + preset picker (grouped by risk tier)
  portfolio.py   — Portfolio, positions, trades
  settings.py    — Settings hub + sub-screens
  emergency.py   — Emergency menu (max 5 rows, progressive disclosure)
  customize.py   — Customize wizard (capital/TP/SL/review)
  onboarding.py  — Welcome + wallet setup flow
  wallet.py      — Wallet actions
  admin.py       — Admin/operator restricted surfaces

Design rules (telegram-keyboard-design skill):
  ✅ Max 2 buttons per row
  ✅ Max 5 rows per screen
  ✅ Back + Home on every nested screen
  ✅ Confirm/Cancel on every destructive action
  ✅ Progressive disclosure (tier picker → preset list)
  ✅ Consistent emoji and label style
  ✅ State-aware button labels
  ✅ edit_message_text, not reply_text for inline nav

Migration from keyboards/ (legacy):
  See MIGRATION.md in this directory.
"""
from __future__ import annotations

# ── Foundation ───────────────────────────────────────────────────
from ._common import (                                       # noqa: F401
    BACK, CANCEL, HOME, NOOP, REFRESH,
    back_home_row, back_row, build_kb, confirm_cancel_row,
    grid_rows, home_back_row, home_row, mark_selected, nav_row,
    pagination_row, refresh_home_row,
)

# ── ReplyKeyboard (bottom bar) ───────────────────────────────────
from .main_menu import main_menu                             # noqa: F401

# ── Inline keyboards by domain ───────────────────────────────────
from .dashboard import (                                     # noqa: F401
    activity_kb, chart_kb, dashboard_kb, insights_kb,
)
from .autotrade import (                                     # noqa: F401
    auto_home_kb, pause_confirm_kb, preset_confirm_kb,
    preset_list_kb, preset_status_kb, preset_stop_confirm_kb,
    preset_switch_confirm_kb, preset_tier_kb, quick_start_kb,
    resume_confirm_kb,
)
from .portfolio import (                                     # noqa: F401
    close_confirm_kb, portfolio_home_kb, position_close_kb,
    positions_list_kb, trades_empty_kb, trades_history_kb,
    trades_home_kb,
)
from .settings import (                                      # noqa: F401
    capital_picker_kb, mode_picker_kb, redeem_picker_kb,
    risk_picker_kb, settings_hub_kb, sl_picker_kb,
    tp_picker_kb, tpsl_done_kb,
)
from .emergency import (                                     # noqa: F401
    emergency_confirm_kb, emergency_done_kb,
    emergency_home_kb, emergency_more_kb,
)
from .customize import (                                     # noqa: F401
    wizard_capital_kb, wizard_custom_input_kb, wizard_done_kb,
    wizard_review_kb, wizard_sl_kb, wizard_targets_kb,
    wizard_tp_kb,
)
from .onboarding import (                                    # noqa: F401
    deposit_prompt_kb, onboard_complete_kb,
    wallet_ready_kb, welcome_kb,
)
from .wallet import wallet_copy_kb, wallet_home_kb           # noqa: F401
from .admin import (                                         # noqa: F401
    admin_confirm_kb, admin_menu_kb, ops_dashboard_kb,
)
