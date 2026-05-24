# WARP•FORGE Report — Enable Auto-Redeem (settlement) in deployed env

- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: the AUTO_REDEEM_ENABLED runtime flag in fly.toml.
- Not in Scope: any code change to the redeem/settlement logic (unchanged); live on-chain redemption (ENABLE_LIVE_TRADING stays false → paper settlement only).
- Suggested Next Step: WARP🔹CMD review + Fly redeploy; confirm positions settle.

---

## 1. What was built

One-line config change: `fly.toml` `AUTO_REDEEM_ENABLED = "false"` → `"true"`.

Diagnosis: `services/redeem/redeem_router.detect_resolutions()` returns at its first
guard when `AUTO_REDEEM_ENABLED` is false, so the resolution/settlement scan never
ran in the deployed env (job_runs showed the `resolution` job finishing in ~1ms with
zero work every 5 min). The code default is `True` with an explicit comment that the
flag is "intentionally True in paper mode so paper users see" settlement, and the
owner already configures auto-redeem per-user (user_settings.auto_redeem_mode) in the
web terminal — but the global fly.toml override (`"false"`) short-circuited it before
the per-user mode was ever read. Flipping the global flag lets the per-user settings
take effect. Paper-only (ENABLE_LIVE_TRADING=false → settle_winning skips the on-chain
CTF step), so there is no live-capital side effect.

## 2. Current system architecture

No code path changed. With the flag true, the existing scheduler `resolution` job
(`check_resolutions` → `detect_resolutions`, every RESOLUTION_CHECK_INTERVAL=300s)
now runs: it classifies positions in resolved markets (losers settle inline, winners
enqueue to redeem_queue; per-user instant/hourly mode governs redeem timing) and flips
`markets.resolved`. Combined with the merged #1326 (candle markets resolve via slug),
crypto candle positions now settle at their end time.

## 3. Files created / modified (full repo-root paths)

- projects/polymarket/crusaderbot/fly.toml (AUTO_REDEEM_ENABLED false → true)
- projects/polymarket/crusaderbot/reports/forge/enable-auto-redeem.md
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

- Verified via live DB: the resolution job runs every 5 min but no-ops in ~1ms
  (AUTO_REDEEM_ENABLED guard); the candidate query returns the 5 stuck positions, so
  enabling the flag is the only thing gating their settlement.
- Paper-safe: settle_winning_position only calls the on-chain redemption when
  `mode == "live"`; ENABLE_LIVE_TRADING=false and all positions are paper.

## 5. Known issues

- Effect is broad: on first post-deploy resolution tick, ALL past-due resolvable
  positions settle (not just the 5 candles) — intended (paper P&L bookkeeping).
- Pure config flip; takes effect only on Fly redeploy.

## 6. What is next

- WARP🔹CMD review + Fly redeploy.
- Confirm via Supabase MCP (project ykyagjdeqcgcktnpdhes) that the 5 stuck positions
  settle (status closed, exit_reason resolution_win/resolution_loss) and
  markets.resolved flips TRUE for past-due updown markets.
- Separate lane (owner raised): tune Late Entry V3 entry timing to the proven
  "final ~35s" window — requires a faster scan cadence for the crypto-candle preset
  (current SIGNAL_SCAN_INTERVAL=180s makes a 35s window unreliable).
