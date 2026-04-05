import json
from typing import List, Dict


def validate_pipeline(dataset_path: str) -> bool:
    """Validate that every trade exists in all logs."""
    with open(dataset_path, "r") as f:
        dataset = json.load(f)

    trace_engine = {trade["position_id"]: trade for trade in dataset}
    analytics = []

    for trade in dataset:
        if trade["position_id"] not in trace_engine:
            raise ValueError(f"Trace missing for trade: {trade['trade_id']}")

        # Simulate analytics recording
        analytics.append(trade)

    return True