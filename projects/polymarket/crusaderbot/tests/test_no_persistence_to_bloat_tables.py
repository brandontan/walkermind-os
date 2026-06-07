"""WARP-82 guard — no production code may persist to the killed bloat tables.

Scans the crusaderbot production source (excluding tests/, migrations/, and the
one-off backup tables) for any write (INSERT INTO / UPDATE) targeting the four
real-time-persistence tables dropped in WARP-82. Must find zero — a regression
re-adding a writer fails here.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]   # projects/polymarket/crusaderbot
_TABLES = ("market_snapshots", "heisenberg_realtime_trades", "risk_log", "job_runs")
_EXCLUDE_DIRS = {"tests", "migrations", "reports", "docs"}

_WRITE_RE = re.compile(
    r"(insert\s+into|update)\s+(market_snapshots|heisenberg_realtime_trades|risk_log|job_runs)\b",
    re.IGNORECASE,
)


def _production_py_files():
    for p in _ROOT.rglob("*.py"):
        rel = p.relative_to(_ROOT)
        if rel.parts and rel.parts[0] in _EXCLUDE_DIRS:
            continue
        yield p


def test_no_write_sites_to_bloat_tables():
    offenders: list[str] = []
    for p in _production_py_files():
        text = p.read_text(encoding="utf-8")
        for m in _WRITE_RE.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            offenders.append(f"{p.relative_to(_ROOT)}:{line_no} -> {m.group(0)!r}")
    assert not offenders, (
        "WARP-82 killed durable persistence to these tables; a writer was "
        "re-introduced:\n" + "\n".join(offenders)
    )


def test_tables_are_listed_for_drop_in_a_migration():
    """Sanity: 087 drops the three reader-safe tables; 088 drops job_runs.

    job_runs was deferred out of 087 — its writer was killed in WARP-82 but three
    operator surfaces still read it via raw SQL. The follow-up lane repoints those
    readers to the in-memory ring, so 088 can drop job_runs without erroring them.
    """
    mig_dir = _ROOT / "migrations"
    drops_087 = "\n".join(
        p.read_text(encoding="utf-8").lower() for p in mig_dir.glob("087_*.sql")
    )
    for tbl in ("market_snapshots", "heisenberg_realtime_trades", "risk_log"):
        assert f"drop table if exists {tbl}" in drops_087, f"087 must drop {tbl}"
    drops_088 = "\n".join(
        p.read_text(encoding="utf-8").lower() for p in mig_dir.glob("088_*.sql")
    )
    assert "drop table if exists job_runs" in drops_088, "088 must drop job_runs"


_READ_RE = re.compile(r"""\b(from|join)\s+['"]?job_runs['"]?\b""", re.IGNORECASE)


def test_no_read_sites_to_job_runs():
    """No production code may SELECT FROM job_runs — the table is dropped (088).

    Readers were repointed to the in-memory job ring (domain/ops/job_tracker.py);
    a re-introduced raw-SQL read of the dropped table fails here.
    """
    offenders: list[str] = []
    for p in _production_py_files():
        text = p.read_text(encoding="utf-8")
        for m in _READ_RE.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            offenders.append(f"{p.relative_to(_ROOT)}:{line_no} -> {m.group(0)!r}")
    assert not offenders, (
        "job_runs is dropped (088); read it from the in-memory ring instead:\n"
        + "\n".join(offenders)
    )
