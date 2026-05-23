# WARP•SENTINEL — rls-enable-anon-lockout

Validated: 2026-05-23 09:01 WIB
Branch: WARP/rls-enable-anon-lockout
PR: #1296 | SENTINEL task: #1297
Environment: prod (Supabase project ykyagjdeqcgcktnpdhes) — read-only verification
Tier: MAJOR (DB-wide security foundation)
Source report: projects/polymarket/crusaderbot/reports/forge/rls-enable-anon-lockout.md

## TEST PLAN

Phase 0 — Pre-test gate.
Phase 1 — Migration correctness (coverage, idempotency, no destructive ops).
Phase 2 — Security claim: anon/authenticated denied after enable.
Phase 3 — Safety claim: backend access unchanged (owner / BYPASSRLS bypass).
Phase 4 — Failure modes (reversibility, partial apply, FORCE, policy conflicts, SECURITY DEFINER).
Telegram / latency phases: N/A (no runtime/UI/trading-path change).

## PHASE 0 — PRE-TEST

- Forge report present at correct path with all 6 sections + Tier/Claim/Target/Not-in-Scope: PASS.
- PROJECT_STATE.md updated for the lane (Status/KNOWN ISSUES/NEXT PRIORITY): PASS.
- No phase*/ folders; migration in canonical migrations/ dir, sequential (046 after 045): PASS.
- No shims, no re-export files: PASS.
Phase 0 = PASS.

## FINDINGS (evidence: file:line + live catalog)

Phase 1 — Migration correctness
- migrations/046_enable_rls_anon_lockout.sql:33-58 — DO loop over a fixed 42-name array, existence-guarded against pg_tables before each ALTER. PASS.
- Coverage verified live: named=42, matched_existing=42, total public tables=42, typos_missing=none, public_tables_not_in_list=none → every public table covered, none missed. PASS.
- Idempotency: ENABLE ROW LEVEL SECURITY on an enabled table is a no-op; loop is existence-guarded. Live: already_rls_enabled=0 (migration is meaningful). PASS.
- No DROP / no data mutation / no schema change. PASS.

Phase 2 — Security claim (anon lockout)
- 046:...ENABLE (not FORCE), zero policies created. With RLS enabled + no policy, anon/authenticated (rolbypassrls=FALSE) are denied all rows — Postgres-documented behavior. PASS.
- Live exposure confirmed real: an active authenticator/PostgREST connection (rolbypassrls=false) is the anon data plane this migration closes. PASS.

Phase 3 — Safety claim (backend unchanged)
- All 42 tables owned by postgres; postgres + service_role have rolbypassrls=TRUE (live pg_roles). Owner + BYPASSRLS bypass non-FORCE RLS. PASS.
- Connection-role proof: database.py:126 runs migrations/*.sql via DATABASE_URL; the resulting tables are owned by postgres → the app's connection role IS postgres → bypasses RLS. PASS (by ownership inference; live socket not observable now — see Fix Rec #1).
- force_rls_tables=null → no table forces RLS on its owner. PASS.
- security_definer_funcs=0 in public; NOTIFY/trigger functions execute as table owner (postgres) → unaffected by RLS. PASS.
- Frontend (webtrader/frontend/src/lib/api.ts:1, sse.ts:32) uses backend /api/web + SSE only; no Supabase client / anon key (grep: zero createClient / .from / VITE_SUPABASE). No legitimate anon consumer impacted. PASS.

Phase 4 — Failure modes
- Reversible: ALTER TABLE ... DISABLE ROW LEVEL SECURITY. PASS.
- Partial apply: per-table ALTER is atomic; existence guard prevents hard-fail on a missing name. PASS.
- Policy conflict: existing_policies=0 → nothing to collide with. PASS.
- Apply path: database.py auto-runs on next deploy → no manual step, no drift. PASS.

## CRITICAL ISSUES

None found.

## STABILITY SCORE

- Architecture (20%): 20 — owner-bypass model is sound and proven.
- Functional (20%): 20 — covers exactly 42/42 tables, idempotent, no policies.
- Failure modes (20%): 18 — reversible/atomic; −2 for live backend socket not directly observable (bot down).
- Risk rules (20%): 20 — no trading-risk surface touched; improves data-plane security.
- Infra (10%): 10 — validated against live catalog (roles, ownership, policies, FORCE).
- Latency (10%): 10 — owner bypass = zero query overhead for backend.
TOTAL: 98/100.

## GO-LIVE STATUS

APPROVED — Score 98/100, zero critical issues.

Reasoning: the security gain (closing the anon/authenticated full-data-plane exposure on 42 tables) is real and the "backend unchanged" claim is proven by table ownership (postgres) + BYPASSRLS + no FORCE + no policies + frontend-via-backend-only. Safe to merge; auto-applies on next Fly deploy.

## FIX RECOMMENDATIONS (priority ordered)

1. (P1, deploy-time belt-and-suspenders) After the post-merge Fly redeploy, confirm the live bot connection role: `SELECT DISTINCT usename FROM pg_stat_activity WHERE application_name ILIKE '%crusader%' OR usename='postgres'` — expect postgres. If a non-BYPASSRLS role ever appears, RLS would silently return 0 rows (looks like empty data, not an error) → would need scoped policies. Not a blocker today (ownership proves postgres).
2. (P3, optional) Future direct browser→Supabase paths must add scoped policies (e.g. user rows by auth.uid()) before using the anon key — the deny-by-default is intentional.

## TELEGRAM PREVIEW

N/A — no Telegram, UI, or trading-runtime surface in this lane.
