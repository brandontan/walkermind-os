from dataclasses import dataclass
from typing import Literal

@dataclass
class GatewayConfig:
    """Configuration for the Public/App Gateway."""
    mode: Literal["legacy", "platform", "disabled"] = "disabled"
    # Future: Add more config options for Phase 2.9