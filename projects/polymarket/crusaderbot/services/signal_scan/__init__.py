"""P3d signal scan service — per-user signal_following scan loop."""
from .signal_scan_job import run_once

__all__ = ["run_once"]
