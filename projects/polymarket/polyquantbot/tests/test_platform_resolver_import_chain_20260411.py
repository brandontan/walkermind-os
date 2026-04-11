from __future__ import annotations


def test_import_chain_main_to_resolver() -> None:
    import projects.polymarket.polyquantbot.main as main_module
    from projects.polymarket.polyquantbot.execution import strategy_trigger
    from projects.polymarket.polyquantbot.legacy.adapters import context_bridge
    from projects.polymarket.polyquantbot.platform.context import resolver
    from projects.polymarket.polyquantbot.telegram import command_handler

    assert main_module is not None
    assert command_handler is not None
    assert strategy_trigger is not None
    assert context_bridge is not None
    assert resolver is not None
