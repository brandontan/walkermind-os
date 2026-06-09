# WARP•R00T Report — per-user-clob-client-async-hardening

- Validation Tier: MAJOR (per-user real-money key custody surface — same scope as the Step 1 lane it hardens; the single-flight bug below is a cross-user-isolation-adjacent defect because defeating single-flight means concurrent vault decryptions for the same user under cancellation patterns)
- Claim Level: NARROW INTEGRATION (touches ONLY the new ``integrations/clob/user_client.py``; no callers / wiring / execution paths changed)
- Validation Target: ``_build_and_cache`` now owns its own ``_inflight`` cleanup in a ``finally`` keyed by ``asyncio.current_task()``; ``get_user_clob_client`` no longer manages the slot; ``_evict_lru_if_full`` keeps a strong ref to the eviction task; ``clear_user_clob_cache`` cancels + awaits in-flight + background tasks; new ``test_holder_cancellation_does_not_defeat_single_flight`` regression
- Not in Scope: execution rewiring (still Step 4); ``wallets.polymarket_deposit_wallet`` persistence (still Step 2); any change to ``router`` / ``live.py`` / vault / risk gate / strategy logic
- Suggested Next Step: WARP🔹CMD review + merge

---

## 1. What was built

Five-fix follow-up — four from the gemini-code-assist review on #1731 (Step 1 foundation, merged ``de4fc1af``) plus one from the gemini review on this PR (#1732) that surfaced a follow-on edge case. All five findings were validated as real:

* **HIGH — single-flight cancellation race.** PRE: the caller's ``try/except BaseException`` popped ``_inflight[user_id]`` on cancellation. But the underlying ``_build_and_cache`` task is awaited via ``asyncio.shield``, so it keeps running in the background. A waiter arriving during the still-running build would see no in-flight slot and spawn a SECOND ``AsyncSecureClient.create`` for the same user — defeating single-flight. POST: ``_inflight`` is cleared in ``_build_and_cache``'s own ``finally``, keyed by ``asyncio.current_task()``, so the slot disappears exactly when the task finishes (success or failure), never on caller cancellation. The caller is now a thin ``await asyncio.shield(task); return entry.client`` — no try/except, no race surface.
* **HIGH — caller simplification follows from the cleanup move.** PRE: a try/except wrapping ``asyncio.shield`` in ``get_user_clob_client``. POST: removed; the task owns its own slot lifecycle.
* **MEDIUM — eviction-task GC risk.** PRE: the LRU evict ``aclose`` was a bare ``asyncio.create_task(...)``. The event loop only keeps WEAK references to created tasks — a still-running ``aclose`` can be GC'd mid-flight, skipping the close and leaking the client. POST: a module-level ``_background_tasks: set[asyncio.Task[None]]`` holds strong refs; ``add_done_callback(_background_tasks.discard)`` drops the ref once aclose finishes so the set never grows.
* **MEDIUM — test isolation / cache clear semantics.** PRE: ``clear_user_clob_cache`` only dropped the cache + inflight dict; pending tasks could outlive the clear and bleed into the next test. The autouse test fixture also did not touch ``_background_tasks``. POST: ``clear_user_clob_cache`` cancels + ``gather(... return_exceptions=True)``s every in-flight + background task before closing entries; the test fixture clears ``_background_tasks`` too.
* **MEDIUM — second pass: task-cancellation wedges ``_inflight``.** Gemini's review on this PR (#1732) flagged a follow-on edge case in the HIGH-1 fix. PRE: the ``finally`` in ``_build_and_cache`` did ``async with _state_lock: _inflight.pop(...)``. If the BUILD TASK itself is cancelled (vs the caller), the ``async with`` await raises ``CancelledError`` immediately and skips the pop, leaving a dead task in ``_inflight``. Every future ``get_user_clob_client`` for that user would then ``await asyncio.shield(dead_task)`` which re-raises ``CancelledError`` immediately and never repopulates the slot — permanent per-user wedge. POST: the cleanup is extracted into ``_release_inflight(user_id, current)`` and the ``finally`` calls ``await asyncio.shield(_release_inflight(uid, current))``, so the pop completes even when the task is cancelled mid-flight.

Two regression tests **pin** the cancellation-class bugs:

