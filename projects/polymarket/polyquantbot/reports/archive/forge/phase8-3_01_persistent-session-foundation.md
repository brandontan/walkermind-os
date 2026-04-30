# What was built

Phase 8.3 implemented a persistent auth/session storage foundation and completed immediate post-merge truth sync for Phase 8.2.

Repo-truth sync completed in this task:
- `PROJECT_STATE.md` updated to close stale Phase 8.2 merge-pending wording.
- `ROADMAP.md` updated to mark Phase 8.2 as done and start Phase 8.3 persistent session lane.
- timestamps advanced using Asia/Jakarta full timestamp format.

Implementation completed in this lane:
- added persistent local-file session store boundary in `server/storage/session_store.py`
- switched `AuthSessionService` session read/write lifecycle from in-memory dict to persistent storage boundary
- preserved trusted scope derivation contract while enforcing persisted session lifecycle states
- added minimal revoke route for truthful session invalidation behavior
- added targeted restart-safe and lifecycle tests

# Current system architecture

Phase 8.3 auth/session persistence slice:
- `server/storage/session_store.py`
  - `PersistentSessionStore` persists session records to deterministic JSON payload (`version=1`)
  - supports `put_session`, `get_session`, and `set_session_status`
  - reloads sessions at process start for restart continuity
- `server/services/auth_session_service.py`
  - now depends on `SessionStore` for session lifecycle operations
  - session issuance persists immediately
  - scope derivation reads persisted session state
  - revoke path mutates persisted status to `revoked`
- `server/main.py`
  - wires `PersistentSessionStore` using `CRUSADER_SESSION_STORAGE_PATH`
  - default local file path: `/tmp/crusaderbot/runtime/foundation_sessions.json`
- `server/api/multi_user_foundation_routes.py`
  - adds `/foundation/sessions/{session_id}/revoke` endpoint
  - `/foundation/auth/scope` and protected wallet reads continue deriving scope from session-backed dependency

# Files created / modified

Created:
- `projects/polymarket/polyquantbot/server/storage/session_store.py`
- `projects/polymarket/polyquantbot/reports/forge/phase8-3_01_persistent-session-foundation.md`

Modified:
- `projects/polymarket/polyquantbot/server/services/auth_session_service.py`
- `projects/polymarket/polyquantbot/server/main.py`
- `projects/polymarket/polyquantbot/server/api/multi_user_foundation_routes.py`
- `projects/polymarket/polyquantbot/tests/test_phase8_1_multi_user_foundation_20260419.py`
- `projects/polymarket/polyquantbot/docs/crusader_multi_user_foundation.md`
- `PROJECT_STATE.md`
- `ROADMAP.md`

# What is working

- issued sessions are persisted to disk through `PersistentSessionStore`
- persisted sessions are loaded after app restart and remain valid for scope derivation
- revoked sessions are rejected at authenticated scope dependency
- expired sessions are rejected deterministically by trusted scope guard
- `/foundation/auth/scope` remains functional with persisted session backend
- protected wallet read route still enforces authenticated scope and ownership checks

# Known issues

- persistence backend is local-file JSON and not yet database-backed
- identity handoff remains trusted-header foundation flow for controlled backend surfaces
- this lane is not full production auth (no OAuth, token rotation platform, or RBAC rollout)

# What is next

- SENTINEL validation for MAJOR Phase 8.3 persistent session foundation lane
- follow-up lane for public client auth handoff integration over this persistent backbone
- follow-up lane for wallet-linking and broader per-user runtime persistence surfaces

Validation Tier   : MAJOR
Claim Level       : FOUNDATION
Validation Target : Persistent session storage boundary + AuthSessionService persistent lifecycle integration + protected foundation auth scope routes in `projects/polymarket/polyquantbot/server/`.
Not in Scope      : Full Telegram/web login UX, OAuth, token rotation platform, RBAC, delegated wallet signing lifecycle, full DB migration platform, and broad wallet lifecycle rollout.
Suggested Next    : SENTINEL required before merge.
