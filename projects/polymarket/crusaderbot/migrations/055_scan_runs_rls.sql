-- Migration 055: Enable RLS on scan_runs (completes 43/43 public tables)
-- Applied to Supabase 2026-05-26; this file formalises the migration in repo.
-- scan_runs contains scanner telemetry only — no user-identifiable data.
-- RLS deny-by-default for anon; postgres + service_role bypass as owner.

ALTER TABLE scan_runs ENABLE ROW LEVEL SECURITY;
