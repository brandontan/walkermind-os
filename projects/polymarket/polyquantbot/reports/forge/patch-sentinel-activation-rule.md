# Forge Report — patch-sentinel-activation-rule

Branch: claude/patch-sentinel-activation-WDoXb
(COMMANDER task declared: NWAP/patch-sentinel-activation-rule — branch name mismatch due to harness auto-assignment; noted for COMMANDER awareness)
Timestamp: 2026-04-24 18:28 Asia/Jakarta

---

## 1. What Was Changed

Inserted `## SENTINEL ACTIVATION RULE (AUTHORITATIVE)` block into `AGENTS.md` immediately after the **OPERATING MODES > Degen Mode** block, before the `## RULE PRIORITY` section.

The rule codifies when SENTINEL runs in both Normal and Degen modes:
- **Normal mode**: SENTINEL sweeps per priority done (before next priority opens)
- **Degen mode**: SENTINEL deferred per task and per priority; SENTINEL sweep required per phase done (non-negotiable gate)
- **Both modes**: COMMANDER review per task, always

Version bumped from 2.2 → 2.3.
`Last Updated` updated to `2026-04-24 18:28 Asia/Jakarta` (derived, not hardcoded).

---

## 2. Files Modified

```
AGENTS.md
```

Full path (repo-root relative): `AGENTS.md`

---

## 3. Validation Metadata

```
Validation Tier   : MINOR
Claim Level       : FOUNDATION
Validation Target : Rule text insertion at correct location in AGENTS.md; version bump; timestamp update
Not in Scope      : CLAUDE.md, COMMANDER.md, any state files, any project code, any runtime behavior
Suggested Next    : COMMANDER review → merge if clean
```
