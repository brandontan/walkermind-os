"""Inline keyboard builders — standardized action:<name> callback format.

All callback_data values follow the format: ``action:<name>``

This ensures every button press is routed through CallbackRouter which
uses editMessageText (inline UI, no duplicate messages).

Usage::

    from .telegram.ui.keyboard import build_main_menu

    payload = {"_keyboard": build_main_menu()}
"""
from __future__ import annotations

from typing import Any

# ── Type alias ─────────────────────────────────────────────────────────────────
InlineKeyboard = list[list[dict[str, Any]]]

# ── Prefix ─────────────────────────────────────────────────────────────────────
_PREFIX = "action:"


def _btn(text: str, action: str) -> dict[str, str]:
    """Shorthand for an inline keyboard button with action:<name> data."""
    return {"text": text, "callback_data": f"{_PREFIX}{action}"}


# ── Main navigation ────────────────────────────────────────────────────────────


def build_main_menu() -> InlineKeyboard:
    """Legacy compatibility entry-point.

    The persistent reply keyboard is now the only root navigation layer, so
    inline callbacks default to Dashboard contextual actions.
    """
    return build_dashboard_menu()


# ── Status sub-menu ────────────────────────────────────────────────────────────


def build_status_menu() -> InlineKeyboard:
    """Status detail actions.

    Layout::

        [📈 Positions]   [💹 PnL          ]
        [📊 Performance] [📉 Exposure     ]
        [🔄 Refresh    ] [🏠 Main Menu    ]
    """
    return build_dashboard_menu()


def build_dashboard_menu() -> InlineKeyboard:
    """Dashboard contextual menu (two-layer model)."""
    return [
        [_btn("🏠 Home", "dashboard_home"), _btn("🧠 System", "dashboard_system")],
        [_btn("🔄 Refresh All", "dashboard_refresh_all")],
    ]


def build_portfolio_menu() -> InlineKeyboard:
    """Portfolio contextual menu."""
    return [
        [_btn("💰 Wallet", "portfolio_wallet"), _btn("📈 Positions", "portfolio_positions")],
        [_btn("📊 Exposure", "portfolio_exposure"), _btn("💹 PnL", "portfolio_pnl")],
        [_btn("🏁 Performance", "portfolio_performance"), _btn("⚡ Trade", "portfolio_trade")],
    ]


def build_trade_menu() -> InlineKeyboard:
    """Trade contextual submenu for Portfolio -> ⚡ Trade."""
    return [
        [_btn("📡 Signal", "trade_signal"), _btn("🧪 Paper Execute", "trade_paper_execute")],
        [_btn("🛑 Kill Switch", "trade_kill_switch"), _btn("📊 Trade Status", "trade_status")],
    ]


def build_markets_menu(all_markets_enabled: bool) -> InlineKeyboard:
    """Markets contextual menu with compact control grouping."""
    all_markets_label = "🌍 All Markets ✅" if all_markets_enabled else "🌍 All Markets ⬜"
    return [
        [_btn("📡 Overview", "markets_overview"), _btn(all_markets_label, "markets_all_toggle")],
        [_btn("🗂 Categories", "markets_categories"), _btn("✅ Active Scope", "markets_active_scope")],
        [_btn("🔄 Refresh All", "markets_refresh_all")],
    ]


def build_help_menu() -> InlineKeyboard:
    """Help contextual menu."""
    return [
        [_btn("🧭 Guidance", "help_guidance"), _btn("ℹ️ Bot Info", "help_bot_info")],
    ]


def build_market_categories_menu(
    categories: list[str],
    enabled_categories: set[str],
) -> InlineKeyboard:
    """Category toggle menu with strategy-like checkbox rows."""
    rows: InlineKeyboard = []
    for idx in range(0, len(categories), 2):
        row: list[dict[str, str]] = []
        for name in categories[idx : idx + 2]:
            marker = "✅" if name in enabled_categories else "⬜"
            row.append(_btn(f"{marker} {name}", f"markets_category_toggle:{name}"))
        rows.append(row)
    rows.append([_btn("💾 Save Selection", "markets_categories_save")])
    rows.append([_btn("🔙 Back", "markets")])
    return rows


# ── Wallet sub-menu ────────────────────────────────────────────────────────────


