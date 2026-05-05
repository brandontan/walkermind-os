# WARP•FORGE — P3A Strategy Registry Foundation

Branch: `WARP/CRUSADERBOT-P3A-STRATEGY-REGISTRY`
Validation Tier: STANDARD
Claim Level: FOUNDATION ONLY — pure interface + registry + persistence DDL, zero execution
Validation Target: `BaseStrategy` ABC contract + `StrategyRegistry` boundary + dataclass invariants + migration 008 idempotency
Not in Scope: Copy Trade strategy, Signal Following strategy, signal scan loop, execution queue, risk gate wiring, CLOB client, activation guards, Telegram strategy-config UI
Suggested Next Step: P3b — implement Copy Trade strategy as the first concrete `BaseStrategy` consumer

---

## 1. What was built

A pluggable strategy plane for CrusaderBot, foundation-only. Three new domain modules, one migration, one test module:

- `BaseStrategy` ABC pinning the three hooks every concrete strategy must satisfy: `scan`, `evaluate_exit`, `default_tp_sl`. Class attributes (`name`, `version`, `risk_profile_compatibility`) are validated at registration time, not at definition time, so authors get errors when they wire into the registry rather than at module import.
- `StrategyRegistry` singleton that loads, validates, and routes strategies. One instance per process via `instance()`. Validates name regex, semver-like version, non-empty subset of risk profiles, and rejects duplicate names. Test-only `_reset_for_tests()` hook so the suite can isolate state without spawning new processes.
- Four immutable dataclasses (`SignalCandidate`, `ExitDecision`, `MarketFilters`, `UserContext`) with `__post_init__` invariants — bad input fails fast at the boundary.
- Migration `008_strategy_tables.sql` adding `strategy_definitions`, `user_strategies`, `user_risk_profile`. All `IF NOT EXISTS`, idempotent, FK to `users(id) ON DELETE CASCADE`.

No strategy logic. No signal generation. No risk evaluation. No execution path touched.

## 2. Current system architecture

The strategy plane sits between user config and the (future) signal scan loop. Today only the registry boundary exists; downstream consumers are P3b/P3c lanes.

```
┌──────────────────────────────────────────────────────────────────┐
│  Telegram strategy-config UI  (P5 lane — not in this scope)      │
└────────────────────────┬─────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  StrategyRegistry  (this lane)                                   │
│    - instance()    -> singleton per process                       │
│    - register()    -> validate ABC, semver, profile, dedup        │
│    - get(name)     -> KeyError if missing                         │
│    - list_available() -> serializable catalog                     │
│    - get_compatible(profile) -> filtered list                     │
└────────────────────────┬─────────────────────────────────────────┘
                         │ (P3b lane wires this in)
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  BaseStrategy.scan() / evaluate_exit() / default_tp_sl()         │
│    Concrete strategies: Copy Trade (P3b), Signal Following (P3b) │
└────────────────────────┬─────────────────────────────────────────┘
                         │
                         ▼
                  Signal candidates → Risk gate → Execution
                  (downstream — untouched in this lane)
```

Persistence (migration 008):

