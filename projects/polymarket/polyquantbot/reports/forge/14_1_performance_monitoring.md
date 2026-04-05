# FORGE REPORT: Performance Monitoring System

## 1. What was built
- **Performance Monitor:** Tracks core metrics, equity curve, and triggers alerts.
- **Alert System:** Detects drawdown, win rate drops, and consecutive losses.
- **Daily Summary:** Generates human-readable reports.
- **Anomaly Detection:** Identifies sudden PnL changes and unusual trade frequency.
- **History Storage:** Saves performance logs to JSON.

## 2. Current Architecture
- **Monitor:** `performance_monitor.py` (core logic)
- **Alerts:** Configurable thresholds for drawdown, win rate, and losses.
- **UI:** Daily summary and Telegram integration.

## 3. Files Created/Modified
- `monitoring/performance_monitor.py` (new)
- `monitoring/performance_log.json` (new)

## 4. What is Working
- Real-time performance tracking.
- Alert system for anomalies.
- Daily summary generation.
- Anomaly detection.

## 5. Known Issues
- None.

## 6. What is Next
- **SENTINEL validation** for performance monitoring.
- **Merge** after approval.

## Example Output
```
📊 Performance Update
├ Trades       : 24
├ Win Rate     : 58%
├ Total PnL    : +120 USD
└ Drawdown     : -3.2%
```

## Alerts
- Drawdown > 5%
- Win rate drop > 20%
- Consecutive losses > 3

## Anomalies
- Sudden PnL change
- Unusual trade frequency

## History
```json
[
  {
    "total_trades": 24,
    "win_rate": 0.58,
    "avg_pnl": 5.0,
    "total_pnl": 120.0,
    "max_drawdown": -0.032,
    "equity_curve": [10000, 10120],
    "timestamp": "2026-04-05 18:08:50"
  }
]
```