* ``test_holder_cancellation_does_not_defeat_single_flight`` (Gemini #1731 HIGH) — starts caller A, cancels it 20 ms in, asserts ``_inflight`` slot is STILL occupied (the shielded task survived), then a fresh caller B joins the same task and the counters prove ONE vault decrypt + ONE SDK call across both callers.
* ``test_task_cancellation_does_not_wedge_inflight`` (Gemini #1732 MED) — starts a caller, grabs a handle to the in-flight BUILD TASK, cancels the task itself, asserts the ``_inflight`` slot DOES clear (proves the shielded cleanup ran), then a fresh call succeeds. Without ``asyncio.shield`` around ``_release_inflight``, this test would leave a dead task in ``_inflight`` and the fresh call would re-raise ``CancelledError`` indefinitely.

## 2. Current system architecture (relevant slice)

```text
get_user_clob_client(uid, settings)
  ├── isolation guard / USE_REAL_CLOB guard (unchanged)
  ├── cache hit ─► _user_cache[uid].client (LRU move_to_end)
  └── miss:
        async with _state_lock:
          task = _inflight.get(uid) or create_task(_build_and_cache(uid, s))
          _inflight[uid] = task
        return (await asyncio.shield(task)).client   # ← no try/except

_build_and_cache(uid, settings)        (single-flight task body)
  current = asyncio.current_task()
  try:
    entry = await _build_for_user(uid, settings)
    async with _state_lock:
      await _evict_lru_if_full()       # strong-refs eviction aclose tasks
      _user_cache[uid] = entry
      _user_cache.move_to_end(uid)
    return entry
  finally:
    # asyncio.shield around the cleanup so task-cancellation does not
    # skip _inflight.pop and leave a dead task wedging future callers.
    await asyncio.shield(_release_inflight(uid, current))

_release_inflight(uid, task):
  async with _state_lock:
    if _inflight.get(uid) is task:
      _inflight.pop(uid, None)

_evict_lru_if_full()                   (called with _state_lock held)
  while len(_user_cache) >= CAP:
    evicted = _user_cache.popitem(last=False)
    task = create_task(_safe_aclose(evicted.client))
    _background_tasks.add(task)        # ← strong ref
    task.add_done_callback(_background_tasks.discard)
```

The public surface (``resolve_deposit_wallet_creds``, ``get_user_clob_client``, ``PerUserClobError``, ``PerUserClobIsolationError``, ``USER_CACHE_CAPACITY``, ``clear_user_clob_cache``) is byte-compatible.

## 3. Files created / modified (full repo-root paths)

Modified:

* ``projects/polymarket/crusaderbot/integrations/clob/user_client.py`` — ``_build_and_cache`` finally + current_task slot release; ``get_user_clob_client`` try/except removed; ``_evict_lru_if_full`` strong-ref + done-callback; ``clear_user_clob_cache`` cancel + gather; ``_background_tasks`` module-level set.
* ``projects/polymarket/crusaderbot/tests/test_user_clob_client.py`` — fixture clears ``_background_tasks``; new ``test_holder_cancellation_does_not_defeat_single_flight``.

Created:

* ``projects/polymarket/crusaderbot/reports/forge/per-user-clob-client-async-hardening.md`` — this report.

State / changelog:

* ``projects/polymarket/crusaderbot/state/PROJECT_STATE.md`` (Status + [COMPLETED] + [NEXT PRIORITY]).
* ``projects/polymarket/crusaderbot/state/CHANGELOG.md`` (append).

NOT modified: execution routing / ``router`` / ``live.py`` / vault / migrations / risk constants / Kelly / ``ENABLE_LIVE_TRADING`` / ``USE_CLOB_V2`` default / kill switch / strategy entry-exit / the per-user public API surface.

## 4. What is working

* 15 user_client tests pass (14 inherited + 1 new cancellation regression).
* Full ``clob`` + ``deposit_wallet`` regression: **249 passed**, 3066 deselected, 12 pre-existing warnings.
* ruff clean on touched files.
* The new ``test_holder_cancellation_does_not_defeat_single_flight`` deterministically reproduces the pre-fix bug: applied to the pre-fix code it FAILS (two SDK calls); applied to the post-fix code it PASSES (one SDK call).

## 5. Known issues

* None introduced. The strong-ref set ``_background_tasks`` is bounded by ``USER_CACHE_CAPACITY`` in the worst case (one eviction per insert), so it cannot grow without bound.
* The hardening does not change the FOUNDATION-only posture: execution path still uses the single-wallet client (Step 4 wires per-user). Pre-post ``resolved_wallet == stored_wallet`` assertion still gated on Step 2 (column).

## 6. What is next

* WARP🔹CMD review + merge.
* Step 2 lane (``WARP/root-per-user-deposit-wallet-persist``) per the #1730 plan and Gemini #1730 advisory (sequential backfill).
* Live per-user order remains SENTINEL-gated (#1730 §5).

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: ``integrations/clob/user_client.py`` async hardening — task-owned ``_inflight`` cleanup, eviction strong-ref, ``clear_user_clob_cache`` cancel+gather, cancellation regression test
Not in Scope: execution rewiring; per-user wallet persistence; sweep/bridge funding; per-user gasless wiring; any change to the public API surface
Suggested Next Step: WARP🔹CMD review + merge
