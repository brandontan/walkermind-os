#CrusaderBot — WALKERMIND OS

## UI Standards
- **Branding:** ❧𝗖𝗥𝗨𝗦𝗔𝗗𝗘𝗥 | 𝗔𝗨𝗧𝗢𝗕𝗢𝗧
- **Language:** English-only (US).
- **Terminal HUD:** Use <pre> blocks for monospaced financial data.
- **Dividers:** Use heavy box characters (━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
).
- **Width:** 40+-character headers for full-width mobile bubbles.

## Runtime Pipeline
- **Scanner:** Log candidate counts to process_metadata.
- **Analyzer:** Generate 'reasoning' string for every SignalCandidate.
- **Execution: **Push Realtime Events via SSE.

## Role Model
- **Admin:** ROOT_ADMIN_ID or 'ADMIN' tier in db.
- **User:** Any registered user; no tier gates.