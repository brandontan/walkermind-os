from .config import GatewayConfig
from .legacy_core_facade import LegacyCoreFacade

class PublicAppGateway:
    """Non-activating public/app gateway skeleton."""

    def __init__(self, facade: LegacyCoreFacade, config: GatewayConfig):
        self._facade = facade
        self._config = config

    @property
    def is_active(self) -> bool:
        """Returns True if the gateway is in an active mode."""
        return self._config.mode != "disabled"

    @property
    def mode(self) -> str:
        """Returns the current mode."""
        return self._config.mode