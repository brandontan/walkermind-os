"""Wallet keyboards — deposit, balance, withdraw.

Simple 2-col grid. Max 3 rows.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ._common import back_home_row, build_kb, grid_rows


def wallet_home_kb() -> InlineKeyboardMarkup:
    """Wallet hub — deposit / balance / withdraw + nav. 3 rows."""
    return build_kb(
        grid_rows([
            InlineKeyboardButton("📥 Deposit",  callback_data="wallet:deposit"),
            InlineKeyboardButton("💵 Balance",  callback_data="wallet:balance"),
            InlineKeyboardButton("📤 Withdraw", callback_data="wallet:withdraw"),
        ]),
        nav=back_home_row("menu:home"),
    )


def wallet_copy_kb() -> InlineKeyboardMarkup:
    """Wallet address — copy + home. 2 rows."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copy Address", callback_data="wallet:copy")],
        [InlineKeyboardButton("🏠 Home",          callback_data="menu:home")],
    ])


def wallet_deposit_kb() -> InlineKeyboardMarkup:
    """Deposit instructions — copy address + back."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copy Address",  callback_data="wallet:copy")],
        [InlineKeyboardButton("🔄 Refresh Balance", callback_data="wallet:balance")],
        [InlineKeyboardButton("← Back",            callback_data="wallet:home")],
    ])


def withdraw_cancel_kb() -> InlineKeyboardMarkup:
    """Cancel withdraw flow mid-step."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="wallet:home")],
    ])


def withdraw_confirm_kb(amount: str, address: str) -> InlineKeyboardMarkup:
    """Confirm / cancel withdraw — encode amount+address in callback."""
    safe_addr = address[:6] + "…" + address[-4:]
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"✅ Confirm ${amount}",
                callback_data=f"wallet:withdraw_confirm:{amount}:{address}",
            ),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="wallet:home")],
    ])


def withdraw_history_kb() -> InlineKeyboardMarkup:
    """After withdraw submitted."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 History",   callback_data="wallet:withdraw_history")],
        [InlineKeyboardButton("🏠 Home",       callback_data="menu:home")],
    ])


# ── Admin withdrawal keyboards ─────────────────────────────────────────────────

def admin_withdrawals_kb(pending_count: int) -> InlineKeyboardMarkup:
    label = f"📋 Pending ({pending_count})" if pending_count else "📋 Pending (none)"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data="admin:withdrawals:list")],
        [InlineKeyboardButton("⚙️ Approval Mode", callback_data="admin:withdrawals:mode")],
        [InlineKeyboardButton("← Back",            callback_data="admin:menu")],
    ])


def admin_approval_mode_kb(current: str) -> InlineKeyboardMarkup:
    auto_mark  = "✅ " if current == "auto"   else ""
    manual_mark = "✅ " if current == "manual" else ""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{auto_mark}🤖 Auto Approve",    callback_data="admin:withdrawals:set_mode:auto")],
        [InlineKeyboardButton(f"{manual_mark}👤 Manual Approve", callback_data="admin:withdrawals:set_mode:manual")],
        [InlineKeyboardButton("← Back", callback_data="admin:withdrawals")],
    ])


def admin_approve_reject_kb(withdrawal_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"admin:withdrawals:approve:{withdrawal_id}"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"admin:withdrawals:reject:{withdrawal_id}"),
        ],
        [InlineKeyboardButton("← Back", callback_data="admin:withdrawals:list")],
    ])
