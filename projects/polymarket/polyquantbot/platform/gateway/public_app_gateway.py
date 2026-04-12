from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..context.resolver import LegacySessionSeed
from .legacy_core_facade import LegacyCoreFacade, LegacyCoreFacadeResolution

PUBLIC_APP_GATEWAY_DISABLED = "disabled"
PUBLIC_APP_GATEWAY_LEGACY_ONLY = "legacy-only"
PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW = "platform-gateway-shadow"
PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY = "platform-gateway-primary"
PUBLIC_APP_GATEWAY_LEGACY_FACADE = "legacy-facade"


@dataclass(frozen=True)
class PublicAppGatewayConfig:
    """Deterministic gateway config for foundation-only app/public seam construction."""

    mode: str = PUBLIC_APP_GATEWAY_DISABLED
    activation_requested: bool = False


@dataclass(frozen=True)
class PublicAppGatewayRoutingTrace:
    """Normalized routing trace contract for deterministic mode/path inspection."""

    selected_mode: str
    selected_path: str
    platform_participated: bool
    adapter_enforced: bool
    runtime_activation_remained_disabled: bool


@dataclass(frozen=True)
class PublicAppGatewayResolution:
    """Boundary result contract for future app/public gateway composition (always non-activating in Phase 2.7)."""

    activated: bool
    runtime_routing_active: bool
    mode: str
    source: str
    facade_resolution: LegacyCoreFacadeResolution | None
    adapter_enforced: bool
    routing_trace: PublicAppGatewayRoutingTrace


@runtime_checkable
class PublicAppGateway(Protocol):
    """Stable app-facing seam that remains non-activating by default."""

    def resolve(self, seed: LegacySessionSeed) -> PublicAppGatewayResolution:
        """Resolve through selected gateway mode without auto-activating runtime routing."""


class PublicAppGatewayDisabled:
    """Deterministic default gateway mode with no runtime activation."""

    def __init__(self, config: PublicAppGatewayConfig | None = None) -> None:
        self._config = config or PublicAppGatewayConfig(mode=PUBLIC_APP_GATEWAY_DISABLED)

    def resolve(self, seed: LegacySessionSeed) -> PublicAppGatewayResolution:
        _ = seed
        routing_trace = PublicAppGatewayRoutingTrace(
            selected_mode=self._config.mode,
            selected_path=PUBLIC_APP_GATEWAY_DISABLED,
            platform_participated=False,
            adapter_enforced=False,
            runtime_activation_remained_disabled=True,
        )
        return PublicAppGatewayResolution(
            activated=False,
            runtime_routing_active=False,
            mode=self._config.mode,
            source=PUBLIC_APP_GATEWAY_DISABLED,
            facade_resolution=None,
            adapter_enforced=False,
            routing_trace=routing_trace,
        )


class PublicAppGatewayLegacyFacade:
    """Foundation-only skeleton mode that resolves context via LegacyCoreFacade seam."""

    def __init__(self, *, facade: LegacyCoreFacade, config: PublicAppGatewayConfig | None = None) -> None:
        self._facade = facade
        self._config = config or PublicAppGatewayConfig(mode=PUBLIC_APP_GATEWAY_LEGACY_FACADE)

    def resolve(self, seed: LegacySessionSeed) -> PublicAppGatewayResolution:
        if not self._facade.assert_adapter_usage():
            raise RuntimeError("adapter_not_used_in_gateway_path")
        if self._config.activation_requested:
            raise RuntimeError("attempted_active_routing_without_explicit_safe_contract")
        facade_resolution = self._facade.prepare_execution_context(seed)
        routing_trace = PublicAppGatewayRoutingTrace(
            selected_mode=self._config.mode,
            selected_path=PUBLIC_APP_GATEWAY_LEGACY_ONLY,
            platform_participated=False,
            adapter_enforced=True,
            runtime_activation_remained_disabled=True,
        )
        return PublicAppGatewayResolution(
            activated=False,
            runtime_routing_active=False,
            mode=self._config.mode,
            source=PUBLIC_APP_GATEWAY_LEGACY_ONLY,
            facade_resolution=facade_resolution,
            adapter_enforced=True,
            routing_trace=routing_trace,
        )


class PublicAppGatewayPlatformGatewayShadow:
    """Shadow-only routing mode that composes platform path without runtime activation."""

    def __init__(self, *, facade: LegacyCoreFacade, config: PublicAppGatewayConfig | None = None) -> None:
        self._facade = facade
        self._config = config or PublicAppGatewayConfig(mode=PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW)

    def resolve(self, seed: LegacySessionSeed) -> PublicAppGatewayResolution:
        if not self._facade.assert_adapter_usage():
            raise RuntimeError("adapter_not_used_in_platform_gateway_path")
        if self._config.activation_requested:
            raise RuntimeError("attempted_active_routing_without_explicit_safe_contract")
        facade_resolution = self._facade.prepare_execution_context(seed)
        routing_trace = PublicAppGatewayRoutingTrace(
            selected_mode=self._config.mode,
            selected_path=PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW,
            platform_participated=True,
            adapter_enforced=True,
            runtime_activation_remained_disabled=True,
        )
        return PublicAppGatewayResolution(
            activated=False,
            runtime_routing_active=False,
            mode=self._config.mode,
            source=PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW,
            facade_resolution=facade_resolution,
            adapter_enforced=True,
            routing_trace=routing_trace,
        )


class PublicAppGatewayPlatformGatewayPrimary:
    """Primary-contract routing mode kept structurally inactive until explicit safe enablement phase."""

    def __init__(self, *, facade: LegacyCoreFacade, config: PublicAppGatewayConfig | None = None) -> None:
        self._facade = facade
        self._config = config or PublicAppGatewayConfig(mode=PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY)

    def resolve(self, seed: LegacySessionSeed) -> PublicAppGatewayResolution:
        if not self._facade.assert_adapter_usage():
            raise RuntimeError("adapter_not_used_in_platform_gateway_path")
        if self._config.activation_requested:
            raise RuntimeError("attempted_active_routing_without_explicit_safe_contract")
        facade_resolution = self._facade.prepare_execution_context(seed)
        routing_trace = PublicAppGatewayRoutingTrace(
            selected_mode=self._config.mode,
            selected_path=PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY,
            platform_participated=True,
            adapter_enforced=True,
            runtime_activation_remained_disabled=True,
        )
        return PublicAppGatewayResolution(
            activated=False,
            runtime_routing_active=False,
            mode=self._config.mode,
            source=PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY,
            facade_resolution=facade_resolution,
            adapter_enforced=True,
            routing_trace=routing_trace,
        )
