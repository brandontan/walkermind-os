"""Application configuration — loaded from environment, fail-fast on missing secrets."""
from __future__ import annotations

import logging
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Names checked at boot by ``validate_required_env``. Missing entries are
# logged at ERROR (key only — values are NEVER logged) so the operator alert
# layer can surface a degraded state without crashing the process.
REQUIRED_ENV_VARS: tuple[str, ...] = (
    "TELEGRAM_BOT_TOKEN",
    "DATABASE_URL",
    "ALCHEMY_POLYGON_WS_URL",
    "OPERATOR_CHAT_ID",
    "WALLET_HD_SEED",
    "WALLET_ENCRYPTION_KEY",
)

# "At least one of" groups: validation passes for the group when any of its
# members resolves to a non-empty value. ``check_alchemy_rpc`` falls back to
# the legacy ``POLYGON_RPC_URL`` when the Alchemy alias is unset, so a
# deployment using only the legacy name is healthy and must NOT be paged.
REQUIRED_ENV_VAR_GROUPS: tuple[tuple[str, ...], ...] = (
    ("ALCHEMY_POLYGON_RPC_URL", "POLYGON_RPC_URL"),
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- Required at startup ---
    TELEGRAM_BOT_TOKEN: str
    # Public @username of the bot (no leading @). Optional — used only to render
    # a tap-to-open t.me deep link in the WebTrader "Link Telegram" flow. When
    # unset, the UI still shows the plain `/link <code>` instruction.
    TELEGRAM_BOT_USERNAME: str = ""
    OPERATOR_CHAT_ID: int
    DATABASE_URL: str
    POLYGON_RPC_URL: str
    WALLET_HD_SEED: str
    WALLET_ENCRYPTION_KEY: str

    # --- Alchemy endpoints (optional aliases used by deposit watcher + health) ---
    # Falling back through ``ALCHEMY_POLYGON_RPC_URL`` lets operators provide a
    # single Alchemy URL without renaming the legacy ``POLYGON_RPC_URL``.
    ALCHEMY_POLYGON_RPC_URL: Optional[str] = None
    ALCHEMY_POLYGON_WS_URL: Optional[str] = None
    # Hard per-request deadline for every Polygon JSON-RPC call. Without it the
    # aiohttp session falls back to its 5-minute default and a single hung call
    # can wedge an APScheduler job slot for the rest of the process lifetime
    # (the 2026-06-11 06:12 UTC scheduler stall). Applied both as the aiohttp
    # ClientTimeout on the provider and as an asyncio deadline around each call.
    POLYGON_RPC_TIMEOUT_SECONDS: int = 20
    # Ceiling for each blocking Builder-relayer SDK call (execute / wait) on the
    # Safe-custody path. Relayed Polygon txs normally mine in seconds; 180s is
    # generous. On expiry the withdrawal/sweep fails AMBIGUOUS (no auto-refund —
    # the relayer may already have broadcast) instead of hanging forever.
    RELAYER_CALL_TIMEOUT_SECONDS: int = 180

    # --- Optional infra ---
    REDIS_URL: Optional[str] = None  # falls back to in-memory cache if missing

    # --- Telegram webhook (set to use webhook mode instead of polling) ---
    # Example: https://my-app.fly.dev/telegram/webhook
    TELEGRAM_WEBHOOK_URL: Optional[str] = None
    # Random secret to validate that updates come from Telegram (auto-generated
    # if not set, but setting it explicitly lets you rotate it without redeploying).
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = None

    # --- Admin REST API (disabled when unset) ---
    ADMIN_API_TOKEN: Optional[str] = None

    # --- WebTrader browser dashboard (disabled when unset) ---
    # JWT secret for signing user tokens issued after Telegram Login Widget auth.
    # Generate: openssl rand -hex 32
    # Set in Fly.io: fly secrets set WEBTRADER_JWT_SECRET=<value>
    WEBTRADER_JWT_SECRET: Optional[str] = None
    # Public URL for the WebTrader dashboard — sent via Dashboard button in TG notifications.
    WEBTRADER_URL: Optional[str] = None

    # --- /ops dashboard write controls (disabled when unset) ---
    # GET /ops stays open (read-only operator console). POST /ops/kill +
    # POST /ops/resume require this shared secret via the ``X-Ops-Token``
    # header OR ``?token=<value>`` query param. Disabled (503) when this
    # value is unset. Full auth hardening (per-operator login, rotation,
    # token-out-of-URL) is an INTENTIONAL documented deferral for the
    # paper-mode beta — tracked in PROJECT_STATE KNOWN ISSUES, rationale
    # in the ``api/ops.py`` module docstring. Not an incomplete stub.
    OPS_SECRET: Optional[str] = None

    # --- Sentry-related app metadata ---
    # SENTRY_DSN and SENTRY_TRACES_SAMPLE_RATE are intentionally NOT declared
    # on Settings: monitoring.sentry reads them directly from os.environ to
    # keep Sentry init independent of the rest of the app config (a
    # malformed sample-rate env value would otherwise break every later
    # get_settings() call and turn an optional observability knob into a
    # boot blocker — see Codex P2 on PR #901).
    #
    # APP_VERSION is kept here because /health surfaces it; Optional[str]
    # cannot fail validation, so this stays safe.
    APP_VERSION: Optional[str] = None

    # --- Heisenberg / Falcon API (market data + signal enrichment) ---
    HEISENBERG_API_TOKEN: Optional[str] = None

    # --- DB retention (prevent unbounded operational-table growth) ---
    # WARP•R00T follow-up to the WARP-82 disk-full P0: disk_monitor only ALERTS,
    # it never frees space. The db_retention job prunes operational time-series
    # tables beyond these windows (idempotency_keys keys off its own expires_at).
    # Generous defaults — well clear of any read path; audit.log + core trading
    # tables are deliberately never auto-pruned. Default ON so the DB self-limits.
    DB_RETENTION_ENABLED: bool = True
    DB_RETENTION_SYSTEM_ALERTS_DAYS: int = 30
    DB_RETENTION_SCAN_RUNS_DAYS: int = 30
    DB_RETENTION_PORTFOLIO_SNAPSHOTS_DAYS: int = 90
    DB_RETENTION_EXECUTION_QUEUE_DAYS: int = 30

    # --- Heisenberg agent 556 (real-time trades) buffer ---
    # Triple-gated foundation lane: scheduler registers the sync job only when
    # this flag is on. Default OFF so the buffer table sits idle until WARP🔹CMD
    # explicitly enables it (field-name assumptions in services/heisenberg_trades.py
    # need confirmation against real production responses first).
    HEISENBERG_REALTIME_TRADES_ENABLED: bool = False
    HEISENBERG_REALTIME_TRADES_INTERVAL_SEC: int = 60   # poll cadence
    HEISENBERG_REALTIME_TRADES_WINDOW_SEC: int = 300    # look-back per poll
    HEISENBERG_REALTIME_TRADES_RETENTION_HOURS: int = 24  # buffer retention

    # --- Copy-trade fast-track (consumes heisenberg_realtime_trades buffer) ---
    # Scheduler registers the consumer job only when this flag is on. Default
    # OFF — flip to true once the agent 556 buffer is observed populating
    # cleanly. Dedup via existing copy_trade_idempotency table prevents double
    # execution with the slower wallet-watcher monitor.
    HEISENBERG_FAST_TRACK_ENABLED: bool = False
    HEISENBERG_FAST_TRACK_INTERVAL_SEC: int = 30

    # --- WeatherStrategy (WARP-49) ---
    # Feature-flag gates scheduler registration. Default OFF — operator must
    # set WEATHER_STRATEGY_ENABLED=true to activate the hourly scan and
    # 10-minute monitor jobs. VISUALCROSSING_API_KEY is read from env only
    # inside strategies/weather/forecast.py; it is never stored here.
    WEATHER_STRATEGY_ENABLED: bool = False

    # --- PLAYBOOK sports strategy router (WARP/ROOT/playbook-live-dispatch) ---
    # Operator switch for the PLAYBOOK sports scan dispatch (Phase 2a). Default
    # OFF — even with the code wired, the scan loop emits nothing for the
    # `playbook` preset until the operator sets PLAYBOOK_STRATEGY_ENABLED=true
    # (mirrors WEATHER_STRATEGY_ENABLED). PAPER-only; LIVE stays behind the
    # existing activation guards. Runtime-overridable via the admin overlay.
    PLAYBOOK_STRATEGY_ENABLED: bool = False

    # PLAYBOOK external feed adapters (Phase-2d Injury Alpha / Phase-2e Public Fade,
    # WARP/ROOT/playbook-feed-adapters). Both default OFF — even enabled, the feed
    # only activates when a market→event resolver is supplied (domain.playbook.
    # feeds_http.build_sports_feed returns NullFeed otherwise), so production stays
    # network-free + paper-only. PLAYBOOK_INJURY_FEED_ENABLED arms the ESPN free
    # injury feed (no key). PLAYBOOK_PUBLIC_FEED_ENABLED arms The Odds API
    # consensus / public-lean feed and additionally requires ODDS_API_KEY in the
    # env (read inside the adapter only, never stored here — VISUALCROSSING pattern).
    PLAYBOOK_INJURY_FEED_ENABLED: bool = False
    PLAYBOOK_PUBLIC_FEED_ENABLED: bool = False

    # Phase-2c-2: when true, each scan tick persists the raw full-universe market
    # state to market_snapshots (walk-forward replay substrate). Default OFF; pure
    # append-only telemetry, fail-soft, no effect on trading. Apply migration 080.
    # Runtime-config wired (RUNTIME_SETTINGS): the DB overlay overrides this static
    # default, so PAPER capture can be flipped from the web admin without a redeploy.
    SCAN_SNAPSHOT_ENABLED: bool = False

    # WARP-80 sub-lane 1a: when true, each scan tick records weather + playbook
    # near-miss observability (distance-to-threshold + would-pass-at-relaxed-
    # threshold + feed state) into strategy_scan_observations. Default ON; pure
    # append-only telemetry written fail-soft AFTER the strategy returns, no
    # effect on selection/thresholds/trading. Apply migration 086. Set false as a
    # Fly secret to kill it without a redeploy if log volume ever spikes.
    SCAN_OBSERVABILITY_ENABLED: bool = True

    # WARP-78 cutover emergency kill-switch. When true, the candle_auto + rule
    # "auto" orchestrator (EV-comparator) is DISABLED and those users fall back to
    # the precedence router. Default OFF (orchestrator allowed). Runtime-config
    # wired (RUNTIME_SETTINGS) so it is a no-redeploy DB toggle for instant
    # fallback; this static value is the redeploy-proof backstop (set true as a Fly
    # secret to force the router even if the DB overlay is unreadable). Mirrors the
    # SCAN_SNAPSHOT_ENABLED runtime-config pattern (#1663).
    ORCHESTRATOR_KILL_SWITCH: bool = False

    # Phase-2c-1b: when true, the scheduler runs the Monte Carlo robustness
    # classifier periodically (module_robustness table). Default OFF; pure
    # read-side analytics, fail-soft, no effect on trading. Apply migration 079.
    ROBUSTNESS_CLASSIFY_ENABLED: bool = False
    ROBUSTNESS_CLASSIFY_INTERVAL_SEC: int = 3600  # hourly refresh

    # Phase-2c-1b (part 2): when true, an UNTRADEABLE module (Monte Carlo OOS
    # verdict) is forced to PAPER even if all live guards otherwise pass —
    # DOWNGRADE-ONLY, can never enable live. Default OFF → no effect. Reads
    # module_robustness (mig 079) gate-side in domain.risk.gate._robustness_downgrade.
    ROBUSTNESS_GATE_ENABLED: bool = False

    # --- Complete-set arbitrage (WARP/ROOT/complete-set-arb epic) ---
    # Master kill switch for the complete-set arb scan + booking path. Default
    # OFF — even with the code wired (Lane 2C), nothing scans or books a set
    # until the operator sets COMPLETE_SET_ARB_ENABLED=true. The edge is rare
    # (MM vig) + UNMEASURED, so the path ships dormant: Lane 2C only LOGS live
    # fillable quotes; PAPER booking and any LIVE capital are gated behind this
    # flag (LIVE additionally behind the existing activation guards, Lane 3).
    COMPLETE_SET_ARB_ENABLED: bool = False

    # Adaptive per-market margin for the complete-set arb (heuristic). Default OFF
    # (static MIN_COMPLETE_SET_EDGE base only). When ON, a per-market execution-
    # slippage premium is added on top of the base floor — never below the 2% hard
    # floor. Operator-flippable at runtime via the admin overlay (no redeploy).
    COMPLETE_SET_ADAPTIVE_MARGIN_ENABLED: bool = False

    # --- Smart Strike LIVE slippage-gate edge policy (WARP smart-strike-slippage-
    # edge-gate, F1) --- late_entry_v3 (book-imbalance) reports NO measured edge,
    # so the LIVE step-14b slippage-of-edge tier (which fail-closes on a None edge)
    # would HALT every live Smart Strike candidate. Default False (CMD pick
    # 2026-06-08): for a cell with an explicit per-cell $ cap, that cap is the sole
    # LIVE control when no edge is measured (cap-only) — an uncapped cell still
    # HALTs. Flip True (admin overlay, no redeploy) to require a real measured edge
    # once the real-edge lane lands (then a missing edge HALTs). PAPER is unaffected
    # (step 14b runs only for chosen_mode='live').
    SMART_STRIKE_REQUIRE_MEASURED_EDGE: bool = False

    # --- Multi-asset crypto oracle (WARP-62, candle edge engine foundation) ---
    # Foundation knobs for the candle oracle layer. Default OFF — even with the
    # client code present, the runtime factory
    # (domain.strategy.oracle.oracle_from_settings) refuses to construct until
    # the operator sets ORACLE_ENABLED=true. Chunk 1 is the data client only;
    # fair-value calc and late_entry_v3 wiring land in later chunks (no trading
    # effect yet).
    #
    # Access path: Polymarket Real-Time Data Stream (RTDS) WebSocket — the SAME
    # Chainlink price the crypto up/down markets resolve against, so NO separate
    # Chainlink Data Streams credentials are needed. The oracle is multi-asset,
    # keyed by symbol: ORACLE_SYMBOLS is a CSV "symbol map" (base/quote pairs)
    # that the client subscribes to and is extensible to more pairs. SOL/ETH/BTC
    # all stream from one connection. ORACLE_STALENESS_SEC is the max tick age
    # before get_price refuses a symbol (returns None, never a stale value).
    ORACLE_ENABLED: bool = False
    ORACLE_RTDS_WS_URL: str = "wss://ws-live-data.polymarket.com"
    ORACLE_SYMBOLS: str = "btc/usd,eth/usd,sol/usd"
    ORACLE_STALENESS_SEC: float = 10.0
    # WARP-68 — Polymarket exposes NO candle "Price to Beat" field (verified live
    # vs the Gamma payload); the candle resolves on Chainlink, the SAME source as
    # our feed. So price_to_beat is DERIVED from our own RTDS Chainlink history at
    # the candle-open epoch (eventStartTime). ORACLE_HISTORY_WINDOW_SEC sizes the
    # per-symbol ring (30 min covers the 15m candle + margin); ORACLE_PTB_TOLERANCE_SEC
    # is the nearest-tick match window (Chainlink is 1 Hz aligned to whole seconds,
    # so ~2 s matches the open tick — beyond it the open is an honest no_price_to_beat,
    # never a fabricated/stale baseline).
    ORACLE_HISTORY_WINDOW_SEC: float = 1800.0
    ORACLE_PTB_TOLERANCE_SEC: float = 2.0
    # WARP-76 H3 — feed-loss fail-safe. ORACLE_STALENESS_SEC (10s) governs the
    # per-symbol get_price freshness drop for a single edge computation;
    # ORACLE_FEED_TIMEOUT_SEC is the longer "the stream is DOWN" threshold: when
    # the newest RTDS tick across all symbols is older than this, the signal scan
    # halts (no new market evaluation) and the operator is paged, auto-resuming on
    # the next tick after the feed recovers. Default 120s; strictly positive.
    ORACLE_FEED_TIMEOUT_SEC: int = 120
    # WARP-77 Phase 1.2 — real-CLOB-data feed heartbeat. CLOB_DATA_FEED_TIMEOUT_SEC
    # is the "CLOB data feed is DOWN" threshold: when the newest SUCCESSFUL
    # MarketDataClient read is older than this, the operator is paged (Telegram) +
    # Sentry ONCE per transition, auto-clearing on recovery. The alarm ARMS ONLY
    # when USE_PYSDK_CLOB is true (paper-on-real-data / live) — fully dormant on the
    # legacy adapter, so it can never page in current prod. CLOB_DATA_FEED_CHECK_
    # INTERVAL_SEC is how often the scheduler check runs; CLOB_DATA_FEED_HEARTBEAT_
    # ENABLED unregisters the job entirely. Tune the timeout during the post-cutover
    # 24h observation (default 180s; strictly positive).
    CLOB_DATA_FEED_TIMEOUT_SEC: int = 180
    CLOB_DATA_FEED_CHECK_INTERVAL_SEC: int = 60
    CLOB_DATA_FEED_HEARTBEAT_ENABLED: bool = True
    # WARP-64 Chunk 3 — wire the oracle edge into late_entry_v3 as an ADVISORY
    # signal: when ON (and ORACLE_ENABLED=true so the RTDS feed actually runs),
    # the strategy computes + logs + stamps per-candidate fair-value/edge metadata
    # (delta, fair_up, edge_up/edge_down, would_pass) but does NOT block trades —
    # gating to a hard reject is a deliberate follow-up after the live RTDS feed
    # is verified. Default OFF; PAPER-only. Requires ORACLE_ENABLED=true to have
    # any effect (the lazy singleton oracle is built via oracle_from_settings).
    ORACLE_EDGE_GATE_ENABLED: bool = False

    # WARP/oracle-edge-entry-gate — promote the advisory oracle edge+distance
    # verdict from OBSERVE-only to a HARD entry reject in late_entry_v3. The
    # verdict (edge_meta["oracle_edge_would_pass"]) is already computed per candle:
    # would_pass = (min_dist <= |delta| <= max_dist) AND (max(edge_up, edge_down)
    # >= min_edge), using the Kreo-aligned per-preset bands in signal_scan_job
    # _CANDLE_PRESET_EDGE (close_sweep 0.05-2%/edge 2%, flip_hunter 0.05-5%/edge 3%,
    # safe_close 0.03-1%/edge 1%). When True (default), a candle whose oracle status
    # is 'computed' and would_pass is False is skipped (scan reason
    # oracle_edge_distance_reject) instead of entering on the structural gates
    # alone — this is what makes late_entry_v3 selective ("only enter when the
    # edge/distance rules are met") rather than effectively time-gated.
    #
    # FAIL-OPEN by construction: it ONLY bites when the oracle actually produced a
    # 'computed' verdict, so a dark feed (ORACLE_ENABLED=false), warmup, feed_down
    # or stale tick never blocks a trade — the structural gates stay the floor,
    # behaviour identical to today. REQUIRES ORACLE_ENABLED=true AND
    # ORACLE_EDGE_GATE_ENABLED=true to have ANY effect (those build the edge_cfg +
    # run the RTDS feed). Set False for advisory/observe-only mode (compute + log
    # would_pass without enforcing it).
    ORACLE_EDGE_HARD_REJECT_ENABLED: bool = True  # env: ORACLE_EDGE_HARD_REJECT_ENABLED

    # WARP-72 Phase 1 (WARP•R00T) — SMART STRIKE factor-vector SHADOW telemetry.
    # When ON, late_entry_v3 assembles + emits the full 7-factor scorable surface
    # (momentum / volatility / liquidity / spread / depth / TTL / oracle) plus the
    # router-selected rule and the realized open->close label for EVERY evaluated
    # candle — traded or not — as a structured "factor_vector" log + factor_*
    # candidate/position metadata. This is the labeled dataset the Phase-2 scorer
    # derives weights from. PURE telemetry: never selects, sizes, gates, or blocks
    # a trade (decoupled from execution, like the oracle advisory). Default ON;
    # set false to silence the dataset emission with zero capital-path effect.
    FACTOR_VECTOR_SHADOW_ENABLED: bool = True

    # WARP-72 Phase 2 prep — durable factor-vector dataset (table factor_vectors,
    # migration 081). When ON, the shadow factor vector is UPSERTed (one row per
    # candle, latest-wins) at the entry-decision point and a scheduled backfill
    # resolves the realized open->close label at candle resolution. This is the
    # queryable training set the Phase-2 scorer derives weights from. PURE shadow
    # telemetry — no selection/sizing/gate effect. Default ON; requires the table
    # (operator applies migration 081) and, for the settled label, ORACLE_ENABLED.
    FACTOR_DATASET_PERSIST_ENABLED: bool = True
    # Settlement backfill cadence (seconds). Must be well inside
    # ORACLE_HISTORY_WINDOW_SEC so a closed candle's open tick still lives in the
    # ring when its row is resolved.
    FACTOR_SETTLEMENT_INTERVAL_SEC: int = 60

    # WARP-72 Phase 2 — SMART STRIKE scoring orchestrator (StrategyScorer). When
    # ON, the scorer runs in SHADOW alongside the precedence router on every candle
    # evaluation, logging the rule it WOULD have selected (event "scorer_shadow")
    # next to the rule the router actually picked. PURE telemetry: selection,
    # sizing, the 13-step risk gate, and every protection gate are untouched.
    # Default ON; set false to silence the shadow comparison with zero capital-path
    # effect. The scorer consumes weights derived offline by scorer_trainer.py into
    # config/scorer_weights.json (a missing/untrained model degrades to the
    # precedence ladder — never raises into the scan loop).
    SCORER_SHADOW_ENABLED: bool = True
    # CUTOVER FLAG. When True the scorer's selection would CONTROL execution instead
    # of the router. Default False — the router controls execution and the scorer is
    # shadow-only. Flipping this to True is a WARP🔹CMD-gated cutover that requires
    # the A/B (scorer_ab.py) to prove the scorer beats the router on held-out
    # settled data with >= 20 rows per cell. NOTHING in the codebase reads this as a
    # selection authority yet — cutover wiring is deliberately not implemented.
    SCORER_ACTIVE: bool = False

    # --- Polymarket (only required for LIVE trading) ---
    POLYMARKET_API_KEY: Optional[str] = None
    POLYMARKET_API_SECRET: Optional[str] = None
    # Legacy name (still consumed by integrations.polymarket._build_clob_client
    # which wraps py-clob-client). New ClobAdapter (Phase 4A) reads
    # POLYMARKET_API_PASSPHRASE first, falling back to POLYMARKET_PASSPHRASE.
    POLYMARKET_PASSPHRASE: Optional[str] = None
    POLYMARKET_API_PASSPHRASE: Optional[str] = None
    # L1 (EIP-712) signing key used by ClobAdapter to derive API credentials
    # and prove wallet ownership. Distinct from MASTER_WALLET_PRIVATE_KEY so
    # the trading signer can be rotated independently from the hot pool.
    POLYMARKET_PRIVATE_KEY: Optional[str] = None
    # Funder address (Gnosis Safe / proxy wallet that holds USDC + CTF) used
    # in L2 signature_type=GNOSIS_SAFE flow. None = funder defaults to signer.
    POLYMARKET_FUNDER_ADDRESS: Optional[str] = None
    # Signature type for L2 order signing: 0=EOA, 1=POLY_PROXY, 2=GNOSIS_SAFE.
    # Default 2 matches the most common Polymarket account shape.
    POLYMARKET_SIGNATURE_TYPE: int = 2

    # --- Polymarket builder program (optional, order attribution) ---
    POLYMARKET_BUILDER_API_KEY: Optional[str] = None
    POLYMARKET_BUILDER_API_SECRET: Optional[str] = None
    POLYMARKET_BUILDER_PASSPHRASE: Optional[str] = None
    # Accepted alias for POLYMARKET_BUILDER_API_SECRET: operators commonly set
    # the Fly secret as POLYMARKET_BUILDER_SECRET (Polymarket's own naming).
    # Aliased into *_API_SECRET by _alias_builder_secret so either name works.
    POLYMARKET_BUILDER_SECRET: Optional[str] = None
    # On-chain builder attribution for py-clob-client-v2's BuilderConfig: the
    # 32-byte builder code + the API-only builder address from
    # polymarket.com/settings (Builders tab). NOT secrets, but kept env-driven
    # so they are never hardcoded; consumed only by the v2 CLOB backend.
    POLYMARKET_BUILDER_CODE: Optional[str] = None
    POLYMARKET_BUILDER_ADDRESS: Optional[str] = None

    # --- ClobAdapter toggle (Phase 4A) ---
    # Default False keeps every caller on MockClobClient (paper-safe). Real
    # network calls are unreachable until an operator flips this AND every
    # other activation guard. See docs/runbooks/clob-adapter.md (TBD).
    USE_REAL_CLOB: bool = False

    # --- CLOB order backend (WARP/clob-v2-migration) ---
    # When True (and USE_REAL_CLOB=True), the order path uses the official
    # polymarket-client (CLOB v2 SignedOrder schema) instead of the legacy
    # ClobAdapter (archived py-clob-client v1, rejected by CLOB v2 with
    # 400 order_version_mismatch). Default False so prod and the test suite
    # are unchanged until the staging proof + SENTINEL validate the new
    # backend; the staging-proof harness sets this to 1.
    USE_PYSDK_CLOB: bool = False

    # --- CLOB v2 cutover (WARP/clob-v2-cutover) ---
    # When True (and USE_REAL_CLOB=True), the order path uses py-clob-client-v2
    # (stable 1.0.1) -- the single-package successor that builds the v2 order
    # struct natively + native builder attribution -- taking precedence over
    # USE_PYSDK_CLOB. Default False: the proven PolymarketSdkClient stays the
    # active real path until ClobV2Client is validated against the real broker
    # via the WARP-74 staging harness (allow_fills=false). Flip to 1 only after
    # that proof. Live trading remains independently gated by ENABLE_LIVE_TRADING.
    USE_CLOB_V2: bool = False

    # --- Rust order sidecar (WARP/root-rust-order-sidecar) ---
    # When True (and USE_REAL_CLOB=True), the order path invokes the Rust
    # order-sidecar binary (sidecar/ crate, official polymarket_client_sdk_v2
    # canary) -- the only client that signs POLY_1271 deposit-wallet orders
    # (wrapped EIP-1271 signature; py-clob-client-v2 cannot, upstream #70).
    # Takes precedence over USE_CLOB_V2 and USE_PYSDK_CLOB. Default False:
    # flip only after the staging proof validates the sidecar against the
    # real broker. Live trading remains gated by ENABLE_LIVE_TRADING.
    USE_RUST_SIDECAR: bool = False
    # Absolute path to the compiled sidecar binary inside the runtime image.
    RUST_SIDECAR_PATH: str = "/usr/local/bin/order-sidecar"

    # --- Per-user on-chain execution (WARP/root-per-user-execution-wiring) ---
    # When True (and USE_REAL_CLOB=True), live orders are signed per user
    # against THE USER'S OWN deposit wallet via get_user_clob_client (#1731)
    # + the cross-user isolation assertion in
    # domain/execution/per_user_clob.resolve_user_clob_client
    # (resolved_wallet == wallets.polymarket_deposit_wallet, REFUSES to sign
    # on drift — the SAFETY-CRITICAL #1730 §4 invariant in code). Default
    # False: the proven single-wallet get_clob_client(s) path stays the
    # active real path. Flip ONLY after backfill_deposit_wallets() has
    # populated wallets.polymarket_deposit_wallet for every user, the
    # per-user SENTINEL gate (Step 5) is green, and ENABLE_LIVE_TRADING is
    # owner-enabled — this flag does NOT widen ENABLE_LIVE_TRADING.
    USE_PER_USER_EXECUTION: bool = False

    # --- Balance alerting ---
    # Fire low_balance alert when user wallet balance drops below this value.
    # Set to 0 to disable the alert globally.
    LOW_BALANCE_THRESHOLD_USDC: float = 50.0

    # --- Polygon ---
    USDC_POLYGON: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    USDC_DECIMALS: int = 6
    # Native (Circle-issued) USDC on Polygon. NOT Polymarket's CTF collateral —
    # that is USDC.e (USDC_POLYGON above). The deposit watcher scans this
    # contract ONLY to DETECT-AND-ALERT wrong-token deposits; it NEVER credits
    # native USDC (a distinct ERC-20, untradeable on Polymarket without a swap).
    USDC_NATIVE_POLYGON: str = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    # Toggle for the credit-neutral wrong-token (native USDC) alert pass. Default
    # ON — the pass moves no capital, it only records + notifies the user.
    WRONG_TOKEN_ALERTS_ENABLED: bool = True

    # --- Master / hot-pool wallet (derived from HD seed index 0 if not set) ---
    MASTER_WALLET_ADDRESS: Optional[str] = None
    MASTER_WALLET_PRIVATE_KEY: Optional[str] = None

    # --- Builder Program / gasless relayer (custody migration foundation) ---
    # Credentials issued by polymarket.com/settings?tab=builder. Required for
    # any relayer call; absent → relayer paths raise BuilderRelayerUnavailable.
    # All three default None — the relayer code is dormant until enrolled.
    POLY_BUILDER_API_KEY: Optional[str] = None
    POLY_BUILDER_SECRET: Optional[str] = None
    POLY_BUILDER_PASSPHRASE: Optional[str] = None
    POLY_RELAYER_URL: str = "https://relayer-v2.polymarket.com"
    # Master toggle for routing capital ops via the gasless relayer. Stays
    # False until the Safe-proxy custody migration cuts over. CUSTODY_MODE is
    # the future enum that selects the active custody implementation.
    USE_BUILDER_RELAYER: bool = False
    CUSTODY_MODE: str = "eoa"  # eoa | safe — 'safe' enabled after Phase 4 cutover

    # --- On-chain deposit sweep (LIVE only) ---
    # Consolidates per-user EOA deposit wallets into the master hot-pool.
    # Gated behind EXECUTION_PATH_VALIDATED AND this flag: even after a
    # go-live flip the on-chain sweep stays OFF until an operator explicitly
    # enables it (the logical accounting sweep always runs). Default OFF.
    SWEEP_ONCHAIN_ENABLED: bool = False
    # Skip wallets holding less than this much USDC (dust not worth the gas).
    SWEEP_MIN_USDC: float = 1.0
    # MATIC the master tops a user wallet up to when it lacks gas for one
    # ERC-20 transfer. Bridged-USDC wallets receive no native token on deposit.
    SWEEP_GAS_TOPUP_MATIC: float = 0.05

    # --- Activation guards ---
    # Paper-safe default: False. A live order is only ever reachable when an
    # operator EXPLICITLY overrides this via env (fly.toml / .env) AND every
    # other guard below is true AND the user is Tier 4. Defaulting False means
    # a dev/test/local boot WITHOUT fly.toml can never silently arm live
    # trading. Production behaviour is unchanged — fly.toml forces this false.
    ENABLE_LIVE_TRADING: bool = False
    EXECUTION_PATH_VALIDATED: bool = False
    CAPITAL_MODE_CONFIRMED: bool = False
    # Set to True ONLY after WARP•SENTINEL validates the risk assertion layer
    # (domain.risk.hardening.audit_risk_constants returns passed=True and the
    # readiness validator issues PASS on all checks).  Never set without an
    # explicit WARP🔹CMD decision backed by a SENTINEL report.
    RISK_CONTROLS_VALIDATED: bool = False
    SECURITY_HARDENING_VALIDATED: bool = False
    # Owner: WARP•SENTINEL. Required ON before any live operation.
    # Verifies: kill switch drill passed, audit-log append-only enforced,
    # operator role boundary tested, no PII in logs. See blueprint §12.
    FEE_COLLECTION_ENABLED: bool = False

    # --- Risk caps (Track D) — hard caps enforced per-user before any order ---
    MAX_SINGLE_POSITION_PCT: float = 0.05      # 5% of balance per position
    MAX_TOTAL_EXPOSURE_PCT: float = 0.60       # 60% of balance max open exposure
    MAX_DAILY_LOSS_USD: float = -50.00         # configurable via env MAX_DAILY_LOSS_USD
    MAX_OPEN_POSITIONS: int = 20               # hard cap on concurrent open positions
    REFERRAL_PAYOUT_ENABLED: bool = False
    # AUTO_REDEEM_ENABLED is intentionally True in paper mode so paper users see
    # redeems happen on resolution. Before live launch, this guard flips to False
    # alongside ENABLE_LIVE_TRADING — auto-redeem then requires explicit operator
    # enable per blueprint §12 default-OFF policy.
    AUTO_REDEEM_ENABLED: bool = True

    # --- App config ---
    APP_ENV: str = "development"
    PORT: int = 8080
    HOST: str = "0.0.0.0"
    MIN_DEPOSIT_USDC: float = 50.0
    MARKET_SCAN_INTERVAL: int = 300
    DEPOSIT_WATCH_INTERVAL: int = 120
    # Confirmation depth before a deposit credits the ledger. Polygon reorgs are
    # rare but real; a USDC transfer seen at block N is only credited once it is
    # this many blocks deep on the canonical chain. See migration 047.
    DEPOSIT_CONFIRMATION_DEPTH: int = 32
    # Cold-start lookback for the deposit scanner: when the chain cursor is 0
    # (never advanced — fresh deploy or recovery from a long RPC outage) the
    # first successful scan starts at head minus this many blocks. Polygon does
    # ~43k blocks/day, so the 50k default re-finds deposits sent within the
    # last ~28h; raise via env for a deeper rescue scan (catch-up advances
    # 1000 blocks per watcher tick once the cursor is live). Without this, a
    # recovered watcher silently skipped anything older than 2000 blocks
    # (~70 min) — deposits sent during an outage were permanently missed.
    DEPOSIT_SCAN_LOOKBACK_BLOCKS: int = 50_000
    # Per-tick eth_getLogs request budget for the deposit scanner. Providers
    # cap the block range per request (Alchemy Free caps at 10 blocks — the
    # cap that kept the prod cursor at block 0); the scanner covers its window
    # in as many accepted-size chunks as this budget allows and advances the
    # cursor over whatever it covered. At a 10-block cap the discovered span
    # is 7: 60 requests/tick ≈ 420 blocks/tick vs ~60 produced per 120s
    # interval (Polygon ~2s blocks) — catches up at ~360 blocks/tick net,
    # verified live 2026-06-11. Raise via env for faster catch-up.
    DEPOSIT_SCAN_MAX_RPC_PER_TICK: int = 60
    SIGNAL_SCAN_INTERVAL: int = 180
    # Dedicated high-frequency scan for the close_sweep / late_entry_v3 preset.
    # Late Entry V3 only enters in the final ~35s of a crypto candle, so it must
    # be scanned far more often than the 180s main loop or the window is missed.
    CLOSE_SWEEP_SCAN_INTERVAL: int = 15
    # Late Entry V3 runtime-tuning — override via fly secrets without code change.
    LATE_ENTRY_MIN_ASK_DIFF: float = 0.05   # env: LATE_ENTRY_MIN_ASK_DIFF
    LATE_ENTRY_WINDOW_SEC: float = 35.0     # env: LATE_ENTRY_WINDOW_SEC
    LATE_ENTRY_FLIP_STOP: float = 0.10      # env: LATE_ENTRY_FLIP_STOP — near-disabled for close_sweep (hold to resolution)
    LATE_ENTRY_FAV_PRICE_MIN: float = 0.50  # env: LATE_ENTRY_FAV_PRICE_MIN — favored side must be majority-probability
    LATE_ENTRY_FAV_PRICE_MAX: float = 0.70  # env: LATE_ENTRY_FAV_PRICE_MAX — skip expensive favored entries (fav>0.70 net-loss zone: 17-31% win, asymmetric ~100% downside)

    # Per-preset overrides for late_entry_v3 — each preset passes its own
    # values to _evaluate_market instead of reading the global env vars above.
    # close_sweep  : final 35s, moderate lean (≥0.05 diff), fav ≥0.55 (hold to candle close);
    #                time-based sizing: <10s=0.5x, 10–35s=0.75x (Directive 1.4)
    # safe_close   : enter rem 30–60s, Kreo Min Edge 1% (ask_diff ≥0.01), favored side, force-exit at rem 30s
    # flip_hunter  : Directive Mode A (Pure Arb) — enter cheap side (0.10–0.35) in final 60–180s;
    #                min_arb_edge=1%, underdog_mode=True, hold to settlement (force_exit=0)
    PRESET_CLOSE_SWEEP_WINDOW_SEC: float = 35.0
    PRESET_CLOSE_SWEEP_MIN_ASK_DIFF: float = 0.05
    PRESET_CLOSE_SWEEP_FAV_PRICE_MIN: float = 0.55
    # Force-exit close_sweep when rem ≤ this many seconds (Kreo "exit at 299s").
    # close_sweep used to hold to on-chain resolution, but the 30s exit watcher
    # could miss the near-resolution mark → position mislabelled market_expired
    # / 0% PnL. The dedicated fast exit loop (CLOSE_SWEEP_EXIT_INTERVAL) plus
    # this threshold close it via CLOB ~1–8s before the candle resolves. TP/SL
    # still exit earlier if they hit first.
    PRESET_CLOSE_SWEEP_FORCE_EXIT_REM_SEC: float = 8.0
    # Dedicated fast exit loop for candle-preset positions near resolution.
    CLOSE_SWEEP_EXIT_INTERVAL: int = 5     # poll cadence (s) — only candle positions
    CLOSE_SWEEP_EXIT_NEAR_SEC: int = 90    # only evaluate positions within this many s of resolution
    # Kreo "Min Edge" ~2%: per-scan min_ask_diff is randomized in this range so
    # the entry threshold varies between ticks (2–4%, looser than the old fixed
    # 0.05). Set MIN == MAX to pin a deterministic value.
    PRESET_CLOSE_SWEEP_MIN_ASK_DIFF_MIN: float = 0.02
    PRESET_CLOSE_SWEEP_MIN_ASK_DIFF_MAX: float = 0.04

    PRESET_SAFE_CLOSE_WINDOW_SEC: float = 60.0
    PRESET_SAFE_CLOSE_MIN_ASK_DIFF: float = 0.01  # Kreo Min Edge 1% (was 0.08)
    PRESET_SAFE_CLOSE_FAV_PRICE_MIN: float = 0.60
    # Entry allowed only when seconds_left is between MIN_ENTRY_SEC and WINDOW_SEC.
    # Safe Close 5m: elapsed 240–270s = 30–60s before close → min_entry_sec=30.
    PRESET_SAFE_CLOSE_MIN_ENTRY_SEC: float = 30.0
    # Force-exit when rem ≤ this. Kreo Safe Close exits at elapsed 270s (5m) / 870s (15m)
    # — both correspond to rem 30s — so a single value covers both timeframes.
    # Closes the position BEFORE the noisy final 30s where SL gets hit at random.
    PRESET_SAFE_CLOSE_FORCE_EXIT_REM_SEC: float = 30.0

    # flip_hunter — Directive Mode A (Pure Arb): enter cheap side (0.10–0.35) in final
    # 60–180s before close. arb_edge = 1 - (cheap_ask + expensive_bid). Timeframe-aware.
    PRESET_FLIP_HUNTER_MIN_ASK_DIFF: float = 0.01   # Directive min_arb_edge=1% (was 0.03 Kreo)
    PRESET_FLIP_HUNTER_FAV_PRICE_MIN: float = 0.10  # cheap_side_min_price=0.10 (was 0.50 Kreo)
    PRESET_FLIP_HUNTER_FAV_PRICE_MAX: float = 0.36  # cheap_side_max_price=0.35 (excl; was 0.95 Kreo)
    # 5m candle: entry window = 60–180s remaining (Mode A: ~1–3 min before close).
    PRESET_FLIP_HUNTER_5M_MIN_REM_SEC: float = 60.0
    PRESET_FLIP_HUNTER_5M_MAX_REM_SEC: float = 180.0
    PRESET_FLIP_HUNTER_5M_FORCE_EXIT_REM_SEC: float = 0.0   # Mode A: hold to settlement (0=no exit)
    # 15m candle: same 60–180s entry window (close-in arb window).
    PRESET_FLIP_HUNTER_15M_MIN_REM_SEC: float = 60.0
    PRESET_FLIP_HUNTER_15M_MAX_REM_SEC: float = 180.0
    PRESET_FLIP_HUNTER_15M_FORCE_EXIT_REM_SEC: float = 0.0  # Mode A: hold to settlement (0=no exit)
    MARKET_SIGNAL_SCAN_INTERVAL: int = 60

    # --- Multi-asset oracle fair-value calculator (WARP-61 Chunk 2 / WARP-63) ---
    # Per-asset realized-vol scale for the candle fair-value model, expressed as
    # the asset's log-return volatility per sqrt(second):
    #   z = delta / (sigma * sqrt(time_left)).
    # sigma is PER ASSET because realized vol differs materially (SOL > ETH > BTC);
    # a single shared sigma would misprice fair value on the higher-vol assets.
    # Each default = annualized_vol / sqrt(31_557_600 s/yr); tune via env per regime.
    #   BTC 0.00010 ~= 56% annualized (0.00010 * sqrt(31_557_600) ~= 0.562)
    #   ETH 0.00013 ~= 73% annualized (ETH realized vol historically above BTC)
    #   SOL 0.00020 ~= 112% annualized (SOL the most volatile of the three)
    ORACLE_BTC_SIGMA_PER_SQRT_SEC: float = 0.00010  # env: ORACLE_BTC_SIGMA_PER_SQRT_SEC
    ORACLE_ETH_SIGMA_PER_SQRT_SEC: float = 0.00013  # env: ORACLE_ETH_SIGMA_PER_SQRT_SEC
    ORACLE_SOL_SIGMA_PER_SQRT_SEC: float = 0.00020  # env: ORACLE_SOL_SIGMA_PER_SQRT_SEC

    @property
    def oracle_sigma_per_sqrt_sec(self) -> dict[str, float]:
        """Per-asset sigma map {btc, eth, sol} consumed by the fair-value calc.

        Keys are lowercase asset symbols, matching ``sigma_for_asset`` in
        ``domain/strategy/oracle/fair_value.py``. The calculator stays pure —
        the strategy layer (Chunk 3) passes this map in; the calculator never
        reads Settings itself.
        """
        return {
            "btc": self.ORACLE_BTC_SIGMA_PER_SQRT_SEC,
            "eth": self.ORACLE_ETH_SIGMA_PER_SQRT_SEC,
            "sol": self.ORACLE_SOL_SIGMA_PER_SQRT_SEC,
        }

    # --- Signal scanner thresholds (demo path edge_finder) ---
    # Market eligibility price range: excludes near-resolved markets and
    # extreme longshots / near-certainties where momentum edge is unreliable.
    SCANNER_EDGE_MIN_PRICE: float = 0.15   # env: SCANNER_EDGE_MIN_PRICE
    SCANNER_EDGE_MAX_PRICE: float = 0.85   # env: SCANNER_EDGE_MAX_PRICE
    # Minimum edge in basis points (1 bps = 0.01%) to publish a signal
    SCANNER_MIN_EDGE_BPS: int = 200        # env: SCANNER_MIN_EDGE_BPS
    # Minimum confidence score for published signals
    SCANNER_MIN_CONFIDENCE: float = 0.55  # env: SCANNER_MIN_CONFIDENCE
    # Live path candle deviation threshold (was hardcoded 0.08)
    SCANNER_EDGE_DEVIATION_PCT: float = 0.05  # env: SCANNER_EDGE_DEVIATION_PCT
    # Discovery liquidity floor — lower than execution floor (10k) to widen pool
    SCANNER_MIN_LIQUIDITY: float = 5_000.0  # env: SCANNER_MIN_LIQUIDITY
    # Max markets pulled from Gamma per scan tick (sorted by 24h volume desc).
    # Wider than the prior fixed 200 so the short-dated liquid universe surfaces.
    SCANNER_MARKET_FETCH_LIMIT: int = 500  # env: SCANNER_MARKET_FETCH_LIMIT
    # Resolution-horizon cap for the demo edge generator: markets resolving
    # beyond this many days are NOT published. Keeps the feed on near-dated
    # markets and stops far-dated futures (e.g. 2026/2028 championship winners)
    # from being entered and locking concurrency slots.
    SCANNER_MAX_RESOLUTION_DAYS: int = 30  # env: SCANNER_MAX_RESOLUTION_DAYS
    # Routes the edge-finder scan output. Default FALSE: the scan publishes
    # real Polymarket markets (is_demo=FALSE) to the LIVE feed so paper users
    # trade real, officially-resolvable markets. Set TRUE only for hermetic
    # tests / local dev — then the scan publishes synthetic is_demo=TRUE rows
    # to the demo feed. Production must never enable this.
    SCANNER_DEMO_FEED_ENABLED: bool = False  # env: SCANNER_DEMO_FEED_ENABLED
    COPY_TRADE_MONITOR_INTERVAL: int = 60  # Fast Track B — copy trade tick cadence
    EXIT_WATCH_INTERVAL: int = 30  # Track A: TP/SL poll cadence (30s per spec)
    PORTFOLIO_SNAPSHOT_INTERVAL: int = 60  # WARP-52: cb_portfolio NOTIFY heartbeat
    REDEEM_INTERVAL: int = 3600
    RESOLUTION_CHECK_INTERVAL: int = 300
    DB_POOL_MAX: int = 10
    TIMEZONE: str = "Asia/Jakarta"
    DAILY_REPORT_HOUR: int = 23  # env: DAILY_REPORT_HOUR (0-23 UTC)

    # --- Instant redeem gas guard (R10): if Polygon gas exceeds this when a
    # live position becomes redeemable, defer to the hourly queue. ---
    INSTANT_REDEEM_GAS_GWEI_MAX: float = 200.0

    # --- Bankroll dynamic sizing
    #     (WARP/R00T/bankroll-dynamic-sizing, Lane 5/5) ---
    # Scales the candidate's base size by the user's bankroll deviation
    # from its EMA-smoothed baseline. Applied in
    # signal_scan_job._build_trade_signal BEFORE the risk gate, so the
    # engine's Kelly + position caps still authoritatively bound the
    # final size after the multiplier.
    #
    # Disabled by default — flip ENABLED to true after operator review
    # of how the multiplier interacts with their bankroll distribution.
    # Fail-safe: when disabled OR the user has no prior baseline (first
    # observation seeds it) OR the current balance is non-positive OR
    # any config read raises, the multiplier is 1.0 (no scaling).
    BANKROLL_DYNAMIC_SIZING_ENABLED: bool = False  # env: BANKROLL_DYNAMIC_SIZING_ENABLED

    # Bounds on the multiplier so a recent win streak can't blow up
    # position sizes and a recent loss streak can't shrink them below
    # min-size gates. Default [0.5, 1.5] matches the Polybot directive.
    BANKROLL_MULTIPLIER_MIN: float = 0.5  # env: BANKROLL_MULTIPLIER_MIN
    BANKROLL_MULTIPLIER_MAX: float = 1.5  # env: BANKROLL_MULTIPLIER_MAX

    # EMA smoothing factor for the baseline (0 < alpha <= 1).
    # alpha=0.05 makes the baseline drift slowly: ~95% of the change
    # from a sudden balance shift takes ~60 observations to absorb,
    # giving the multiplier a meaningful window in which to react.
    BANKROLL_EMA_ALPHA: float = 0.05  # env: BANKROLL_EMA_ALPHA

    # Minimum interval between baseline EMA updates (seconds).
    # `_process_candidate` is called sequentially for multiple
    # candidates of the same user within one scan tick (e.g. several
    # candle markets for one late_entry_v3 user); without throttling,
    # each candidate drifts the baseline toward the static
    # intra-tick balance, collapsing it to ~= current and zeroing the
    # multiplier for the rest of the tick. 5s is comfortably longer
    # than a single scan tick (15s cadence at most, but the per-tick
    # candidate burst is sub-second) and shorter than the
    # CLOSE_SWEEP_SCAN_INTERVAL fast loop, so legitimate cross-tick
    # updates still land.
    BANKROLL_BASELINE_UPDATE_MIN_INTERVAL_SEC: float = 5.0  # env: BANKROLL_BASELINE_UPDATE_MIN_INTERVAL_SEC

    # --- Bankroll circuit breaker (WARP/R00T/bankroll-circuit-breaker) ---
    # Halt new-entry processing for a user when their current balance
    # drops below `baseline * BANKROLL_CIRCUIT_BREAKER_THRESHOLD`. Resumes
    # only when balance climbs back to
    # `baseline * BANKROLL_CIRCUIT_BREAKER_THRESHOLD * (1 + HYSTERESIS)`
    # — hysteresis prevents a thrashing trip/reset loop at the boundary
    # (directive Appendix C "circuit breaker loop" failure mode).
    #
    # `baseline` is the slow-moving EMA reference that Lane 5
    # (`bankroll-dynamic-sizing`) already maintains per user — same
    # _bankroll_ema_baseline dict, no second source of truth. This means
    # the gate fires on relative bankroll deterioration vs the user's own
    # equilibrium, not against a fixed-USD target (each user starts at a
    # different balance, so a fixed-USD target would be meaningless).
    #
    # The gate only blocks NEW entries — existing open positions and
    # their TP/SL exits are unaffected (operator can still emergency-stop
    # via /kill which routes through `users.set_paused(True)` and the
    # existing exit pipeline). A future live-mode lane will add active
    # order cancellation as the directive spec calls for.
    #
    # Default OFF (dark launch). Operator enables once we've watched the
    # `skipped_circuit_breaker` rate in paper mode for a couple of
    # sessions and confirmed it does not over-fire on benign DD.
    BANKROLL_CIRCUIT_BREAKER_ENABLED: bool = False  # env: BANKROLL_CIRCUIT_BREAKER_ENABLED
    # Trip threshold as a fraction of the user's bankroll baseline:
    # gate fires when `balance < baseline * THRESHOLD`. Default 0.20 →
    # trip when bankroll falls below 20% of baseline (~80% drawdown).
    # Matches the Polybot directive #6 reference (stop when only 20%
    # of bankroll remains). Bounds: (0, 1].
    BANKROLL_CIRCUIT_BREAKER_THRESHOLD: float = 0.20  # env: BANKROLL_CIRCUIT_BREAKER_THRESHOLD
    # Hysteresis cushion above the threshold required to resume trading.
    # Default 0.10 → resume at `threshold * 1.10` (22% recovery). Bounds:
    # [0, 1].
    BANKROLL_CIRCUIT_BREAKER_HYSTERESIS: float = 0.10  # env: BANKROLL_CIRCUIT_BREAKER_HYSTERESIS

    # --- Safe-close direction concentration limit
    #     (WARP/R00T/safe-close-direction-limit, Lane 4/5) ---
    # Max accepted safe_close entries per (user, side) within a rolling
    # 1h window. Defends against the trending-market case where the
    # dynamic `fav_side` filter in late_entry_v3 leans the same
    # direction across many candles, aggregating directional risk that
    # the per-candle filter never sees (Polybot research: BTC downtrend
    # Dec 14-18 2025 produced 55.9% NO win-rate = sample-period bias,
    # not edge).
    #
    # Default 8 (Polybot directive reference). Set to 0 to disable the
    # gate (escape hatch — runtime branches on `> 0`). Negative values
    # rejected at config load (same trap as the other guardrail knobs).
    SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR: int = 8  # env: SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR

    # --- Correlated crypto-majors same-direction entry cap
    #     (WARP/correlated-majors-entry-guard) ---
    # BTC/ETH/SOL are tightly correlated intraday: a market-wide move pushes all
    # three candle "Up or Down" markets the same way. Opening same-direction
    # positions on all three at one candle close = one 3x-leveraged directional
    # bet that stops out as a cluster on reversal (observed prod loss pattern).
    # The per-user max_concurrent count cap (5/12/20) does NOT catch this — three
    # correlated entries are well under the count limit. This caps how many
    # crypto-majors (domain.risk.constants.CORRELATED_CRYPTO_MAJORS) a user may
    # enter in the SAME direction AT ONCE (counted authoritatively from the
    # user's currently-open positions in the DB — see
    # signal_scan_job._open_correlated_majors_count — so the cap survives a
    # process restart / Fly redeploy and multiple scan workers; the in-memory
    # window alone did NOT, which let a redeploy mid-candle reset the counter
    # and open a 3rd correlated major).
    #
    # Default 1 (owner directive 2026-06-10): treat BTC/ETH/SOL as a SINGLE
    # correlated bet — take only the best one per direction, skip the rest, so
    # the cluster can never stop out together. Set to 2 to allow two correlated
    # majors, or 0 to disable the gate entirely (escape hatch — runtime branches
    # on `> 0`). Negative values rejected at config load (same silent-disable
    # trap as the other guardrail knobs).
    CORRELATED_MAJORS_SAME_DIR_LIMIT: int = 1  # env: CORRELATED_MAJORS_SAME_DIR_LIMIT

    # --- Safe-close inventory imbalance override
    #     (WARP/R00T/safe-close-imbalance-override, Polybot directive 1.2.1.c) ---
    # When a safe_close candidate fires on a market where the user
    # already holds imbalanced exposure (|imbalance_usdc| > threshold),
    # override the candidate side to the lagging leg and bypass the
    # standard same-market open-position dedup. Lets the strategy
    # rebalance toward complete-set parity (the "balance lagging leg"
    # half of the directive's dual-leg arb model — full simultaneous
    # entry is a future lane).
    #
    # Inventory source: `domain.strategy.inventory.compute_market_inventory`
    # (foundation lane WARP/R00T/inventory-tracker-foundation). Reads
    # the same `positions` table the existing dedup gate reads.
    #
    # Default OFF (dark launch). When OFF the override path is fully
    # bypassed and behaviour is identical to pre-lane. When ON it ONLY
    # fires for late_entry_v3 candidates whose user has
    # active_preset='safe_close' — every other strategy / preset
    # continues to use the broad open-position dedup.
    SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED: bool = False  # env: SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED
    # Imbalance threshold in USDC cost basis (NOT shares — the directive
    # spec uses shares but our position model tracks cost basis). At
    # 5.0 USDC, a user with $30 YES + $5 NO ($25 imbalance) triggers
    # the override; $30 YES + $25 NO ($5 imbalance) does NOT — there's
    # already near-parity and the standard dedup correctly blocks a
    # second entry.
    #
    # Bounds: must be > 0. Zero would override on any imbalance which
    # collapses to "always override when both legs aren't exactly
    # equal" — a noise amplifier, not a guardrail. Reject at config
    # load.
    SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC: float = 5.0  # env: SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC

    # --- Flip Hunter fast top-up (WARP/R00T/flip-hunter-fast-topup,
    #     Polybot directive 1.5 + 1.3.2) ---
    # After a successful safe_close / flip_hunter entry that left the
    # user's per-market exposure imbalanced (`|imbalance_usdc| >=
    # FAST_TOPUP_MIN_USDC`), immediately fire a follow-up entry for the
    # opposite (lagging) leg via the standard TradeEngine path. Lets
    # the strategy chase complete-set parity in the moments after the
    # lead leg fills, recovering from the case where only one side of
    # an intended pair actually landed.
    #
    # Cooldown is per-(user, market) so two markets independently
    # rebalance without rate-limiting each other.
    #
    # Default OFF (dark launch). When ON it ONLY fires after a
    # SUCCESSFUL `late_entry_v3` execution where the user's
    # `active_preset` is `safe_close` or `flip_hunter`.
    FLIP_HUNTER_FAST_TOPUP_ENABLED: bool = False  # env: FLIP_HUNTER_FAST_TOPUP_ENABLED
    # Minimum imbalance (USDC cost basis) required to trigger a top-up.
    # Bounds: must be > 0. Zero would fire on any non-zero imbalance,
    # producing infinite back-and-forth between legs. Rejected at load.
    FAST_TOPUP_MIN_USDC: float = 5.0  # env: FAST_TOPUP_MIN_USDC
    # Cooldown window between top-ups for the same (user, market) pair.
    # Default 15s matches the Polybot directive reference. Bounds:
    # must be > 0. Zero cooldown would allow the same (user, market)
    # to spin top-ups continuously.
    FAST_TOPUP_COOLDOWN_SECONDS: float = 15.0  # env: FAST_TOPUP_COOLDOWN_SECONDS

    # --- Close-sweep dual-leg execution
    #     (WARP/R00T/close-sweep-dual-leg, Polybot directive 1.1.2.c) ---
    # Extends the fast-topup mechanism (D-3) to close_sweep candidates.
    # The directive specifies close_sweep should enter BOTH legs
    # simultaneously via TAKER market orders because the final 35s
    # entry window is too tight for staged dual-leg placement. Our
    # paper engine fills instantly, so "simultaneous" collapses to
    # "lead entry succeeds → immediately fire opposite-leg top-up" —
    # the same mechanism Lane D-3 ships for safe_close + flip_hunter.
    #
    # This knob simply extends the eligible-preset set to include
    # close_sweep so the existing _maybe_fire_fast_topup helper
    # handles it. Default OFF (dark launch). Independent of the
    # FLIP_HUNTER_FAST_TOPUP_ENABLED flag so the operator can enable
    # close_sweep dual-leg without enabling the safe_close /
    # flip_hunter top-up at the same time (or vice versa).
    #
    # Shares the same FAST_TOPUP_MIN_USDC + FAST_TOPUP_COOLDOWN_SECONDS
    # knobs as D-3 — no need for separate close_sweep-specific
    # thresholds, and using shared limits keeps operator dashboards
    # honest about the unified mechanism.
    CLOSE_SWEEP_DUAL_LEG_ENABLED: bool = False  # env: CLOSE_SWEEP_DUAL_LEG_ENABLED

    # --- Close-sweep per-leg spread gate (WARP/R00T/close-sweep-spread-gate) ---
    # Max per-side bid-ask spread (best_ask - best_bid) tolerated by the
    # close_sweep preset. Wide per-leg spread in the noisy final ~35s of a
    # candle = thin book + high slippage on the taker fill. Scoped to
    # close_sweep only via _resolve_preset_params → late_entry_v3.scan;
    # safe_close + flip_hunter pass None (no-op) since they entry earlier
    # in the candle where this is not the dominant risk.
    #
    # Default 0.02 (2c) matches the Polybot research reference.
    # Set to 0 to disable the gate (escape hatch — operator can revert
    # without redeploy). Negative values are rejected at config load.
    CLOSE_SWEEP_MAX_LEG_SPREAD: float = 0.02  # env: CLOSE_SWEEP_MAX_LEG_SPREAD

    # --- Complete-set edge gate (WARP/R00T/complete-set-edge-gate) ---
    # Polymarket binary UP/DOWN settles to $1.00 at expiry, so the spot
    # arbitrage bound is `cost = ask_UP + ask_DOWN`. When cost >= $1.00,
    # the per-side ask is already at or above the settlement bound — any
    # entry there is a guaranteed loss vs the complete-set arb (paying $1
    # to receive $1). The metric was stamped observationally in PR #1477
    # (late_entry_v3._evaluate_market → metadata["complete_set_edge"]);
    # this knob promotes it to a real entry gate in
    # services.signal_scan.signal_scan_job._process_candidate.
    #
    # Threshold: minimum `complete_set_edge = round(1 - (ask_UP + ask_DOWN), 4)`
    # required to accept the candidate. Default 0.005 (50 bps) matches the
    # directive's MIN_EDGE: covers Polymarket maker/taker fees + a thin
    # buffer above pure arb breakeven.
    #
    # Set to 0 to disable the gate (escape hatch — operator can revert
    # without redeploy). Negative values are rejected at config load
    # (the runtime check is `metric < threshold`, and a negative threshold
    # would silently accept negative-edge entries — the directional
    # analogue of the negative-spread silent-disable trap).
    #
    # Scoped to candidates that carry the stamp (late_entry_v3 — close_sweep,
    # safe_close, flip_hunter); signal_following / copy_trade bypass.
    MIN_COMPLETE_SET_EDGE: float = 0.0  # env: MIN_COMPLETE_SET_EDGE — 0 disables gate

    # Lane 3C-2: bound the poll of a Polymarket `delayed` (non-terminal) complete-set
    # FOK accept before halting, so a transient delay resolves to matched/unmatched
    # instead of forcing an operator halt. 0 attempts -> halt immediately (legacy).
    COMPLETE_SET_DELAYED_POLL_ATTEMPTS: int = 3
    COMPLETE_SET_DELAYED_POLL_INTERVAL_SEC: float = 1.0

    # Lane 3C-2 crash-recovery reconciler: a complete-set order still 'pending'/
    # 'unknown' older than STALE_SEC is a crash leftover (normal flow resolves in
    # ms) -> reconcile it against broker truth (or halt+page on any uncertainty).
    COMPLETE_SET_RECONCILE_STALE_SEC: int = 300
    COMPLETE_SET_RECONCILE_INTERVAL_SEC: int = 300

    # Lane 3C-2: tolerance for an over-budget complete-set fill. A FOK can fill above
    # the gate-approved budget when the book drifts up within the FOK limits; the set
    # stays riskless, so we page+flag (not halt) only when actual exceeds budget by
    # more than this fraction (avoids noise on expected tick-level overshoots).
    COMPLETE_SET_BUDGET_BREACH_PCT: float = 0.01

    # --- WARP-74 LIVE reconciliation epic (generalized live reconciler) ---
    # The OrderLifecycleManager (domain/execution/lifecycle.py) owns directional
    # live orders in ('submitted','pending','partial_filled'); the complete-set
    # reconciler owns 'complete_set_arb%' rows. NEITHER touches:
    #   * directional 'unknown' orders — an ambiguous post-submit (live.execute
    #     marks 'unknown' with NO broker id) that the poller never selects, so a
    #     crash leaves it orphaned (P0 #1); and
    #   * live 'closing' positions stranded by a crash mid-close (P0 #2).
    # reconcile_live_orders + reconcile_closing_positions close exactly those gaps
    # for late_entry_v3 / signal_following / copy_trade — NEVER complete-set.
    LIVE_RECONCILE_ENABLED: bool = True
    # A directional 'unknown'/'stale' live order older than this is a crash
    # leftover (the normal flow resolves in seconds) -> reconcile against broker
    # truth (or page on any uncertainty). Mirrors COMPLETE_SET_RECONCILE_STALE_SEC.
    LIVE_RECONCILE_STALE_SEC: int = 300
    LIVE_RECONCILE_INTERVAL_SEC: int = 300
    # A live position in 'closing' older than this (measured from closing_at) is a
    # crash-stranded close — a clean close finalizes in milliseconds. Tighter than
    # the order stale window because a stranded close holds real on-chain exposure.
    LIVE_CLOSING_STALE_SEC: int = 120

    # --- WARP-74 Chunk C: broker<->DB open-order drift detector ---
    # Periodically compares the broker's open-orders set against the DB rows the
    # bot believes are open. Divergence (broker-only = untracked resting order;
    # DB-only = phantom open) pages the operator. Alert-only — never auto-cancels.
    ORDER_DRIFT_DETECT_ENABLED: bool = True
    ORDER_DRIFT_INTERVAL_SEC: int = 600

    @field_validator(
        "DB_RETENTION_SYSTEM_ALERTS_DAYS",
        "DB_RETENTION_SCAN_RUNS_DAYS",
        "DB_RETENTION_PORTFOLIO_SNAPSHOTS_DAYS",
        "DB_RETENTION_EXECUTION_QUEUE_DAYS",
    )
    @classmethod
    def validate_db_retention_days(cls, v: int) -> int:
        # Retention windows feed a DELETE job — a 0/negative value would prune
        # active/recent rows. Fail fast at config load rather than lose data.
        if v <= 0:
            raise ValueError(f"DB retention days must be strictly positive (got {v}).")
        return v

    @field_validator("LIVE_RECONCILE_INTERVAL_SEC", "ORDER_DRIFT_INTERVAL_SEC")
    @classmethod
    def validate_live_reconcile_intervals(cls, v: int) -> int:
        # Scheduler cadences — APScheduler requires strictly positive seconds, so a
        # 0/negative misconfig would crash setup. Fail fast at config load.
        if v <= 0:
            raise ValueError(
                f"live-reconcile / drift scheduler interval must be > 0 (got {v})."
            )
        return v

    @field_validator("ORACLE_FEED_TIMEOUT_SEC")
    @classmethod
    def validate_oracle_feed_timeout(cls, v: int) -> int:
        # WARP-76 H3 — a 0/negative feed timeout would make the scan halt
        # permanently (or never), so reject it at config load.
        if v <= 0:
            raise ValueError(f"ORACLE_FEED_TIMEOUT_SEC must be > 0 (got {v}).")
        return v

    @field_validator("LIVE_RECONCILE_STALE_SEC", "LIVE_CLOSING_STALE_SEC")
    @classmethod
    def validate_live_reconcile_windows(cls, v: int) -> int:
        # Staleness / lookback windows feed SQL interval math, never APScheduler;
        # 0 is meaningful (reconcile immediately), negative is not.
        if v < 0:
            raise ValueError(
                f"live-reconcile stale/window seconds must be >= 0 (got {v})."
            )
        return v

    # --- TOB freshness gate (WARP/R00T/tob-freshness-gate) ---
    # Max age in milliseconds for the orderbook snapshot that produced
    # a candidate's metadata["entry_price"]. Read by
    # services.signal_scan.signal_scan_job._process_candidate step 3b-0:
    # if (now - metadata["entry_price_ts"]) > TOB_STALE_MS, the candidate
    # is rejected with scan_outcome="skipped_stale_tob".
    #
    # Set to 0 to disable the gate (escape hatch — operator can revert
    # without redeploy). Default 2000ms matches the Polybot research
    # reference value: scan->fill latency above 2s means the live mark has
    # materially moved away from the strategy's intended setup.
    #
    # Scoped to candidates that carry the stamp (late_entry_v3 — close_sweep,
    # safe_close, flip_hunter); candidates without the stamp no-op.
    TOB_STALE_MS: int = 2000  # env: TOB_STALE_MS

    # --- Order lifecycle polling (Phase 4C) ---
    # Interval between OrderLifecycleManager.poll_once ticks. Default 30s
    # gives a snappy dashboard without hammering the broker API.
    ORDER_POLL_INTERVAL_SECONDS: int = 30
    # Max consecutive poll attempts before an order is marked 'stale'
    # and the operator paged. Default 48 ticks * 30s = 24 minutes per
    # order before manual reconciliation.
    ORDER_POLL_MAX_ATTEMPTS: int = 48

    # --- Live order reconciliation (WARP-74 Chunk A) ---
    # Periodic broker-truth sweep: pulls the broker's open orders and diffs them
    # against the DB to surface ORPHANS (resting at the broker but not tracked as
    # open) and db-only drift. Detection / telemetry ONLY — never cancels, sizes,
    # or mutates an order. No-op when USE_REAL_CLOB=False. Set ENABLED=False to
    # unregister the job without a redeploy (the sweep also self-skips in paper).
    RECONCILE_LIVE_ORDERS_ENABLED: bool = True
    RECONCILE_INTERVAL_SEC: int = 120

    # --- CLOB WebSocket (Phase 4D) ---
    # Polymarket exposes two WS channels:
    #   wss://ws-subscriptions-clob.polymarket.com/ws/user    -> user fills + orders
    #   wss://ws-subscriptions-clob.polymarket.com/ws/market  -> market data
    # Phase 4D consumes the user channel only. The client opens the
    # socket only when USE_REAL_CLOB=True; paper mode never touches
    # the network.
    CLOB_WS_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
    # Reconnect backoff cap. Initial delay 1s, doubled per attempt with
    # +/-25% jitter, clipped at this value. Default 60s matches the
    # Polymarket guidance for keep-alive backoff.
    WS_RECONNECT_MAX_DELAY_SECONDS: int = 60
    # Polymarket recycles connections that go ~10s without a heartbeat,
    # so the client sends literal "PING" text every 10s and the peer
    # echoes "PONG"; the timeout window adds the same again before we
    # treat the socket as dead.
    WS_HEARTBEAT_INTERVAL_SECONDS: int = 10
    WS_HEARTBEAT_TIMEOUT_SECONDS: int = 10
    # APScheduler watchdog interval for the WebSocket client. Fires
    # every N seconds and reconnects when ``client.is_alive()`` is
    # False, covering both clean exits and silent socket deaths the
    # heartbeat path missed.
    WS_WATCHDOG_INTERVAL_SECONDS: int = 60

    # --- CLOB resilience (Phase 4E) ---
    # Number of consecutive transport failures (rate limit / 5xx /
    # timeout / network / max-retries) that trip the breaker from
    # CLOSED to OPEN. Auth-class errors (400/401/403) do NOT count --
    # those are operator-credential issues, not transport incidents.
    CIRCUIT_BREAKER_THRESHOLD: int = 5
    # Time the breaker stays OPEN before auto-transitioning to
    # HALF_OPEN. A successful trial in HALF_OPEN closes the breaker;
    # a failed trial re-opens it and restarts this window.
    CIRCUIT_BREAKER_RESET_SECONDS: int = 60
    # Token-bucket rate limiter applied to every outbound CLOB call.
    # Set below Polymarket's per-account ceiling so we throttle
    # locally before the broker's 429 path triggers.
    CLOB_RATE_LIMIT_RPS: int = 10

    # --- Inbound HTTP rate limiting (public abuse control) ---
    # Per-client (source-IP) request ceiling over RATE_LIMIT_WINDOW_SECONDS,
    # enforced by RateLimitMiddleware on the public API/webhook surface.
    # Health/readiness probes, /legal/*, and the Telegram webhook are exempt.
    # Set RATE_LIMIT_ENABLED=False to disable throttling entirely.
    #
    # 600/min ≈ 10 req/s per source IP. A normal WebTrader dashboard load
    # fires ~10-15 /api/web/* calls (markets, positions, portfolio summary,
    # alerts, signals, scan history) plus periodic refreshes, so the prior
    # 120/min (2 req/s) ceiling was tripping live users on first page-in
    # ("Too many requests. Please slow down"). 10 req/s still leaves 5x
    # headroom over normal usage so the limiter catches abusive scrapers
    # but not legitimate operators.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_RPM: int = 600
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    @model_validator(mode="before")
    @classmethod
    def _alias_builder_secret(cls, data):
        """Accept POLYMARKET_BUILDER_SECRET as an alias for *_API_SECRET.

        The Builder Program secret is commonly set under the shorter name
        (Polymarket's own naming + the operator's Fly secret); copy it into the
        canonical field when that is empty so builder auth is not silently
        half-configured (key+passphrase set, secret missing).
        """
        if isinstance(data, dict):
            canon = data.get("POLYMARKET_BUILDER_API_SECRET")
            alias = data.get("POLYMARKET_BUILDER_SECRET")
            if (canon is None or str(canon).strip() == "") and alias:
                data["POLYMARKET_BUILDER_API_SECRET"] = alias
        return data

    @model_validator(mode="before")
    @classmethod
    def _alias_polygon_rpc_url(cls, data):
        """Allow alias-only deployments: when only ``ALCHEMY_POLYGON_RPC_URL``
        is supplied, copy it into ``POLYGON_RPC_URL`` so the latter's
        ``str`` (required) field is satisfied. ``validate_required_env``
        and ``check_alchemy_rpc`` both accept either name; this keeps
        ``Settings`` consistent with that contract instead of raising a
        validation error at boot in the alias-only path.
        """
        if isinstance(data, dict):
            legacy = data.get("POLYGON_RPC_URL")
            alias = data.get("ALCHEMY_POLYGON_RPC_URL")
            if (legacy is None or str(legacy).strip() == "") and alias:
                data["POLYGON_RPC_URL"] = alias
        return data

    @field_validator("BANKROLL_MULTIPLIER_MIN", "BANKROLL_MULTIPLIER_MAX")
    @classmethod
    def validate_bankroll_multiplier_bound(cls, v: float) -> float:
        # The multiplier IS the size scaler — non-finite or non-positive
        # would zero / NaN the proposed_size at runtime. Fail fast at
        # load with a clear error.
        if not math.isfinite(v):
            raise ValueError(
                f"BANKROLL_MULTIPLIER_{{MIN,MAX}} must be a finite "
                f"number (got {v!r}); typical bounds are 0.5..1.5."
            )
        if v <= 0:
            raise ValueError(
                f"BANKROLL_MULTIPLIER_{{MIN,MAX}} must be > 0 (got {v}); "
                f"a non-positive multiplier would zero out trade sizes."
            )
        return v

    @field_validator("FACTOR_SETTLEMENT_INTERVAL_SEC")
    @classmethod
    def validate_factor_settlement_interval(cls, v: int) -> int:
        # Scheduler interval — APScheduler requires strictly positive seconds, so
        # a 0/negative misconfig would crash setup. Fail fast at config load.
        if v <= 0:
            raise ValueError(
                f"FACTOR_SETTLEMENT_INTERVAL_SEC must be > 0 (got {v}); it is the "
                f"factor-vector settlement backfill cadence in seconds."
            )
        return v

    @field_validator("RECONCILE_INTERVAL_SEC")
    @classmethod
    def validate_reconcile_interval(cls, v: int) -> int:
        # Scheduler interval — APScheduler requires strictly positive seconds, so
        # a 0/negative misconfig would crash setup. Fail fast at config load.
        if v <= 0:
            raise ValueError(
                f"RECONCILE_INTERVAL_SEC must be > 0 (got {v}); it is the "
                f"live-order broker-reconcile sweep cadence in seconds."
            )
        return v

    @field_validator("BANKROLL_BASELINE_UPDATE_MIN_INTERVAL_SEC")
    @classmethod
    def validate_bankroll_baseline_throttle(cls, v: float) -> float:
        # Must be finite + non-negative (0 disables the throttle).
        if not math.isfinite(v):
            raise ValueError(
                f"BANKROLL_BASELINE_UPDATE_MIN_INTERVAL_SEC must be "
                f"finite (got {v!r})."
            )
        if v < 0:
            raise ValueError(
                f"BANKROLL_BASELINE_UPDATE_MIN_INTERVAL_SEC must be "
                f">= 0 (got {v}); use 0 to disable the throttle, or "
                f"a positive value to require N seconds between "
                f"baseline EMA updates."
            )
        return v

    @field_validator("BANKROLL_EMA_ALPHA")
    @classmethod
    def validate_bankroll_ema_alpha(cls, v: float) -> float:
        # alpha must be in (0, 1] — 0 freezes the baseline forever (no
        # tracking), > 1 over-shoots and oscillates. Fail fast at load.
        if not math.isfinite(v):
            raise ValueError(
                f"BANKROLL_EMA_ALPHA must be a finite number (got {v!r})."
            )
        if v <= 0 or v > 1:
            raise ValueError(
                f"BANKROLL_EMA_ALPHA must be in (0, 1] (got {v}); "
                f"alpha=0 freezes the baseline, alpha>1 overshoots."
            )
        return v

    @field_validator("BANKROLL_CIRCUIT_BREAKER_THRESHOLD")
    @classmethod
    def validate_circuit_breaker_threshold(cls, v: float) -> float:
        # Threshold must be in (0, 1]: 0 would mean "trip at zero
        # bankroll" (never useful — by then the trade is already moot),
        # > 1 would mean "trip above 100% baseline" (always tripped, no
        # entries ever land — silent kill switch). Both fail closed at
        # config load.
        if not math.isfinite(v):
            raise ValueError(
                f"BANKROLL_CIRCUIT_BREAKER_THRESHOLD must be a finite "
                f"number (got {v!r})."
            )
        if v <= 0 or v > 1:
            raise ValueError(
                f"BANKROLL_CIRCUIT_BREAKER_THRESHOLD must be in (0, 1] "
                f"(got {v}); 0 would never trip, > 1 would always trip."
            )
        return v

    @field_validator("BANKROLL_CIRCUIT_BREAKER_HYSTERESIS")
    @classmethod
    def validate_circuit_breaker_hysteresis(cls, v: float) -> float:
        # Hysteresis must be in [0, 1]: 0 = no cushion (gate flaps on the
        # boundary), > 1 would require > 200% recovery to resume (silent
        # permanent lockout once tripped — exactly the trap to avoid).
        if not math.isfinite(v):
            raise ValueError(
                f"BANKROLL_CIRCUIT_BREAKER_HYSTERESIS must be a finite "
                f"number (got {v!r})."
            )
        if v < 0 or v > 1:
            raise ValueError(
                f"BANKROLL_CIRCUIT_BREAKER_HYSTERESIS must be in [0, 1] "
                f"(got {v}); 0 disables hysteresis, > 1 would lock the "
                f"breaker permanently."
            )
        return v

    @model_validator(mode="after")
    def validate_bankroll_multiplier_range(self) -> "Settings":
        # MIN must not exceed MAX — otherwise the runtime `max(MIN, min(MAX, raw))`
        # clamp clamps to MIN unconditionally (raw <= MAX always evaluates to
        # the smaller MAX → outer max picks MIN), effectively constant-multiplier
        # at MIN regardless of bankroll. Fail fast at load.
        if self.BANKROLL_MULTIPLIER_MIN > self.BANKROLL_MULTIPLIER_MAX:
            raise ValueError(
                f"BANKROLL_MULTIPLIER_MIN ({self.BANKROLL_MULTIPLIER_MIN}) "
                f"must not exceed BANKROLL_MULTIPLIER_MAX "
                f"({self.BANKROLL_MULTIPLIER_MAX})."
            )
        return self

    @field_validator("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR")
    @classmethod
    def validate_safe_close_direction_limit(cls, v: int) -> int:
        # Same silent-disable trap as the other guardrail knobs: runtime
        # branches on `> 0`, so a negative value would behave identically
        # to 0 (disabled). Fail fast at load with a clear error.
        if v < 0:
            raise ValueError(
                f"SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR must be >= 0 (got {v}); "
                f"use 0 to disable the gate, or a positive integer (e.g. 8) "
                f"for the max entries per (user, side) per hour."
            )
        return v

    @field_validator("CORRELATED_MAJORS_SAME_DIR_LIMIT")
    @classmethod
    def validate_correlated_majors_same_dir_limit(cls, v: int) -> int:
        # Same silent-disable trap as the other guardrail knobs: runtime
        # branches on `> 0`, so a negative value would behave identically
        # to 0 (disabled). Fail fast at load with a clear error.
        if v < 0:
            raise ValueError(
                f"CORRELATED_MAJORS_SAME_DIR_LIMIT must be >= 0 (got {v}); "
                f"use 0 to disable the gate, or a positive integer (e.g. 2) "
                f"for the max same-direction crypto-majors per candle window."
            )
        return v

    @field_validator("SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC")
    @classmethod
    def validate_safe_close_imbalance_threshold(cls, v: float) -> float:
        # Non-finite (NaN / ±Inf) and non-positive thresholds collapse
        # the gate to "always override" (NaN comparisons are False;
        # `|imbalance| > 0` is true on any non-zero exposure). Both are
        # silent disable / silent over-fire traps. Reject at load with
        # a clear error.
        if not math.isfinite(v):
            raise ValueError(
                f"SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC must be a finite "
                f"number (got {v!r}); use a positive value such as 5.0 "
                f"for the minimum imbalance (USDC cost basis) that "
                f"triggers a side override."
            )
        if v <= 0:
            raise ValueError(
                f"SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC must be > 0 "
                f"(got {v}); 0 would override on any non-zero imbalance, "
                f"collapsing the gate into a noise amplifier."
            )
        return v

    @field_validator("FAST_TOPUP_MIN_USDC")
    @classmethod
    def validate_fast_topup_min_usdc(cls, v: float) -> float:
        # Non-finite + non-positive both collapse to silent over-fire.
        # Reject at load.
        if not math.isfinite(v):
            raise ValueError(
                f"FAST_TOPUP_MIN_USDC must be a finite number (got {v!r})."
            )
        if v <= 0:
            raise ValueError(
                f"FAST_TOPUP_MIN_USDC must be > 0 (got {v}); "
                f"0 would trigger top-ups on any non-zero imbalance, "
                f"producing infinite back-and-forth between legs."
            )
        return v

    @field_validator("FAST_TOPUP_COOLDOWN_SECONDS")
    @classmethod
    def validate_fast_topup_cooldown(cls, v: float) -> float:
        # 0 cooldown would allow the same (user, market) to spin
        # top-ups continuously. Non-finite would silently disable
        # the cooldown by making every comparison False.
        if not math.isfinite(v):
            raise ValueError(
                f"FAST_TOPUP_COOLDOWN_SECONDS must be a finite number "
                f"(got {v!r})."
            )
        if v <= 0:
            raise ValueError(
                f"FAST_TOPUP_COOLDOWN_SECONDS must be > 0 (got {v}); "
                f"zero cooldown would let the same (user, market) "
                f"spin top-ups indefinitely."
            )
        return v

    @field_validator("ROBUSTNESS_CLASSIFY_INTERVAL_SEC")
    @classmethod
    def validate_robustness_classify_interval(cls, v: int) -> int:
        # APScheduler raises ValueError at boot for a non-positive interval, so
        # reject it here with a clear message instead of crashing the process.
        if v <= 0:
            raise ValueError(
                f"ROBUSTNESS_CLASSIFY_INTERVAL_SEC must be > 0 (got {v}); "
                f"a non-positive interval is invalid for the scheduler."
            )
        return v

    @field_validator("CLOSE_SWEEP_MAX_LEG_SPREAD")
    @classmethod
    def validate_close_sweep_max_leg_spread(cls, v: float) -> float:
        # Reject NaN / +Inf / -Inf BEFORE the sign check. Pydantic accepts
        # non-finite floats by default; NaN comparisons are always False
        # (NaN > 0 → False) so NaN would silently disable the gate, and
        # +Inf would make `leg_spread_yes > max_leg_spread` impossible to
        # satisfy (also a silent disable). Same silent-disable trap as
        # the negative-value case — fail fast at load with a clear error.
        if not math.isfinite(v):
            raise ValueError(
                f"CLOSE_SWEEP_MAX_LEG_SPREAD must be a finite number "
                f"(got {v!r}); use 0 to disable the gate or a positive "
                f"finite value (e.g. 0.02 for 2 cents)."
            )
        # Same rationale as TOB_STALE_MS: the runtime check branches on
        # `> 0`, so a negative value would silently disable the gate.
        # Reject at load with a clear ValueError.
        if v < 0:
            raise ValueError(
                f"CLOSE_SWEEP_MAX_LEG_SPREAD must be >= 0 (got {v}); use 0 "
                f"to disable the gate, any positive value (e.g. 0.02 for "
                f"2 cents) for the per-leg spread threshold."
            )
        return v

    @field_validator("MIN_COMPLETE_SET_EDGE")
    @classmethod
    def validate_min_complete_set_edge(cls, v: float) -> float:
        # Same defence-in-depth as CLOSE_SWEEP_MAX_LEG_SPREAD: a non-finite
        # threshold (NaN / ±Inf) would silently disable the gate (`metric <
        # NaN` is always False; `metric < +Inf` always accepts), and a
        # negative threshold would accept negative-edge entries (the exact
        # bug the gate exists to prevent). Both fail-closed at config load.
        if not math.isfinite(v):
            raise ValueError(
                f"MIN_COMPLETE_SET_EDGE must be a finite number (got {v!r}); "
                f"use 0 to disable the gate, or a positive value such as "
                f"0.005 for 50 bps minimum complete-set edge."
            )
        if v < 0:
            raise ValueError(
                f"MIN_COMPLETE_SET_EDGE must be >= 0 (got {v}); use 0 to "
                f"disable the gate, any positive value for the minimum edge "
                f"required to accept the entry."
            )
        return v

    @field_validator("TOB_STALE_MS")
    @classmethod
    def validate_tob_stale_ms(cls, v: int) -> int:
        # Reject negative values explicitly: the gate disable sentinel is 0,
        # and the freshness check branches on `_tob_stale_ms > 0`. A negative
        # value would silently disable the gate the same as 0, hiding the
        # misconfiguration from the operator. Fail fast at config load.
        if v < 0:
            raise ValueError(
                f"TOB_STALE_MS must be >= 0 (got {v}); use 0 to disable the "
                f"freshness gate, any positive integer for the threshold in ms."
            )
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        # asyncpg.create_pool accepts postgres:// and postgresql:// but NOT
        # the SQLAlchemy-style "postgresql+asyncpg://" prefix.
        if v.startswith("postgresql+asyncpg://"):
            return "postgresql://" + v[len("postgresql+asyncpg://"):]
        if v.startswith("postgres://"):
            return "postgresql://" + v[len("postgres://"):]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def resolve_trading_mode(settings: "Settings | None" = None) -> str:
    """Return ``"live"`` only when all three live-trading guards are open.

    Single source of truth for the paper/live label shared by the scheduler,
    the ops API, and the operator panel. The ``ENABLE_LIVE_TRADING`` guard must
    never diverge between those surfaces, so the condition lives here once.

    ``settings`` may be passed so a caller's own ``get_settings()`` result is
    used (each surface imports it locally, which tests monkeypatch); when
    omitted the canonical cached settings are read.
    """
    s = settings or get_settings()
    if s.ENABLE_LIVE_TRADING and s.EXECUTION_PATH_VALIDATED and s.CAPITAL_MODE_CONFIRMED:
        return "live"
    return "paper"


def _load_env_file_values() -> dict[str, str]:
    """Read the same ``.env`` file ``Settings`` consumes, without overriding
    real environment values. Missing or unreadable files yield an empty
    dict — validation must never crash boot.

    Path resolution intentionally matches ``SettingsConfigDict(env_file=".env")``
    exactly: cwd-relative only. A module-dir fallback would read a file
    that ``get_settings()`` will NOT read, which could suppress missing-env
    alerts the operator needs to see and let boot fail later with a
    ``ValidationError`` instead.
    """
    path = Path(".env")
    if not path.exists():
        return {}
    try:
        from dotenv import dotenv_values

        return {k: v for k, v in dotenv_values(str(path)).items() if v is not None}
    except Exception as exc:  # noqa: BLE001 — never crash boot on .env read
        logger.warning(
            "config validation: .env read failed at %s: %s", path, exc,
        )
        return {}


def validate_required_env() -> list[str]:
    """Return the list of REQUIRED env vars that are missing at boot.

    Reads from the same sources ``Settings`` consumes: ``os.environ`` plus
    the ``.env`` file (when present). Logs an ERROR line per missing
    variable (key name only — values are NEVER logged). The process is
    allowed to continue so that the health endpoint can surface the
    degraded state via the operator alert path. Callers must NOT log the
    returned values; they are key names only.
    """
    resolved: dict[str, str] = dict(os.environ)
    for key, value in _load_env_file_values().items():
        # os.environ wins over .env, matching pydantic-settings precedence.
        if key not in resolved:
            resolved[key] = value

    def _has(key: str) -> bool:
        return bool((resolved.get(key) or "").strip())

    missing: list[str] = [k for k in REQUIRED_ENV_VARS if not _has(k)]
    for group in REQUIRED_ENV_VAR_GROUPS:
        if not any(_has(name) for name in group):
            # Report the group as a single composite key so the operator
            # sees both candidate names without two duplicate alerts.
            missing.append(" or ".join(group))
    for key in missing:
        logger.error("required env var missing: %s", key)
    return missing
