from __future__ import annotations

from pathlib import Path


def test_dockerfile_uses_truthful_api_entrypoint_and_python_healthcheck() -> None:
    dockerfile = Path("projects/polymarket/polyquantbot/Dockerfile").read_text(encoding="utf-8")

    assert 'CMD ["python3", "-m", "projects.polymarket.polyquantbot.scripts.run_api"]' in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/health" in dockerfile
    assert "urllib.request.urlopen" in dockerfile


def test_fly_toml_matches_runtime_availability_and_readiness_contract() -> None:
    fly_toml = Path("projects/polymarket/polyquantbot/fly.toml").read_text(encoding="utf-8")

    assert "internal_port = 8080" in fly_toml
    assert "auto_stop_machines = 'off'" in fly_toml
    assert "min_machines_running = 1" in fly_toml
    assert "[[http_service.checks]]" in fly_toml
    assert 'path = "/ready"' in fly_toml
    assert "[deploy]" in fly_toml
    assert 'strategy = "rolling"' in fly_toml
