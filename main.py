"""Root-level entrypoint for Railway deployment.

Delegates to projects.polymarket.polyquantbot.main so that Railway's
Railpack auto-detection can find a single top-level main.py without
requiring nested package discovery.

Usage::

    python main.py
"""
from __future__ import annotations

import asyncio
import os
import sys

# Ensure the repo root is on sys.path so that the `projects` package
# is importable regardless of the working directory.
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Load .env (if present) before importing the pipeline so that env vars
# set in .env are available to all downstream modules.
try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=os.path.join(_ROOT, ".env"), override=False)
except ImportError:
    pass  # python-dotenv not installed — rely on env vars set externally

from projects.polymarket.polyquantbot.main import main  # noqa: E402

if __name__ == "__main__":
    asyncio.run(main())
