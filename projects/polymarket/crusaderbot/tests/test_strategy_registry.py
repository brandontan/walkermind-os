"""Foundation tests for the CrusaderBot strategy plane.

Covers:
    BaseStrategy ABC enforcement
    StrategyRegistry singleton, register / get / list / filter behaviour
    SignalCandidate / ExitDecision / MarketFilters / UserContext invariants

No execution, no risk, no signal generation in scope — these tests exist to
lock the foundation contract before later phases wire in real strategies.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from projects.polymarket.crusaderbot.domain.strategy import (
    BaseStrategy,
    ExitDecision,
    MarketFilters,
    SignalCandidate,
    StrategyRegistry,
    UserContext,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _StubStrategy(BaseStrategy):
    """Minimal concrete BaseStrategy used across tests."""

    name = "stub_strategy"
    version = "1.0.0"
    risk_profile_compatibility = ["conservative", "balanced", "aggressive"]

    async def scan(
        self,
        market_filters: MarketFilters,
        user_context: UserContext,
    ) -> list[SignalCandidate]:
        return []

    async def evaluate_exit(self, position: dict) -> ExitDecision:
        return ExitDecision(should_exit=False, reason="hold")

    def default_tp_sl(self) -> tuple[float, float]:
        return (0.20, 0.10)


def _make_strategy(
    *,
    name: str = "stub_strategy",
    version: str = "1.0.0",
    compat: list[str] | None = None,
) -> BaseStrategy:
    cls = type(
        f"_S_{name}",
        (_StubStrategy,),
        {
            "name": name,
            "version": version,
            "risk_profile_compatibility": compat
            if compat is not None
            else ["balanced"],
        },
    )
    return cls()


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    StrategyRegistry._reset_for_tests()
    yield
    StrategyRegistry._reset_for_tests()


# ---------------------------------------------------------------------------
# BaseStrategy ABC
# ---------------------------------------------------------------------------


def test_base_strategy_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        BaseStrategy()  # type: ignore[abstract]


def test_base_strategy_subclass_missing_methods_cannot_instantiate() -> None:
    class Incomplete(BaseStrategy):
        name = "incomplete"
        version = "0.1.0"
        risk_profile_compatibility = ["balanced"]

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_concrete_subclass_instantiates_and_exposes_metadata() -> None:
    s = _StubStrategy()
    assert s.name == "stub_strategy"
    assert s.version == "1.0.0"
    assert "balanced" in s.risk_profile_compatibility


def test_default_tp_sl_returns_tuple() -> None:
    tp, sl = _StubStrategy().default_tp_sl()
    assert isinstance(tp, float)
    assert isinstance(sl, float)


# ---------------------------------------------------------------------------
# StrategyRegistry — singleton
# ---------------------------------------------------------------------------


def test_registry_instance_is_singleton() -> None:
    a = StrategyRegistry.instance()
    b = StrategyRegistry.instance()
    assert a is b


def test_registry_singleton_persists_registrations() -> None:
    StrategyRegistry.instance().register(_make_strategy(name="alpha"))
    assert StrategyRegistry.instance().get("alpha").name == "alpha"


# ---------------------------------------------------------------------------
# StrategyRegistry — register
# ---------------------------------------------------------------------------


def test_register_stores_strategy() -> None:
    reg = StrategyRegistry.instance()
    reg.register(_make_strategy(name="alpha"))
    assert reg.get("alpha").name == "alpha"


def test_register_duplicate_name_raises_value_error() -> None:
    reg = StrategyRegistry.instance()
    reg.register(_make_strategy(name="alpha", version="1.0.0"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_make_strategy(name="alpha", version="2.0.0"))


def test_register_non_basestrategy_raises_type_error() -> None:
    reg = StrategyRegistry.instance()

    class NotAStrategy:
        name = "fake"
        version = "1.0.0"
        risk_profile_compatibility = ["balanced"]

    with pytest.raises(TypeError):
        reg.register(NotAStrategy())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_name",
    ["", "Bad", "1strategy", "has space", "x" * 51, "weird-name", "UPPER"],
)
def test_register_invalid_name_raises_value_error(bad_name: str) -> None:
    reg = StrategyRegistry.instance()
    with pytest.raises(ValueError, match="name"):
        reg.register(_make_strategy(name=bad_name))


@pytest.mark.parametrize(
    "bad_version",
    ["", "1", "1.0", "v1.0.0", "1.0.0.0", "abc"],
)
def test_register_invalid_version_raises_value_error(bad_version: str) -> None:
    reg = StrategyRegistry.instance()
    with pytest.raises(ValueError, match="version"):
        reg.register(_make_strategy(name="alpha", version=bad_version))


def test_register_accepts_semver_with_prerelease() -> None:
    reg = StrategyRegistry.instance()
    reg.register(_make_strategy(name="alpha", version="1.2.3-beta.1"))
    assert reg.get("alpha").version == "1.2.3-beta.1"


def test_register_empty_compatibility_raises_value_error() -> None:
    reg = StrategyRegistry.instance()
    with pytest.raises(ValueError, match="risk_profile_compatibility"):
        reg.register(_make_strategy(name="alpha", compat=[]))


def test_register_invalid_compatibility_raises_value_error() -> None:
    reg = StrategyRegistry.instance()
    with pytest.raises(ValueError, match="risk_profile_compatibility"):
        reg.register(_make_strategy(name="alpha", compat=["balanced", "yolo"]))


# ---------------------------------------------------------------------------
# StrategyRegistry — get / list / filter
# ---------------------------------------------------------------------------


def test_get_unknown_name_raises_key_error() -> None:
    reg = StrategyRegistry.instance()
    with pytest.raises(KeyError):
        reg.get("missing")


def test_list_available_returns_all_registered_sorted() -> None:
    reg = StrategyRegistry.instance()
    reg.register(_make_strategy(name="zeta", version="1.0.0", compat=["balanced"]))
    reg.register(
        _make_strategy(name="alpha", version="2.1.0", compat=["aggressive"])
    )

    listed = reg.list_available()
    assert [item["name"] for item in listed] == ["alpha", "zeta"]
    assert listed[0] == {
        "name": "alpha",
        "version": "2.1.0",
        "risk_profile_compatibility": ["aggressive"],
    }
    assert listed[1]["risk_profile_compatibility"] == ["balanced"]


def test_list_available_returns_empty_when_no_strategies() -> None:
    assert StrategyRegistry.instance().list_available() == []


def test_get_compatible_filters_by_profile() -> None:
    reg = StrategyRegistry.instance()
    reg.register(
        _make_strategy(name="copy_trade", compat=["conservative", "balanced"])
    )
    reg.register(_make_strategy(name="momentum", compat=["aggressive"]))
    reg.register(
        _make_strategy(
            name="signal_following", compat=["conservative", "balanced", "aggressive"]
        )
    )

    conservative = [s.name for s in reg.get_compatible("conservative")]
    aggressive = [s.name for s in reg.get_compatible("aggressive")]

    assert conservative == ["copy_trade", "signal_following"]
    assert aggressive == ["momentum", "signal_following"]


def test_get_compatible_invalid_profile_raises_value_error() -> None:
    reg = StrategyRegistry.instance()
    with pytest.raises(ValueError):
        reg.get_compatible("yolo")


def test_get_compatible_returns_empty_when_no_match() -> None:
    reg = StrategyRegistry.instance()
    reg.register(_make_strategy(name="momentum_only", compat=["aggressive"]))
    assert reg.get_compatible("conservative") == []


# ---------------------------------------------------------------------------
# Type invariants
# ---------------------------------------------------------------------------


def test_signal_candidate_valid_construction() -> None:
    sc = SignalCandidate(
        market_id="m1",
        condition_id="c1",
        side="YES",
        confidence=0.8,
        suggested_size_usdc=50.0,
        strategy_name="alpha",
        signal_ts=datetime.now(timezone.utc),
    )
    assert sc.metadata == {}


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"side": "MAYBE"}, "side"),
        ({"confidence": -0.1}, "confidence"),
        ({"confidence": 1.1}, "confidence"),
        ({"suggested_size_usdc": -1.0}, "suggested_size_usdc"),
        ({"market_id": ""}, "market_id"),
        ({"condition_id": ""}, "condition_id"),
        ({"strategy_name": ""}, "strategy_name"),
    ],
)
def test_signal_candidate_invalid_inputs_raise(kwargs: dict, match: str) -> None:
    base = {
        "market_id": "m1",
        "condition_id": "c1",
        "side": "YES",
        "confidence": 0.5,
        "suggested_size_usdc": 10.0,
        "strategy_name": "alpha",
        "signal_ts": datetime.now(timezone.utc),
    }
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        SignalCandidate(**base)


def test_exit_decision_hold_requires_should_exit_false() -> None:
    ExitDecision(should_exit=False, reason="hold")
    with pytest.raises(ValueError):
        ExitDecision(should_exit=True, reason="hold")


def test_exit_decision_strategy_exit_requires_should_exit_true() -> None:
    ExitDecision(should_exit=True, reason="strategy_exit")
    with pytest.raises(ValueError):
        ExitDecision(should_exit=False, reason="strategy_exit")


def test_exit_decision_invalid_reason_raises() -> None:
    with pytest.raises(ValueError):
        ExitDecision(should_exit=False, reason="other")


def test_market_filters_validation() -> None:
    MarketFilters(
        categories=["politics"],
        min_liquidity=10_000.0,
        max_time_to_resolution_days=30,
        blacklisted_market_ids=[],
    )
    with pytest.raises(ValueError):
        MarketFilters(
            categories=[],
            min_liquidity=-1.0,
            max_time_to_resolution_days=30,
            blacklisted_market_ids=[],
        )
    with pytest.raises(ValueError):
        MarketFilters(
            categories=[],
            min_liquidity=0.0,
            max_time_to_resolution_days=-1,
            blacklisted_market_ids=[],
        )


def test_user_context_validation() -> None:
    UserContext(
        user_id="u1",
        sub_account_id="s1",
        risk_profile="balanced",
        capital_allocation_pct=0.5,
        available_balance_usdc=1000.0,
    )
    with pytest.raises(ValueError, match="risk_profile"):
        UserContext(
            user_id="u1",
            sub_account_id="s1",
            risk_profile="yolo",
            capital_allocation_pct=0.5,
            available_balance_usdc=1000.0,
        )
    with pytest.raises(ValueError, match="capital_allocation_pct"):
        UserContext(
            user_id="u1",
            sub_account_id="s1",
            risk_profile="balanced",
            capital_allocation_pct=1.5,
            available_balance_usdc=1000.0,
        )
    with pytest.raises(ValueError, match="available_balance_usdc"):
        UserContext(
            user_id="u1",
            sub_account_id="s1",
            risk_profile="balanced",
            capital_allocation_pct=0.5,
            available_balance_usdc=-1.0,
        )
    with pytest.raises(ValueError, match="user_id"):
        UserContext(
            user_id="",
            sub_account_id="s1",
            risk_profile="balanced",
            capital_allocation_pct=0.5,
            available_balance_usdc=0.0,
        )