```
strategy_definitions         operator-managed catalog
  ├─ id UUID PK
  ├─ name VARCHAR(50) UNIQUE
  ├─ version VARCHAR(20)
  ├─ params_schema JSONB
  ├─ status VARCHAR(20) DEFAULT 'active'
  └─ created_at TIMESTAMPTZ

user_strategies              per-user enrolment
  ├─ id UUID PK
  ├─ user_id UUID FK users(id) ON DELETE CASCADE
  ├─ strategy_name VARCHAR(50)
  ├─ weight DOUBLE PRECISION DEFAULT 1.0
  ├─ enabled BOOLEAN DEFAULT TRUE
  ├─ params_json JSONB
  ├─ created_at TIMESTAMPTZ
  ├─ UNIQUE(user_id, strategy_name)
  └─ INDEX (user_id, enabled)

user_risk_profile            per-user risk profile selection
  ├─ user_id UUID PK FK users(id) ON DELETE CASCADE
  ├─ profile_name VARCHAR(20) DEFAULT 'balanced'
  ├─ custom_overrides JSONB
  └─ updated_at TIMESTAMPTZ
```

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/domain/strategy/__init__.py`
- `projects/polymarket/crusaderbot/domain/strategy/base.py`
- `projects/polymarket/crusaderbot/domain/strategy/registry.py`
- `projects/polymarket/crusaderbot/domain/strategy/types.py`
- `projects/polymarket/crusaderbot/infra/migrations/008_strategy_tables.sql`
- `projects/polymarket/crusaderbot/tests/test_strategy_registry.py`
- `projects/polymarket/crusaderbot/reports/forge/p3a-strategy-registry.md`

Modified: state files (this lane closure):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

No production runtime files touched. No execution path, risk gate, CLOB client, scheduler, or activation guard modified.

## 4. What is working

- `BaseStrategy` is non-instantiable; subclasses missing any of the three abstract hooks also raise `TypeError` at instantiation. Verified by `test_base_strategy_cannot_be_instantiated_directly`, `test_base_strategy_subclass_missing_methods_cannot_instantiate`.
- `StrategyRegistry.instance()` returns the same object across calls and registrations persist across calls. Verified by `test_registry_instance_is_singleton`, `test_registry_singleton_persists_registrations`.
- `register()` validates: type is `BaseStrategy` (TypeError otherwise), name regex `[a-z][a-z0-9_]{1,49}`, semver-like version, risk-profile subset of `{conservative, balanced, aggressive}`, and rejects duplicate names with `ValueError("...already registered")`. Parametrised tests cover 7 bad-name and 6 bad-version cases.
- `get(name)` raises `KeyError` for unknown strategies; `list_available()` returns deterministic, sorted serializable dicts; `get_compatible(profile)` filters by `risk_profile_compatibility` and rejects unknown profiles.
- Dataclass invariants: side ∈ {YES, NO}, confidence ∈ [0, 1], non-negative sizes/balances, non-empty IDs, exit-decision reason/should_exit consistency. Bad inputs raise `ValueError` at construction.
- Migration 008 is idempotent: `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` on every statement; FK uses `ON DELETE CASCADE` matching existing 001_init style.
- Test suite: 44 new tests added. Full crusaderbot suite passes locally — 196 total green (152 prior + 44 new). Baseline 140 → 152 reflects R12d/R12e/R12f tests landed since the foundation lane was scoped; all green.

## 5. Known issues

- **Migration path divergence (intentional, flagged for WARP🔹CMD).** The WARP🔹CMD task spec explicitly placed migration 008 at `infra/migrations/008_strategy_tables.sql`. Existing migrations (001–007) live at `migrations/` under the project root, and the current migration runner reads from there. As written, the foundation DDL exists in repo but will NOT auto-apply at startup until either (a) a follow-up lane moves the runner to read `infra/migrations/`, or (b) the file is mirrored/moved to the legacy `migrations/` folder. This was scoped intentionally per the task brief — calling it out here so WARP🔹CMD can decide path before P3b consumes the tables.
- The registry singleton is intentionally process-local. Multi-process deployments (e.g. workers + API on separate processes) each hold their own registry; that is correct because the registry holds in-memory class instances, not DB rows. The catalog row source-of-truth is `strategy_definitions`.
- `_reset_for_tests()` is exposed under a leading underscore. Production code must not call it; the test fixture is the only caller.

## 6. What is next

P3b — implement Copy Trade strategy as the first concrete `BaseStrategy` subclass. Wire it through the registry at startup, add per-user signal scan loop scaffolding (still not yet feeding execution). After P3b lands, P3c implements Signal Following, then P3d wires the scan loop into the existing risk gate.

Before P3b begins:
- WARP🔹CMD decision on migration path (`infra/migrations/` vs `migrations/`).
- WARP🔹CMD decision on whether the registry should auto-load strategies from `strategy_definitions` at boot or stay code-only for the closed beta.
