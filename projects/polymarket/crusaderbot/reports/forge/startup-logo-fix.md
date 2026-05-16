# WARP•FORGE REPORT — startup-logo-fix

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: startup notification dedup + WebTrader logo placement
Not in Scope: logo PNG binary (pending WARP🔹CMD delivery), npm build verification (env lacks Vite toolchain)
Suggested Next Step: WARP🔹CMD provides crusaderbot-logo.png binary → commits to public/ → deploys

---

## 1. What Was Built

**Fix 1 — Startup notification dedup**

Eliminated duplicate Telegram startup alerts on Fly.io rolling deploys.

Root cause: two separate notification paths fired on every boot:
- Direct `notifications.send(OPERATOR_CHAT_ID, "🟢 CrusaderBot up …")` in `main.py` lifespan — no cooldown
- `monitoring_alerts.schedule_alert(alert_startup(…))` — separate "[CrusaderBot][admin] startup event" message, /tmp-only cooldown (instance-local, ineffective across deploys)

Fix: removed the `alert_startup` schedule_alert call (duplicate). Added a 60-second Redis cache dedup guard to the remaining direct send. Cache key `startup_notif_sent` with TTL=60s is shared across Fly.io instances via Redis, suppressing the second instance's notification when a rolling deploy produces two overlapping instances.

**Fix 2 — WebTrader logo placement**

Added CrusaderBot logo (`/crusaderbot-logo.png`) to two surfaces:

- Dashboard topbar (`DashboardPage.tsx`): 32×32 `<img>` with gold drop-shadow filter, placed left of "CrusaderBot" text
- Auth page (`AuthPage.tsx`): 80×80 `<img>` with gold drop-shadow filter, displayed block-centered above the `<h1>` title

The `public/` directory was created at `webtrader/frontend/public/` (was absent). The PNG binary (`crusaderbot-logo.png`) is NOT yet in the repo — see Known Issues.

---

## 2. Current System Architecture

Startup notification path (after fix):

```
lifespan() boot
  → init_cache()           ← Redis or in-memory fallback
  → ...
  → if OPERATOR_CHAT_ID:
      get_cache("startup_notif_sent")
        → if truthy: suppress (log INFO)
        → else:
            set_cache("startup_notif_sent", "1", ttl=60)
            notifications.send(OPERATOR_CHAT_ID, "🟢 CrusaderBot up …")
  → if missing_env: schedule_alert(alert_missing_env)
  → run_health_checks → schedule_alert(alert_dependency_unreachable) per failure
```

Dedup behavior:
- Rolling deploy window (~15s): new instance checks Redis → key present (set by first instance) → suppressed
- Genuine crash restart after >60s: key expired → sends normally
- No Redis (in-memory fallback): dedup is process-local only; cross-instance dedup requires Redis

WebTrader logo path:
```
/dashboard route (StaticFiles) → index.html → React SPA
  → AuthPage: /crusaderbot-logo.png (80px, gold glow)
  → DashboardPage topbar: /crusaderbot-logo.png (32px, gold glow)
  Vite serves public/ assets at root URL path at build time
```

---

## 3. Files Created / Modified

Modified:
- `projects/polymarket/crusaderbot/main.py`
  - Import: added `get_cache, set_cache` to cache imports
  - Added module-level constants `_STARTUP_DEDUP_KEY`, `_STARTUP_DEDUP_TTL`
  - Added 60s dedup guard around operator startup send
  - Removed `monitoring_alerts.schedule_alert(alert_startup(…))` call
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/DashboardPage.tsx`
  - Added `<img src="/crusaderbot-logo.png" …>` (32×32, gold filter) to topbar
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AuthPage.tsx`
  - Added `<img src="/crusaderbot-logo.png" …>` (80×80, gold filter) above `<h1>`

Created:
- `projects/polymarket/crusaderbot/webtrader/frontend/public/` (directory)
- `projects/polymarket/crusaderbot/reports/forge/startup-logo-fix.md` (this file)

Pending (not in this commit):
- `projects/polymarket/crusaderbot/webtrader/frontend/public/crusaderbot-logo.png` — binary PNG, requires WARP🔹CMD delivery

---

## 4. What Is Working

- `main.py` compiles cleanly (`python -m compileall` — 0 errors)
- TypeScript check passes (`tsc --noEmit` — 0 errors after `npm install`)
- Dedup guard is exception-safe: cache read/write failures log warnings and fall through to send (no silent failures, no boot crash risk)
- Monitoring alerts for missing_env and dependency_unreachable are preserved
- Auth page and dashboard topbar reference correct public path `/crusaderbot-logo.png`
- `public/` directory created — Vite will serve files from it at root path

---

## 5. Known Issues

- **Logo PNG binary absent** — `webtrader/frontend/public/crusaderbot-logo.png` is not yet in the repo. The `<img>` references in DashboardPage and AuthPage will render as broken images until the PNG is committed. WARP🔹CMD must provide the binary file and commit it to the `public/` path.
- **In-memory dedup is process-local** — If REDIS_URL is not set in Fly.io env, the in-memory fallback cannot deduplicate across the two rolling-deploy instances. Production Fly.io app has Redis configured, so this is not a live-deploy concern. Local dev without Redis will send two notifications per restart pair, which is acceptable.
- **Branch name** — Execution environment assigned `claude/fix-startup-logo-update-NtuVK` instead of `WARP/CRUSADERBOT-STARTUP-AND-LOGO-FIX`. WARP🔹CMD to rename or re-target PR on merge.

---

## 6. What Is Next

1. WARP🔹CMD provides `crusaderbot-logo.png` binary → commit to `webtrader/frontend/public/`
2. WARP🔹CMD reviews PR and merges when PNG is in place
3. Deploy: startup spam is suppressed immediately on next rolling deploy
4. Logo renders on /dashboard auth and dashboard topbar after Vite build + deploy
