from datetime import datetime

def emit_event(trace_id, event_type, component, outcome, payload=None):
    return {
        "trace_id": trace_id,
        "event_type": event_type,
        "component": component,
        "outcome": outcome,
        "timestamp": datetime.utcnow().isoformat(),
        "payload": payload or {},
    }
