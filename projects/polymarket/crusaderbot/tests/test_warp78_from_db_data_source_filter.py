"""WARP-78 --from-db data_source filter (cutover trains on paper_real only).

Hermetic — a fake asyncpg pool captures the SQL + bound args so we can assert
the provenance filter is applied. No real DB, no file writes.
"""
from __future__ import annotations

import asyncio
from typing import Any

from projects.polymarket.crusaderbot.domain.strategy import ev_comparator as ev
from projects.polymarket.crusaderbot.domain.strategy import scorer_trainer as tr
from projects.polymarket.crusaderbot.scripts import report_cutover_holdout as rep


def _run(coro):
    return asyncio.run(coro)


class _CaptureConn:
    def __init__(self, sink: dict[str, Any]) -> None:
        self._sink = sink

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self._sink["query"] = query
        self._sink["args"] = args
        return []

    async def __aenter__(self) -> "_CaptureConn":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _CapturePool:
    def __init__(self, sink: dict[str, Any]) -> None:
        self._conn = _CaptureConn(sink)

    def acquire(self) -> _CaptureConn:
        return self._conn


class _BadPool:
    def acquire(self) -> Any:
        raise RuntimeError("db down")


def test_paper_real_filter_applied() -> None:
    sink: dict[str, Any] = {}
    _run(tr.fetch_settled_rows(pool=_CapturePool(sink), data_source="paper_real"))
    assert "data_source = $1" in sink["query"]
    assert sink["args"] == ("paper_real",)


def test_no_filter_when_data_source_none() -> None:
    sink: dict[str, Any] = {}
    _run(tr.fetch_settled_rows(pool=_CapturePool(sink), data_source=None))
    assert "data_source" not in sink["query"]
    assert sink["args"] == ()


def test_default_is_unfiltered_backcompat() -> None:
    # The parked WARP-72 scorer / A-B callers must keep reading every provenance.
    sink: dict[str, Any] = {}
    _run(tr.fetch_settled_rows(pool=_CapturePool(sink)))
    assert "data_source" not in sink["query"]


def test_fetch_failsoft_to_empty() -> None:
    assert _run(tr.fetch_settled_rows(pool=_BadPool(), data_source="paper_real")) == []


def test_ev_comparator_cutover_default_is_paper_real(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def _fake_fetch(pool: object | None = None, *, data_source: str | None = None):
        captured["data_source"] = data_source
        return []

    monkeypatch.setattr(tr, "fetch_settled_rows", _fake_fetch)
    monkeypatch.setattr(ev, "write_ev_model", lambda model, out=None: "(/tmp/fake.json)")

    # default CLI path
    assert ev.main(["--from-db"]) == 0
    assert captured["data_source"] == "paper_real"

    # explicit 'all' disables the provenance filter
    assert ev.main(["--from-db", "--data-source", "all"]) == 0
    assert captured["data_source"] is None


def test_report_renderer_cutover_default_is_paper_real(monkeypatch) -> None:
    # The renderer imports scorer_trainer by its bare path (domain.strategy.…),
    # which is a distinct module object from the projects.* alias, so patch the
    # one _fetch_real_rows actually resolves.
    import domain.strategy.scorer_trainer as dtr  # noqa: PLC0415

    captured: dict[str, Any] = {}

    async def _fake_fetch(pool: object | None = None, *, data_source: str | None = None):
        captured["data_source"] = data_source
        return []

    monkeypatch.setattr(dtr, "fetch_settled_rows", _fake_fetch)
    assert rep.CUTOVER_DATA_SOURCE == "paper_real"
    _run(rep._fetch_real_rows())
    assert captured["data_source"] == "paper_real"
    _run(rep._fetch_real_rows(None))
    assert captured["data_source"] is None
