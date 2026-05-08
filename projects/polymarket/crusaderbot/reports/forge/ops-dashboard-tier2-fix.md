# WARP•FORGE Report — Ops Dashboard + Tier 2 Operator Seed

Lane: `WARP/CRUSADERBOT-OPS-DASHBOARD-TIER2-FIX`
Date: 2026-05-08 Asia/Jakarta
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION — adds one HTML route + two POST routes
that delegate to the existing `domain.ops.kill_switch.set_active` source
of truth, and one idempotent release-time DB seeder. No trading or
execution code touched. Activation guards remain NOT SET.
Validation Target: `GET /ops`, `POST /ops/kill`, `POST /ops/resume`,
`scripts/seed_operator_tier.py`, Fly `release_command` wiring.
Not in Scope: auth hardening on `/ops*` (deferred post-demo, in-code
TODO), multi-operator allowlist for `/kill` Telegram surface, schema
migrations.
Suggested Next Step: WARP🔹CMD review + merge — STANDARD tier, no
SENTINEL required per task brief.

---

## 1. What was built

### Tier 2 operator seeder (`scripts/seed_operator_tier.py`)
A new script that reads `ADMIN_USER_IDS` (comma-separated Telegram user
ids) and ensures each id has a row in `users` with `access_tier >= 2`.
Behaviour:
- Existing user with `access_tier < 2` → UPDATE to 2.
- Existing user with `access_tier >= 2` → no-op (we never demote).
- Missing user → INSERT with `access_tier=2`, `auto_trade_on=FALSE`,
  `paused=FALSE`. The `user_settings` row is provisioned lazily on the
  first call to `users.get_settings_for(...)` — keeping this script
  narrow to what the brief asked for.
- Each insert / raise also writes one `audit.log` row
  (`actor_role=operator`, `action=operator_tier_seed`, payload includes
  the affected `telegram_user_id`, `prev_tier`, `new_tier`,
  `source=scripts.seed_operator_tier`).
- All work runs in one DB transaction so a partial failure rolls the
  batch back. Audit writes are best-effort and never break the seed.

Internal status codes (returned by `_run()` for tests + programmatic
callers; the CLI entrypoint `main()` ALWAYS exits 0 so Fly's
release_command never aborts the deploy on a recoverable seeder
failure):
- `0` — seed applied or already in place (no-op).
- `2` — `ADMIN_USER_IDS` unset / empty / unparseable. Logged at WARNING.
- `3` — `DATABASE_URL` missing.
- `4` — DB error (network blip, schema not migrated yet — notably the
  very first deploy where `run_migrations()` runs in the app lifespan
  AFTER the release_command).

Wiring: added `[deploy] release_command = "python -m
crusaderbot.scripts.seed_operator_tier"` to `fly.toml`. The release
hook runs after build, before the new release becomes primary, on
every deploy. The dotted path here is the *installed* package path —
the Fly Dockerfile installs the project as top-level `crusaderbot`
(`include = ["crusaderbot*"]` in `pyproject.toml`), NOT as
`projects.polymarket.crusaderbot` which only exists in the dev repo
layout. The CLI entrypoint `main()` always exits 0 even on the
documented warn / error paths so Fly's release_command (which aborts
the deploy on any non-zero exit) never blocks a release on a missing
operator secret, missing `DATABASE_URL`, or a transient DB blip
(notably first-deploy where `run_migrations()` has not yet run — that
happens later in the app lifespan).

### `/ops` HTML dashboard (`api/ops.py`)
Single-page operator console served as inline HTML — no JS bundle, no
external CSS. Auto-refreshes every 30 seconds via
`<meta http-equiv="refresh">`. Mobile-responsive grid layout (CSS
`grid-template-columns: repeat(auto-fit, minmax(260px, 1fr))`).

Page contents:
- Header strip: service name, version (from `APP_VERSION` falling back
  to `unknown`), mode (PAPER vs LIVE — same activation-guard contract
  as `/health`), uptime since process boot, current UTC timestamp,
  refresh interval.
- Service card — name + stack summary.
- Active users card — `SELECT COUNT(*) FROM users` (degrades to N/A on
  DB failure).
- Kill switch card — colour-coded `ACTIVE` (red) / `PAUSED` (green) /
  N/A (amber). Reads through the cached
  `domain.ops.kill_switch.is_active` so a busy gate is not slammed.
- Health checks card — four rows (database, telegram, alchemy_rpc,
  alchemy_ws) each rendered as ok / fail / warn badge from
  `monitoring.health.run_health_checks()`.
- Controls card — two buttons that POST to `/ops/kill` and
  `/ops/resume`.
- Audit log card — last 10 rows from `audit.log` (ts, action, actor).
- Optional `flash` query param — confirmation banner after a POST
  round-trip.

