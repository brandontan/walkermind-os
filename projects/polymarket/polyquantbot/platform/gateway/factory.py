from .config import GatewayConfig
from .legacy_core_facade import LegacyCoreFacade
from .public_app_gateway import PublicAppGateway

class GatewayFactory:
    """Factory for deterministic gateway construction."""

    @staticmethod
    def build_gateway(config: GatewayConfig) -> PublicAppGateway:
        """Builds the gateway with the given config."""
        facade = LegacyCoreFacade()  # Reuse Phase 2.8 facade seam
        return PublicAppGateway(facade, config)