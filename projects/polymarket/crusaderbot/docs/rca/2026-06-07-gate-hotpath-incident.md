# Post-Incident RCA — 2026-06-07 Production Wedge (gate hot-path / boot-connect)

Author: WARP•R00T (WARP-88) · Written: 2026-06-08 09:39 Asia/Jakarta
Status: ROOT CAUSE OPEN (two competing hypotheses — see §3 and §7)
References: Linear WARP-88 · PR #1694 (`WARP/root-risk-profile-capital`) ·
PR #1688 (`WARP/honest-tpsl-controls`) · Sentry issue DAWN-SNOWFLAKE-1729-2J ·
follow-on remediation #1698 / #1699

---

## 1. Summary

On 2026-06-07 the CrusaderBot production app (Fly) became unresponsive twice in a
~1h13m window: `/health` froze reporting a database `TimeoutError`, the asyncio
event loop hung, and no trades executed after the wedge. The app runs in PAPER
mode — no real capital was at risk. An owner-authorised Fly machine restart
recovered it immediately each time. Postgres / Supavisor were healthy throughout
(no stuck queries, connections well within pool limits).

Two root-cause hypotheses remain on the table and have **not** been reconciled to
a single conclusion — this RCA records both rather than asserting a disputed one
(see §3). This document is deliberately written while the question is still open
so the timeline and evidence are preserved.

## 2. Timeline (UTC)

