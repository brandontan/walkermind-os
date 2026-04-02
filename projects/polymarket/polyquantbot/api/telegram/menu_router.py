"""MenuRouter — routes Telegram callback_query data to handler functions.

Each callback_data string maps to an async action.  The router always
receives a UserContext so all actions are scoped per user.

Rules:
    - No trading logic here — control layer only.
    - All callbacks are idempotent.
    - Invalid / unknown callbacks return a safe fallback message.
    - Uses edit_message to update the existing message (no spam).

Usage::

    router = MenuRouter(
        command_handler=cmd_handler,
        state_manager=state_mgr,
        wallet_manager=wallet_mgr,
        telegram_sender=send_fn,
    )
    await router.route(callback_data="status", user_context=ctx,
                       chat_id=123, message_id=456)
"""
from __future__ import annotations

import asyncio
from typing import Callable, Awaitable, Optional

import structlog

from ...core.user_context import UserContext
from ...core.system_state import SystemStateManager
from ...core.pipeline.live_mode_controller import LiveModeController
from ...core.prelive_validator import PreLiveValidator
from ...wallet.wallet_manager import WalletManager
from .menu_handler import (
    build_control_menu,
    build_main_menu,
    build_settings_menu,
    build_status_menu,
    build_stop_confirm_menu,
    build_strategy_menu,
    build_wallet_menu,
    build_mode_confirm_menu,
)

log = structlog.get_logger()

# Callable type: async (chat_id, text, reply_markup, message_id) -> None
EditFn = Callable[..., Awaitable[None]]

_KNOWN_STRATEGIES: list[str] = ["ev_momentum", "mean_reversion", "liquidity_edge"]


