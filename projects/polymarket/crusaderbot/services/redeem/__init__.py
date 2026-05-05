"""R12e auto-redeem services.

Three collaborators:
  * ``redeem_router`` — resolution detection + dispatch (per-user mode)
  * ``instant_worker`` — fast path with gas guard + 30s retry
  * ``hourly_worker``  — batch drain of redeem_queue with operator alert

The scheduler invokes ``redeem_router.detect_resolutions`` on the resolution
interval and ``hourly_worker.run_once`` on the redeem interval. The instant
worker is fired in-process from the router when a winning position belongs
to a user with ``auto_redeem_mode='instant'``.

All entry points short-circuit when ``Settings.AUTO_REDEEM_ENABLED`` is
false; redeem activity is fully suppressed without raising or crashing the
caller.
"""
from __future__ import annotations

from . import hourly_worker, instant_worker, redeem_router

__all__ = ("redeem_router", "instant_worker", "hourly_worker")
