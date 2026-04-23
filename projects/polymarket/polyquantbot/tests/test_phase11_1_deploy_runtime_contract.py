"""Phase 11.1 deploy/runtime contract checks.

Scope: Dockerfile + fly.toml + module-resolution contract only.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _dockerfile_text() -> str:
    return (_project_root() / "Dockerfile").read_text(encoding="utf-8")


def _fly_toml_text() -> str:
    return (_project_root() / "fly.toml").read_text(encoding="utf-8")


def _extract_json_cmd(dockerfile_text: str) -> list[str]:
    match = re.search(r'^CMD\s+(\[.*\])\s*$', dockerfile_text, flags=re.MULTILINE)
    assert match is not None, "Dockerfile must define JSON-array CMD"
    payload = json.loads(match.group(1))
    assert isinstance(payload, list), "Dockerfile CMD must decode to list"
    assert all(isinstance(item, str) for item in payload), "Dockerfile CMD list items must be strings"
    return payload


def test_phase11_1_copy_layout_preserves_projects_package_root() -> None:
    dockerfile_text = _dockerfile_text()
    assert re.search(
        r"^RUN\s+mkdir\s+-p\s+/app/projects/polymarket/polyquantbot\s*$",
        dockerfile_text,
        flags=re.MULTILINE,
    )
    assert re.search(
        r"^COPY\s+\.\s+/app/projects/polymarket/polyquantbot\s*$",
        dockerfile_text,
        flags=re.MULTILINE,
    )


def test_phase11_1_workdir_and_cmd_match_module_resolution_contract() -> None:
    dockerfile_text = _dockerfile_text()
    assert re.search(r"^WORKDIR\s+/app\s*$", dockerfile_text, flags=re.MULTILINE)
    cmd = _extract_json_cmd(dockerfile_text)
    assert cmd[:2] == ["python3", "-m"]
    assert cmd[2] == "projects.polymarket.polyquantbot.scripts.run_api"


@pytest.mark.parametrize("required_fragment", ["internal_port = 8080", "processes = ['app']"])
def test_phase11_1_fly_http_service_keeps_runtime_contract(required_fragment: str) -> None:
    fly_toml_text = _fly_toml_text()
    assert "[http_service]" in fly_toml_text
    assert required_fragment in fly_toml_text


def test_phase11_1_module_path_is_discoverable() -> None:
    spec = importlib.util.find_spec("projects.polymarket.polyquantbot.scripts.run_api")
    assert spec is not None
