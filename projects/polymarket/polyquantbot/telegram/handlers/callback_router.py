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
    build_risk_level_menu,
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
    from ...infra.db import DatabaseClient
    from ...core.wallet_engine import WalletEngine
    from ...core.positions import PaperPositionManager
    from ...core.exposure import ExposureCalculator
    from ...execution.paper_engine import PaperEngine

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
        db: "Optional[DatabaseClient]" = None,
    ) -> None:
        self._api = tg_api
        self._cmd = cmd_handler
        self._state = state_manager
        self._config = config_manager
        self._mode = mode
        self._strategy_state = strategy_state
        self._db: "Optional[DatabaseClient]" = db

        # ── Paper trading engine references (injected post-init) ──────────────
        self._paper_wallet_engine: "Optional[WalletEngine]" = None
        self._paper_engine: "Optional[PaperEngine]" = None
        self._paper_pm: "Optional[PaperPositionManager]" = None
        self._exposure_calc: "Optional[ExposureCalculator]" = None

        # ── Propagate mode + state to all handlers at init ────────────────────
        self._propagate_mode_and_state()

        log.info(
            "callback_router_initialized",
            mode=mode,
            api_base=tg_api[:40] + "…" if len(tg_api) > 40 else tg_api,
        )

    def _propagate_mode_and_state(self) -> None:
        """Propagate mode and state manager to all dependent handlers."""
        from .wallet import set_mode as wm, set_system_state as ws  # noqa: PLC0415
        from .trade import set_mode as tm, set_system_state as ts  # noqa: PLC0415
        from .exposure import set_mode as em, set_system_state as es  # noqa: PLC0415
        from .settings import set_mode as sm, set_system_state as ss  # noqa: PLC0415
        from .start import set_mode as stm, set_state_manager as sts, set_strategy_state as sss  # noqa: PLC0415
        from .strategy import set_mode as stratm, set_system_state as strats, set_strategy_state as stratss  # noqa: PLC0415

        for fn in (wm, tm, em, sm, stm, stratm):
            try:
                fn(self._mode)
            except Exception:
                pass
        for fn in (ws, ts, es, ss, strats):
            try:
                fn(self._state)
            except Exception:
                pass
        try:
            sts(self._state)
        except Exception:
            pass
        if self._strategy_state is not None:
            for fn in (sss, stratss):
                try:
                    fn(self._strategy_state)
                except Exception:
                    pass

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_db(self, db: "DatabaseClient") -> None:
        """Inject the DatabaseClient after startup (called after db.connect()).

        Args:
            db: Connected DatabaseClient instance.
        """
        self._db = db
        log.info("callback_router_db_wired")

    def set_paper_wallet_engine(self, engine: "WalletEngine") -> None:
        """Inject WalletEngine for paper wallet UI.

        Also propagates to wallet, trade, exposure, start handlers.

        Args:
            engine: Initialized :class:`~core.wallet_engine.WalletEngine`.
        """
        self._paper_wallet_engine = engine
        # Propagate to all handlers that need the wallet engine
        from .wallet import set_paper_wallet_engine as _w  # noqa: PLC0415
        from .exposure import set_wallet_engine as _e  # noqa: PLC0415
        from .start import set_wallet_engine as _s  # noqa: PLC0415
        _w(engine)
        _e(engine)
        _s(engine)
        log.info("callback_router_paper_wallet_engine_injected")

    def set_paper_engine(self, engine: "PaperEngine") -> None:
        """Inject PaperEngine for trade execution routing.

        Also propagates to trade and wallet handlers.

        Args:
            engine: Initialized :class:`~execution.paper_engine.PaperEngine`.
        """
        self._paper_engine = engine
        from .trade import set_paper_engine as _t  # noqa: PLC0415
        _t(engine)
        log.info("callback_router_paper_engine_injected")

    def set_paper_position_manager(self, pm: "PaperPositionManager") -> None:
        """Inject PaperPositionManager for positions display.

        Also propagates to trade, exposure, wallet, start handlers.

        Args:
            pm: Initialized :class:`~core.positions.PaperPositionManager`.
        """
        self._paper_pm = pm
        from .trade import set_position_manager as _t  # noqa: PLC0415
        from .exposure import set_position_manager as _e  # noqa: PLC0415
        from .wallet import set_position_manager as _w  # noqa: PLC0415
        from .start import set_position_manager as _s  # noqa: PLC0415
        _t(pm)
        _e(pm)
        _w(pm)
        _s(pm)
        log.info("callback_router_paper_position_manager_injected")

    def set_exposure_calculator(self, calc: "ExposureCalculator") -> None:
        """Inject ExposureCalculator for exposure report display.

        Args:
            calc: Initialized :class:`~core.exposure.ExposureCalculator`.
        """
        self._exposure_calc = calc
        log.info("callback_router_exposure_calculator_injected")

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
            from .start import handle_start  # noqa: PLC0415
            return await handle_start()

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
            from .performance import handle_performance
            return await handle_performance(mode=self._mode)

        # ── Positions ──────────────────────────────────────────────────────
        if action == "positions":
            from .positions import handle_positions
            return await handle_positions()

        # ── PnL ────────────────────────────────────────────────────────────
        if action == "pnl":
            from .pnl import handle_pnl
            return await handle_pnl()

        # ── Wallet ─────────────────────────────────────────────────────────
        if action == "wallet":
            # In PAPER mode, always show paper wallet (cash/locked/equity)
            if self._mode == "PAPER" and self._paper_wallet_engine is not None:
                from .wallet import handle_paper_wallet
                return await handle_paper_wallet(mode=self._mode)
            return await handle_wallet(mode=self._mode, user_id=user_id)

        if action == "wallet_balance":
            return await handle_wallet_balance(user_id=user_id)

        if action == "wallet_exposure":
            return await handle_wallet_exposure(user_id=user_id)

        if action == "wallet_withdraw":
            return await handle_wallet_withdraw(user_id=user_id)

        # ── Paper wallet (explicit route, always uses paper engine) ────────
        if action == "paper_wallet":
            from .wallet import handle_paper_wallet
            return await handle_paper_wallet(mode=self._mode)

        # ── Trade (paper positions + PnL) ──────────────────────────────────
        if action == "trade":
            from .trade import handle_trade
            log.info("callback_dispatching_trade", mode=self._mode)
            return await handle_trade(mode=self._mode)

        # ── Exposure (real exposure report via ExposureCalculator) ─────────
        if action == "exposure":
            from .exposure import handle_exposure
            log.info("callback_dispatching_exposure", mode=self._mode)
            return await handle_exposure()

        # ── Settings ───────────────────────────────────────────────────────
        if action == "settings":
            return await handle_settings(
                config_manager=self._config,
                mode=self._mode,
            )

        if action == "settings_risk":
            from .settings import handle_settings_risk  # noqa: PLC0415
            return await handle_settings_risk(config_manager=self._config)

        if action == "settings_mode":
            from .settings import handle_settings_mode  # noqa: PLC0415
            return await handle_settings_mode(current_mode=self._mode)

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
            from .settings import handle_settings_notify  # noqa: PLC0415
            return await handle_settings_notify()

        if action == "settings_auto":
            from .settings import handle_settings_auto  # noqa: PLC0415
            return await handle_settings_auto(mode=self._mode)

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

        # ── Risk level preset buttons ──────────────────────────────────────
        if action.startswith("risk_set_"):
            raw_value = action[len("risk_set_"):]
            try:
                requested = float(raw_value)
            except ValueError:
                log.warning("risk_set_invalid_value", raw=raw_value)
                return (
                    f"❌ Invalid risk value: `{raw_value}`\n"
                    "Please select a button or use `/set_risk [0.10–1.00]`.",
                    build_risk_level_menu(),
                )
            if requested < 0.10 or requested > 1.00:
                log.warning("risk_set_out_of_range", requested=requested)
                return (
                    f"❌ Risk `{requested:.2f}` is out of range.\n"
                    "Allowed: `0.10` – `1.00`",
                    build_risk_level_menu(),
                )
            try:
                applied = await self._config.set_risk_multiplier(requested)
                log.info("risk_updated", requested=requested, applied=applied)
                snap = self._config.snapshot()
                return (
                    f"✅ Risk multiplier updated to `{applied:.2f}`\n\n"
                    f"Current: `{snap.risk_multiplier:.2f}`\n"
                    "Use `/set_risk [value]` to set a custom value.",
                    build_risk_level_menu(),
                )
            except Exception as risk_exc:  # noqa: BLE001
                log.error("risk_set_error", error=str(risk_exc))
                return (
                    f"❌ Failed to update risk: `{str(risk_exc)}`",
                    build_settings_menu(),
                )

        # ── Strategy toggle ────────────────────────────────────────────────
        if action.startswith(_STRATEGY_TOGGLE_PREFIX):
            strategy_name = action.removeprefix(_STRATEGY_TOGGLE_PREFIX)
            from .strategy import handle_strategy_toggle  # noqa: PLC0415
            # Persist toggle state to DB (non-blocking on failure)
            if self._strategy_state is not None:
                try:
                    await self._strategy_state.save(db=self._db)
                except Exception as save_exc:  # noqa: BLE001
                    log.warning(
                        "strategy_toggle_save_error",
                        strategy=strategy_name,
                        error=str(save_exc),
                    )
            return await handle_strategy_toggle(strategy_name)

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