class MenuRouter:
    """Routes callback_query data to the correct handler.

    Args:
        command_handler: Existing CommandHandler (for status/pause/etc).
        state_manager: SystemStateManager for control callbacks.
        wallet_manager: WalletManager for wallet callbacks.
        edit_message_fn: Async fn(chat_id, text, reply_markup, message_id).
        active_strategy: Currently active strategy id (mutable, single-active).
        mode: Current trading mode ("PAPER" | "LIVE").
        live_mode_controller: Optional LiveModeController — when provided,
            mode switches call enable_live() / enable_paper() to propagate
            the change to the execution layer.
        prelive_validator: Optional PreLiveValidator — when provided,
            switching to LIVE is blocked unless validation passes.
    """

    def __init__(
        self,
        command_handler: object,
        state_manager: SystemStateManager,
        wallet_manager: WalletManager,
        edit_message_fn: EditFn,
        active_strategy: Optional[str] = None,
        mode: str = "PAPER",
        live_mode_controller: Optional[LiveModeController] = None,
        prelive_validator: Optional[PreLiveValidator] = None,
    ) -> None:
        self._handler = command_handler
        self._state = state_manager
        self._wm = wallet_manager
        self._edit = edit_message_fn
        self._active_strategy: Optional[str] = active_strategy
        self._mode = mode
        self._live_ctrl = live_mode_controller
        self._prelive_validator = prelive_validator
        self._lock = asyncio.Lock()

        log.info("menu_router_initialized", mode=mode)

    # ── Primary entry point ────────────────────────────────────────────────────

    async def route(
        self,
        callback_data: str,
        user_context: UserContext,
        chat_id: int,
        message_id: int,
    ) -> None:
        """Route a callback_data string to the correct action.

        Args:
            callback_data: Value from Telegram callback_query.data.
            user_context: Scoped per-user context.
            chat_id: Telegram chat ID for the message.
            message_id: Message ID to edit (not send new).
        """
        log.info(
            "menu_router_callback",
            callback_data=callback_data,
            telegram_user_id=user_context.telegram_user_id,
            message_id=message_id,
        )

        async with self._lock:
            try:
                await self._dispatch(callback_data, user_context, chat_id, message_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "menu_router_error",
                    callback_data=callback_data,
                    error=str(exc),
                    exc_info=True,
                )
                await self._edit(
                    chat_id,
                    "⚠️ An error occurred. Please try again.",
                    build_main_menu(),
                    message_id,
                )

    # ── Dispatch table ─────────────────────────────────────────────────────────

    async def _dispatch(
        self,
        data: str,
        ctx: UserContext,
        chat_id: int,
        message_id: int,
    ) -> None:
        # ── Navigation ───────────────────────────────────────────────────────
        if data == "main_menu":
            await self._show_main_menu(chat_id, message_id)
            return

        if data == "noop":
            return  # ignore, idempotent

        # ── Status ───────────────────────────────────────────────────────────
        if data == "status":
            await self._show_status(ctx, chat_id, message_id)
            return

        if data == "performance":
            await self._show_via_handler("performance", ctx, chat_id, message_id, build_status_menu())
            return

        if data == "health":
            await self._show_via_handler("health", ctx, chat_id, message_id, build_status_menu())
            return

        if data == "strategies":
            await self._show_strategy_list(chat_id, message_id)
            return

        # ── Wallet ───────────────────────────────────────────────────────────
        if data == "wallet":
            await self._show_wallet(ctx, chat_id, message_id)
            return

        if data == "wallet_balance":
            balance = await self._wm.get_balance(ctx.wallet_id)
            await self._edit(
                chat_id,
                f"💵 *Balance*\n`{balance:.4f} USD`",
                build_wallet_menu(),
                message_id,
            )
            return

        if data == "wallet_exposure":
            exposure = await self._wm.get_exposure(ctx.wallet_id)
            await self._edit(
                chat_id,
                f"📉 *Open Exposure*\n`{exposure:.4f} USD`",
                build_wallet_menu(),
                message_id,
            )
            return

        # ── Settings ─────────────────────────────────────────────────────────
        if data == "settings":
            await self._show_settings(ctx, chat_id, message_id)
            return

        if data == "settings_risk":
            await self._edit(
                chat_id,
                "⚠️ *Risk Level*\nSend `/set_risk [0.1–1.0]` to update.",
                build_settings_menu(),
                message_id,
            )
            return

        if data == "settings_mode":
            new_mode = "LIVE" if self._mode == "PAPER" else "PAPER"
            await self._edit(
                chat_id,
                f"🔀 *Mode Switch*\nSwitch from `{self._mode}` → `{new_mode}`?\n\n⚠️ Confirm before proceeding.",
                build_mode_confirm_menu(new_mode),
                message_id,
            )
            return

        if data.startswith("mode_confirm_"):
            new_mode = data.replace("mode_confirm_", "").upper()
            if new_mode in ("PAPER", "LIVE"):
                await self._handle_mode_switch(new_mode, ctx, chat_id, message_id)
            else:
                await self._edit(
                    chat_id,
                    "❌ Unknown mode. Returning to settings.",
                    build_settings_menu(),
                    message_id,
                )
            return

        if data == "settings_strategy":
            await self._show_strategy_list(chat_id, message_id)
            return

        if data == "settings_notify":
            await self._edit(
                chat_id,
                "🔔 *Notifications*\nAlerts enabled for: trade executed, warning, critical.",
                build_settings_menu(),
                message_id,
            )
            return

        if data == "settings_auto":
            await self._edit(
                chat_id,
                f"🤖 *Auto Trade*\nMode: `{self._mode}`\nSystem will trade automatically when RUNNING.",
                build_settings_menu(),
                message_id,
            )
            return

        # ── Strategy toggles ──────────────────────────────────────────────────
        if data.startswith("strategy_toggle_"):
            strategy_id = data.replace("strategy_toggle_", "")
            await self._handle_strategy_toggle(strategy_id, ctx, chat_id, message_id)
            return

        # ── Control ───────────────────────────────────────────────────────────
        if data == "control":
            await self._show_control(chat_id, message_id)
            return

        if data == "control_pause":
            await self._handle_pause(ctx, chat_id, message_id)
            return

        if data == "control_resume":
            await self._handle_resume(ctx, chat_id, message_id)
            return

        if data == "control_stop_confirm":
            await self._edit(
                chat_id,
                "🛑 *Stop Trading*\nThis will HALT the system. Are you sure?",
                build_stop_confirm_menu(),
                message_id,
            )
            return

        if data == "control_stop_execute":
            await self._handle_stop(ctx, chat_id, message_id)
            return

        # ── Unknown ───────────────────────────────────────────────────────────
        log.warning("menu_router_unknown_callback", callback_data=data)
        await self._edit(
            chat_id,
            "❓ Unknown action. Returning to main menu.",
            build_main_menu(),
            message_id,
        )

    # ── Action implementations ─────────────────────────────────────────────────

    async def _show_main_menu(self, chat_id: int, message_id: int) -> None:
        snap = self._state.snapshot()
        state_str = snap.get("state", "UNKNOWN")
        await self._edit(
            chat_id,
            f"🤖 *KrusaderBot*\nMode: `{self._mode}` | State: `{state_str}`",
            build_main_menu(),
            message_id,
        )

    async def _show_status(
        self, ctx: UserContext, chat_id: int, message_id: int
    ) -> None:
        snap = self._state.snapshot()
        # Reflect real mode from LiveModeController when available
        real_mode = self._mode
        if self._live_ctrl is not None:
            real_mode = self._live_ctrl.mode.value
        lines = [
            "📊 *SYSTEM STATUS*",
            "",
            f"State: `{snap.get('state', 'UNKNOWN')}`",
            f"Reason: `{snap.get('reason', '-')}`",
            f"Mode: `{real_mode}`",
            f"Wallet: `{ctx.wallet_id}`",
        ]
        await self._edit(chat_id, "\n".join(lines), build_status_menu(), message_id)

    async def _show_wallet(
        self, ctx: UserContext, chat_id: int, message_id: int
    ) -> None:
        balance = await self._wm.get_balance(ctx.wallet_id)
        exposure = await self._wm.get_exposure(ctx.wallet_id)
        lines = [
            "💰 *WALLET*",
            "",
            f"Wallet ID: `{ctx.wallet_id}`",
            f"Balance: `{balance:.4f} USD`",
            f"Exposure: `{exposure:.4f} USD`",
        ]
        await self._edit(chat_id, "\n".join(lines), build_wallet_menu(), message_id)

    async def _show_settings(
        self, ctx: UserContext, chat_id: int, message_id: int
    ) -> None:
        lines = [
            "⚙️ *SETTINGS*",
            "",
            f"Mode: `{self._mode}`",
            f"Active Strategy: `{self._active_strategy or 'none'}`",
            "",
            "_Select a setting to modify:_",
        ]
        await self._edit(chat_id, "\n".join(lines), build_settings_menu(), message_id)

    async def _show_strategy_list(self, chat_id: int, message_id: int) -> None:
        kb = build_strategy_menu(
            strategies=_KNOWN_STRATEGIES,
            active=self._active_strategy,
        )
        lines = [
            "📐 *STRATEGIES*",
            "",
            "Select strategy to activate (single active only):",
            f"Active: `{self._active_strategy or 'none'}`",
        ]
        await self._edit(chat_id, "\n".join(lines), kb, message_id)

    async def _handle_strategy_toggle(
        self, strategy_id: str, ctx: UserContext, chat_id: int, message_id: int
    ) -> None:
        if strategy_id not in _KNOWN_STRATEGIES:
            await self._edit(
                chat_id,
                f"❌ Unknown strategy: `{strategy_id}`",
                build_strategy_menu(_KNOWN_STRATEGIES, self._active_strategy),
                message_id,
            )
            return

        if self._active_strategy == strategy_id:
            # Cannot disable the only active strategy
            await self._edit(
                chat_id,
                f"⚠️ Cannot disable `{strategy_id}` — must keep at least one active.",
                build_strategy_menu(_KNOWN_STRATEGIES, self._active_strategy),
                message_id,
            )
            return

        self._active_strategy = strategy_id
        log.info(
            "strategy_activated",
            strategy_id=strategy_id,
            telegram_user_id=ctx.telegram_user_id,
        )
        kb = build_strategy_menu(_KNOWN_STRATEGIES, self._active_strategy)
        await self._edit(
            chat_id,
            f"✅ Strategy `{strategy_id}` activated.",
            kb,
            message_id,
        )

    async def _show_control(self, chat_id: int, message_id: int) -> None:
        state_str = self._state.state.value
        await self._edit(
            chat_id,
            f"▶ *CONTROL*\nSystem state: `{state_str}`",
            build_control_menu(state_str),
            message_id,
        )

    async def _handle_pause(
        self, ctx: UserContext, chat_id: int, message_id: int
    ) -> None:
        current = self._state.state
        from ...core.system_state import SystemState
        if current is SystemState.PAUSED:
            await self._edit(
                chat_id, "ℹ️ System already PAUSED.", build_control_menu("PAUSED"), message_id
            )
            return
        if current is SystemState.HALTED:
            await self._edit(
                chat_id, "🔴 System HALTED — cannot pause.", build_control_menu("HALTED"), message_id
            )
            return
        await self._state.pause(reason="telegram_menu_pause")
        log.info("control_pause", telegram_user_id=ctx.telegram_user_id)
        await self._edit(
            chat_id, "⏸ Trading *PAUSED*.", build_control_menu("PAUSED"), message_id
        )

    async def _handle_resume(
        self, ctx: UserContext, chat_id: int, message_id: int
    ) -> None:
        current = self._state.state
        from ...core.system_state import SystemState
        if current is SystemState.RUNNING:
            await self._edit(
                chat_id, "ℹ️ System already RUNNING.", build_control_menu("RUNNING"), message_id
            )
            return
        if current is SystemState.HALTED:
            await self._edit(
                chat_id, "🔴 System HALTED — manual restart required.", build_control_menu("HALTED"), message_id
            )
            return
        success = await self._state.resume(reason="telegram_menu_resume")
        if success:
            log.info("control_resume", telegram_user_id=ctx.telegram_user_id)
            await self._edit(
                chat_id, "▶️ Trading *RESUMED*.", build_control_menu("RUNNING"), message_id
            )
        else:
            await self._edit(
                chat_id, "❌ Resume failed. Check logs.", build_control_menu(current.value), message_id
            )

    async def _handle_stop(
        self, ctx: UserContext, chat_id: int, message_id: int
    ) -> None:
        await self._state.halt(reason="telegram_menu_stop")
        log.warning("control_stop_executed", telegram_user_id=ctx.telegram_user_id)
        await self._edit(
            chat_id,
            "🛑 Trading *HALTED*. Manual restart required.",
            build_control_menu("HALTED"),
            message_id,
        )

    async def _handle_mode_switch(
        self,
        new_mode: str,
        ctx: UserContext,
        chat_id: int,
        message_id: int,
    ) -> None:
        """Handle a confirmed mode switch request.

        When switching to LIVE:
          1. Runs PreLiveValidator (if configured) — blocks on failure.
          2. Calls LiveModeController.enable_live() (if configured).
          3. Updates internal ``_mode`` to reflect the real execution mode.

        When switching to PAPER:
          1. Calls LiveModeController.enable_paper() (if configured).
          2. Updates internal ``_mode``.
        """
        if new_mode == "LIVE":
            # Pre-live validation gate
            if self._prelive_validator is not None:
                result = self._prelive_validator.run()
                if result.status != "PASS":
                    log.warning(
                        "mode_switch_blocked_prelive",
                        reason=result.reason,
                        telegram_user_id=ctx.telegram_user_id,
                    )
                    await self._edit(
                        chat_id,
                        "❌ Cannot switch to LIVE — validation failed\n"
                        f"`{result.reason}`",
                        build_settings_menu(),
                        message_id,
                    )
                    return

            # Wire live mode controller
            if self._live_ctrl is not None:
                self._live_ctrl.enable_live()

            self._mode = "LIVE"
            log.info(
                "mode_switched_live",
                telegram_user_id=ctx.telegram_user_id,
            )
        else:
            # Switch to PAPER
            if self._live_ctrl is not None:
                self._live_ctrl.enable_paper()

            self._mode = "PAPER"
            log.info(
                "mode_switched_paper",
                telegram_user_id=ctx.telegram_user_id,
            )

        await self._edit(
            chat_id,
            f"✅ Mode switched to `{self._mode}`.",
            build_settings_menu(),
            message_id,
        )

    async def _show_via_handler(
        self,
        cmd: str,
        ctx: UserContext,
        chat_id: int,
        message_id: int,
        kb: list,
    ) -> None:
        """Delegate text rendering to the existing command handler."""
        try:
            result = await self._handler.handle(  # type: ignore[union-attr]
                command=cmd,
                user_id=str(ctx.telegram_user_id),
            )
            text = result.message if result else "No data."
        except Exception as exc:  # noqa: BLE001
            log.error("menu_router_handler_error", cmd=cmd, error=str(exc))
            text = f"⚠️ Error fetching {cmd}."
        await self._edit(chat_id, text, kb, message_id)
