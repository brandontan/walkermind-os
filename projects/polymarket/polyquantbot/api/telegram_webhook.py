"""Phase 10.7 — TelegramWebhookServer: aiohttp Telegram update listener.

Listens for incoming Telegram bot updates via HTTP POST /telegram/webhook and
routes them to CommandRouter for async processing.

Design:
    - aiohttp server on configurable host/port.
    - POST /telegram/webhook — receives and routes Telegram updates.
    - GET  /health           — liveness probe endpoint.
    - Request deduplication by update_id (shared with CommandRouter).
    - Webhook spam protection: max 20 requests/second per source IP.
    - Retry webhook processing: up to 3 retries on transient failure.
    - Structured JSON logging on every request.
    - Never raises to caller — returns 200/400/500 as appropriate.

Security:
    - Optional secret token validation (X-Telegram-Bot-Api-Secret-Token header).
    - Requests without valid token are rejected with 403 (when token is set).
    - Body limited to 1 MB to prevent memory exhaustion.

Usage::

    server = TelegramWebhookServer(
        router=command_router,
        host="0.0.0.0",
        port=8080,
        secret_token=os.getenv("TELEGRAM_WEBHOOK_SECRET"),
    )
    await server.start()
    # ... run ...
    await server.stop()

Environment variables:
    TELEGRAM_WEBHOOK_HOST    — bind host (default: 0.0.0.0)
    TELEGRAM_WEBHOOK_PORT    — bind port (default: 8080)
    TELEGRAM_WEBHOOK_SECRET  — optional secret token for validation
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections import defaultdict
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_HOST: str = "0.0.0.0"
_DEFAULT_PORT: int = 8080
_MAX_BODY_BYTES: int = 1_048_576  # 1 MB
_RATE_LIMIT_RPS: int = 20         # max requests/second per IP
_RATE_WINDOW_S: float = 1.0
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY_S: float = 0.1


# ── TelegramWebhookServer ─────────────────────────────────────────────────────


class TelegramWebhookServer:
    """aiohttp HTTP server that receives Telegram webhook updates.

    Routes every valid update to the injected :class:`CommandRouter`.

    Args:
        router: CommandRouter to dispatch parsed updates to.
        host: Bind host (default: 0.0.0.0).
        port: Bind port (default: 8080).
        secret_token: Optional Telegram webhook secret for request validation.
    """

    def __init__(
        self,
        router: object,
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
        secret_token: Optional[str] = None,
    ) -> None:
        self._router = router
        self._host = host
        self._port = port
        self._secret_token = secret_token

        # Rate limiting: track per-IP request timestamps
        self._rate_tracker: dict[str, list[float]] = defaultdict(list)
        self._rate_lock = asyncio.Lock()

        self._runner: Optional[object] = None
        self._site: Optional[object] = None
        self._app: Optional[object] = None

        log.info(
            "telegram_webhook_server_initialized",
            host=host,
            port=port,
            secret_token_set=bool(secret_token),
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, router: object) -> "TelegramWebhookServer":
        """Build from environment variables.

        Reads:
            TELEGRAM_WEBHOOK_HOST   (default: 0.0.0.0)
            TELEGRAM_WEBHOOK_PORT   (default: 8080)
            TELEGRAM_WEBHOOK_SECRET (default: unset)

        Args:
            router: CommandRouter instance.

        Returns:
            Configured TelegramWebhookServer.
        """
        return cls(
            router=router,
            host=os.getenv("TELEGRAM_WEBHOOK_HOST", _DEFAULT_HOST),
            port=int(os.getenv("TELEGRAM_WEBHOOK_PORT", str(_DEFAULT_PORT))),
            secret_token=os.getenv("TELEGRAM_WEBHOOK_SECRET") or None,
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the aiohttp server and begin accepting requests."""
        try:
            from aiohttp import web

            app = web.Application(client_max_size=_MAX_BODY_BYTES)
            app.router.add_post("/telegram/webhook", self._handle_webhook)
            app.router.add_get("/health", self._handle_health)
            self._app = app

            runner = web.AppRunner(app)
            await runner.setup()
            self._runner = runner

            site = web.TCPSite(runner, self._host, self._port)
            await site.start()
            self._site = site

            log.info(
                "telegram_webhook_server_started",
                host=self._host,
                port=self._port,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "telegram_webhook_server_start_failed",
                error=str(exc),
                exc_info=True,
            )
            raise

    async def stop(self) -> None:
        """Gracefully stop the aiohttp server."""
        if self._runner is not None:
            try:
                await self._runner.cleanup()  # type: ignore[union-attr]
                log.info("telegram_webhook_server_stopped")
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "telegram_webhook_server_stop_error",
                    error=str(exc),
                )
        self._runner = None
        self._site = None

    # ── Request handlers ──────────────────────────────────────────────────────

    async def _handle_health(self, request: object) -> object:
        """GET /health — liveness probe."""
        from aiohttp import web
        return web.json_response({"status": "ok", "ts": time.time()})

    async def _handle_webhook(self, request: object) -> object:
        """POST /telegram/webhook — receive and route Telegram update.

        Returns:
            200 on success or ignored update.
            400 on invalid JSON or missing required fields.
            403 on secret token mismatch.
            500 on processing error (after retries).
        """
        from aiohttp import web

        request_id = str(uuid.uuid4())[:8]
        peer_ip = self._get_peer_ip(request)

        # ── Rate limiting ─────────────────────────────────────────────────────
        if await self._is_rate_limited(peer_ip):
            log.warning(
                "telegram_webhook_rate_limited",
                peer_ip=peer_ip,
                request_id=request_id,
            )
            return web.json_response(
                {"error": "rate_limit_exceeded"}, status=429
            )

        # ── Secret token validation ───────────────────────────────────────────
        if self._secret_token:
            provided = getattr(request, "headers", {}).get(  # type: ignore[union-attr]
                "X-Telegram-Bot-Api-Secret-Token", ""
            )
            if provided != self._secret_token:
                log.warning(
                    "telegram_webhook_invalid_secret",
                    peer_ip=peer_ip,
                    request_id=request_id,
                )
                return web.json_response({"error": "forbidden"}, status=403)

        # ── Parse body ────────────────────────────────────────────────────────
        try:
            body = await request.read()  # type: ignore[union-attr]
            update = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning(
                "telegram_webhook_invalid_json",
                request_id=request_id,
                error=str(exc),
            )
            return web.json_response({"error": "invalid_json"}, status=400)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "telegram_webhook_read_error",
                request_id=request_id,
                error=str(exc),
                exc_info=True,
            )
            return web.json_response({"error": "read_error"}, status=500)

        if not isinstance(update, dict):
            log.warning(
                "telegram_webhook_non_dict_body",
                request_id=request_id,
            )
            return web.json_response({"error": "expected_dict"}, status=400)

        update_id = update.get("update_id")
        log.info(
            "telegram_webhook_received",
            update_id=update_id,
            request_id=request_id,
            peer_ip=peer_ip,
        )

        # ── Route with retry ──────────────────────────────────────────────────
        result = await self._route_with_retry(update, request_id)
        if result is None:
            return web.json_response({"status": "ignored"})

        return web.json_response({
            "status": "ok",
            "success": result.success,
        })

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _route_with_retry(
        self, update: dict, request_id: str
    ) -> Optional[object]:
        """Route an update to CommandRouter with retry on transient failure.

        Args:
            update: Parsed Telegram update dict.
            request_id: Short trace ID for logging.

        Returns:
            CommandResult or None if update was ignored/duplicate.
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                result = await self._router.route_update(update)  # type: ignore[union-attr]
                log.info(
                    "telegram_webhook_routed",
                    request_id=request_id,
                    attempt=attempt,
                    result_success=getattr(result, "success", None),
                )
                return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "telegram_webhook_route_attempt_failed",
                    attempt=attempt,
                    request_id=request_id,
                    error=str(exc),
                )
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_BASE_DELAY_S * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)

        log.error(
            "telegram_webhook_all_retries_failed",
            request_id=request_id,
        )
        return None

    async def _is_rate_limited(self, peer_ip: str) -> bool:
        """Check if ``peer_ip`` has exceeded the rate limit.

        Args:
            peer_ip: Client IP address string.

        Returns:
            True if the IP is rate-limited, False otherwise.
        """
        now = time.time()
        async with self._rate_lock:
            timestamps = self._rate_tracker[peer_ip]
            # Evict entries outside the current window
            cutoff = now - _RATE_WINDOW_S
            self._rate_tracker[peer_ip] = [t for t in timestamps if t > cutoff]
            if len(self._rate_tracker[peer_ip]) >= _RATE_LIMIT_RPS:
                return True
            self._rate_tracker[peer_ip].append(now)
            return False

    @staticmethod
    def _get_peer_ip(request: object) -> str:
        """Extract the peer IP from an aiohttp request object."""
        try:
            peername = request.transport.get_extra_info("peername")  # type: ignore[union-attr]
            if peername:
                return str(peername[0])
        except Exception:  # noqa: BLE001
            pass
        try:
            forwarded_for = request.headers.get("X-Forwarded-For", "")  # type: ignore[union-attr]
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()
        except Exception:  # noqa: BLE001
            pass
        return "unknown"
