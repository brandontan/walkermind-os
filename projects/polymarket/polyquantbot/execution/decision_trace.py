from typing import Dict


def log_decision_trace(trade: Dict) -> str:
    """Log the full decision flow for a trade."""
    return f"""[INTEL]
score: {trade['intelligence_score']}
threshold: {trade['decision_threshold']}

[DECISION]
→ {trade['action']}

[RESULT]
pnl: {trade['pnl']}
"""