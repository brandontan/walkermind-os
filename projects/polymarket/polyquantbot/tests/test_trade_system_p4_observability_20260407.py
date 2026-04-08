from projects.polymarket.polyquantbot.execution.trace_context import generate_trace_id
from projects.polymarket.polyquantbot.execution.event_logger import emit_event

def test_trace_id_exists():
    trace_id = generate_trace_id()
    assert trace_id is not None

def test_event_structure():
    event = emit_event("t1", "execution_attempt", "engine", "executed")
    assert "trace_id" in event
    assert "event_type" in event
    assert "outcome" in event
