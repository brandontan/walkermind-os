# Kill Switch Procedure — CrusaderBot

**Owner:** Operator (Bayue Walker)
**Audience:** WARP🔹CMD operator on call.
**Last reviewed:** 2026-05-08 Asia/Jakarta — R12 production-paper deploy.

This runbook covers the end-to-end kill-switch workflow used both in
incidents and during the investor demo. The kill switch halts new trades
without closing existing positions, so it is the safest "pause" lever
during paper or live operation.

---

## 1. What the kill switch does

Activating the kill switch (`/kill` or `/killswitch pause`):

- Sets `system_settings.key = 'kill_switch_active'` to `true`.
- Causes `domain.risk.gate` to short-circuit step 1 — every new candidate
  is rejected with `KILL_SWITCH_ACTIVE` before any execution path runs.
- Triggers a fan-out Telegram broadcast to every user with
  `auto_trade_on=true OR access_tier >= 2` so subscribers know trading
  is paused.
- Writes one `audit.log` row (`kill_switch_pause`).
- Live → paper auto-fallback fires for every currently-live user when the
  `lock` variant is used (see §3 below). The plain `pause` does NOT flip
  trading mode — open live positions stay live.

Deactivating (`/resume` or `/killswitch resume`) reverses the gate and
emits a complementary broadcast.

---

## 2. Operator entry points

The kill switch can be triggered from three places. They all converge on
the same audited `domain.ops.kill_switch.set_active(...)` path.

| Surface | Command | Notes |
| --- | --- | --- |
| Telegram (alias) | `/kill` and `/resume` | Demo-readiness alias. Operator-only; non-operators silently ignored. |
| Telegram (canonical) | `/killswitch pause`, `/killswitch resume`, `/killswitch lock` | Same gate, exposes `lock` (force every user `auto_trade_on=false` + live→paper cascade). |
| Web dashboard | `POST /ops/kill`, `POST /ops/resume` (via the buttons on `GET /ops`) | Demo-grade auth: requires the `OPS_SECRET` Fly secret via the `X-Ops-Token` header OR `?token=<value>` query param. Operator opens `https://crusaderbot.fly.dev/ops?token=<OPS_SECRET>` from a phone bookmark and taps the button. `OPS_SECRET` unset → 503. Wrong / missing token → 403. Full per-operator auth deferred post-demo (TODO in `api/ops.py`). |
| REST | `POST /admin/kill?active=true` | Bearer-protected by `ADMIN_API_TOKEN`. Use only when Telegram is unavailable. |

Operator allowlist for the Telegram surface is the
`OPERATOR_CHAT_ID` Fly secret. `bot/handlers/admin._is_operator` accepts
**only** the Telegram user whose `effective_user.id` matches
`OPERATOR_CHAT_ID` (verified at `bot/handlers/admin.py:34-37`). The bot
rejects the command silently for non-operators to avoid confirming the
surface to unauthorised users. To grant operator access, set
`OPERATOR_CHAT_ID` to the operator's Telegram user id (in a 1:1 chat
with the bot, the user id and chat id are identical, which is why the
same value is reused for both alert delivery and command authorisation).
The `ADMIN_USER_IDS` Fly secret (comma-separated Telegram user ids) is
consumed by the Tier 2 operator seeder
(`projects/polymarket/crusaderbot/scripts/seed_operator_tier.py`),
which runs on every Fly deploy via `[deploy] release_command` and
upserts each id into `users` with `access_tier >= 2`. It does NOT
gate `/kill` / `/resume` — that path remains the single
`OPERATOR_CHAT_ID` allowlist verified at
`bot/handlers/admin.py:_is_operator`. Multi-operator command access
is a separate, unimplemented lane.

---

## 3. Demo / drill procedure

Run this sequence against `crusaderbot.fly.dev` when verifying a deploy
or rehearsing the investor demo. All steps are paper-mode safe — the
activation guards remain NOT SET throughout, so no live capital is
touched even on accidental kill-switch usage.

### 3.1 Pre-flight

```bash
# 1. Confirm app is healthy:
curl -fsS https://crusaderbot.fly.dev/health | jq '.status, .mode'
# expected: "ok", "paper"

# 2. Confirm the kill switch is currently OFF (default):
curl -fsS -X GET https://crusaderbot.fly.dev/admin/status \
  -H "Authorization: Bearer <ADMIN_API_TOKEN>" | jq '.kill_switch'
# expected: false
```

### 3.2 Activate via Telegram

