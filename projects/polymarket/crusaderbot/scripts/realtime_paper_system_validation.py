"""Realtime paper full-system validation harness.

Runs evidence-oriented checks and prints markdown + JSON summary.
Never fakes success: blocked dependencies are marked NOT_VALIDATED.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from projects.polymarket.crusaderbot.config import get_settings
from projects.polymarket.crusaderbot.database import close_pool, init_pool
from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import run_once as signal_scan_run_once


@dataclass
class CheckResult:
    area: str
    check: str
    status: str  # PASSED | FAILED | NOT_VALIDATED
    detail: str


NS = "warp_rt_validation"


async def _db_checks() -> list[CheckResult]:
    out: list[CheckResult] = []
    pool = await init_pool()
    async with pool.acquire() as conn:
        tables = [
            "users", "user_settings", "wallets", "positions", "orders",
            "signal_publications", "user_strategies", "insights_weekly",
        ]
        existing = set(await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        names = {r["tablename"] for r in existing}
        missing = [t for t in tables if t not in names]
        out.append(CheckResult("database", "required tables exist", "PASSED" if not missing else "FAILED", f"missing={missing}"))

        a = 990001
        b = 990002
        await conn.execute(
            """
            INSERT INTO users (id, telegram_user_id, username, access_tier, auto_trade_on, paused)
            VALUES (gen_random_uuid(), $1, $2, 3, TRUE, FALSE),
                   (gen_random_uuid(), $3, $4, 3, TRUE, FALSE)
            ON CONFLICT (telegram_user_id) DO NOTHING
            """,
            a, f"{NS}_user_a", b, f"{NS}_user_b",
        )
        rows = await conn.fetch(
            "SELECT telegram_user_id, username FROM users WHERE telegram_user_id IN ($1,$2) ORDER BY telegram_user_id",
            a, b,
        )
        out.append(CheckResult("multi_user", "two test users available", "PASSED" if len(rows) == 2 else "FAILED", f"rows={len(rows)}"))
    return out


async def _market_scan_check() -> CheckResult:
    token = os.getenv("HEISENBERG_API_TOKEN")
    if not token:
        return CheckResult("market_signal", "market provider credential", "NOT_VALIDATED", "HEISENBERG_API_TOKEN missing")
    try:
        summary = await signal_scan_run_once()
        return CheckResult("market_signal", "signal scanner run_once", "PASSED", f"summary={summary}")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("market_signal", "signal scanner run_once", "FAILED", f"{type(exc).__name__}: {exc}")


def _guard_checks() -> list[CheckResult]:
    keys = [
        "ENABLE_LIVE_TRADING", "EXECUTION_PATH_VALIDATED", "CAPITAL_MODE_CONFIRMED", "RISK_CONTROLS_VALIDATED", "USE_REAL_CLOB",
    ]
    out = []
    for k in keys:
        v = os.getenv(k)
        ok = (v is None) or (str(v).lower() in {"0", "false", "off", "not_set"})
        out.append(CheckResult("guards", f"{k} OFF/NOT SET", "PASSED" if ok else "FAILED", f"value={v}"))
    return out


async def run_harness() -> dict[str, Any]:
    settings = get_settings()
    results: list[CheckResult] = []
    try:
        results.extend(_guard_checks())
        results.extend(await _db_checks())
        results.append(await _market_scan_check())
        results.append(CheckResult("telegram_ui", "route-check", "NOT_VALIDATED", "requires Telegram bot runtime interaction"))
        results.append(CheckResult("paper_lifecycle", "open/close lifecycle", "NOT_VALIDATED", "requires live runtime callbacks or seeded publication flow"))
        results.append(CheckResult("health", "/health runtime probe", "NOT_VALIDATED", "requires running app process endpoint"))
    finally:
        await close_pool()

    counts = {"PASSED": 0, "FAILED": 0, "NOT_VALIDATED": 0}
    for r in results:
        counts[r.status] += 1
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "database_url_host": settings.DATABASE_URL.split("@")[ -1].split("/")[0],
        "results": [asdict(r) for r in results],
        "summary": counts,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Realtime Paper System Validation Harness Result",
        f"- Timestamp (UTC): {payload['timestamp_utc']}",
        f"- DB Host: {payload['database_url_host']}",
        f"- Summary: {payload['summary']}",
        "",
        "| Area | Check | Status | Detail |",
        "|---|---|---|---|",
    ]
    for r in payload["results"]:
        lines.append(f"| {r['area']} | {r['check']} | {r['status']} | {str(r['detail']).replace('|','/')} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()
    payload = asyncio.run(run_harness())
    print(_render_markdown(payload))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)


if __name__ == "__main__":
    main()
