"""Observability layer: health checks, operator alerts, structured logging.

Modules:
- health   : per-dependency liveness checks with hard timeouts.
- alerts   : Telegram operator-alert dispatcher with cooldown.
- logging  : JSON-renderer setup + HTTP request middleware.

Trading and execution paths are intentionally out of scope for this layer.
"""
