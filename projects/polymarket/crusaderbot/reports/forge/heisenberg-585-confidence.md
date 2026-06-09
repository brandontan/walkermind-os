# WARP•FORGE REPORT — heisenberg-585-confidence

Branch: `WARP/ROOT/heisenberg-585-confidence`
Role: WARP•R00T
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: agent 585 social momentum confidence-boost wire in `_run_heisenberg_signals`
Not in Scope: trading logic, risk gate, execution path, other Heisenberg agents
Suggested Next Step: WARP🔹CMD review + merge. Post-deploy operator check: in `signal_publications.payload` look for rows with `social_momentum=true` AND `confidence > 0.65` (default) — confirms the wire is live.

---

## 1. What was built

Closes the dead-end the `WARP/ROOT/heisenberg-survey` lane flagged: agent 585
(Polymarket Social Pulse) was already enriching the live signal payload with
`payload["social_momentum"] = True` when its two thresholds aligned
(`acceleration > 1.2` AND `author_diversity_pct > 40`), but nothing downstream
read the flag — risk gate ignored it, position sizer ignored it. The agent's
contribution to bot performance was effectively zero beyond logging.

This lane wires the flag into a principled, ceiling-protected confidence boost:

- New module-level constants in `jobs/market_signal_scanner.py`:
  - `SOCIAL_MOMENTUM_CONFIDENCE_BOOST = 0.05`
  - `SOCIAL_MOMENTUM_CONFIDENCE_CEIL = 0.90`
- When the 585 thresholds fire, the existing line
  `payload["social_momentum"] = True` is followed by a `min()`-clamped
  confidence bump:
  ```python
  payload["confidence"] = min(
      float(payload.get("confidence", DEFAULT_CONFIDENCE))
      + SOCIAL_MOMENTUM_CONFIDENCE_BOOST,
      SOCIAL_MOMENTUM_CONFIDENCE_CEIL,
  )
  ```
- The confidence value flows downstream into `signal_scan_job._resolve_size_usdc`
  via the existing `SignalCandidate.confidence` plumbing, so the boost
  translates into a real (capped) position-size effect, not just metadata.

---

## 2. Current system architecture

```text
agent 585 (Social Pulse)
        │
        ├─► acceleration > 1.2 AND author_diversity_pct > 40
        │       │
        │       ├─► payload["social_momentum"] = True       ← was the only effect (dead)
        │       └─► payload["confidence"]                   ← NEW
        │             = min(prev + 0.05, 0.90)              ← min() protected
        │
        └─► thresholds NOT met OR empty response OR exception
                └─► confidence unchanged (default 0.65)
                    no social_momentum flag, no crash

signal_publications.payload (JSONB)
        │
        ▼
signal_scan_job._process_candidate
        │
        ▼
SignalCandidate(confidence=…)
        │
        ▼
signal_evaluator._resolve_size_usdc
        │
        ▼
size_usdc effect (capped by capital_alloc_pct + per-trade max)
```

No new endpoints, no schema change, no migration. Single hot-path edit in the
existing live signal pipeline.

---

## 3. Files created / modified

- `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py`
  (+2 module-level constants; +5 lines inside the `_run_heisenberg_signals`
  social block to apply the ceiling-protected boost)
- `projects/polymarket/crusaderbot/tests/test_market_signal_scanner.py`
  (+5 new hermetic tests for the 585 path; new helper
  `_run_heisenberg_with_social` that drives `_run_heisenberg_signals` end-to-end
  with patched `heisenberg.retrieve` so the boost is asserted on the actual
  published payload, not a synthetic call site)
- `projects/polymarket/crusaderbot/reports/forge/heisenberg-585-confidence.md` (this)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

---

## 4. What is working

- `pytest projects/polymarket/crusaderbot/tests/test_market_signal_scanner.py`
  → **23 passed** (19 prior + 5 new):
  - `test_585_social_momentum_boosts_confidence` — high acceleration +
    diverse authors → `confidence = 0.65 + 0.05 = 0.70` AND
    `social_momentum=True`
  - `test_585_social_below_threshold_does_not_boost` — low acceleration →
    no flag, confidence at default
  - `test_585_empty_social_response_does_not_crash` — agent returns `[]` →
    confidence untouched, signal still published
  - `test_585_confidence_ceiling_caps_boost` — patched DEFAULT_CONFIDENCE=0.88
    + boost path fires → result clamped to 0.90 (not 0.93)
  - `test_585_confidence_constants_pinned` — source-level pin on the two new
    constants (fails closed if anyone re-tunes them without intent)
- Full test suite: **1856 passed, 6 skipped, 0 failed** (no regression).
- `python -m py_compile` clean on `market_signal_scanner.py`.
- No frontend impact.

---

## 5. Known issues

- The 585 thresholds (`acceleration > 1.2`, `author_diversity_pct > 40`) are
  unchanged from the original wire — they remain assumed from the Heisenberg
  task spec; if the real agent response uses different field names, the boost
  path simply never fires (signal still publishes at default confidence). Both
  of those calibrations are existing risk, not introduced here.
- The boost magnitude (`+0.05`) and ceiling (`0.90`) are hardcoded
  module-level constants rather than runtime config knobs. Promoted to
  `config.SOCIAL_MOMENTUM_*` env-driven knobs in a follow-up only if the boost
  proves over-aggressive in production; current values match the survey
  recommendation and the existing `DEFAULT_CONFIDENCE` pattern.

---

## 6. What is next

- WARP🔹CMD review + merge.
- Post-deploy operator visual check (no Telegram alert wiring needed — the
  effect is observable in the DB):
  - In Supabase: `SELECT market_id, payload->>'social_momentum' AS sm,
    payload->>'confidence' AS conf, published_at FROM signal_publications
    WHERE feed_id='00000000-0000-0000-0002-000000000001' AND
    payload ? 'social_momentum' ORDER BY published_at DESC LIMIT 20;`
    — confirms boosted signals are landing with `confidence ≈ 0.70+`.
- Watch 24-48h: if 585 boost noticeably worsens fill rate or worsens P&L on
  signal_following, drop `SOCIAL_MOMENTUM_CONFIDENCE_BOOST` to `0.03` or revert.
- Next lane: `WARP/ROOT/heisenberg-556-realtime-trades` — wire agent 556
  (real-time trades stream) into the copy-trade feed so we get sub-minute
  fresh-entry detection instead of relying solely on the 30-minute leaderboard
  poll.

---

Validation Tier: **STANDARD** — single-file runtime behavior change, narrow
hot-path mutation, ceiling-protected, no risk-gate or capital-path impact.
Claim Level: **NARROW INTEGRATION**
Validation Target: `_run_heisenberg_signals` social-block path + new constants
Not in Scope: agent 568/575/574/584/581/556 wires, risk gate, position sizer,
execution router
Suggested Next Step: WARP🔹CMD review on the diff (single hot-path file +
5 hermetic tests). MAJOR-tier SENTINEL not required.
