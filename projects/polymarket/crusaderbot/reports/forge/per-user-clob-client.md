# WARP•R00T Report — per-user-clob-client

- Validation Tier: MAJOR (per-user real-money key custody surface — even though Step 1 does not yet wire execution, the new module decrypts user keys and constructs the order client per-user; the cross-user isolation invariant lives here)
- Claim Level: FOUNDATION (per #1730 Step 1 — module + tests only; no order path is rewired, ``router`` / ``live.py`` still call the single-wallet ``get_clob_client(s)``)
- Validation Target: ``projects/polymarket/crusaderbot/integrations/clob/user_client.py`` — the cross-user isolation guard (``user_id`` required, hard-fail on missing / wrong type), the single-flight ``asyncio.Task`` per user, the bounded LRU eviction + ``aclose`` on evict, the extracted ``resolve_deposit_wallet_creds`` reusing the proven #1727 / #1729 AsyncSecureClient path
- Not in Scope: execution rewiring (Step 4); per-user deposit-wallet persistence on the ``wallets`` row (Step 2); sweep/bridge funding (Step 3); per-user gasless relayer wiring (Step 3); the pre-post ``resolved_wallet == stored_wallet`` assertion (gated on Step 2 persistence); any live order from a per-user wallet (SENTINEL-gated per #1730 §5)
- Suggested Next Step: WARP🔹CMD review + Step 2 lane — onboarding persists ``wallets.polymarket_deposit_wallet`` (migration + ``create_wallet_for_user`` resolves + stores it; sequential backfill for existing users — Gemini #1730 advisory). Live per-user order remains SENTINEL-gated.

---

## 1. What was built

Step 1 (foundation) of the per-user on-chain execution lane designed in PR #1730. A per-user analogue of ``get_clob_client`` lives at ``integrations/clob/user_client.py`` and exposes:

* ``resolve_deposit_wallet_creds(private_key) -> (wallet, creds)`` — extracted from ``ensure_clob_credentials`` so per-user callers reuse the proven ``AsyncSecureClient`` resolution that #1727 (broker-validated) + #1729 (turnkey auto-derive, merged today) established. Pure: takes a key, returns the SDK-resolved deposit wallet + L2 creds; the key never appears in the return value or in any log.
* ``get_user_clob_client(user_id, settings) -> ClobV2Client`` — the per-user analogue. Decrypts the user's key via ``wallet.vault.get_decrypted_pk``, resolves their deposit wallet + creds, constructs a sig-3 ``ClobV2Client`` with the user's deposit wallet as ``funder_address`` (the maker), and caches it per ``user_id``.

Concurrency + memory follow the #1730 design and the Gemini review on that PR:

* **Single-flight** — concurrent calls for the same ``user_id`` share ONE in-flight ``asyncio.Task`` (one vault decryption + one ``AsyncSecureClient.create``); waiters ``asyncio.shield`` the shared task so a caller's cancellation cannot bring the build down for other waiters and the task's exception is always consumed locally.
* **Bounded LRU eviction** — the per-user cache is an ``OrderedDict`` capped at ``USER_CACHE_CAPACITY=256``; on insert past the boundary the LRU entry is removed and its client's ``aclose`` runs in a fire-and-forget task. ``OrderedDict.move_to_end`` promotes hits to MRU.

Cross-user isolation is the #1 invariant (owner-set in #1730 §4) and lives in this module:

* ``user_id`` is REQUIRED on the public entry point. ``None`` / wrong type raises ``PerUserClobIsolationError`` (subclass of ``ClobError``) and emits a structured ``WARNING`` log naming the violation, so even a swallowed exception still surfaces in logs.
* There is no fallback "default user" path. ``USE_REAL_CLOB=False`` raises ``ClobConfigError`` pointing the caller at ``get_clob_client()`` — paper mode never silently fabricates a per-user client.
* The per-user cache is keyed by ``user_id`` only. There is no shared mutable global client and no read of the existing single-wallet ``_derived`` / ``_derived_wallet`` globals.
* The vault-decrypted private key is scoped to the build closure; it is never stored on the ``_CachedClient`` dataclass (the ``creds`` field is ``repr=False`` for the same reason) and never logged.

The module is re-exported through ``integrations/clob/__init__.py`` so callers don't need to know which submodule defines it.

## 2. Current system architecture (relevant slice)

Single-wallet path (unchanged today):

```text
ensure_clob_credentials(settings)   ─► AsyncSecureClient.create(pk_op, wallet=None)
   _derived  /  _derived_wallet (module globals)
get_clob_client(settings)           ─► ClobV2Client(pk=pk_op, funder=_derived_wallet, sig 3)
   router.execute / live.py uses this client
```

Per-user path (new, foundation only — NOT YET wired into execution):

```text
get_user_clob_client(user_id, settings)
   ├── isolation guard: isinstance(user_id, UUID) else PerUserClobIsolationError
   ├── USE_REAL_CLOB guard: False -> ClobConfigError
   ├── cache hit ─► _user_cache[uid].client (LRU move_to_end)
   ├── in-flight hit ─► await asyncio.shield(task)
   └── miss ─► spawn _build_and_cache(uid, s)
                  vault.get_decrypted_pk(uid)  ─► pk_U  (in-memory only)
                  resolve_deposit_wallet_creds(pk_U)
                    AsyncSecureClient.create(pk_U, wallet=None)
                      ─► (wallet_U, creds_U)
                  ClobV2Client(pk=pk_U, funder=wallet_U, sig 3, creds_U, builder*, breaker, limiter)
                  evict LRU if at capacity ─► aclose(evicted.client)
                  _user_cache[uid] = _CachedClient(client_U, wallet_U, creds_U, t0)
```

The breaker + limiter are the package singletons (``get_clob_breaker(s)`` / ``get_clob_rate_limiter(s)``) — every per-user client throttles against the same bucket and shares circuit state, matching the single-wallet client.

## 3. Files created / modified (full repo-root paths)

Created:

* ``projects/polymarket/crusaderbot/integrations/clob/user_client.py`` — the new module (resolve, ``get_user_clob_client``, single-flight + LRU, isolation guard, ``clear_user_clob_cache`` test seam, ``PerUserClobError`` / ``PerUserClobIsolationError``).
* ``projects/polymarket/crusaderbot/tests/test_user_clob_client.py`` — 14 tests (see §4).
* ``projects/polymarket/crusaderbot/reports/forge/per-user-clob-client.md`` — this report.

Modified:

* ``projects/polymarket/crusaderbot/integrations/clob/__init__.py`` — imports + ``__all__`` entries for the per-user surface (``resolve_deposit_wallet_creds``, ``get_user_clob_client``, ``PerUserClobError``, ``PerUserClobIsolationError``, ``USER_CACHE_CAPACITY``, ``clear_user_clob_cache``).
* ``projects/polymarket/crusaderbot/state/PROJECT_STATE.md`` — Status + ``[COMPLETED]`` + ``[NEXT PRIORITY]`` (per the 7-section surgical-edit rule).
* ``projects/polymarket/crusaderbot/state/CHANGELOG.md`` — append lane-closure entry.

Not modified (deliberate, Step 1 = foundation):

* ``projects/polymarket/crusaderbot/domain/execution/router.py`` / ``live.py`` — still call ``get_clob_client(s)``. Step 4 threads ``user_id`` through.
* ``projects/polymarket/crusaderbot/wallet/vault.py`` / ``create_wallet_for_user`` — Step 2 persists ``wallets.polymarket_deposit_wallet``.

## 4. What is working

Tests (all mocks; no network, no DB, no key material):

* ``test_package_reexports_per_user_surface`` — the per-user surface is reachable from ``clob_pkg``.
* ``test_resolve_returns_wallet_and_creds`` — ``resolve_deposit_wallet_creds`` returns the SDK wallet + ``{api_key, api_secret, passphrase}`` and the private key is NOT present in the creds dict.
* ``test_resolve_rejects_empty_private_key`` — empty key → ``PerUserClobError``.
* ``test_isolation_violation_on_none_user_id`` — ``user_id=None`` → ``PerUserClobIsolationError`` + a structured ``WARNING`` log containing ``"ISOLATION VIOLATION"``; no SDK call, no client built.
* ``test_isolation_violation_on_wrong_type`` — ``user_id="not-a-uuid"`` → ``PerUserClobIsolationError``; no SDK call.
* ``test_paper_mode_refuses`` — ``USE_REAL_CLOB=False`` → ``ClobConfigError`` pointing at ``get_clob_client``.
* ``test_no_key_in_vault_hard_fails`` — missing ``encrypted_key`` → ``PerUserClobError`` naming ``encrypted_key``.
* ``test_two_users_get_distinct_wallets_and_clients`` — two users → two distinct clients with their own resolved wallets (``client_A.funder != client_B.funder``); the SDK saw each user's key exactly once. Proves wallets do NOT cross.
* ``test_same_user_repeat_calls_hit_cache`` — three calls for one user → ONE SDK call + ONE client (cache hit).
* ``test_single_flight_collapses_concurrent_same_user`` — 10 concurrent calls for one user, with a slow vault + slow SDK → ONE vault decryption + ONE SDK call + ONE client; all 10 results are the same instance.
* ``test_single_flight_failure_propagates_and_clears`` — concurrent calls share the failure; the in-flight slot is cleared so a retry (with a key in vault) succeeds.
* ``test_lru_eviction_at_capacity_closes_evicted_client`` — capacity=2 forces the LRU evict; the evicted client's ``aclose`` runs (best-effort background task) and the new entries stay.
* ``test_cache_hit_promotes_to_mru`` — touching an existing entry promotes it past the LRU boundary so a different entry is evicted next.
* ``test_clear_cache_closes_all`` — the test seam drains the cache + closes every client.

Regression: ``pytest -k "clob or deposit_wallet"`` → **248 passed**, 12 pre-existing warnings, ruff clean on the new files.

## 5. Known issues

* **Foundation only.** ``router`` / ``live.py`` still use the single-wallet client; no order yet executes through ``get_user_clob_client``. Step 4 wires it.
* **Persisted-wallet assertion deferred.** #1730 §4 requires every order path to assert ``resolved_wallet == wallets.polymarket_deposit_wallet`` pre-post. That column does not yet exist (Step 2 migration). Step 1 returns the resolved wallet on ``_CachedClient.wallet`` so Step 2 / Step 4 can wire the assertion without changing this module's contract.
* **TTL not implemented.** The LRU bounds memory; we do not yet expire on age. A long-running process may hold a per-user CLOB client for the whole uptime. If creds rotation becomes a concern, add a TTL to the cached entry (the ``created_at`` field is already there).
* **Wrong-cache fallback not wired into ``get_clob_client``.** Operators flipping a user from PAPER → LIVE today still see the single-wallet path. The per-user path activates only when Step 4 threads ``user_id`` through the execution surface.
* **AsyncSecureClient resolution is network-dependent.** It runs the same on-chain factory check ``ensure_clob_credentials`` already does (proven on the real broker in #1727). Cache misses pay one round-trip per user; single-flight collapses concurrent misses; LRU bounds memory.

## 6. What is next

* WARP🔹CMD review of this PR (Validation Tier MAJOR, Claim Level FOUNDATION).
* Step 2 lane — ``WARP/root-per-user-deposit-wallet-persist``: migration adds ``wallets.polymarket_deposit_wallet``; ``create_wallet_for_user`` resolves + stores it on enrolment; sequential backfill job for existing users (Gemini #1730 advisory — no ``asyncio.gather`` to avoid DB-pool + Polymarket-API pressure).
* Step 3 lane — sweep/bridge per-user routing (owner directive: bot sweeps per-user) + gasless relayer wiring (owner directive: ``setup_gasless_wallet`` / relayer endpoints; if the relayer does not cover CLOB ops, fall back to per-user POL top-up for the affected op).
* Step 4 lane — execution rewiring: thread ``user_id`` through ``router.execute`` / ``live.py``; assert ``resolved_wallet == stored_wallet`` pre-post; keep the single-wallet path as fallback behind a flag during rollout.
* Step 5 — per-user staging proof (WARP-74 harness parameterised by a user key, ``allow_fills=false``).
* Step 6 — WARP•SENTINEL audit (cross-user key/fund isolation + key handling) — REQUIRED before the first live per-user order (#1730 §5).
* Gradual rollout — per-user opt-in (existing) gates who is live; start with one user, expand.

---

Validation Tier: MAJOR
Claim Level: FOUNDATION
Validation Target: ``integrations/clob/user_client.py`` — isolation guard, single-flight, bounded LRU + ``aclose`` on evict, ``resolve_deposit_wallet_creds`` extraction
Not in Scope: execution rewiring; per-user wallet persistence; sweep/bridge funding; per-user gasless wiring; pre-post wallet assertion; any live per-user order
Suggested Next Step: WARP🔹CMD review + Step 2 lane
