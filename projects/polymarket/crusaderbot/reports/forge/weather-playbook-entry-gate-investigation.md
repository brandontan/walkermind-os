# WARP — Weather + Playbook zero-entry investigation

Role: WARP•R00T (investigate / diagnose — REPORT ONLY, no code change)
Validation Tier: MINOR (diagnosis doc; any resulting fix is a separate lane)
Claim Level: FOUNDATION (root-cause established from runtime DB + code; no build)
Validation Target: why weather + playbook book 0 positions (historical + post-deploy)
while late_entry_v3 trades normally.
Not in Scope: any code change, threshold tuning, or flag flip — all CMD decisions.
Suggested Next Step: WARP🔹CMD picks an observability/tuning lane from §6.

---

## 1. The question

Expected: after #1595/#1596 merged + deployed (~14:00 UTC), weather/playbook
should attempt entries. Reality: only `late_entry_v3` enters (1170 positions, 8
in the last ~40 min); weather + playbook = **0 positions, ever**.

## 2. Decisive finding — the handoff's framing is WRONG

The handoff assumed the blocker is the operator flag being OFF / the #1595/#1596
fix not being reached. **Both are false.** The live `scan_runs` telemetry is
unambiguous:

```
scan_runs.zero_reason_breakdown (every multi-user tick, 14:00–14:10 UTC):
  weather:filter_or_no_match  : 1
  playbook:filter_or_no_match : 1
  late_entry_v3:filter_or_no_match : 1   (big-universe scan)
```

The reason is **`filter_or_no_match`, NOT `strategy_disabled`.** In
`signal_scan_job.run_once` the strategy emits `strategy_disabled` only when the
flag resolves OFF (lines 3278, 3327); `filter_or_no_match` is emitted only after
the strategy actually **dispatched and ran `.scan()` and got back zero
candidates** (lines 3279, 3328). So:

- **The flags ARE ON.** `WEATHER_STRATEGY_ENABLED` / `PLAYBOOK_STRATEGY_ENABLED`
  default `False` in code (config.py:132,140) and have **no `cfg:` override row**
  in `system_settings` (only `cfg:COMPLETE_SET_ARB_ENABLED=true` and
  `cfg:SCAN_SNAPSHOT_ENABLED=true` exist) — therefore the Fly env sets both to
  `true`, which is what `resolve_bool` returns absent a DB override.
- **Corroboration:** the flag-gated user-independent market sync
  (`_sync_weather_markets` / `_sync_playbook_sports_markets`, run only when the
  flag is ON — lines 3115–3147) IS running: `markets.synced_at` for Weather and
  sports rows is **2026-06-06 14:10 UTC** (current, post-deploy). If the gate
  were closed, those rows would be stale.
- **#1595/#1596 code path IS reached.** Those PRs fixed the sourcing functions
  (`_sync_*_markets`); the fresh 14:10 syncs prove they execute every tick.

## 3. Actual root cause — opportunistic strategies, strict edge bars, no qualifying setups

Both strategies run every ~3-min tick but their `.scan()` returns `[]` because no
market currently clears their (intentionally conservative) entry filters. This is
behaviour-by-design starvation, not a gate or a bug.