Every external dependency probe is independent: a DB outage degrades a
single card to "N/A — data not available" but the page still renders so
the operator can see what failed and the kill switch state.

XSS safety: every value rendered into the page goes through
`html.escape`. The `flash` query string included.

### `POST /ops/kill` and `POST /ops/resume`
Thin wrappers that delegate to `domain.ops.kill_switch.set_active`
(`pause` and `resume` actions respectively) — the same path used by
the `/kill` / `/resume` Telegram aliases and the bearer-protected
`/admin/kill` REST endpoint. Each flip:
- Writes one `kill_switch_history` row inside the
  `set_active` transaction (existing R12f behaviour).
- Writes one `audit.log` row from the `/ops` route
  (`action=kill_switch_pause` / `kill_switch_resume`,
  `payload.source="ops_dashboard_web"`) so the source of the flip is
  distinguishable from a Telegram-driven flip.
- Returns a 303 redirect to `/ops?flash=<message>` so the operator
  sees a confirmation banner after the round-trip.

Failure mode: if `set_active` raises, the route still redirects to
`/ops?flash=Kill failed: <ExceptionClass>` — the operator never sees a
500 page.

### Auth note (post-demo TODO)
The `/ops*` surface ships unauthenticated for the demo. Both the
module docstring and the source comment record this explicitly:
`# TODO: add auth hardening post-demo`. The bearer-protected
`/admin/kill` endpoint is preserved as the hardened path — operators
who need auth today use that.

### Runbook update (`docs/runbooks/kill-switch-procedure.md`)
The kill-switch runbook previously said `ADMIN_USER_IDS` was reserved
for a future lane and "not consumed by the runtime today". That is no
longer true — the seeder consumes it on every deploy. Updated the
relevant paragraph to point at `scripts/seed_operator_tier.py` and
clarify that the secret upgrades Tier 2 access only; it does NOT gate
`/kill` / `/resume` Telegram commands (those remain `OPERATOR_CHAT_ID`
single-allowlist).

---

## 2. Current system architecture

```
HTTP browser (operator phone or desktop)
    │
    ▼
api/ops.py
  GET /ops          ── run_health_checks() ──► monitoring.health
                    ── _count_users()      ──► database pool (SELECT COUNT users)
                    ── _kill_switch_state()──► domain.ops.kill_switch.is_active (cached 30s)
                    ── _fetch_audit_tail() ──► database pool (SELECT audit.log LIMIT 10)
                    ── _resolve_mode()     ──► get_settings() — paper unless ALL guards open
                    └── HTMLResponse with auto-refresh meta tag (30s)

  POST /ops/kill    ── domain.ops.kill_switch.set_active(action="pause")
                       └─► system_settings (upsert kill_switch_active=true)
                       └─► kill_switch_history (insert)
                    ── audit.write(action="kill_switch_pause",
                                    payload.source="ops_dashboard_web")
                    └── 303 redirect to /ops?flash=...

  POST /ops/resume  ── domain.ops.kill_switch.set_active(action="resume")
                       └─► system_settings (upsert kill_switch_active=false,
                                              kill_switch_lock_mode=false)
                       └─► kill_switch_history (insert)
                    ── audit.write(action="kill_switch_resume",
                                    payload.source="ops_dashboard_web")
                    └── 303 redirect to /ops?flash=...

Fly.io deploy
    │
    ▼
[deploy] release_command
    │
    ▼
scripts/seed_operator_tier.py
    │
    ├── _parse_ids(os.environ["ADMIN_USER_IDS"])
    ├── connect(asyncpg, DATABASE_URL)
    ├── for tg_id in ids:
    │     INSERT INTO users (telegram_user_id, access_tier=2, ...) ON CONFLICT DO NOTHING
    │     OR UPDATE users SET access_tier=2 WHERE access_tier < 2
    │     INSERT INTO audit.log (actor_role=operator, action=operator_tier_seed, ...)
    └── exit 0|2|3|4

main.py — lifespan unchanged, just adds api_ops to the include_router list.

domain/risk/gate.py step [1] — unchanged. Same is_active call from before.
```

---

## 3. Files created / modified (full repo-root paths)

### Created
- `projects/polymarket/crusaderbot/scripts/seed_operator_tier.py`
- `projects/polymarket/crusaderbot/api/ops.py`
- `projects/polymarket/crusaderbot/tests/test_seed_operator_tier.py`
- `projects/polymarket/crusaderbot/tests/test_api_ops.py`
- `projects/polymarket/crusaderbot/reports/forge/ops-dashboard-tier2-fix.md`

### Modified
- `projects/polymarket/crusaderbot/main.py` — included
  `api_ops.router` alongside `api_health` and `api_admin`. Two-line
  surgical change.
