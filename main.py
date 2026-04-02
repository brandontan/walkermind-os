"""Root entrypoint — Railway/Procfile launcher for PolyQuantBot.

Delegates to:
    projects.polymarket.polyquantbot.main.run()

Usage:
    python main.py
"""
from __future__ import annotations

import os
import sys

# Ensure repo root is on the path so all package imports resolve correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env if present (local dev / Railway build phase)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

print("🚀 PolyQuantBot starting (Railway)")

from projects.polymarket.polyquantbot.main import run  # noqa: E402

if __name__ == "__main__":
    run()