1. Operator opens the bot in Telegram.
2. Send `/kill`.
3. Expect the bot to reply **within 3 seconds** with:
   ```
   🔴 Kill switch *ACTIVE*. Auto-trade paused (≤30s propagation).
   Use `/killswitch resume` to re-open.
   ```
4. Within ~5 seconds, broadcast messages reach every active subscriber:
   ```
   🛑 Auto-trade paused by operator. New trades are blocked.
   Existing positions remain open until you close them.
   ```

**Operator log:**

```
[YYYY-MM-DD HH:MM Asia/Jakarta] /kill ack Δt = ___ seconds (target < 3s)
[YYYY-MM-DD HH:MM Asia/Jakarta] broadcast fan-out completed in Δt = ___ seconds
```

### 3.3 Verify the gate is closed

```bash
# 1. /admin/status reports kill_switch=true:
curl -fsS https://crusaderbot.fly.dev/admin/status \
  -H "Authorization: Bearer <ADMIN_API_TOKEN>" | jq '.kill_switch'
# expected: true

# 2. Operator dashboard reflects the killed state. Open in Telegram:
#    /ops_dashboard
#    The header should display 🔴 KILL SWITCH ACTIVE.

# 3. Audit log captured the event:
#    Run /auditlog 5 in Telegram and confirm one entry of type
#    kill_switch_pause within the last minute.
```

### 3.4 Resume via Telegram

1. Send `/resume`.
2. Expect within 3 seconds:
   ```
   🟢 Kill switch deactivated. Auto-trade resumed.
   ```
3. Subscribers do **not** receive a broadcast on resume (intentional —
   operators control re-engagement timing per user).
4. `/admin/status` `kill_switch` flips back to `false`.
5. New auto-trade signals begin executing again on the next signal scan
   tick (≤ 60 seconds depending on `SIGNAL_SCAN_INTERVAL`).

**Operator log:**

```
[YYYY-MM-DD HH:MM Asia/Jakarta] /resume ack Δt = ___ seconds (target < 3s)
[YYYY-MM-DD HH:MM Asia/Jakarta] gate observed open within Δt = ___ seconds (next signal scan)
```

---

## 4. Lock variant (incident-only)

`/killswitch lock` is the harder stop. Use only during a real incident.
On top of the `pause` behaviour, lock:

- Flips `users.auto_trade_on = false` for every user (force opt-out).
- Cascades a live → paper fallback for every user currently in live mode
  (single SQL UPDATE inside the lock transaction; one Telegram fallback
  message per affected user).

After `lock`, the **only** way to resume is `/killswitch resume`, AND
each user must individually re-opt-in to auto-trade from `/dashboard`.
This is intentional: a lock implies the operator wants user-level
re-confirmation before any further activity.

Do NOT use `lock` for demo or drill. Use `pause` + `resume` only.

---

## 5. Failure modes

| Symptom | Probable cause | Mitigation |
| --- | --- | --- |
| Bot does not reply to `/kill` within 3 seconds | Telegram polling/webhook stalled, or PTB updater stopped | Hit `POST /admin/kill?active=true` with bearer token. Inspect `flyctl logs` for `bot shutdown` or `updater stop` lines. |
| `/admin/kill` returns 503 | `ADMIN_API_TOKEN` unset | Set it via `flyctl secrets set ADMIN_API_TOKEN=...`, then redeploy. Telegram path remains available in the meantime. |
| Subscribers don't receive broadcast | Telegram outbound failures | Per-user delivery is best-effort; failures are logged but do not block the operator path. Inspect logs for `killswitch broadcast send failed`. |
| New trades still execute after `/kill` ack | `domain.risk.gate` cache window | The 30-second cache means residual signals already past the gate may still execute. Wait 30 seconds, confirm via `/admin/status`. |

---

## 6. References

- Implementation: `projects/polymarket/crusaderbot/domain/ops/kill_switch.py`
- Telegram handlers: `projects/polymarket/crusaderbot/bot/handlers/admin.py`
  (`kill_command`, `resume_command`, `killswitch_command`).
- REST endpoint: `projects/polymarket/crusaderbot/api/admin.py` (`/admin/kill`).
- Risk gate integration: `projects/polymarket/crusaderbot/domain/risk/gate.py`
  step 1 (`kill_switch_active` check).
- Live → paper cascade: `projects/polymarket/crusaderbot/domain/execution/fallback.py`
  (`trigger_all_live_users`).
