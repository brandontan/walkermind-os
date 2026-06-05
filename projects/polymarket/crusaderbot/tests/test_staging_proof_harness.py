"""Anti-regression tests for the staging-proof pass/fail determination.

The WARP-74 Fly proof decides PASS/FAIL from an explicit `PROOF_RESULT=<PASS|FAIL>`
sentinel echoed by the guest machine and captured via `flyctl logs`. Because
`flyctl logs --app <app>` streams EVERY machine in the app over a recent window,
a PRIOR run's `PROOF_RESULT=PASS` can leak into a later run's capture. The fix
tags the sentinel with a per-run nonce and matches `PROOF_RESULT=<...> <nonce>`.

These tests drive the SAME shell logic the workflow uses (scripts/proof_result.sh)
against synthetic log files, proving a stale prior-run PASS is never picked up.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "proof_result.sh"


def _run(log_path: Path, nonce: str) -> tuple[str, int]:
    proc = subprocess.run(
        ["bash", str(_SCRIPT), str(log_path), nonce],
        capture_output=True, text=True,
    )
    return proc.stdout.strip(), proc.returncode


pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or not _SCRIPT.exists(),
    reason="bash and scripts/proof_result.sh required",
)


def test_stale_prior_pass_is_not_picked_up(tmp_path):
    """A prior run's PASS line + THIS run's FAIL line -> FAIL (no false green)."""
    log = tmp_path / "fly-proof.log"
    log.write_text(
        "app[oldmachine] nrt [info]PROOF_RESULT=PASS 111-1\n"   # stale prior run
        "app[newmachine] nrt [info]1 failed in 9s\n"
        "app[newmachine] nrt [info]PROOF_RESULT=FAIL 222-1\n"   # this run
    )
    out, rc = _run(log, "222-1")
    assert out == "FAIL"
    assert rc == 1


def test_current_pass_is_recognised(tmp_path):
    log = tmp_path / "fly-proof.log"
    log.write_text(
        "app[oldmachine] nrt [info]PROOF_RESULT=FAIL 111-1\n"   # stale prior run
        "app[newmachine] nrt [info]PROOF_RESULT=PASS 222-1\n"   # this run
    )
    out, rc = _run(log, "222-1")
    assert out == "PASS"
    assert rc == 0


def test_only_stale_pass_is_inconclusive_not_pass(tmp_path):
    """Only a prior run's PASS present (this run produced no sentinel) -> NOT a
    pass; must be INCONCLUSIVE so the job fails loudly rather than green."""
    log = tmp_path / "fly-proof.log"
    log.write_text("app[oldmachine] nrt [info]PROOF_RESULT=PASS 111-1\n")
    out, rc = _run(log, "222-1")
    assert out == "INCONCLUSIVE"
    assert rc == 2


def test_missing_log_is_inconclusive(tmp_path):
    out, rc = _run(tmp_path / "does-not-exist.log", "222-1")
    assert out == "INCONCLUSIVE"
    assert rc == 2
