"""Shared guard for test modules that import the full runtime stack.

Root cause (WARP-76 H1): several test modules import production code whose
import chain pulls optional runtime dependencies (``bcrypt``, ``asyncpg``,
``fastapi``, ``pydantic``, ``structlog``, ``apscheduler``, ``web3``, …).

CI installs the complete dependency set from ``pyproject.toml``
``[project.dependencies]`` (see ``.github/workflows/crusaderbot-ci.yml``), so
these suites collect and run normally there. Dependency-less sandboxes (the
Codex ``work`` worktree, a bare local checkout) do not have those wheels, so
the bare ``from projects...`` import raised ``ModuleNotFoundError`` at
collection time — surfaced by pytest as a hard collection ERROR rather than a
clean, documented SKIP.

Wrapping the project-level imports in :func:`optional_runtime_imports` degrades
that case to a module-level skip naming the exact missing dependency, while
leaving CI behaviour (full stack present) completely unchanged.

This module is intentionally named with a leading underscore so pytest's
``test_*.py`` collection glob never picks it up. It imports only stdlib +
pytest, both always available.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pytest


@contextmanager
def optional_runtime_imports(suite: str) -> Iterator[None]:
    """Skip the enclosing test module if an optional runtime dep is absent.

    Usage::

        from projects.polymarket.crusaderbot.tests._runtime_deps import (
            optional_runtime_imports,
        )

        with optional_runtime_imports("webtrader auth/bcrypt"):
            from projects.polymarket.crusaderbot.webtrader.backend import auth

    In CI (full runtime stack installed) the body imports succeed and the
    context manager is a no-op. In a dependency-less environment the first
    missing dependency raises ``ModuleNotFoundError``, which is converted into
    ``pytest.skip(..., allow_module_level=True)`` so the module is reported as
    SKIPPED (with the missing dep name) instead of ERRORED.

    A missing *internal* module (one whose name starts with ``projects.``) is
    re-raised rather than skipped: that signals a real typo or refactor break in
    the project itself, which must surface as an error, not be masked.
    """
    try:
        yield
    except ModuleNotFoundError as exc:  # optional runtime dep not installed
        # A missing *internal* module (``projects.*``) is a real typo / refactor
        # break, not an absent optional dependency — surface it as an error so it
        # is never silently masked by a skip.
        if exc.name and exc.name.startswith("projects."):
            raise
        pytest.skip(
            f"{suite} suite skipped — optional runtime dependency "
            f"'{exc.name}' not installed in this environment "
            f"(CI installs the full stack from pyproject.toml)",
            allow_module_level=True,
        )
