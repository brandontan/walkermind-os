from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

import structlog

from ...platform.context.models import PlatformContextEnvelope
from ...platform.context.resolver import ContextResolver, LegacySessionSeed
from ...platform.accounts.service import AccountService
from ...platform.permissions.service import PermissionService
from ...platform.storage import build_repository_bundle_from_env
from ...platform.strategy_subscriptions.service import StrategySubscriptionService
from ...platform.wallet_auth.service import WalletAuthService
from ...platform.storage.models import AuditEventRecord, utc_now

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class LegacyBridgeResult:
    context: PlatformContextEnvelope | None
    attached: bool
    fallback_used: bool
    strict_mode_blocked: bool


class LegacyContextBridge:
    """Phase 2 foundation bridge, still read-only and feature-flagged."""

    def __init__(self, resolver: ContextResolver | None = None) -> None:
        if resolver is not None:
            self._resolver = resolver
            self._audit_events = None
            return
        bundle = build_repository_bundle_from_env()
        self._audit_events = bundle.audit_events
        self._resolver = ContextResolver(
            account_service=AccountService(repository=bundle.accounts),
            wallet_auth_service=WalletAuthService(repository=bundle.wallet_bindings),
            permission_service=PermissionService(repository=bundle.permissions),
            strategy_subscription_service=StrategySubscriptionService(repository=bundle.strategy_subscriptions)
        )

    @staticmethod
    def bridge_enabled() -> bool:
        return os.getenv("ENABLE_PLATFORM_CONTEXT_BRIDGE", "false").strip().lower() in {"1", "true", "yes"}

    @staticmethod
    def strict_mode_enabled() -> bool:
        return os.getenv("PLATFORM_CONTEXT_STRICT_MODE", "false").strip().lower() in {"1", "true", "yes"}

    def attach_context(self, *, seed: LegacySessionSeed) -> LegacyBridgeResult:
        if not self.bridge_enabled():
            return LegacyBridgeResult(
                context=None,
                attached=False,
                fallback_used=True,
                strict_mode_blocked=False,
            )
        try:
            envelope = self._resolver.resolve(seed)
            log.info(
                "platform_context_resolved",
                user_id=envelope.execution_context.user_id,
                wallet_binding_id=envelope.execution_context.wallet_binding_id,
                trace_id=envelope.execution_context.trace_id,
            )
            log.info(
                "platform_context_bridge_attached",
                user_id=envelope.execution_context.user_id,
                mode=envelope.execution_context.mode,
                trace_id=envelope.execution_context.trace_id,
            )
            return LegacyBridgeResult(
                context=envelope,
                attached=True,
                fallback_used=False,
                strict_mode_blocked=False,
            )
        except Exception as exc:
            log.warning(
                "platform_context_missing",
                reason=str(exc),
                trace_id=seed.trace_id,
            )
            strict_mode = self.strict_mode_enabled()
            if strict_mode:
                self._write_bridge_audit(seed=seed, action="strict_mode_blocked", status="blocked")
                return LegacyBridgeResult(
                    context=None,
                    attached=False,
                    fallback_used=False,
                    strict_mode_blocked=True,
                )
            log.info("legacy_fallback_path_used", trace_id=seed.trace_id)
            self._write_bridge_audit(seed=seed, action="bridge_fallback_used", status="ok")
            return LegacyBridgeResult(
                context=None,
                attached=False,
                fallback_used=True,
                strict_mode_blocked=False,
            )

    def _write_bridge_audit(self, *, seed: LegacySessionSeed, action: str, status: str) -> None:
        if self._audit_events is None:
            return
        self._audit_events.append(
            AuditEventRecord(
                event_id=f"evt-{uuid.uuid4().hex[:10]}",
                user_id=seed.user_id,
                category="bridge",
                action=action,
                status=status,
                trace_id=seed.trace_id,
                payload_json={"mode": seed.mode},
                created_at=utc_now(),
            )
        )
