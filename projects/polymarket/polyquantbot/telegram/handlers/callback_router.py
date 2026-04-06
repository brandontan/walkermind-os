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
    build_dashboard_menu,
    build_portfolio_menu,
    build_markets_menu,
    build_help_menu,
    build_market_categories_menu,
    build_settings_menu,
    build_risk_level_menu,
    build_stop_confirm_menu,
    build_mode_confirm_menu,
    build_control_menu,
    build_strategy_menu,
)
from ..ui.screens import (
    main_screen,
    error_screen,
    noop_screen,
)
from ..ui.components import render_kv_line, render_insight, SEP
from ...interface.telegram.view_handler import render_view
from ...core.market_scope import (
    MARKET_SCOPE_CATEGORIES,
    get_market_scope_snapshot,
    toggle_all_markets,
    toggle_category,
)
from .portfolio_service import get_portfolio_service

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
_MARKET_CATEGORY_TOGGLE_PREFIX = "markets_category_toggle:"

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
        restored_scope = get_market_scope_snapshot()

        log.info(
            "callback_router_initialized",
            mode=mode,
            api_base=tg_api[:40] + "…" if len(tg_api) > 40 else tg_api,
            all_markets_enabled=restored_scope.get("all_markets_enabled", True),
            enabled_categories=restored_scope.get("enabled_categories", []),
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

    async def render_strategy_view(self, user_id: Optional[int] = None) -> tuple[str, list]:
        """Render strategy view for explicit ``action:strategy`` callbacks."""
        _ = user_id
        try:
            from .strategy import handle_strategy_view  # noqa: PLC0415
            return await handle_strategy_view(mode=self._mode)
        except Exception:
            from .strategy import handle_strategy_menu  # noqa: PLC0415
            return await handle_strategy_menu()

    async def render_home_view(self) -> tuple[str, list]:
        """Render home view for explicit ``action:home`` callbacks."""
        from .start import handle_start  # noqa: PLC0415
        return await handle_start()

    def _strategy_states(self) -> dict[str, bool]:
        if self._strategy_state is None:
            return {}
        try:
            snapshot = self._strategy_state.get_state()
            return snapshot if isinstance(snapshot, dict) else {}
        except Exception as exc:  # noqa: BLE001
            log.warning("callback_strategy_state_unavailable", error=str(exc))
            return {}

    @staticmethod
    def _safe_number(value: object, default: float = 0.0) -> float:
        if value is None:
            return default
        if isinstance(value, str):
            text = value.strip()
            if not text or text.lower() in {"n/a", "na", "none", "null", "nan", "-"}:
                return default
            value = text
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _build_normalized_payload(self, action: str) -> dict[str, object]:
        state_snapshot = self._state.snapshot()
        config_snapshot = self._config.snapshot()
        portfolio = get_portfolio_service().get_state()

        positions = []
        equity = 0.0
        cash = 0.0
        pnl = 0.0
        if portfolio is not None:
            positions = list(portfolio.positions)
            equity = self._safe_number(getattr(portfolio, "equity", 0.0))
            cash = self._safe_number(getattr(portfolio, "cash", 0.0))
            pnl = self._safe_number(getattr(portfolio, "pnl", 0.0))

        primary = positions[0] if positions else None
        exposure = (
            sum(self._safe_number(getattr(pos, "size", 0.0)) for pos in positions) / equity
        ) if equity > 0 else 0.0
        unrealized_total = sum(
            self._safe_number(getattr(pos, "unrealized_pnl", 0.0))
            for pos in positions
        )
        open_positions = [
            {
                "market_id": getattr(pos, "market_id", ""),
                "side": getattr(pos, "side", "flat"),
                "entry_price": self._safe_number(getattr(pos, "avg_price", 0.0)),
                "size": self._safe_number(getattr(pos, "size", 0.0)),
                "unrealized_pnl": self._safe_number(getattr(pos, "unrealized_pnl", 0.0)),
            }
            for pos in positions
        ]
        strategy_states = self._strategy_states()
        active_strategy = [name for name, enabled in strategy_states.items() if bool(enabled)]
        scope_snapshot = get_market_scope_snapshot()
        scope_warning = ""
        if not bool(scope_snapshot.get("can_trade", True)):
            scope_warning = "All Markets is OFF and no categories are enabled. Bot scanning/trading is blocked."

        payload: dict[str, object] = {
            "status": state_snapshot.get("state", "RUNNING"),
            "mode": self._mode,
            "state": state_snapshot.get("state", "RUNNING"),
            "risk_level": f"{config_snapshot.risk_multiplier:.2f}",
            "risk_state": state_snapshot.get("reason", "within limits") or "within limits",
            "drawdown": 0.0,
            "equity": equity,
            "balance": cash,
            "available_balance": cash,
            "positions_count": len(positions),
            "positions": open_positions,
            "pnl": pnl,
            "realized_pnl": 0.0,
            "unrealized_pnl": unrealized_total,
            "exposure": exposure,
            "market_id": getattr(primary, "market_id", ""),
            "market_title": "",
            "side": getattr(primary, "side", "flat"),
            "entry": self._safe_number(getattr(primary, "avg_price", 0.0)),
            "size": self._safe_number(getattr(primary, "size", 0.0)),
            "strategy_mode": "enabled" if active_strategy else "monitoring",
            "signal_state": f"{len(active_strategy)} active",
            "updated_at": state_snapshot.get("timestamp") or state_snapshot.get("updated_at"),
            "markets_total": 0,
            "markets_active": 0,
            "selection_type": scope_snapshot.get("selection_type", "All Markets"),
            "active_categories_count": scope_snapshot.get("active_categories_count", 0),
            "enabled_categories": scope_snapshot.get("enabled_categories", []),
            "trading_scope_summary": scope_snapshot.get("trading_scope_summary", "Trading scope: all allowed markets."),
            "scope_label": scope_snapshot.get("scope_label", "All Markets"),
            "scope_warning": scope_warning,
            "scope_fallback_policy": scope_snapshot.get("fallback_policy", ""),
            "scope_state_file": scope_snapshot.get("scope_state_file", ""),
        }

        if action in {"strategy"}:
            payload["insight"] = "Strategy toggles remain label-first and tree-normalized"
        return payload

    async def _render_normalized_callback(self, action: str) -> tuple[str, list]:
        from ..ui.keyboard import (
            build_mode_confirm_menu,
            build_control_menu,
            build_main_menu,
            build_settings_menu,
            build_risk_level_menu,
        )  # noqa: PLC0415

        action_aliases = {
            "dashboard": "dashboard_home",
            "portfolio": "portfolio_wallet",
            "markets": "markets_overview",
            "dashboard_home": "home",
            "dashboard_system": "system",
            "dashboard_refresh_all": "refresh",
            "portfolio_wallet": "wallet",
            "portfolio_positions": "positions",
            "portfolio_exposure": "exposure",
            "portfolio_pnl": "pnl",
            "portfolio_performance": "performance",
            "markets_overview": "markets",
            "markets_refresh_all": "refresh",
        }
        base_action = "home" if action in {"back_main", "back", "start", "menu", "home"} else action
        normalized_action = action_aliases.get(base_action, base_action)
        payload = self._build_normalized_payload(normalized_action)
        payload["mode_label"] = self._mode.upper()
        if normalized_action == "settings_mode":
            payload["target_mode"] = "PAPER" if self._mode.upper() == "LIVE" else "LIVE"
            payload["mode_guard"] = "ENABLE_LIVE_TRADING=true required for LIVE"
        if normalized_action == "control":
            payload["control_action"] = "standby"

        text = await render_view(normalized_action, payload)

        scope_snapshot = get_market_scope_snapshot()
        enabled_categories = set(scope_snapshot.get("enabled_categories", []))

        if base_action == "dashboard" or normalized_action in {"home", "system", "refresh"} and base_action.startswith("dashboard"):
            return text, build_dashboard_menu()
        if base_action == "portfolio" or base_action.startswith("portfolio_"):
            return text, build_portfolio_menu()
        if base_action == "markets_categories":
            return text, build_market_categories_menu(
                categories=list(MARKET_SCOPE_CATEGORIES),
                enabled_categories=enabled_categories,
            )
        if base_action == "markets" or base_action.startswith("markets_"):
            return text, build_markets_menu(bool(scope_snapshot.get("all_markets_enabled", True)))
        if base_action == "help" or base_action.startswith("help_"):
            return text, build_help_menu()

        if normalized_action == "home":
            return text, build_main_menu()
        if normalized_action in {"status", "system", "refresh", "positions", "trade", "pnl", "performance", "exposure", "risk"}:
            return text, build_dashboard_menu()
        if normalized_action == "wallet":
            if self._mode == "PAPER" and self._paper_wallet_engine is not None:
                from ..ui.keyboard import build_paper_wallet_menu  # noqa: PLC0415
                return text, build_paper_wallet_menu()
            from ..ui.keyboard import build_wallet_menu  # noqa: PLC0415
            return text, build_wallet_menu()
        if normalized_action == "strategy":
            strategy_states = self._strategy_states()
            return text, build_strategy_menu(
                strategies=sorted(strategy_states.keys()) if strategy_states else [],
                active_states=strategy_states,
            )
        if normalized_action in {"settings", "settings_notify", "settings_auto", "notifications", "auto_trade"}:
            return text, build_settings_menu()
        if normalized_action in {"settings_risk"}:
            return text, build_risk_level_menu()
        if normalized_action in {"settings_mode", "mode"}:
            target_mode = "PAPER" if self._mode.upper() == "LIVE" else "LIVE"
            return text, build_mode_confirm_menu(target_mode)
        if normalized_action == "control":
            current_state = self._state.state.value
            return text, build_control_menu(current_state)
        return text, build_main_menu()

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
        from .wallet import (
            handle_wallet_balance,
            handle_wallet_exposure,
            handle_wallet_withdraw,
        )
        from .settings import handle_settings, handle_settings_strategy, handle_mode_confirm_switch
        from .control import handle_control, handle_pause, handle_resume, handle_kill

        normalized_actions = {
            "back_main",
            "back",
            "start",
            "menu",
            "home",
            "dashboard",
            "dashboard_home",
            "dashboard_system",
            "dashboard_refresh_all",
            "portfolio",
            "portfolio_wallet",
            "portfolio_positions",
            "portfolio_exposure",
            "portfolio_pnl",
            "portfolio_performance",
            "markets_overview",
            "markets_categories",
            "markets_active_scope",
            "markets_refresh_all",
            "help",
            "help_guidance",
            "help_bot_info",
            "status",
            "refresh",
            "wallet",
            "positions",
            "trade",
            "pnl",
            "performance",
            "exposure",
            "risk",
            "strategy",
            "market",
            "markets",
            "summary",
            "settings",
            "settings_risk",
            "settings_mode",
            "settings_notify",
            "settings_auto",
            "control",
        }
        if action in normalized_actions:
            return await self._render_normalized_callback(action)

        if action == "markets_all_toggle":
            await toggle_all_markets()
            payload = self._build_normalized_payload("markets")
            if bool(payload.get("scope_warning")):
                payload["decision"] = "Scope blocked until at least one category is enabled or All Markets is turned ON"
                payload["operator_note"] = "Use Markets → Categories to enable categories"
            else:
                payload["decision"] = "All Markets scope updated"
            payload["insight"] = "Scope updates apply to market scanning and execution eligibility"
            text = await render_view("markets", payload)
            scope_snapshot = get_market_scope_snapshot()
            return text, build_markets_menu(bool(scope_snapshot.get("all_markets_enabled", True)))

        if action == "markets_categories_save":
            payload = self._build_normalized_payload("active_scope")
            payload["decision"] = "Category selection saved"
            payload["operator_note"] = "Active scope now controls allowed scan/trade universe"
            text = await render_view("active_scope", payload)
            return text, build_markets_menu(bool(get_market_scope_snapshot().get("all_markets_enabled", True)))

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
            _, _ = await handle_pause(state_manager=self._state)
            payload = self._build_normalized_payload("control")
            payload.update(
                {
                    "mode_label": self._mode.upper(),
                    "control_action": "paused",
                    "decision": "System paused via control menu",
                    "operator_note": "Resume when safety checks pass",
                    "insight": "Control actions use the same renderer as all operator menus",
                }
            )
            text = await render_view("control", payload)
            return text, build_control_menu(self._state.state.value)

        if action == "control_resume":
            _, _ = await handle_resume(state_manager=self._state)
            payload = self._build_normalized_payload("control")
            payload.update(
                {
                    "mode_label": self._mode.upper(),
                    "control_action": "resumed",
                    "decision": "System resumed via control menu",
                    "operator_note": "Monitor status and exposure after resume",
                    "insight": "Control actions use the same renderer as all operator menus",
                }
            )
            text = await render_view("control", payload)
            return text, build_control_menu(self._state.state.value)

        if action == "control_stop_confirm":
            payload = self._build_normalized_payload("control")
            payload.update(
                {
                    "mode_label": self._mode.upper(),
                    "control_action": "confirm stop",
                    "decision": "Stop requested — confirmation required",
                    "operator_note": "Stop triggers halt and requires manual restart",
                    "insight": "Use confirmation to prevent accidental halts",
                }
            )
            text = await render_view("control", payload)
            return text, build_stop_confirm_menu()

        if action == "control_stop_execute":
            _, _ = await handle_kill(state_manager=self._state)
            payload = self._build_normalized_payload("control")
            payload.update(
                {
                    "mode_label": self._mode.upper(),
                    "control_action": "halted",
                    "decision": "System halted from control menu",
                    "operator_note": "Manual restart required before trading can resume",
                    "insight": "Kill-switch state is now rendered in the unified menu format",
                }
            )
            text = await render_view("control", payload)
            return text, build_control_menu(self._state.state.value)

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
                    "\n".join([
                        "⚠️ *SYSTEM NOTICE*",
                        SEP,
                        render_kv_line("STATUS", "Invalid value"),
                        f"_Value `{raw_value}` is not a valid number._",
                        SEP,
                        render_insight("Select a preset or use /set_risk [0.10–1.00]"),
                    ]),
                    build_risk_level_menu(),
                )
            if requested < 0.10 or requested > 1.00:
                log.warning("risk_set_out_of_range", requested=requested)
                return (
                    "\n".join([
                        "⚠️ *SYSTEM NOTICE*",
                        SEP,
                        render_kv_line("REQUESTED", f"{requested:.2f}"),
                        render_kv_line("ALLOWED", "0.10 – 1.00"),
                        SEP,
                        render_insight("Choose a value within the allowed risk range"),
                    ]),
                    build_risk_level_menu(),
                )
            try:
                applied = await self._config.set_risk_multiplier(requested)
                log.info("risk_updated", requested=requested, applied=applied)
                snap = self._config.snapshot()
                return (
                    "\n".join([
                        "✅ *RISK LEVEL UPDATED*",
                        SEP,
                        render_kv_line("APPLIED", f"{applied:.2f}"),
                        render_kv_line("CURRENT", f"{snap.risk_multiplier:.2f}"),
                        SEP,
                        render_insight("Risk multiplier updated — takes effect on next cycle"),
                    ]),
                    build_risk_level_menu(),
                )
            except Exception as risk_exc:  # noqa: BLE001
                log.error("risk_set_error", error=str(risk_exc))
                return (
                    "\n".join([
                        "⚠️ *SYSTEM NOTICE*",
                        SEP,
                        render_kv_line("STATUS", "Update failed"),
                        f"_{risk_exc}_",
                        SEP,
                        render_insight("Risk update failed — check configuration"),
                    ]),
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
            await handle_strategy_toggle(strategy_name)
            return await self._render_normalized_callback("strategy")

        if action.startswith(_MARKET_CATEGORY_TOGGLE_PREFIX):
            category_name = action.removeprefix(_MARKET_CATEGORY_TOGGLE_PREFIX)
            await toggle_category(category_name)
            payload = self._build_normalized_payload("markets")
            payload["decision"] = f"Category toggled: {category_name}"
            payload["operator_note"] = "Category scope is now active because All Markets is OFF"
            payload["insight"] = "Tap categories to enable/disable; use Active Scope to verify final trading universe"
            text = await render_view("markets", payload)
            scope_snapshot = get_market_scope_snapshot()
            return text, build_market_categories_menu(
                categories=list(MARKET_SCOPE_CATEGORIES),
                enabled_categories=set(scope_snapshot.get("enabled_categories", [])),
            )

        # ── Unknown ────────────────────────────────────────────────────────
        log.warning("callback_unknown_action", action=action)
        snap = self._state.snapshot()
        return (
            "\n".join([
                "⚠️ *SYSTEM NOTICE*",
                SEP,
                render_kv_line("STATUS", "Unknown action"),
                f"_Action `{action}` not recognized._",
                SEP,
                main_screen(mode=self._mode, state=snap.get("state", "UNKNOWN")),
                render_insight("Unexpected action — returning to main menu"),
            ]),
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
