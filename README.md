<div align="center">

```
██╗    ██╗ █████╗ ██╗     ██╗  ██╗███████╗██████╗
██║    ██║██╔══██╗██║     ██║ ██╔╝██╔════╝██╔══██╗
██║ █╗ ██║███████║██║     █████╔╝ █████╗  ██████╔╝
██║███╗██║██╔══██║██║     ██╔═██╗ ██╔══██╗██╔══██╗
╚███╔███╔╝██║  ██║███████╗██║  ██╗███████╗██║  ██║
 ╚══╝╚══╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
           AI  T R A D I N G  T E A M
```

**Multi-Agent AI Build System for Trading Infrastructure**

*Polymarket · TradingView · MT4/MT5 · Kalshi*

---

![Status](https://img.shields.io/badge/Status-Paper%20Beta%20Public--Ready-blue?style=for-the-badge)
![Execution](https://img.shields.io/badge/Execution-Paper%20Only-orange?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Private](https://img.shields.io/badge/Repo-Private-red?style=for-the-badge&logo=github)

</div>

---

## Repository Truth Snapshot

### DONE
- CrusaderBot paper beta release path (Phases 9.1, 9.2, 9.3) is completed on `main`.
- Fly runtime is verified responding on `/`, `/health`, and `/ready`.
- Paper-only execution boundary remains explicitly enforced.

### ACTIVE
- Post-launch wording cleanup for public/operator surface clarity under the current staged rollout boundary.
- Telegram first-run onboarding copy refinement for clearer public-safe navigation.

### NEXT
- COMMANDER review for Phase 10 post-launch public-surface cleanup lane closure.

### NOT STARTED
- Live-trading authority rollout.
- Production-capital deployment authority.

---

## Overview

Walker AI Trading Team is a multi-agent development system led by COMMANDER. The team builds and validates trading infrastructure across multiple platforms while preserving strict safety and scope boundaries.

For CrusaderBot, the current public state is **staged and safety-gated** with managed operator posture.

---

## AI Team

| Agent | Role |
|---|---|
| COMMANDER | Task authority, planning, and final decision-maker |
| FORGE-X | Build/implementation execution |
| SENTINEL | Validation/audit role for MAJOR safety-impact lanes |
| BRIEFER | Reporting and communication artifact support |

---

## Current Public Boundary (CrusaderBot)

- Public-ready under the current staged rollout.
- Live Fly runtime responding (`/`, `/health`, `/ready`).
- Execution remains staged and safety-gated.
- Public-safe Telegram command baseline: `/start`, `/help`, `/status`, `/paper`, `/about`, `/risk_info`, `/account`, `/link`.
- Runtime/operator `/risk` remains separate from the public-safe informational command set.
- `/risk_info` is informational/public-safe; `/risk` is runtime/operator-only.
- Not live-trading ready.
- Not production-capital ready.

---

## Repository Structure

```text
walker-ai-team/
├── AGENTS.md
├── PROJECT_STATE.md
├── ROADMAP.md
├── docs/
└── projects/
    ├── polymarket/polyquantbot/
    ├── tradingview/indicators/
    ├── tradingview/strategies/
    └── mt5/
```

---

## Note

This repository includes research, build, and operational artifacts for multiple trading-system lanes. Public-facing claims should always follow `PROJECT_STATE.md`, `ROADMAP.md`, and validated FORGE/SENTINEL reports.

<div align="center">

---

```
WALKER AI TRADING TEAM
Build with discipline. Validate with evidence.
```

*Private Repository — Bayue Walker © 2026*

</div>
