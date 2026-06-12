from __future__ import annotations

import inspect

from projects.polymarket.crusaderbot import scheduler
from projects.polymarket.crusaderbot.wallet import withdrawals
from projects.polymarket.crusaderbot.webtrader.backend import notification_prefs


def test_deposit_confirm_creates_deduped_web_alert_independent_of_telegram():
    src = inspect.getsource(scheduler._confirm_ready_deposits)
    assert "persist_user_alert_once" in src
    assert 'alert_kind="deposit_confirmed"' in src
    assert 'dedup_key=f"deposit:{d[\'tx_hash\']}:confirmed"' in src
    assert "notifications.send" not in src


def test_withdrawal_completed_creates_deduped_web_alert_only_after_completion():
    src = inspect.getsource(withdrawals._attempt_onchain_transfer)
    assert "RETURNING user_id, id, amount_usdc, destination_address, tx_hash" in src
    assert "persist_user_alert_once" in src
    assert 'alert_kind="withdrawal_confirmed"' in src
    assert 'dedup_key=f"withdrawal:{completed[\'id\']}:completed"' in src
    assert "status = 'completed'" in src


def test_web_alert_once_is_atomic_on_conflict_dedup():
    # WARP•R00T #1808: dedup must be atomic (ON CONFLICT DO NOTHING against the
    # partial unique index), NOT check-then-insert. Pin the atomic shape and
    # the absence of the old SELECT-probe race window.
    src = inspect.getsource(notification_prefs.persist_user_alert_once)
    assert "metadata->>'dedup_key'" in src
    assert "ON CONFLICT" in src
    assert "DO NOTHING" in src
    # The prior check-then-insert SELECT probe must be gone.
    assert "SELECT 1 FROM system_alerts" not in src


def test_migration_101_adds_partial_unique_dedup_index():
    import pathlib

    mig = (
        pathlib.Path(__file__).resolve().parent.parent
        / "migrations/101_system_alerts_dedup_unique.sql"
    ).read_text(encoding="utf-8")
    assert "uq_system_alerts_money_dedup" in mig
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in mig
    assert "metadata->>'dedup_key'" in mig
    assert "WHERE metadata->>'dedup_key' IS NOT NULL" in mig
