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
- Post-launch documentation and communication polishing for founder/operator/public clarity.
- Monitor integration and observability hardening follow-up (admin/internal path guardrails + runtime visibility completion).

### NEXT
- Controlled paper-beta hardening lane execution focused on observability and monitor/admin visibility closure.

### NOT STARTED
- Live-trading authority rollout.
- Production-capital deployment authority.

---

## Overview

Walker AI Trading Team is a multi-agent development system led by COMMANDER. The team builds and validates trading infrastructure across multiple platforms while preserving strict safety and scope boundaries.

For CrusaderBot, the current public state is **paper beta only** with managed operator posture.

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

- Public-ready for paper beta.
- Live Fly runtime responding (`/`, `/health`, `/ready`).
- Paper-only execution boundary is enforced.
- Public-safe Telegram command baseline: `/start`, `/help`, `/status`, `/paper`, `/about`, `/risk_info`, `/account`, `/link`.
- Runtime/operator `/risk` remains separate from the public-safe informational command set.
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
