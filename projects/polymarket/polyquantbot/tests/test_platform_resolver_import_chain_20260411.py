"""Import-chain smoke test for resolver purity surgical fix (PR392).

Verifies that all modules in the import chain load without SyntaxError or
ImportError after the resolver purity fix is applied.
"""
from __future__ import annotations

import importlib
import sys


def _assert_importable(module_path: str) -> None:
    try:
        importlib.import_module(module_path)
    except ImportError as exc:
        raise AssertionError(f"ImportError for {module_path!r}: {exc}") from exc
    except SyntaxError as exc:
        raise AssertionError(f"SyntaxError for {module_path!r}: {exc}") from exc


def test_import_chain_platform_context_resolver() -> None:
    _assert_importable("projects.polymarket.polyquantbot.platform.context.resolver")


def test_import_chain_legacy_context_bridge() -> None:
    _assert_importable("projects.polymarket.polyquantbot.legacy.adapters.context_bridge")


def test_import_chain_execution_strategy_trigger() -> None:
    _assert_importable("projects.polymarket.polyquantbot.execution.strategy_trigger")


def test_import_chain_telegram_command_handler() -> None:
    _assert_importable("projects.polymarket.polyquantbot.telegram.command_handler")


def test_import_chain_main() -> None:
    _assert_importable("projects.polymarket.polyquantbot.main")
