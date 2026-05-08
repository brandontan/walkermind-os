# Rollback Procedure — CrusaderBot

**Owner:** Operator (Bayue Walker)
**Audience:** WARP🔹CMD operator on call.
**Last reviewed:** 2026-05-08 Asia/Jakarta — R12 production-paper deploy.

This runbook covers rolling back a CrusaderBot Fly.io deployment. The
default posture is paper-mode, so the rollback is reversible without
risking real capital, but the kill switch should still be the FIRST tool
reached for during an active incident — rollback is for known-bad code,
not unknown live-state issues.

---

## 1. When to roll back vs. when to kill-switch

| Symptom | First action |
| --- | --- |
| Recent deploy correlates with errors / Sentry spike / `/health` degraded | **Rollback** (this runbook) |
| Strategy logic appears broken but no recent deploy | Kill switch (see `kill-switch-procedure.md`), then triage in DB |
| Telegram bot unresponsive but app otherwise healthy | `flyctl machine restart`, then evaluate |
| Database migration regression | Migration rollback (see §4 below) — never just redeploy |
| Activation guards leaking (any of EXEC/CAPITAL/LIVE flipped without authorisation) | **Kill switch + rollback simultaneously** |

The kill switch is reversible in seconds. A rollback takes ~2 minutes and
restarts the machine. Use kill switch first for unknown causes; rollback
second once a recent deploy is identified as the trigger.

---

## 2. Pre-flight (before any rollback)

```bash
# 1. Confirm the bad release that you want to roll BACK FROM:
flyctl releases list -a crusaderbot | head -10
# Note the most recent release version (e.g. v62) — this is the current.

# 2. Identify the last known-good release. Cross-reference with:
#    a. The forge report covering the previous lane.
#    b. The CHANGELOG.md entry for the lane that merged before the bad one.
#    c. /health output captured before the bad deploy went out.

# 3. Capture current state:
curl -fsS https://crusaderbot.fly.dev/health | jq '.' > /tmp/pre-rollback-health.json
flyctl status -a crusaderbot > /tmp/pre-rollback-status.txt

# 4. Activate kill switch via Telegram /kill if there's any chance the
#    in-flight signals are routing to a buggy code path. This is
#    REQUIRED if the rollback target predates a risk-gate change.
```

---

## 3. Rollback paths

Three supported paths, in increasing blast radius. Use the smallest one
that addresses the issue.

### 3.1 Re-deploy the previous Docker image (preferred)

Fly retains every released Docker image. The fastest rollback is to
re-deploy the image from the previous release.

```bash
# 1. Find the previous release's image:
flyctl releases list -a crusaderbot --image | head -5
# Example output column "IMAGE" contains the registry path:
#   registry.fly.io/crusaderbot:deployment-01HXXXX...

# 2. Roll back by re-deploying that image:
flyctl deploy -a crusaderbot --image <previous-image> --strategy immediate

# 3. Confirm new release was created:
flyctl releases list -a crusaderbot | head -3
# A new vN+1 entry should reference the same image as the prior known-good.

# 4. Health check:
curl -fsS https://crusaderbot.fly.dev/health | jq '.status, .version'
# Expected: "ok", <build identifier>
#   - When the rolled-back release was deployed via the CD workflow,
#     `version` is the 12-char git short SHA (e.g. "abc1234deadbe").
#     CD stamps APP_VERSION at deploy time per crusaderbot-cd.yml.
#   - When the rolled-back release was deployed via manual flyctl
#     (typical for the §3.1 image re-deploy path, which does NOT
#     re-run the CD workflow), `version` falls back to `fly-<ULID>`
#     extracted from Fly's documented FLY_IMAGE_REF machine runtime env
#     (https://fly.io/docs/machines/runtime-environment/). The new
#     release entry created by the rollback gets a fresh deployment
#     ULID, so the value will differ from the bad release even when
#     they share an underlying Docker image. Use the fresh ULID to
#     confirm the rollback machine boot.
```

**Operator log:**

```
[YYYY-MM-DD HH:MM Asia/Jakarta] rolled back from vNN (sha=XXXX) to vMM (sha=YYYY)
[YYYY-MM-DD HH:MM Asia/Jakarta] /health green within Δt = ___ seconds after deploy
```

### 3.2 Rebuild from a previous git commit

If the previous Docker image is no longer available (image GC, secrets
rotation incompatibility, etc.):

```bash
# 1. Check out the known-good commit locally:
git fetch origin main
git checkout <commit-sha>

# 2. Run the standard deploy:
flyctl deploy -a crusaderbot --strategy immediate

# 3. Same health check as above.
```

