# Phase 9.1 Dependency-Capable Runner Preparation

Last Updated: 2026-04-20 23:08 (Asia/Jakarta)

## Purpose
Define the exact runner requirements needed to execute the canonical Phase 9.1 runtime-proof command in an environment where dependency installation is possible.

Canonical command (unchanged):

```bash
python -m projects.polymarket.polyquantbot.scripts.run_phase9_1_runtime_proof
```

This preparation guide does **not** rerun runtime proof and does **not** refresh canonical evidence artifacts.

## Required environment baseline
- OS: Linux runner with outbound HTTPS access.
- Python: 3.10+ with `venv` module available.
- Locale:
  - `LANG=C.UTF-8`
  - `LC_ALL=C.UTF-8`
  - `PYTHONIOENCODING=utf-8`
- Working directory: repository root.

## Current Codex runner diagnosis (2026-04-20)
- Proxy/default route (`HTTP_PROXY=http://proxy:8080`) to PyPI fails at CONNECT with `403 Forbidden`.
- Direct/no-proxy route fails with outbound network block (`[Errno 101] Network is unreachable`).
- DNS lookup for `pypi.org` and `files.pythonhosted.org` succeeds, so failure is egress-policy/entitlement, not DNS.

Implication: this runner cannot satisfy dependency-complete preconditions; use a separate capable environment path below.

## Reproducible capable environment path
1. Use an external Linux runner (VM or CI host) with outbound HTTPS allowed to:
   - `pypi.org:443`
   - `files.pythonhosted.org:443`
2. Set locale/env baseline:
   - `LANG=C.UTF-8`
   - `LC_ALL=C.UTF-8`
   - `PYTHONIOENCODING=utf-8`
3. From repo root, verify preflight succeeds:
   - `python -m pip index versions fastapi`
   - `python -m pip index versions pytest`
4. Run canonical command unchanged:
   - `python -m projects.polymarket.polyquantbot.scripts.run_phase9_1_runtime_proof`

## Package index reachability requirements
Runner must satisfy at least one reachable install path:

1. Default/proxy route works end-to-end for:
   - `https://pypi.org/simple`
   - `https://files.pythonhosted.org`
2. Or direct/no-proxy route works end-to-end for the same endpoints.

Preflight checks (recommended before canonical run):

```bash
python -m pip --version
python -m pip index versions fastapi
python -m pip index versions pytest
```

Expected outcome: commands return package metadata (no `403 Forbidden`, no DNS/network-unreachable errors).

## Dependency install success requirements
The canonical runner creates:
- `projects/polymarket/polyquantbot/.venv-phase9-1-runtime-proof`

Install phase must succeed for:
- `-r projects/polymarket/polyquantbot/requirements.txt`
- explicit runtime-proof stack: `pytest`, `pytest-asyncio`, `httpx`, `pydantic`, `fastapi`

Install success criteria:
- zero non-zero exits from pip install step
- no unresolved dependency conflict

## py_compile success requirements
The runner compiles every target listed in:
- `projects/polymarket/polyquantbot/tests/runtime_proof_phase9_1_targets.txt`

Success criteria:
- `python -m py_compile` returns exit code 0 for all listed targets.

## Scoped pytest success requirements
The runner executes each target from:
- `projects/polymarket/polyquantbot/tests/runtime_proof_phase9_1_targets.txt`

Success criteria:
- each `python -m pytest -q <target>` returns exit code 0.

## Reproducible execution sequence
From repo root in capable runner:

```bash
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export PYTHONIOENCODING=utf-8
python -m projects.polymarket.polyquantbot.scripts.run_phase9_1_runtime_proof
```

Expected output artifact location (produced only when canonical command is run):
- `projects/polymarket/polyquantbot/reports/forge/phase9-1_01_runtime-proof-evidence.log`

## Out of scope
- No runtime behavior changes.
- No evidence-log refresh in this prep task.
- No Phase 9.2 implementation.