def build_wallet_menu() -> InlineKeyboard:
    """Wallet info actions — includes Withdraw button."""
    return [
        [_btn("💵 Balance",    "wallet_balance"),  _btn("📉 Exposure",   "wallet_exposure")],
        [_btn("💸 Withdraw",   "wallet_withdraw"),  _btn("🔄 Refresh",    "wallet")],
        [_btn("🏠 Main Menu",  "back_main")],
    ]


def build_paper_wallet_menu() -> InlineKeyboard:
    """Paper wallet overview menu — trade and exposure actions.

    Layout::

        [📊 Trade      ] [📉 Exposure ]
        [🔄 Refresh   ] [🏠 Main Menu]
    """
    return [
        [_btn("📊 Trade",    "trade"),    _btn("📉 Exposure",  "exposure")],
        [_btn("🔄 Refresh", "wallet"),   _btn("🏠 Main Menu", "back_main")],
    ]


# ── Settings sub-menu ──────────────────────────────────────────────────────────


def build_settings_menu() -> InlineKeyboard:
    """Settings contextual menu."""
    return [
        [_btn("🔀 Mode", "settings_mode"), _btn("🎛️ Control", "control")],
        [_btn("🛡️ Risk Level", "settings_risk"), _btn("🧠 Strategy", "settings_strategy")],
        [_btn("🔔 Notifications", "settings_notify"), _btn("🤖 Auto Trade", "settings_auto")],
    ]


def build_risk_level_menu() -> InlineKeyboard:
    """Risk level preset buttons with manual fallback hint.

    Provides four preset buttons (0.10 / 0.25 / 0.50 / 1.00) plus a back
    button.  Manual entry is still available via ``/set_risk <value>``.

    Callback format: ``action:risk_set_<value>`` (e.g. ``action:risk_set_0.25``).
    """
    return [
        [_btn("0.10", "risk_set_0.10"), _btn("0.25", "risk_set_0.25")],
        [_btn("0.50", "risk_set_0.50"), _btn("1.00", "risk_set_1.00")],
        [_btn("🔙 Back", "settings")],
    ]


def build_strategy_menu(
    strategies: list[str],
    active: str | None = None,
    active_states: dict[str, bool] | None = None,
) -> InlineKeyboard:
    """Per-strategy toggle list.

    When *active_states* is provided each strategy is shown as ✅ (enabled)
    or ⬜ (disabled).  When only *active* (single str) is provided the legacy
    single-active rendering is used for backward compatibility.

    Args:
        strategies: Ordered list of strategy names to render.
        active: Legacy single-active strategy name.  Ignored when
            *active_states* is also provided.
        active_states: Dict mapping strategy name → enabled bool.

    Callback format: ``action:strategy_toggle:{name}`` (colon separator).
    """
    rows: InlineKeyboard = []
    for name in strategies:
        if active_states is not None:
            marker = "✅" if active_states.get(name, False) else "⬜"
        else:
            marker = "✅" if name == active else "⬜"
        rows.append([_btn(f"{marker} {name}", f"strategy_toggle:{name}")])
    rows.append([_btn("🏠 Main Menu", "back_main")])
    return rows


def build_mode_confirm_menu(new_mode: str) -> InlineKeyboard:
    """Confirmation dialog for mode switch."""
    return [
        [
            _btn(f"✅ Confirm → {new_mode}", f"mode_confirm_{new_mode.lower()}"),
            _btn("❌ Cancel", "settings"),
        ],
    ]


# ── Control sub-menu ───────────────────────────────────────────────────────────


def build_control_menu(system_state: str = "RUNNING") -> InlineKeyboard:
    """State-aware control menu.

    Args:
        system_state: ``"RUNNING"`` | ``"PAUSED"`` | ``"HALTED"``.
    """
    rows: InlineKeyboard = []

    if system_state == "RUNNING":
        rows.append([_btn("⏸ Pause", "control_pause")])
    elif system_state == "PAUSED":
        rows.append([_btn("▶️ Resume", "control_resume")])
    else:
        rows.append([_btn("🔴 HALTED (restart required)", "noop")])

    if system_state != "HALTED":
        rows.append([_btn("🛑 Stop (confirm)", "control_stop_confirm")])

    rows.append([_btn("🏠 Main Menu", "back_main")])
    return rows


def build_stop_confirm_menu() -> InlineKeyboard:
    """Confirmation dialog for stop/halt action."""
    return [
        [
            _btn("⚠️ YES — Stop Trading", "control_stop_execute"),
            _btn("❌ Cancel", "control"),
        ],
    ]
