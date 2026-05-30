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

    # --- ClobAdapter toggle (Phase 4A) ---
    # Default False keeps every caller on MockClobClient (paper-safe). Real
    # network calls are unreachable until an operator flips this AND every
    # other activation guard. See docs/runbooks/clob-adapter.md (TBD).
    USE_REAL_CLOB: bool = False

    # --- Balance alerting ---
    # Fire low_balance alert when user wallet balance drops below this value.
    # Set to 0 to disable the alert globally.
    LOW_BALANCE_THRESHOLD_USDC: float = 50.0

    # --- Polygon ---
    USDC_POLYGON: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    USDC_DECIMALS: int = 6

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
    MAX_SINGLE_POSITION_PCT: float = 0.10      # 10% of balance per position
    MAX_TOTAL_EXPOSURE_PCT: float = 0.80       # 80% of balance max open exposure
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
    # close_sweep  : final 35s, moderate lean (≥0.05 diff), fav ≥0.55 (hold to candle close)
    # safe_close   : enter rem 30–60s, Kreo Min Edge 1% (ask_diff ≥0.01), favored side, force-exit at rem 30s
    # flip_hunter  : Kreo "Early Flip Hunter" — enter early (first 140s elapsed for 5m / 420s for 15m),
    #                follow trend (favored side), Min Edge 3% (ask_diff ≥0.03), force-exit at upper window bound
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

    # flip_hunter — Kreo "Early Flip Hunter": enter early, follow trend (favored side).
    # Timeframe-aware: 5m vs 15m have different absolute windows.
    PRESET_FLIP_HUNTER_MIN_ASK_DIFF: float = 0.03   # Kreo Min Edge 3% (was 0.05)
    PRESET_FLIP_HUNTER_FAV_PRICE_MIN: float = 0.50  # favored side ≥ 0.50 (was 0.26 underdog)
    PRESET_FLIP_HUNTER_FAV_PRICE_MAX: float = 0.95  # skip near-resolved (was 0.36 underdog ceiling)
    # 5m candle: enter elapsed 0–140s → rem 160–300s. Force-exit at elapsed 140s → rem 160s.
    PRESET_FLIP_HUNTER_5M_MIN_REM_SEC: float = 160.0
    PRESET_FLIP_HUNTER_5M_MAX_REM_SEC: float = 300.0
    PRESET_FLIP_HUNTER_5M_FORCE_EXIT_REM_SEC: float = 160.0
    # 15m candle: enter elapsed 0–420s → rem 480–900s. Force-exit at elapsed 420s → rem 480s.
    PRESET_FLIP_HUNTER_15M_MIN_REM_SEC: float = 480.0
    PRESET_FLIP_HUNTER_15M_MAX_REM_SEC: float = 900.0
    PRESET_FLIP_HUNTER_15M_FORCE_EXIT_REM_SEC: float = 480.0
    MARKET_SIGNAL_SCAN_INTERVAL: int = 60
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
    MIN_COMPLETE_SET_EDGE: float = 0.005  # env: MIN_COMPLETE_SET_EDGE

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
