"""Tests for parser-hotfix-outcome-json.

Validates that JSON-encoded string fields (outcomePrices, outcomes,
clobTokenIds) are correctly parsed to native Python types, and that the
trading loop continues even when some markets contain invalid data.

Test IDs: PH-01 through PH-20
"""
from __future__ import annotations

import pytest

from projects.polymarket.polyquantbot.core.utils.json_safe import safe_json_load
from projects.polymarket.polyquantbot.core.market.parser import parse_market
from projects.polymarket.polyquantbot.core.market.ingest import ingest_markets


# ── safe_json_load ─────────────────────────────────────────────────────────────


class TestSafeJsonLoad:
    """PH-01 … PH-08 — core.utils.json_safe.safe_json_load"""

    def test_ph01_parses_json_string_list(self) -> None:
        """PH-01: JSON-encoded string list → native list."""
        result = safe_json_load('["0.545", "0.455"]')
        assert result == ["0.545", "0.455"]

    def test_ph02_returns_list_unchanged(self) -> None:
        """PH-02: Already-parsed list → returned as-is."""
        value = ["0.545", "0.455"]
        assert safe_json_load(value) is value

    def test_ph03_none_returns_none(self) -> None:
        """PH-03: None input → None."""
        assert safe_json_load(None) is None

    def test_ph04_malformed_json_returns_none(self) -> None:
        """PH-04: Malformed JSON string → None (no exception raised)."""
        assert safe_json_load("[broken") is None

    def test_ph05_empty_string_returns_none(self) -> None:
        """PH-05: Empty string is valid JSON (empty string is not valid JSON list)."""
        # json.loads("") raises JSONDecodeError → None
        assert safe_json_load("") is None

    def test_ph06_numeric_returned_unchanged(self) -> None:
        """PH-06: Non-string, non-None value → returned unchanged."""
        assert safe_json_load(42) == 42

    def test_ph07_dict_returned_unchanged(self) -> None:
        """PH-07: Dict value → returned unchanged."""
        d = {"a": 1}
        assert safe_json_load(d) is d

    def test_ph08_parses_json_object_string(self) -> None:
        """PH-08: JSON object string → native dict."""
        result = safe_json_load('{"key": "value"}')
        assert result == {"key": "value"}


# ── parse_market ───────────────────────────────────────────────────────────────


