## PROJECT REGISTRY
> **Last Updated: 2025-07-11

### ACTIVE PROJECTS
```table
+-----------------+----------------------------------------+---------+
| Project         | Path                                   | Status  |
+-----------------+----------------------------------------+---------+
| CrusaderBot     | projects/polymarket/polyquantbot        | ACTIVE  |
| TV Indicators   | projects/tradingview/indicators         | DORMANT |
| TV Strategies   | projects/tradingview/strategies         | DORMANT |
| MT5 EA          | projects/mt5/ea                        | DORMANT |
| MT5 Indicators  | projects/mt5/indicators                | DORMANT |
+-----------------+----------------------------------------+---------+
```
### CURRENT FOCUS

CrusaderBot — projects/polymarket/polyquantbot

### STATUS DEFINITIONS
```table
+---------+----------------------------------------------+
| Status  | Meaning                                      |
+---------+----------------------------------------------+
| ACTIVE  | Currently in development with active lanes   |
| DORMANT | Present in repo but not active               |
| PAUSED  | Previously active, intentionally on hold     |
+---------+----------------------------------------------+
```
### RULES

- 1 project active    → NEXUS defaults to it, no tag needed
- Multi-project active → every task must tag the project
- No tag + multi       → NEXUS asks, never assumes
- State per project    → self-contained in {PROJECT_ROOT}/state/
