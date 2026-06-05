#!/usr/bin/env bash
# Authoritative pass/fail for a WARP-74 staging-proof run, scoped to the
# CURRENT run nonce.
#
# WHY A NONCE: the proof's pass/fail is an explicit `PROOF_RESULT=<PASS|FAIL>`
# sentinel the guest machine echoes. The runner captures it with
# `flyctl logs --app <app>`, which streams EVERY machine in the app over a
# recent window -- so a PRIOR run's `PROOF_RESULT=PASS` (a stopped machine that
# Fly still retains in its log buffer) can leak into THIS run's capture. An
# unscoped `grep PROOF_RESULT=PASS` then reports a FALSE PASS even when this
# run's pytest FAILED (observed: an all-broker run with 2 failures went green
# off the prior case3 PASS line). Tagging the sentinel with a per-run nonce and
# matching `PROOF_RESULT=<PASS|FAIL> <nonce>` makes a stale line impossible to
# pick up: a different run has a different nonce.
#
# Usage:  proof_result.sh <logfile> <nonce>
# Prints: PASS | FAIL | INCONCLUSIVE
# Exits:  0 (PASS) | 1 (FAIL) | 2 (INCONCLUSIVE / no nonce-matched sentinel)
set -u

log="${1:?usage: proof_result.sh <logfile> <nonce>}"
nonce="${2:?usage: proof_result.sh <logfile> <nonce>}"

if [ ! -f "$log" ]; then
  echo "INCONCLUSIVE"
  exit 2
fi

# Fixed-string match (-F): the nonce + sentinel are literal, never a pattern.
if grep -qF "PROOF_RESULT=PASS ${nonce}" "$log"; then
  echo "PASS"
  exit 0
elif grep -qF "PROOF_RESULT=FAIL ${nonce}" "$log"; then
  echo "FAIL"
  exit 1
else
  echo "INCONCLUSIVE"
  exit 2
fi
