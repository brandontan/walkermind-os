"""Phase 10 — GO-LIVE Controller. Compatibility shim → redirects to domain modules."""
from ..core.pipeline.go_live_controller import GoLiveController, TradingMode
from ..core.pipeline.run_controller import RunController
from ..core.pipeline.execution_guard import ExecutionGuard
from ..core.pipeline.capital_allocator import CapitalAllocator
from ..core.pipeline.live_mode_controller import LiveModeController
from ..core.pipeline.arb_detector import ArbDetector
from ..core.pipeline.pipeline_runner import Phase10PipelineRunner
from ..core.pipeline.live_paper_runner import LivePaperRunner

__all__ = [
    "GoLiveController", "TradingMode", "RunController",
    "ExecutionGuard", "CapitalAllocator", "LiveModeController",
    "ArbDetector", "Phase10PipelineRunner", "LivePaperRunner",
]
