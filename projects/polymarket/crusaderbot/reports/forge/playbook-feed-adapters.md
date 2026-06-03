# WARP•FORGE Report — PLAYBOOK Phase-2d/2e Feed Adapters

Branch: `WARP/ROOT/playbook-feed-adapters`
Linear: WARP-53 — PLAYBOOK Autonomous Sports-Market Orchestration Engine
Validation Tier: **MAJOR**
Claim Level: **FOUNDATION** (paper-only, default-OFF; no live network dependency)
Validation Target: the two feed-dependent modules (Injury Alpha, Public Fade), their
signal formulas, the external feed adapter layer + factory, and the strategy
feed-attach — all in `domain/playbook/` + `domain/strategy/strategies/playbook.py`.
Not in Scope: a live market→external-event resolver source, provisioning the
`ODDS_API_KEY` secret, the network allowlist for ESPN / The Odds API, any change to
the risk gate / execution / Kelly / `ENABLE_LIVE_TRADING`, the replay report runner,
and Phase-3 modules (Line Momentum / Liquidity Hunt / WebSocket).

---

## 1. What was built

Phase-2d **Injury Alpha** and Phase-2e **Public Fade** — the last two modules in the
PLAYBOOK routing matrix — were promoted from no-claim stubs to **full claim logic**,
together with the **provider-agnostic external feed adapter layer** the WARP-53
blueprint locked ("external feeds designed as pluggable adapters behind a Protocol").

* **Signal formulas** (`domain/playbook/signals.py`) — `news_injury_reading`
  (`confidence = severity · recency · unrepriced`, signed toward the favored side) and
  `public_flow_reading` (`confidence = 2·|pct − 0.5|`, signed toward the public side).
  `compute_signal_bundle` gained default-neutral injury/public params, so every
  Phase-1/2b caller and any `NullFeed` market reproduces the exact Phase-1 placeholder
  readings.
* **Modules** (`domain/playbook/modules.py`) — `InjuryAlphaModule.evaluate`
  (injury present ∧ TTL > 1h ∧ repriced < 50% ∧ confidence ≥ 0.20 → side from the
  reading sign; TP 0.30 / SL 0.15) and `PublicFadeModule.evaluate`
  (public_pct ≥ 0.65 ∧ overreaction ≥ 0.10 over the market-implied prob ∧ TTL > 30 min
  → **fade** to the opposite side). `MarketSnapshot` gained default-neutral injury/public
  fields (same precedent as Phase-2b `sharp_signed_usdc`).
* **Reference adapters** (`domain/playbook/feeds_http.py`, new) — two **free** providers
  behind the existing `SportsFeed` Protocol: `EspnInjuryFeed` (ESPN public endpoint, no
  key) for injury events, and `OddsApiFeed` (The Odds API free tier, `ODDS_API_KEY` read
  from env only) for a no-vig consensus model probability and a **soft-vs-sharp book
  public-lean proxy** (Pinnacle vs DraftKings divergence — the defensible free stand-in
  for paywalled public-ticket%). `HttpSportsFeed` composes them; `build_sports_feed`
  returns `NullFeed` unless a feed flag is on **and** a `market_id → FeedTarget` resolver
  is supplied. All HTTP is `httpx` + timeout + fail-soft (mirrors `weather/forecast.py`);
  parsers are pure functions.
* **Strategy wiring** (`domain/strategy/strategies/playbook.py`) — `PlaybookStrategy`
  takes an injected `SportsFeed` (default `NullFeed`); `_feed_inputs` batch-attaches
  injury/public data per market (fail-soft), threaded into the snapshot + signal bundle.
* **Config** (`config.py`) — `PLAYBOOK_INJURY_FEED_ENABLED` /
  `PLAYBOOK_PUBLIC_FEED_ENABLED`, both default OFF (VISUALCROSSING key-handling pattern).
* **Blueprint** (`docs/blueprint/playbook.md`) — §3 signal table, §4 routing matrix,
  §9 V2 roadmap and §11 ROI plan updated to mark Phase-2d/2e shipped + feed-gated.

## 2. Current system architecture

```
sports market ──> Market Quality Filter ──> Signal Layer ──> Playbook Router ──> Correlation ──> Risk Gate ──> Execution
                                              │  (native: line/liq/ttl/sentiment/sharp)
                                              │  (feed:   news_injury, public_flow)  ◄── SportsFeed
                                              ▼
   PlaybookStrategy._fetch_sports_snapshots ──┘
        └─ self._feed = NullFeed (default)  |  build_sports_feed(settings, resolver)
                                            ├─ EspnInjuryFeed  → get_injury_event
                                            └─ OddsApiFeed     → get_public_flow / get_model_probability

Router precedence (unchanged): injury_alpha(1) > sharp_money(2) > closing_edge(3) > public_fade(4)
```