| Time (UTC) | Event |
|---|---|
| 20:03 | App deployed (the version carrying PR #1694's gate change + migration 090). |
| 20:37 | First wedge — `/health` freezes on database `TimeoutError`; event loop hangs (~34 min after deploy — consistent with a slow drain, not an instant crash). |
| ~20:37–21:17 | No trades execute. Operator paged (×2). |
| 21:17–21:18 | Owner-authorised Fly machine restart (WARP-85 CD reboot). App recovers; one write succeeds. `factor_vectors` last write 21:18:55. |
| ~21:23 | Second wedge — ~5 min after the restart, the same symptom recurs on the same code. `rows_last_5m = 0` confirmed by WARP🔹CMD. |
| ~21:50 | Recovered (owner-authorised restart). Stable thereafter in PAPER mode. |

Supporting evidence during the window:
- DB healthy: `read_only = off`, 16/60 connections in use, no stuck/long-running queries, idle backends present.
- Sentry: `DAWN-SNOWFLAKE-1729-2J` — `TimeoutError`, ~2,511 events concentrated at `/health`.

## 3. Root Cause — TWO HYPOTHESES (unreconciled)

### Hypothesis A — gate hot-path DB read exhausted the pool (the original WARP-88 framing)
PR #1694 introduced `gate._capital_alloc_pct()` — a `SELECT capital_alloc_pct FROM
user_settings WHERE user_id = $1` executed inside the RISK-stage gate (step 8),
which runs **per candidate, per tick**. Under load this can hold/await asyncpg pool
connections faster than they are released, exhausting the pool; an awaited acquire
that never resolves then blocks the event loop, freezing `/health` (which also
needs the DB) → the observed wedge. The 34-min delay to the first wedge fits a slow
pool drain rather than an instant fault.

### Hypothesis B — transient Supabase boot-connect stall (the later WARP/root-db-boot-resilience framing, #1699)
The subsequent analysis concluded the wedge was an **infrastructure boot-connect
stall, not a code regression**: at boot the asyncpg pool's warm-ping/connect to
Supabase/Supavisor hung, the event loop wedged, and `/health` froze on the DB
`TimeoutError`. Evidence cited: the runtime delta from the last healthy version
(v1222) was nil — the intervening merges were #1696 (byte-identical) and #1698
(test-only) — so there was "no code change to regress," pointing at a transient
connectivity stall. The remediation (#1699) hardened the **boot** path (bounded
warm-ping timeout + retry/backoff `create_pool`), not the gate.

### Why this is left OPEN
The two hypotheses are not fully consistent and the evidence does not decisively
pick one:
- Hypothesis A is supported by the deploy-correlated timing (wedge began after the
  20:03 deploy that carried #1694) and the per-tick DB read being a textbook
  event-loop-starvation pattern.
- Hypothesis B is supported by the DB being healthy throughout and the "nil runtime
  delta from v1222" argument — though that argument compares against v1222, not
  against the earlier baseline that predates #1694's gate read.
- **Material unresolved fact:** the `gate._capital_alloc_pct()` per-candidate DB
  read described in Hypothesis A is **still present in `domain/risk/gate.py` today**
  (step 8, `_capital_alloc_pct`, lines ~161–187; called from `evaluate` and
  `resume_safety_check`). It was never removed. So if Hypothesis A is correct, the
  trigger condition is still live; if Hypothesis B is correct, the gate read is a
  latent risk regardless.

WARP🔹CMD should adjudicate A vs B (e.g. by correlating Sentry `/health` Timeout
onset with trade-tick volume, and by load-testing the gate read against pool
saturation) before closing this RCA.

## 4. Fix Applied (and a correction to the original WARP-88 note)

The original WARP-88 incident note stated: *"Fix: Removed DB read from gate hot
path. Branch: WARP/root-gate-capital-alloc-fix."* **This does not match repo
truth:** no such branch exists, and the gate DB read was NOT removed — it is still
in `gate.py`. The corrected record of what actually shipped:

- **#1698 (`WARP/root-gate-test-pool-mock`, test-only):** restored green CI by
  mocking `gate._capital_alloc_pct()` in the gate tests that had been hitting the
  real pool. This addressed a CI failure, **not** the production hot-path read.
- **#1699 (`WARP/root-db-boot-resilience`, MAJOR):** hardened the DB **boot**
  path — `_init_connection` warm-ping bounded by `asyncio.wait_for(5s)`;
  `init_pool()` wraps `create_pool` in bounded retry + exponential backoff
  (5 attempts, 1→16s) then re-raises for a clean Fly restart; `min_size` 1→2;
  `max_inactive_connection_lifetime` 60→300s. This makes a flaky boot self-heal
  (mitigates Hypothesis B) but does **not** touch the gate hot-path read
  (Hypothesis A is not addressed).
- **Migration 090** (`normalize_profile_capital_alloc`, shipped with #1694): kept
  in place — data-only normalisation, assessed safe.

Net: the incident's immediate symptom is mitigated for the boot-stall vector; the
gate-hot-path-read vector remains open (see §6, §7).

## 5. Process Violations

Three process gaps contributed to this incident reaching production unreviewed:

1. **PR #1694 shipped to production without WARP🔹CMD awareness or a Linear issue.**
   A MAJOR capital-path gate change (and the per-tick DB read at its centre) reached
   prod without the gate review that would likely have flagged the hot-path read.
2. **Migration 090 shipped without WARP🔹CMD sign-off.** Bundled into the #1694
   deploy; data-only and safe in hindsight, but deployed without the migration
   awareness gate.
3. **PR #1688 (E.2 TP/SL controls) deployed to production 2026-06-07 19:02 UTC
   without a WARP•SENTINEL gate** — a MAJOR-tier violation (the PR was explicitly
   "HELD for SENTINEL"). This is independent of the wedge but part of the same
   "MAJOR-to-prod-without-gate" pattern. (Closed retroactively by WARP-83 retroactive
   SENTINEL — `docs/sentinel/1688_retroactive_sentinel.md`, CONDITIONAL PASS.)

## 6. Prevention

- **All MAJOR PRs require WARP•SENTINEL + WARP🔹CMD sign-off before merge/deploy.**
  No MAJOR lane goes to prod on CI-green alone.
- **The RISK-stage gate hot path MUST NOT contain DB reads** (asyncpg pool-safety
  invariant). NOTE: this is currently **aspirational, not satisfied** — the
  `gate._capital_alloc_pct()` per-candidate read still exists. A follow-up lane
  should move it off the hot path (preload / cache the per-user `capital_alloc_pct`,
  e.g. thread it onto `GateContext` at candidate construction, or a short-TTL
  in-process cache) so the invariant actually holds. Until then, Hypothesis A's
  trigger remains live.
- **New migrations require WARP🔹CMD awareness before deploy** — listed in correct
  dependency order, with application deploy gated to run only AFTER all required
  migrations have applied. The Fly `release_command`-before-serve ordering (#1676)
  is the enforcing mechanism; this incident's #1694 code + migration 090 co-deploy
  is exactly the code↔migration dependency that ordering protects (cf. the
  load-bearing migration-before-code-read dependency in PR #1688 / migration 089).
- **asyncio-only invariant:** no blocking or unbounded-await calls anywhere in the
  event loop (the #1699 bounded warm-ping/retry is the boot-path instance of this).

## 7. Status

- Symptom: RESOLVED operationally (owner restarts recovered; boot path hardened by
  #1699). PAPER mode throughout — no capital impact.
- Root cause: **OPEN** — Hypotheses A (gate hot-path DB read) and B (transient
  boot-connect stall) are both on record and not reconciled. WARP🔹CMD to adjudicate.
- Open remediation: the gate hot-path DB read (`_capital_alloc_pct`) is still present
  and should be moved off the per-candidate path regardless of which hypothesis is
  primary — it is a standing pool-safety risk and the named invariant violation.
- This RCA is documentation only; no code, migration, or flag was changed in writing it.
