from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = ROOT / "projects/polymarket/polyquantbot"
PREP_VENV_DIR = PROJECT_ROOT / ".venv-phase9-1-preflight"
REQUIRED_PACKAGES = ["pytest", "pytest-asyncio", "httpx", "pydantic", "fastapi"]
REQUIRED_HTTPS_URLS = [
    "https://pypi.org/simple/pip/",
    "https://pypi.org/simple/pytest/",
    "https://files.pythonhosted.org/",
]
REQUIRED_HTTPS_HOSTS = ["pypi.org", "files.pythonhosted.org"]


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


def _run(cmd: Sequence[str], *, env: dict[str, str], timeout_s: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )


def _print_result(ok: bool, message: str) -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {message}")


def _check_tcp(host: str, port: int = 443, timeout_s: float = 5.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True, f"tcp {host}:{port} reachable"
    except OSError as exc:
        return False, f"tcp {host}:{port} unreachable ({exc})"


def _check_https(url: str, timeout_s: float = 8.0) -> tuple[bool, str]:
    req = Request(url, method="HEAD")
    try:
        with urlopen(req, timeout=timeout_s) as response:  # noqa: S310
            status = getattr(response, "status", None)
            return True, f"https {url} reachable (status={status})"
    except URLError as exc:
        return False, f"https {url} unreachable ({exc})"


def _check_install_lane(env: dict[str, str], *, no_proxy: bool) -> tuple[bool, str]:
    check_env = _without_proxy(env) if no_proxy else env
    create = _run([sys.executable, "-m", "venv", str(PREP_VENV_DIR)], env=check_env, timeout_s=120)
    if create.returncode != 0:
        return False, f"venv create failed: {create.stderr.strip() or create.stdout.strip()}"

    venv_python = PREP_VENV_DIR / "bin/python"
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
    install = _run(install_cmd, env=check_env, timeout_s=900)
    if install.returncode != 0:
        stderr_tail = "\n".join(install.stderr.strip().splitlines()[-8:])
        return False, f"dependency install failed (no_proxy={no_proxy}): {stderr_tail}"

    return True, f"dependency install passed (no_proxy={no_proxy})"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare and validate dependency-capable runner prerequisites for Phase 9.1 runtime proof.",
    )
    parser.add_argument(
        "--check-install",
        action="store_true",
        help="Run a full dependency install preflight in an isolated prep venv.",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Remove proxy env vars before running checks/install preflight.",
    )
    args = parser.parse_args()

    env = _without_proxy(_base_env()) if args.no_proxy else _base_env()

    print("Phase 9.1 Dependency-Capable Runner Prep")
    print(f"Python executable: {sys.executable}")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Canonical command: python -m projects.polymarket.polyquantbot.scripts.run_phase9_1_runtime_proof")
    print(f"Proxy mode: {'no-proxy' if args.no_proxy else 'default env'}")

    overall_ok = True

    for host in REQUIRED_HTTPS_HOSTS:
        ok, message = _check_tcp(host)
        _print_result(ok, message)
        overall_ok = overall_ok and ok

    for url in REQUIRED_HTTPS_URLS:
        ok, message = _check_https(url)
        _print_result(ok, message)
        overall_ok = overall_ok and ok

    pip_check = _run([sys.executable, "-m", "pip", "--version"], env=env)
    pip_ok = pip_check.returncode == 0
    _print_result(pip_ok, f"pip available ({pip_check.stdout.strip()})")
    overall_ok = overall_ok and pip_ok

    if args.check_install:
        install_ok, install_message = _check_install_lane(env, no_proxy=args.no_proxy)
        _print_result(install_ok, install_message)
        overall_ok = overall_ok and install_ok

    print("\nRunner requirements summary:")
    print("- outbound HTTPS reachability to pypi.org and files.pythonhosted.org")
    print("- working DNS and TCP/443")
    print("- functional pip install path for requirements + runtime proof packages")
    print("- UTF-8 locale env: LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8")

    if overall_ok:
        print("\nREADY: dependency-capable runner prerequisites satisfied.")
        return 0

    print("\nNOT READY: fix failed prerequisites before Phase 9.1 closure rerun.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