**Weather** (`domain/strategy/strategies/weather.py:228-340`) — a YES candidate
must clear ALL of: `volume_24h ≥ 500`, `spread ≤ 0.03`, `yes_price ≤ 0.45`, valid
temperature bucket, `2 ≤ hours_to_expiry ≤ 72`, **`EV ≥ 0.10` (a 10% modelled
edge)**, and `kelly_size ≥ $0.50` — AND a live forecast ensemble must exist
(`fetch_all` → Open-Meteo/METAR/VisualCrossing; empty → `weather_city_no_data` →
`[]`). The scan reads markets LIVE from Gamma, so the 1034 persisted `Weather`
rows are the WebTrader copy (#1596), not the scan input. A handful of daily city
markets rarely produce a ≥10%-EV / ≤0.45-price dislocation, so most ticks yield
nothing.

**Playbook** (`domain/strategy/strategies/playbook.py:300-398`) — needs sports
markets inside the pre-event window (`select_sports_markets_in_window`), ≥2 token
ids, live orderbooks with valid bid/ask, AND a module edge from the router. The
external sports feed defaults to **`NullFeed`** (line 294;
`PLAYBOOK_INJURY_FEED_ENABLED` / `PLAYBOOK_PUBLIC_FEED_ENABLED` both default OFF
in config), so the Injury-Alpha and Public-Fade modules **abstain** — only
Closing-Edge (Gamma consensus) and Sharp-Money (flow) can fire. Tradeable leans
are correspondingly rare.

## 4. Answers to the three diagnostic questions

1. **Runtime/env flag gating the scan loop?** Yes — `WEATHER_STRATEGY_ENABLED` /
   `PLAYBOOK_STRATEGY_ENABLED` (runtime_config-overridable, default OFF in code).
   But they are currently **ON** (Fly env), so the gate is NOT the blocker.
   Registration is unconditional (`registry.py:163-173`; scheduler.py:1238
   "always registered"), so the strategies are present and dispatching.
2. **Opportunistic by design?** **Yes — this is the actual cause.** Weather fires
   only on a ≥10%-EV temperature-bucket dislocation in a live daily city market;
   playbook fires only on a pre-event sports market with a module edge (2 of its
   4 alpha modules are dark on the default NullFeed). Zero qualifying setups in
   the observed window → `filter_or_no_match` → 0 entries.
3. **Is the #1595/#1596 fix reached at runtime?** **Yes.** Market sourcing runs
   every tick (Weather/sports `synced_at` = 14:10 UTC). The fix works; it is just
   upstream of an edge filter that nothing is currently passing.

## 5. Evidence (live CrusaderBot DB ykyagjdeqcgcktnpdhes)

- `system_settings`: `cfg:` rows = `COMPLETE_SET_ARB_ENABLED=true`,
  `SCAN_SNAPSHOT_ENABLED=true` only. No weather/playbook override → env default.
- `user_settings.active_preset`: `weather_monitor`=2, `playbook`=1 (users exist;
  preset gating is NOT the blocker).
- `positions.strategy_type`: `late_entry_v3`=1170 (the ONLY value, all history);
  weather/playbook = 0.
- `markets.synced_at` (max): Weather 14:10:00, sports 14:10:00, crypto 14:10:29 —
  sourcing live.
- `scan_runs.zero_reason_breakdown`: `weather:filter_or_no_match` +
  `playbook:filter_or_no_match` on every multi-user tick (the decisive signal).

## 6. Recommendation (NO code change without CMD review)

This is not a defect to "fix" — the strategies are healthy and waiting for a
qualifying edge. The real gap is **observability**: today the binding constraint
(no-feed vs. EV-too-low vs. no-in-window-market) lives only in DEBUG logs
(`weather_city_scan_result` skip_* counts, `weather_city_no_data`), invisible
without Fly log access. Options, CMD's call:

1. **Confirm the binding constraint from Fly logs first** — grep
   `weather_city_scan_result` (skip_vol/spread/price/ev/hours/size) and
   `weather_city_no_data`; for playbook check snapshot counts + router abstain
   reasons. This tells us whether it's feed-starvation or threshold-starvation
   before any change.
2. **If feed-starved (weather `no_data` dominant):** verify forecast-host
   reachability under the Fly network policy (Open-Meteo is keyless; VisualCrossing
   needs `VISUALCROSSING_API_KEY`). A blocked egress host would silently zero the
   ensemble.
3. **If threshold-starved (skip_ev/skip_price dominant):** `min_ev=0.10` /
   `max_price=0.45` are conservative; CMD may relax them in the weather config
   (config-only, no code) to accrue paper entries — separate STANDARD lane.
4. **Playbook feed coverage:** enabling `PLAYBOOK_INJURY_FEED_ENABLED` /
   `PLAYBOOK_PUBLIC_FEED_ENABLED` (+ `ODDS_API_KEY`) re-arms 2 dark alpha modules;
   otherwise Gamma-consensus alone rarely leans — separate lane + decision.
5. **Highest-ROI structural fix:** surface per-strategy skip-reason counts into
   `scan_runs` (a new breakdown column or extend `zero_reason_breakdown`) so the
   binding constraint is observable from the DB without log access — small
   STANDARD lane if CMD wants standing visibility.

## 7. Safety / invariants

Investigation only — zero code touched. No secrets, no risk/Kelly/LIVE-guard
surface involved. Read-only DB queries + source review.

Validation Handoff (NEXT PRIORITY):

```
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/weather-playbook-entry-gate-investigation.md
Tier: MINOR
```
