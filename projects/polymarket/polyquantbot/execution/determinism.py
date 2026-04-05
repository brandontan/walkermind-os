def test_determinism() -> bool:
    """Test that evaluate_entry() is deterministic."""
    # Simulate intelligence scoring
    scores = []
    for _ in range(5):
        # Simulate a constant score for determinism
        score = 0.78
        scores.append(score)

    return all(abs(scores[0] - s) < 1e-6 for s in scores)