This path takes longer (~3-5 minutes) because the image rebuilds.

### 3.3 Roll forward with a hotfix

If the bad change is a single file, a forward-fix is sometimes faster
than rollback. Use only when:

- The fix is < 50 lines, touches one module, and is obvious.
- A WARP•FORGE report can be written for the fix within the same incident.
- The kill switch is already engaged so users aren't seeing intermittent
  behaviour.

Otherwise, prefer §3.1 — a rollback is always reversible, a hot-fix may
introduce a second bug.

---

## 4. Database migration rollback

CrusaderBot migrations are forward-only and idempotent (`DO $$`-wrapped
since `migrations/004`). There is **no automated `migrate down`**.

If a migration regression is identified:

1. **Stop the bleed first** — kill switch via Telegram `/kill`.
2. Roll back the application image (§3.1) so the new migration code path
   is no longer executed.
3. Manually reverse the data change in PostgreSQL via a one-off SQL
   patch. Owner: WARP🔹CMD. Document the patch in
   `state/CHANGELOG.md` under `migration-rollback`.
4. Open a follow-up MAJOR lane for a properly-engineered migration fix.

Do NOT attempt to "drop and re-run" a migration in production. The audit
log and trade history depend on append-only continuity.

---

## 5. Dry-run procedure (drill — paper-mode safe)

Run this drill **before** any real incident so the operator has practiced
the exact commands. Recommended cadence: once before each demo, and after
any major change to `fly.toml` or the deploy pipeline.

### 5.1 Drill steps

```bash
# 1. Note the current release:
CURRENT=$(flyctl releases list -a crusaderbot --json | jq -r '.[0].version')
CURRENT_IMAGE=$(flyctl releases list -a crusaderbot --image --json | jq -r '.[0].image_ref')

# 2. Activate kill switch via Telegram /kill so no signals execute during
#    the drill.

# 3. Re-deploy the SAME image (no version bump, but a new release entry).
#    This proves the rollback mechanism works without actually changing
#    application behaviour:
flyctl deploy -a crusaderbot --image "$CURRENT_IMAGE" --strategy immediate

# 4. Confirm a new release was created and points at the same image:
flyctl releases list -a crusaderbot | head -3
# Expected: vN+1 with the same image hash as vN.

# 5. Health check:
curl -fsS https://crusaderbot.fly.dev/health | jq '.status, .version'

# 6. Resume via Telegram /resume.
```

### 5.2 Drill success criteria

- The cold-start Telegram alert fires once during the drill.
- `/health` returns 200 within 30 seconds of the deploy completing.
- `/health` `version` field matches the dry-run target (proves the
  release stamp is wired).
- Kill switch resumes cleanly via `/resume` with no broadcast errors.

**Operator log:**

```
[YYYY-MM-DD HH:MM Asia/Jakarta] dry-run from vNN to vNN (same image) — outcome: pass / fail
[YYYY-MM-DD HH:MM Asia/Jakarta] /health Δt to green = ___ seconds
[YYYY-MM-DD HH:MM Asia/Jakarta] /resume Δt to gate-open = ___ seconds
```

---

## 6. Post-rollback checklist

After any rollback (real or drill):

- [ ] `/health` reports `status=ok` and `mode=paper`.
- [ ] All five activation guards still NOT SET (verified in
      `/admin/live-gate`).
- [ ] Sentry shows no new `error`-level events since the rollback completed.
- [ ] `/admin/status` reports the expected `kill_switch` state (false for
      drill, false after a real incident is resolved).
- [ ] CHANGELOG.md has a new line for the rollback / drill, in the
      format `YYYY-MM-DD HH:MM | <branch> | rolled back from vNN to vMM`.
- [ ] Forge / Sentinel reports for the bad release are linked from the
      CHANGELOG entry.
- [ ] If a real incident: a `state/PROJECT_STATE.md` `[KNOWN ISSUES]`
      entry is added until the root cause is fixed in a forward lane.

---

## 7. References

- Fly.io deploy config: `projects/polymarket/crusaderbot/fly.toml`
- Health endpoint: `projects/polymarket/crusaderbot/api/health.py`
- Kill switch: `projects/polymarket/crusaderbot/domain/ops/kill_switch.py`
  (see `kill-switch-procedure.md`).
- Migrations: `projects/polymarket/crusaderbot/migrations/`
- Audit log writer: `projects/polymarket/crusaderbot/audit.py`
