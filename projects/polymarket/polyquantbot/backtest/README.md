# Backtest Module

**Status:** Placeholder (Phase 11+)

This module will contain the backtesting engine for polyquantbot strategies.

## Planned Components

- `engine.py` — Core backtest runner
- `data_loader.py` — Historical data ingestion  
- `metrics.py` — Performance metrics (Sharpe, Sortino, MDD)
- `reporter.py` — Report generation

## Usage (Future)

```python
from polyquantbot.backtest import BacktestEngine

engine = BacktestEngine(strategy=MyStrategy(), data=historical_data)
results = await engine.run()
print(results.summary())
```
