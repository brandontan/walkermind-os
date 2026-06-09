# WARP•FORGE Report — supabase-function-search-path

**Branch:** WARP/ROOT/supabase-function-search-path
**Validation Tier:** MINOR
**Claim Level:** FOUNDATION
**Validation Target:** Supabase function_search_path_mutable security warning (9 functions)
**Not in Scope:** RLS policy creation, function logic changes, H3 bot handler migration

---

## 1. What was built

Migration 059 — pins `search_path = public, pg_catalog` on all 9 PostgreSQL functions in the
public schema that had a mutable search_path. This eliminates a privilege-escalation vector
where an attacker with schema-creation rights could shadow built-in functions by injecting
objects into an uncontrolled search_path.

---

## 2. Current system architecture

No architecture change. All 9 functions are trigger/notify functions:
- 7 × `_cb_notify_*` — NOTIFY functions backing the realtime SSE pipeline (orders, fills,
  positions, system_alerts, system_settings, portfolio_snapshots, user_settings)
- 2 × `positions_*` — trigger functions on the positions table
  (reject_applied_tpsl_update, snapshot_applied_tpsl)

All remain zero-argument functions; only their `search_path` configuration parameter changed.

---

## 3. Files created / modified

| File | Change |
|---|---|
| `projects/polymarket/crusaderbot/migrations/059_function_search_path.sql` | Created — 9 ALTER FUNCTION statements |
| `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` | Updated — Last Updated, Status, KNOWN ISSUES (RESOLVED), NEXT PRIORITY |
| `projects/polymarket/crusaderbot/state/CHANGELOG.md` | Appended — lane closure entry |

Migration applied live to Supabase project `ykyagjdeqcgcktnpdhes` via `apply_migration`.

---

## 4. What is working

- All 9 `function_search_path_mutable` WARN items cleared from Supabase security advisor.
- Remaining advisor output: `rls_enabled_no_policy` INFO only (server-side tables — expected,
  no user-facing risk, all access via backend API/SSE).
- NOTIFY pipeline unaffected — triggers fire identically, only configuration parameter added.
- No application code changes required; no redeploy needed.

---

## 5. Known issues

None. This is a configuration-only migration with no logic or schema change.

---

## 6. What is next

H3: Migrate 26 legacy HTML bot handlers to MarkdownV2.
Branch: `WARP/ROOT/bot-html-to-markdownv2`
Tier: STANDARD (per handler batch)
Suggested Next Step: WARP🔹CMD review + merge this PR, then confirm H3 start.
