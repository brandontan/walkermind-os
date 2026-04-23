"""Phase 11.1 deploy/runtime contract checks."""

from __future__ import annotations

import json
import re
from pathlib import Path


def _read_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _extract_cmd(dockerfile_text: str) -> list[str]:
    match = re.search(r'^CMD\s+(\[.*\])\s*$', dockerfile_text, flags=re.MULTILINE)
    assert match is not None, "Dockerfile must contain JSON-array CMD"
    payload = json.loads(match.group(1))
    assert isinstance(payload, list)
    assert all(isinstance(item, str) for item in payload)
    return payload


def test_dockerfile_runtime_contract_matches_module_layout() -> None:
    dockerfile = _read_file("projects/polymarket/polyquantbot/Dockerfile")

    assert re.search(r"^WORKDIR\s+/app\s*$", dockerfile, flags=re.MULTILINE)
    assert re.search(r"^COPY\s+\.\s+/app\s*$", dockerfile, flags=re.MULTILINE)
    assert "HEALTHCHECK" in dockerfile
    assert "/health" in dockerfile
    assert "urllib.request.urlopen" in dockerfile

    cmd = _extract_cmd(dockerfile)
    assert cmd[:2] == ["python3", "-m"]
    assert cmd[2] == "projects.polymarket.polyquantbot.scripts.run_api"


def test_fly_runtime_contract_has_readiness_and_availability_guards() -> None:
    fly_toml = _read_file("projects/polymarket/polyquantbot/fly.toml")

    assert "[http_service]" in fly_toml
    assert "internal_port = 8080" in fly_toml
    assert "auto_stop_machines = 'off'" in fly_toml
    assert "min_machines_running = 1" in fly_toml
    assert "[[http_service.checks]]" in fly_toml
    assert 'path = "/ready"' in fly_toml
    assert "[deploy]" in fly_toml
    assert 'strategy = "rolling"' in fly_toml
