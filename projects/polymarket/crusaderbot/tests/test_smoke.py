"""Pytest entry stub for CrusaderBot CI.

Verifies that the test runner discovers tests and that the runtime is on a
supported Python version. Real integration coverage lands in subsequent lanes.
"""
from __future__ import annotations

import sys


def test_pytest_runs() -> None:
    assert True


def test_python_version_is_supported() -> None:
    assert sys.version_info >= (3, 11), "CrusaderBot requires Python 3.11+"
