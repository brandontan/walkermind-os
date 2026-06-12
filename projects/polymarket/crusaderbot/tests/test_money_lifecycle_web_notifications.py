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


def test_web_alert_once_uses_metadata_dedup_key():
    src = inspect.getsource(notification_prefs.persist_user_alert_once)
    assert "metadata->>'dedup_key'" in src
    assert "persist_user_alert(" in src