- `projects/polymarket/crusaderbot/fly.toml` — added `[deploy]` block
  with `release_command` invoking the seeder.
- `projects/polymarket/crusaderbot/docs/runbooks/kill-switch-procedure.md`
  — refreshed the `ADMIN_USER_IDS` paragraph in §2 to reflect the new
  Tier 2 seeder consumption.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`,
  `state/WORKTODO.md`, `state/CHANGELOG.md` — surgical state sync.

---

## 4. What is working

- 42 new tests all green (17 seed + 25 ops). Full CrusaderBot suite
  556/556 green (target was 464+).
- Ruff clean on every changed file
  (`scripts/seed_operator_tier.py`, `api/ops.py`,
  `tests/test_seed_operator_tier.py`, `tests/test_api_ops.py`,
  `main.py`).
- Seed script verified across all four exit codes:
  - `0` — happy path with mock DB, counts inserted/raised/noop correctly.
  - `2` — missing or empty `ADMIN_USER_IDS` → warning logged, deploy
    not blocked.
  - `3` — missing `DATABASE_URL`.
  - `4` — DB connect / query failure raises only on the boundary.
- Idempotency: re-running the seed on a database where every operator
  is already Tier 2 returns `noop` for all rows; no UPDATE issued, no
  audit row written.
- Tier 4 protection: a Tier 4 operator (live-eligible) is never
  demoted to Tier 2 — `_seed_one` early-returns `noop` whenever
  current `access_tier >= 2`.
- `/ops` route renders 200 OK with all brief-required content present:
  service name, version, mode (PAPER), uptime, active users count,
  kill switch state, four health badges, kill / resume buttons, audit
  tail, auto-refresh meta tag, mobile-friendly minimal CSS, no
  external dependencies.
- `/ops/kill` and `/ops/resume` delegate to `kill_switch.set_active`
  with `action="pause"` / `action="resume"`, write a matching
  `audit.log` row tagged `source="ops_dashboard_web"`, and 303
  redirect back to `/ops?flash=...` regardless of success or failure.
- XSS / injection guarded: every dynamic value the page renders is
  `html.escape`-d at the source, including the `flash` query param,
  the kill-state label, the audit action / actor, and the version
  string. Test asserts that `<script>` tags in `flash` come back
  encoded.
- DB-degrade safety: when `get_pool` raises (pool not initialised) or
  the query throws, the affected card renders `N/A` and the rest of
  the page still works.

---

## 5. Known issues

- `/ops*` surface is unauthenticated by design for the demo. Code
  comment + module docstring record `# TODO: add auth hardening
  post-demo`. The bearer-protected `/admin/kill` endpoint is the
  hardened path until then.
- The 30-second propagation window between `/ops/kill` and the risk
  gate seeing it on a *different* process is unchanged from R12f
  (cache TTL on `domain.ops.kill_switch._cache`). Same-process
  invalidate is immediate.
- The seeder logs `ADMIN_USER_IDS` parse warnings at WARNING level. A
  noisy multi-operator list with typos will produce one warning per
  bad token — acceptable for a release-time hook.
- Active users card shows total `users` row count (per task brief).
  This counts demo users (Lane 1C `is_demo=TRUE`). A future filter
  toggle could exclude `is_demo=TRUE` rows; not in scope for this
  lane.
- F401 leakage in `lib/` is unchanged — pre-existing, deferred to
  `WARP/LIB-F401-CLEANUP`.

---

## 6. What is next

- WARP🔹CMD merge decision on this PR (STANDARD tier — no SENTINEL
  required).
- Operator sets `ADMIN_USER_IDS` Fly secret with the demo operators'
  Telegram ids before the next deploy so the release_command actually
  has work to do.
- After deploy, operator hits `https://crusaderbot.fly.dev/ops` from a
  phone browser to verify the dashboard renders, the kill / resume
  buttons round-trip, and the audit tail picks up the new
  `kill_switch_pause` / `_resume` entries with
  `source=ops_dashboard_web`.
- Post-demo follow-up lane (DEFERRED): auth hardening on `/ops*`. Two
  options to consider — bearer token like `/admin`, or sign-in via
  Telegram Login Widget. Out of scope for this build per WARP🔹CMD
  brief.

---

## Validation Tier Declaration

- **Tier:** STANDARD
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** `GET /ops`, `POST /ops/kill`,
  `POST /ops/resume`, `scripts/seed_operator_tier.py`, Fly
  `release_command` wiring.
- **Not in Scope:** auth hardening on `/ops*`, multi-operator
  allowlist for `/kill` Telegram surface, schema migrations.
- **SENTINEL:** NOT REQUIRED per task brief.
- **Suggested Next Step:** WARP🔹CMD review + merge.
