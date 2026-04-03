"""CallbackRouter — centralized Telegram inline-button callback dispatcher.

Routing contract:
    All callback_data MUST use the format ``action:<name>``.
    e.g. ``action:status``, ``action:control_pause``, ``action:back_main``

Behavior:
    1. Parse ``action:<name>`` from callback_data.
    2. Answer the callback_query immediately (stops Telegram loading spinner).
    3. Dispatch to the correct handler, which returns ``(text, keyboard)``.
    4. Edit the existing message in-place (``editMessageText``).
    5. If edit fails (message >48 h old, network error), fall back to sendMessage.
    6. Log every callback received, dispatched, and any failure.

Design:
    - asyncio only — no blocking calls.
    - Retry + timeout on every external call.
    - Zero silent failures.
    - No duplicate messages — edit_message_text exclusively for callbacks.
    - Fallback to send_message only when edit is truly unavailable.
"""
from __future__ import annotations

import asyncio
from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.keyboard import (
    build_main_menu,
    build_settings_menu,
    build_stop_confirm_menu,
    build_mode_confirm_menu,
    build_control_menu,
)
from ..ui.screens import (
    main_screen,
    settings_risk_screen,
    settings_mode_screen,
    settings_notify_screen,
    settings_auto_screen,
    control_stop_confirm_screen,
    error_screen,
    noop_screen,
)

if TYPE_CHECKING:
    import aiohttp
    from ..command_handler import CommandHandler
    from ...core.system_state import SystemStateManager
    from ...config.runtime_config import ConfigManager
    from ...strategy.strategy_manager import StrategyStateManager

_STRATEGY_TOGGLE_PREFIX = "strategy_toggle:"

log = structlog.get_logger(__name__)

# ── Tuning constants ───────────────────────────────────────────────────────────
_ANSWER_TIMEOUT_S: float = 3.0
_EDIT_TIMEOUT_S: float = 5.0
_SEND_TIMEOUT_S: float = 5.0
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY_S: float = 0.5

ACTION_PREFIX = "action:"


