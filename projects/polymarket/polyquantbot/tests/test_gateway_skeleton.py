import pytest
from platform.gateway.config import GatewayConfig
from platform.gateway.factory import GatewayFactory

def test_gateway_default_non_activating():
    """Tests that the default gateway is non-activating."""
    config = GatewayConfig()
    gateway = GatewayFactory.build_gateway(config)
    assert not gateway.is_active
    assert gateway.mode == "disabled"

def test_gateway_explicit_legacy_mode():
    """Tests explicit legacy mode selection."""
    config = GatewayConfig(mode="legacy")
    gateway = GatewayFactory.build_gateway(config)
    assert gateway.is_active
    assert gateway.mode == "legacy"

def test_gateway_explicit_platform_mode():
    """Tests explicit platform mode selection."""
    config = GatewayConfig(mode="platform")
    gateway = GatewayFactory.build_gateway(config)
    assert gateway.is_active
    assert gateway.mode == "platform"