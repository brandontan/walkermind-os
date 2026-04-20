"""Phase 2 platform shell namespace.

This package intentionally lives under
`projects.polymarket.polyquantbot.platform`.

When runtime working directory is set to this project root,
third-party imports like `import platform` can accidentally resolve to this
package instead of Python's stdlib `platform.py`. To prevent startup crashes
(e.g. missing `platform.system()`), unknown top-level attributes are delegated
to the stdlib platform module.
"""
from __future__ import annotations

from importlib import util
from pathlib import Path
import sysconfig
from types import ModuleType
from typing import Any

_STDLIB_PLATFORM: ModuleType | None = None


def _load_stdlib_platform() -> ModuleType:
    """Load stdlib `platform.py` directly from the Python stdlib path."""
    global _STDLIB_PLATFORM
    if _STDLIB_PLATFORM is not None:
        return _STDLIB_PLATFORM

    stdlib_path = Path(sysconfig.get_paths()["stdlib"]) / "platform.py"
    spec = util.spec_from_file_location("_polyquant_stdlib_platform", stdlib_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load stdlib platform module from {stdlib_path}")

    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _STDLIB_PLATFORM = module
    return module


# Commonly used by dependencies during startup validation.
def system() -> str:
    return _load_stdlib_platform().system()


def __getattr__(name: str) -> Any:
    """Delegate unresolved top-level attributes to stdlib `platform` module."""
    try:
        return globals()[name]
    except KeyError:
        return getattr(_load_stdlib_platform(), name)


__all__ = [
    "system",
]
