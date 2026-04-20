from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = ROOT / "projects/polymarket/polyquantbot"
VENV_DIR = PROJECT_ROOT / ".venv-phase9-1-runtime-proof"
TARGETS_FILE = PROJECT_ROOT / "tests/runtime_proof_phase9_1_targets.txt"
EVIDENCE_LOG = PROJECT_ROOT / "reports/forge/phase9-1_01_runtime-proof-evidence.log"

REQUIRED_PACKAGES = ["pytest", "pytest-asyncio", "httpx", "pydantic", "fastapi"]


def _run(cmd: list[str], *, env: dict[str, str], timeout_s: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )


def _run_with_retry(
    cmd: list[str],
    *,
    env: dict[str, str],
    timeout_s: int = 300,
    retries: int = 3,
    base_backoff_s: float = 2.0,
) -> subprocess.CompletedProcess[str]:
    last_result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, retries + 1):
        result = _run(cmd, env=env, timeout_s=timeout_s)
        last_result = result
        if result.returncode == 0:
            return result
        if attempt < retries:
            time.sleep(base_backoff_s * (2 ** (attempt - 1)))
    assert last_result is not None
    return last_result


def _write_line(handle, line: str = "") -> None:
    handle.write(f"{line}\n")


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _without_proxy(env: dict[str, str]) -> dict[str, str]:
    no_proxy_env = env.copy()
    for key in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "all_proxy",
        "no_proxy",
        "NO_PROXY",
    ):
        no_proxy_env.pop(key, None)
    return no_proxy_env


def main() -> int:
    env = _base_env()

    targets = [
        line.strip()
        for line in TARGETS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    EVIDENCE_LOG.parent.mkdir(parents=True, exist_ok=True)

    with EVIDENCE_LOG.open("w", encoding="utf-8") as log:
        _write_line(log, "Phase 9.1 Dependency-Complete Runtime Proof")
        _write_line(log, f"Python executable: {sys.executable}")
        _write_line(log, f"Repo root: {ROOT}")
        _write_line(log, f"Project root: {PROJECT_ROOT}")
        _write_line(log, f"Targets file: {TARGETS_FILE}")
        _write_line(log)

        _write_line(log, f"[1/5] create venv: {VENV_DIR}")
        create_venv = _run([sys.executable, "-m", "venv", str(VENV_DIR)], env=env)
        _write_line(log, create_venv.stdout.rstrip())
        _write_line(log, create_venv.stderr.rstrip())
        if create_venv.returncode != 0:
            _write_line(log, f"FAIL: venv creation exit={create_venv.returncode}")
            return create_venv.returncode

        venv_python = VENV_DIR / "bin/python"
        _write_line(log, f"venv python: {venv_python}")

        _write_line(log, "[2/5] install dependency-complete runtime/test stack")
        _write_line(log, "package entrypoint: python -m projects.polymarket.polyquantbot.scripts.run_phase9_1_runtime_proof")

        install_cmd = [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "-r",
            "projects/polymarket/polyquantbot/requirements.txt",
            *REQUIRED_PACKAGES,
        ]

        _write_line(log, "install attempt A (proxy/default env)")
        install_result = _run_with_retry(install_cmd, env=env, timeout_s=900)
        _write_line(log, install_result.stdout.rstrip())
        _write_line(log, install_result.stderr.rstrip())

        if install_result.returncode != 0:
            no_proxy_env = _without_proxy(env)
            _write_line(log, "install attempt B (direct/no-proxy env)")
            install_result_no_proxy = _run_with_retry(install_cmd, env=no_proxy_env, timeout_s=900)
            _write_line(log, install_result_no_proxy.stdout.rstrip())
            _write_line(log, install_result_no_proxy.stderr.rstrip())
            if install_result_no_proxy.returncode != 0:
                _write_line(log, f"FAIL: dependency install exit={install_result_no_proxy.returncode}")
                return install_result_no_proxy.returncode
            install_result = install_result_no_proxy

        _write_line(log, "PASS: dependency install")
        _write_line(log, "[3/5] runtime-surface py_compile")
        py_compile_cmd = [str(venv_python), "-m", "py_compile", *targets]
        py_compile_result = _run(py_compile_cmd, env=env)
        _write_line(log, py_compile_result.stdout.rstrip())
        _write_line(log, py_compile_result.stderr.rstrip())
        if py_compile_result.returncode != 0:
            _write_line(log, f"FAIL: py_compile exit={py_compile_result.returncode}")
            return py_compile_result.returncode
        _write_line(log, "PASS: py_compile")

        _write_line(log, "[4/5] execute runtime-surface pytest targets")
        for target in targets:
            pytest_cmd = [str(venv_python), "-m", "pytest", "-q", target]
            _write_line(log, f"command: {' '.join(pytest_cmd)}")
            pytest_result = _run(pytest_cmd, env=env, timeout_s=600)
            _write_line(log, pytest_result.stdout.rstrip())
            _write_line(log, pytest_result.stderr.rstrip())
            if pytest_result.returncode != 0:
                _write_line(log, f"FAIL: pytest target {target} exit={pytest_result.returncode}")
                return pytest_result.returncode

        _write_line(log, "PASS: all runtime-surface pytest targets")
        _write_line(log)
        _write_line(log, "[5/5] runtime proof completed")

    print(f"Evidence written: {EVIDENCE_LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
