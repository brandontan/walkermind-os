"""Vendored shared strategy library (algorithmic strategies + risk helpers).

This directory was relocated from the repository root into the crusaderbot
package so it ships inside the Docker build context (build context is the
crusaderbot dir; the old repo-root lib/ was never copied into the image) and so
the strategy modules — which use package-relative imports
(``from ..strategy_base import ...``) — can be loaded as real subpackages
rather than via file-path module loading, which cannot resolve relative imports.

Loaded by services/signal_scan/lib_strategy_runner.py.
"""