class TestParseMarket:
    """PH-09 … PH-16 — core.market.parser.parse_market"""

    def _valid_raw(self) -> dict:
        """Minimal valid raw market with JSON-encoded strings."""
        return {
            "id": "0xabc123",
            "outcomePrices": '["0.545", "0.455"]',
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": '["id1", "id2"]',
        }

    def test_ph09_parses_json_encoded_strings(self) -> None:
        """PH-09: Full parse of JSON-encoded outcomePrices/outcomes/clobTokenIds."""
        result = parse_market(self._valid_raw())
        assert result is not None
        assert result["market_id"] == "0xabc123"
        assert result["p_market"] == pytest.approx(0.545)
        assert result["prices"] == pytest.approx([0.545, 0.455])
        assert result["outcomes"] == ["Yes", "No"]
        assert result["token_ids"] == ["id1", "id2"]

    def test_ph10_parses_native_list_prices(self) -> None:
        """PH-10: Native list outcomePrices (not JSON string) parsed correctly."""
        market = {
            "id": "0xdef456",
            "outcomePrices": ["0.72", "0.28"],
            "outcomes": ["Yes", "No"],
            "clobTokenIds": ["id3", "id4"],
        }
        result = parse_market(market)
        assert result is not None
        assert result["prices"] == pytest.approx([0.72, 0.28])
        assert result["p_market"] == pytest.approx(0.72)

    def test_ph11_malformed_outcome_prices_returns_none(self) -> None:
        """PH-11: Malformed JSON in outcomePrices → None (market skipped)."""
        market = {**self._valid_raw(), "outcomePrices": "[broken"}
        result = parse_market(market)
        assert result is None

    def test_ph12_non_numeric_price_returns_none(self) -> None:
        """PH-12: Non-numeric value inside outcomePrices → None."""
        market = {**self._valid_raw(), "outcomePrices": '["abc", "0.455"]'}
        result = parse_market(market)
        assert result is None

    def test_ph13_short_array_returns_none(self) -> None:
        """PH-13: Array length < 2 → None."""
        market = {**self._valid_raw(), "outcomePrices": '["0.5"]'}
        result = parse_market(market)
        assert result is None

    def test_ph14_missing_market_id_returns_none(self) -> None:
        """PH-14: Missing id/conditionId/market_id → None."""
        market = {
            "outcomePrices": '["0.545", "0.455"]',
            "outcomes": '["Yes", "No"]',
        }
        result = parse_market(market)
        assert result is None

    def test_ph15_price_out_of_range_returns_none(self) -> None:
        """PH-15: p_market = 0.0 or 1.0 → None (boundary excluded)."""
        for price in ('["0.0", "1.0"]', '["1.0", "0.0"]'):
            market = {**self._valid_raw(), "outcomePrices": price}
            result = parse_market(market)
            assert result is None, f"Expected None for outcomePrices={price}"

    def test_ph16_pre_normalised_dict_accepted(self) -> None:
        """PH-16: Pre-normalised dict with p_market key is accepted."""
        market = {"market_id": "0xaaa", "p_market": 0.65}
        result = parse_market(market)
        assert result is not None
        assert result["market_id"] == "0xaaa"
        assert result["p_market"] == pytest.approx(0.65)

    def test_ph17_empty_outcomes_and_token_ids_ok(self) -> None:
        """PH-17: Missing outcomes/clobTokenIds → empty lists (not None)."""
        market = {
            "id": "0xggg",
            "outcomePrices": '["0.6", "0.4"]',
        }
        result = parse_market(market)
        assert result is not None
        assert result["outcomes"] == []
        assert result["token_ids"] == []

    def test_ph18_unexpected_type_prices_returns_none(self) -> None:
        """PH-18: outcomePrices as int → None."""
        market = {**self._valid_raw(), "outcomePrices": 42}
        result = parse_market(market)
        assert result is None


# ── ingest_markets ─────────────────────────────────────────────────────────────


class TestIngestMarkets:
    """PH-19 … PH-20 — core.market.ingest.ingest_markets"""

    def test_ph19_filters_invalid_markets(self) -> None:
        """PH-19: Mix of valid and invalid markets → only valid ones returned."""
        valid = {
            "id": "0xvalid1",
            "outcomePrices": '["0.6", "0.4"]',
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": '["t1", "t2"]',
        }
        invalid = {"id": "0xinvalid", "outcomePrices": "[broken"}

        result = ingest_markets([valid, invalid])
        assert len(result) == 1
        assert result[0]["market_id"] == "0xvalid1"

    def test_ph20_empty_input_returns_empty(self) -> None:
        """PH-20: Empty input list → empty output."""
        assert ingest_markets([]) == []

    def test_ph21_original_fields_preserved(self) -> None:
        """PH-21: Original market fields are merged into the output dict."""
        raw = {
            "id": "0xmerge",
            "question": "Will it happen?",
            "volume": 50000,
            "outcomePrices": '["0.7", "0.3"]',
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": '["ta", "tb"]',
        }
        result = ingest_markets([raw])
        assert len(result) == 1
        out = result[0]
        # Original fields preserved
        assert out["question"] == "Will it happen?"
        assert out["volume"] == 50000
        # Normalised fields present
        assert out["market_id"] == "0xmerge"
        assert out["p_market"] == pytest.approx(0.7)
        assert out["prices"] == pytest.approx([0.7, 0.3])
        assert out["outcomes"] == ["Yes", "No"]
        assert out["token_ids"] == ["ta", "tb"]