The feed sits entirely on the read side. PLAYBOOK still emits a standard
`SignalCandidate`; the unchanged 13-step risk gate and execution router remain the sole
authority. With the default `NullFeed`, both feed modules abstain and behaviour is
identical to Phase-2b.

## 3. Files created / modified (full repo-root paths)

Created:
* `projects/polymarket/crusaderbot/domain/playbook/feeds_http.py`
* `projects/polymarket/crusaderbot/tests/test_playbook_feeds.py`
* `projects/polymarket/crusaderbot/reports/forge/playbook-feed-adapters.md`

Modified:
* `projects/polymarket/crusaderbot/domain/playbook/signals.py`
* `projects/polymarket/crusaderbot/domain/playbook/modules.py`
* `projects/polymarket/crusaderbot/domain/playbook/feeds.py`
* `projects/polymarket/crusaderbot/domain/strategy/strategies/playbook.py`
* `projects/polymarket/crusaderbot/config.py`
* `projects/polymarket/crusaderbot/tests/test_playbook_engine.py` (one stale test name/docstring)
* `docs/blueprint/playbook.md`
* `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
* `projects/polymarket/crusaderbot/state/WORKTODO.md`
* `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

* `pytest` — **27 new** feed tests (`test_playbook_feeds.py`) + **61** existing
  engine/sharp-money + **162** config/runtime-config/registry/signal-scan/preset tests
  all pass. `ruff check` clean on every touched module.
* Signal formulas: sign + recency decay + repricing decay + imbalance verified.
* Module gates: claim/abstain paths for both modules (TTL, threshold, overreaction,
  confidence, already-repriced) verified, including correct side selection (Injury =
  favored side, Public Fade = opposite of the public).
* Router precedence: Injury Alpha outranks Closing Edge when both are eligible; Public
  Fade fires only as the last resort.
* Parsers: `decimal_to_implied`, `devig_two_way`, no-vig consensus probability,
  soft-vs-sharp public-lean (incl. flat-line → 0.5 and missing-book → None), ESPN
  most-severe-recent selection with stale/unknown-status filtering.
* Factory + fail-soft: `build_sports_feed` returns `NullFeed` without a resolver or with
  flags off; both HTTP adapters return `None` (no network) when a target can't resolve.
* Strategy: `_feed_inputs` returns `{}` under the default `NullFeed`;
  `evaluate_snapshot` routes an injury-bearing snapshot to `injury_alpha` end-to-end.

## 5. Known issues

* **Live activation is deliberately gated off.** `build_sports_feed` returns `NullFeed`
  until (a) a `market_id → FeedTarget` resolver source exists, (b) `ODDS_API_KEY` is set,
  and (c) ESPN / The Odds API hosts are in the network allowlist. All three are
  owner/operator-side — none are wired in this PR (FOUNDATION posture). Until then the
  two modules never claim in production.
* **The market→event resolver is not implemented.** Mapping a Polymarket condition_id to
  an ESPN team / Odds API event needs a team-name resolver; it is the documented
  remaining seam (the parsers + adapters are complete and tested against it).
* **Public-ticket% is a proxy, not ground truth.** Genuine public-betting% feeds are
  paywalled; the soft-vs-sharp book divergence is a defensible free approximation and is
  tunable (`lean_scale`) / replaceable by a paid provider drop-in.
* Test-env note: the container lacked several runtime deps (asyncpg, pydantic-settings,
  tenacity, fastapi, sse_starlette, bcrypt) and a broken system `cryptography`/`cffi`
  binding; all were repaired to run the suite. No production code depends on that repair.

## 6. What is next

* **WARP•SENTINEL MAJOR validation** before merge (this report is the source).
* After merge: the **replay report runner** (small, buildable now on the existing
  snapshot substrate) is the most natural next WARP-53 lane; then Phase-3 (Line Momentum
  / Liquidity Hunt / CLOB WebSocket).
* Owner decision to actually trade these modules: pick the resolver source, provision
  `ODDS_API_KEY` + the network allowlist, then flip `PLAYBOOK_INJURY_FEED_ENABLED` /
  `PLAYBOOK_PUBLIC_FEED_ENABLED` (stays paper-only regardless).

---

Suggested Next Step: route to WARP•SENTINEL for MAJOR validation; in parallel the
replay report runner can proceed as an independent lane.