class CallbackRouter:
    """Routes Telegram callback_query ``action:<name>`` events to handlers.

    Uses ``editMessageText`` to keep a single active message (inline UI).
    Falls back to ``sendMessage`` only when editing is not possible.

    Args:
        tg_api: Telegram Bot API base URL (``https://api.telegram.org/botTOKEN``).
        cmd_handler: Existing CommandHandler for status/health/strategy delegation.
        state_manager: SystemStateManager for pause/resume/halt.
        config_manager: ConfigManager for runtime settings.
        mode: Initial trading mode string (``"PAPER"`` or ``"LIVE"``).
    """

    def __init__(
        self,
        tg_api: str,
        cmd_handler: "CommandHandler",
        state_manager: "SystemStateManager",
        config_manager: "ConfigManager",
        mode: str = "PAPER",
        strategy_state: "Optional[StrategyStateManager]" = None,
    ) -> None:
        self._api = tg_api
        self._cmd = cmd_handler
        self._state = state_manager
        self._config = config_manager
        self._mode = mode
        self._strategy_state = strategy_state

        log.info(
            "callback_router_initialized",
            mode=mode,
            api_base=tg_api[:40] + "…" if len(tg_api) > 40 else tg_api,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    async def route(
        self,
        session: "aiohttp.ClientSession",
        cq: dict,
    ) -> None:
        """Route a Telegram callback_query.

        Args:
            session: Active ``aiohttp.ClientSession``.
            cq: Telegram ``callback_query`` dict from ``getUpdates``.
        """
        cb_data: str = (cq.get("data") or "").strip()
        chat_id: Optional[int] = cq.get("message", {}).get("chat", {}).get("id")
        message_id: Optional[int] = cq.get("message", {}).get("message_id")
        cq_id: str = cq.get("id", "")
        user_id: Optional[int] = cq.get("from", {}).get("id") or None

        log.info(
            "callback_received",
            callback_data=cb_data,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
        )
        log.info("telegram_handler", handler="NEW_SYSTEM")

        # Step 1: answer callback_query — required to clear loading spinner
        await self._answer_callback(session, cq_id)

        if not cb_data.startswith(ACTION_PREFIX):
            log.warning("callback_invalid_format", callback_data=cb_data)
            return

        action = cb_data[len(ACTION_PREFIX):]

        log.info("INLINE_UPDATE", action=action)

        # Step 2: dispatch
        try:
            # Hard block: legacy UI keyword prefix check — catches exact actions
            # ("health", "strategies") and any future variants that carry these
            # substrings. "performance" is now a valid inline action.
            if any(x in cb_data for x in ("health", "strategies")):
                log.warning("callback_legacy_blocked", callback_data=cb_data)
                raise RuntimeError("LEGACY UI DISABLED")
            text, keyboard = await self._dispatch(action, user_id=user_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error(
                "callback_dispatch_error",
                action=action,
                error=str(exc),
                exc_info=True,
            )
            text = error_screen(context=action, error=str(exc))
            keyboard = build_main_menu()

        # noop — no message update needed
        if not text:
            return

        # Step 3: edit in-place; fallback to send on failure
        if chat_id and message_id:
            edited = await self._edit_message(session, chat_id, message_id, text, keyboard)
            if not edited:
                log.warning(
                    "callback_edit_failed_sending_new",
                    chat_id=chat_id,
                    action=action,
                )
                await self._send_message(session, chat_id, text, keyboard)
        elif chat_id:
            await self._send_message(session, chat_id, text, keyboard)

    # ── Dispatch table ─────────────────────────────────────────────────────────

    async def _dispatch(self, action: str, user_id: Optional[int] = None) -> tuple[str, list]:
        """Route ``action`` to the correct handler.

        Args:
            action: Action name (without ``action:`` prefix).
            user_id: Telegram user ID extracted from the callback_query.

        Returns:
            ``(text, inline_keyboard)`` tuple — text is Markdown-formatted,
            keyboard is a list[list[dict]] for Telegram ``inline_keyboard``.
        """
        log.info("callback_dispatching", action=action)

        # ── Hard block: legacy UI actions are permanently disabled ──────────
        if action in ("health", "strategies"):
            raise RuntimeError("LEGACY UI DISABLED")

        # Lazy imports — avoids circular deps and speeds up module load
        from .status import handle_status
        from .wallet import (
            handle_wallet,
            handle_wallet_balance,
            handle_wallet_exposure,
            handle_wallet_withdraw,
        )
        from .settings import handle_settings, handle_settings_strategy, handle_mode_confirm_switch
        from .control import handle_control, handle_pause, handle_resume, handle_kill

        # ── Navigation ─────────────────────────────────────────────────────
        if action in ("back_main", "back", "start", "menu"):
            snap = self._state.snapshot()
            return (
                main_screen(mode=self._mode, state=snap.get("state", "UNKNOWN")),
                build_main_menu(),
            )

        # ── Status / Refresh ───────────────────────────────────────────────
        if action in ("status", "refresh"):
            return await handle_status(
                state_manager=self._state,
                config_manager=self._config,
                cmd_handler=self._cmd,
                mode=self._mode,
            )

        # ── Performance ────────────────────────────────────────────────────
        if action == "performance":
            result = await self._cmd.handle("performance")
            from ..ui.keyboard import build_status_menu
            return result.message, build_status_menu()

        # ── Wallet ─────────────────────────────────────────────────────────
        if action == "wallet":
            return await handle_wallet(mode=self._mode, user_id=user_id)

        if action == "wallet_balance":
            return await handle_wallet_balance(user_id=user_id)

        if action == "wallet_exposure":
            return await handle_wallet_exposure(user_id=user_id)

        if action == "wallet_withdraw":
            return await handle_wallet_withdraw(user_id=user_id)

        # ── Settings ───────────────────────────────────────────────────────
        if action == "settings":
            return await handle_settings(
                config_manager=self._config,
                mode=self._mode,
            )

        if action == "settings_risk":
            return settings_risk_screen(), build_settings_menu()

        if action == "settings_mode":
            new_mode = "LIVE" if self._mode == "PAPER" else "PAPER"
            return (
                settings_mode_screen(current_mode=self._mode, new_mode=new_mode),
                build_mode_confirm_menu(new_mode),
            )

        if action.startswith("mode_confirm_"):
            new_mode = action[len("mode_confirm_"):].upper()
            text, keyboard = await handle_mode_confirm_switch(
                new_mode=new_mode,
                config_manager=self._config,
            )
            # Update internal mode on success
            if new_mode in ("PAPER", "LIVE") and text.startswith("✅"):
                self._mode = new_mode
            return text, keyboard

        if action == "settings_strategy":
            return await handle_settings_strategy(
                cmd_handler=self._cmd,
                strategy_state=self._strategy_state,
            )

        if action == "settings_notify":
            return settings_notify_screen(), build_settings_menu()

        if action == "settings_auto":
            return settings_auto_screen(mode=self._mode), build_settings_menu()

        # ── Control ────────────────────────────────────────────────────────
        if action == "control":
            return await handle_control(state_manager=self._state)

        if action == "control_pause":
            return await handle_pause(state_manager=self._state)

        if action == "control_resume":
            return await handle_resume(state_manager=self._state)

        if action == "control_stop_confirm":
            return control_stop_confirm_screen(), build_stop_confirm_menu()

        if action == "control_stop_execute":
            return await handle_kill(state_manager=self._state)

        if action == "noop":
            return noop_screen(), []

        # ── Strategy toggle ────────────────────────────────────────────────
        if action.startswith(_STRATEGY_TOGGLE_PREFIX):
            strategy_name = action.removeprefix(_STRATEGY_TOGGLE_PREFIX)
            if self._strategy_state is not None:
                try:
                    self._strategy_state.toggle(strategy_name)
                except ValueError:
                    log.warning(
                        "strategy_toggle_invalid",
                        strategy=strategy_name,
                    )
                    snap = self._state.snapshot()
                    return (
                        f"❌ Unknown strategy: `{strategy_name}`\n\n"
                        + main_screen(mode=self._mode, state=snap.get("state", "UNKNOWN")),
                        build_main_menu(),
                    )
            else:
                log.warning(
                    "strategy_toggle_no_state_manager",
                    strategy=strategy_name,
                )
            # Re-render strategy menu with updated state
            return await handle_settings_strategy(
                cmd_handler=self._cmd,
                strategy_state=self._strategy_state,
            )

        # ── Unknown ────────────────────────────────────────────────────────
        log.warning("callback_unknown_action", action=action)
        snap = self._state.snapshot()
        return (
            f"❓ Unknown action: `{action}`\n\n"
            + main_screen(mode=self._mode, state=snap.get("state", "UNKNOWN")),
            build_main_menu(),
        )

    # ── Telegram API helpers ───────────────────────────────────────────────────

    async def _answer_callback(
        self,
        session: "aiohttp.ClientSession",
        callback_query_id: str,
    ) -> None:
        """Answer the callback_query — clears the Telegram loading spinner.

        Non-fatal: logs warning on failure but does not raise.
        """
        try:
            await asyncio.wait_for(
                session.post(
                    f"{self._api}/answerCallbackQuery",
                    json={"callback_query_id": callback_query_id},
                ),
                timeout=_ANSWER_TIMEOUT_S,
            )
        except Exception as exc:
            log.warning("callback_answer_failed", error=str(exc))

    async def _edit_message(
        self,
        session: "aiohttp.ClientSession",
        chat_id: int,
        message_id: int,
        text: str,
        keyboard: list,
    ) -> bool:
        """Edit existing message in-place.

        Returns:
            ``True`` on success or "message not modified" (content unchanged).
            ``False`` on non-retriable Telegram error or exhausted retries.
        """
        payload: dict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await asyncio.wait_for(
                    session.post(f"{self._api}/editMessageText", json=payload),
                    timeout=_EDIT_TIMEOUT_S,
                )
                result = await resp.json()
                if result.get("ok"):
                    log.info(
                        "callback_edit_success",
                        chat_id=chat_id,
                        message_id=message_id,
                        attempt=attempt,
                    )
                    return True

                err_code: int = result.get("error_code", 0)
                description: str = result.get("description", "")

                # "message is not modified" is not an error
                if "message is not modified" in description.lower():
                    log.debug("callback_edit_not_modified", chat_id=chat_id)
                    return True

                log.warning(
                    "callback_edit_telegram_error",
                    error_code=err_code,
                    description=description,
                    attempt=attempt,
                )
                # Non-retriable Telegram-level error (bad message_id, etc.)
                return False

            except asyncio.TimeoutError:
                log.warning("callback_edit_timeout", attempt=attempt)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("callback_edit_exception", error=str(exc), attempt=attempt)

            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_DELAY_S * attempt)

        log.error(
            "callback_edit_all_retries_exhausted",
            chat_id=chat_id,
            message_id=message_id,
        )
        return False

    async def _send_message(
        self,
        session: "aiohttp.ClientSession",
        chat_id: int,
        text: str,
        keyboard: list,
    ) -> None:
        """Send a new message — fallback used only when edit is unavailable.

        Retries up to ``_MAX_RETRIES`` times with exponential backoff.
        Logs error on total failure but does not raise.
        """
        payload: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                await asyncio.wait_for(
                    session.post(f"{self._api}/sendMessage", json=payload),
                    timeout=_SEND_TIMEOUT_S,
                )
                log.info("callback_send_success", chat_id=chat_id, attempt=attempt)
                return
            except asyncio.TimeoutError:
                log.warning("callback_send_timeout", attempt=attempt)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("callback_send_exception", error=str(exc), attempt=attempt)

            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_DELAY_S * attempt)

        log.error("callback_send_all_attempts_failed", chat_id=chat_id)
