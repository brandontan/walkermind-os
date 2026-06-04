"""SMART STRIKE Phase-2 scoring orchestrator (WARP-72 Phase 2, WARP•R00T).

Data-derived upgrade to the precedence-only SMART STRIKE router (WARP-71). The
router picks a candle rule by a fixed precedence ladder
(``close_sweep > safe_close > flip_hunter``); this scorer instead RANKS the
candidate rules by a per-cell, factor-weighted score derived from the settled
``factor_vectors`` dataset, then applies the Oracle deny-gate as an ADDITIVE
veto on top of the score.

SCOPE GUARANTEES (locked by the WARP-72 Phase 2 directive):
  * The scorer optimizes SELECTION / win-rate ONLY. It NEVER affects sizing, the
    13-step risk gate, the kill switch, or any protection gate.
  * SHADOW by default (``SCORER_SHADOW_ENABLED=True``): it runs alongside the
    router and logs what it WOULD have picked. The precedence router still
    controls execution while ``SCORER_ACTIVE=False`` (the default). Cutover to
    ``SCORER_ACTIVE=True`` requires an explicit WARP🔹CMD greenlight — this module
    never flips it.
  * Oracle deny is ADDITIVE and cannot be overridden by score: a rule whose
    Oracle edge is below its per-preset threshold (and status == 'computed') is
    DENIED regardless of how high it scores.

The model (per-cell per-rule linear scorer) is produced offline by
``scorer_trainer.py`` and stored in ``config/scorer_weights.json``. This module
only CONSUMES the model; it is fully fail-soft — a missing / malformed / untrained
model degrades to a neutral scorer that reproduces the precedence ladder, so the
shadow path can never raise into the scan loop.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Canonical menu + constants
# ---------------------------------------------------------------------------

# The three candle rules the scorer ranks. Order is the WARP-71 precedence
# ladder, used as the deterministic tie-break and as the neutral-scorer fallback
# so an untrained model exactly reproduces today's router behaviour.
RULE_PRECEDENCE: tuple[str, ...] = ("close_sweep", "safe_close", "flip_hunter")

# The 7 scorable factors (WARP-71 spec). Names match the numeric ``factor_vectors``
# columns / the ``factor_<name>`` candidate-metadata keys.
FACTORS: tuple[str, ...] = (
    "momentum",
    "volatility_sigma",
    "liquidity_usdc",
    "spread",
    "orderbook_depth_usdc",
    "ttl_sec",
    "oracle_edge",
)

# Rules that enter the underdog (cheap) side rather than the favored side. Used to
# derive a rule's hypothetical entry side from the stored ``fav_side`` so win/loss
# is computable for ANY rule on a settled row (the A/B + trainer rely on this).
_UNDERDOG_RULES: frozenset[str] = frozenset({"flip_hunter"})

# Oracle deny-gate thresholds — WARP-66 per-preset minimum edge at 5m (fractions:
# 2.0% / 1.0% / 3.0%). Mirrors ``_CANDLE_PRESET_EDGE[*]["min_edge"]`` in
# signal_scan_job (single source of truth lives there for the live advisory; this
# is the deny-gate's authoritative copy). A rule's Oracle edge below its threshold
# — when the Oracle actually produced a reading (status == 'computed') — is an
# ADDITIVE denial: it cannot be overridden by a high factor score.
ORACLE_DENY_THRESHOLDS: dict[str, float] = {
    "close_sweep": 0.020,
    "safe_close": 0.010,
    "flip_hunter": 0.030,
}

# Oracle status that arms the deny-gate. Any other status (warming_up,
# no_price_to_beat, error, None) means the Oracle did NOT produce a usable edge,
# so the deny-gate stays inert (fail-open: never deny on a non-reading).
ORACLE_STATUS_COMPUTED: str = "computed"

# Outcome labels (mirror domain/signal/factors.py).
OUTCOME_UP: str = "UP"
OUTCOME_DOWN: str = "DOWN"

# Default model location: <project_root>/config/scorer_weights.json. scorer.py
# lives at domain/strategy/scorer.py → parents[2] is the project root.
_DEFAULT_WEIGHTS_PATH: Path = (
    Path(__file__).resolve().parents[2] / "config" / "scorer_weights.json"
)

MODEL_SCHEMA_VERSION: int = 1


# ---------------------------------------------------------------------------
# Side / win helpers (pure, shared by the trainer + A/B harness)
# ---------------------------------------------------------------------------


def normalize_cell_key(asset: Optional[str], timeframe: Optional[str]) -> Optional[str]:
    """Build the canonical ``ASSET/timeframe`` cell key (e.g. ``"BTC/5m"``).

    Asset is upper-cased (the dataset stores it lower-case); timeframe is taken
    verbatim. Returns ``None`` when either part is missing so callers skip a row
    rather than minting a bogus ``NONE/5m`` cell.
    """
    if not asset or not timeframe:
        return None
    a = str(asset).strip().upper()
    tf = str(timeframe).strip()
    if not a or not tf:
        return None
    return f"{a}/{tf}"


def rule_entry_side(rule: str, fav_side: Optional[str]) -> Optional[str]:
    """The side a rule would enter given the market's favored side.

    Favorite rules (close_sweep / safe_close) enter ``fav_side``; underdog rules
    (flip_hunter) enter the opposite. Returns ``None`` when ``fav_side`` is unknown
    or not a binary side, mirroring ``late_entry_v3``'s own entry-side derivation.
    """
    if fav_side not in ("YES", "NO"):
        return None
    if rule in _UNDERDOG_RULES:
        return "NO" if fav_side == "YES" else "YES"
    return fav_side


def winning_side(realized_outcome: Optional[str]) -> Optional[str]:
    """Map a realized candle direction to the winning binary side.

    ``UP`` → YES, ``DOWN`` → NO. ``FLAT`` / unknown → ``None`` (undecidable; the
    trainer and A/B treat these as pushes and skip them rather than guessing).
    """
    if realized_outcome == OUTCOME_UP:
        return "YES"
    if realized_outcome == OUTCOME_DOWN:
        return "NO"
    return None


def rule_won(
    rule: str, fav_side: Optional[str], realized_outcome: Optional[str]
) -> Optional[bool]:
    """Whether ``rule`` would have won on this settled row. ``None`` = undecidable.

    Win = the rule's hypothetical entry side matches the realized winning side.
    Returns ``None`` (skip) when the entry side or the realized winner cannot be
    determined (missing ``fav_side`` / FLAT / unresolved), never a fabricated loss.
    """
    entry = rule_entry_side(rule, fav_side)
    winner = winning_side(realized_outcome)
    if entry is None or winner is None:
        return None
    return entry == winner


# ---------------------------------------------------------------------------
# Scored-rule result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoredRule:
    """One ranked candidate rule: its score, denial state, and the reason."""

    rule: str
    score: float
    denied: bool
    reason: str  # "ok" | "oracle_deny" — why this rule is/ isn't selectable


# ---------------------------------------------------------------------------
# The scorer
# ---------------------------------------------------------------------------


class StrategyScorer:
    """Ranks candle rules by a per-cell factor-weighted linear score + Oracle veto.

    Construct from a model dict (see ``scorer_trainer.build_weights`` for the
    schema) via :meth:`from_file` / :meth:`from_model`, or :meth:`neutral` for a
    no-model fallback. The scorer is stateless after construction and safe to
    share across scan ticks.
    """

    def __init__(self, model: Mapping[str, Any]):
        self._model: dict[str, Any] = dict(model or {})
        cells = self._model.get("cells")
        self._cells: dict[str, Any] = dict(cells) if isinstance(cells, dict) else {}
        self.trained: bool = bool(self._model.get("trained", False))

    # -- construction -------------------------------------------------------

    @classmethod
    def neutral(cls) -> "StrategyScorer":
        """A model-free scorer: every rule scores 0, so selection falls back to the
        precedence ladder. Used when the weights file is absent / malformed."""
        return cls({"trained": False, "cells": {}})

    @classmethod
    def from_model(cls, model: Mapping[str, Any]) -> "StrategyScorer":
        return cls(model)

    @classmethod
    def from_file(cls, path: str | os.PathLike[str] | None = None) -> "StrategyScorer":
        """Load the model from ``path`` (default ``config/scorer_weights.json``).

        Fail-soft: a missing or unparseable file logs at INFO/WARNING and returns
        a :meth:`neutral` scorer — the shadow path must never raise on a bad model.
        """
        p = Path(path) if path is not None else _DEFAULT_WEIGHTS_PATH
        try:
            if not p.exists():
                log.info("scorer_weights_absent", path=str(p))
                return cls.neutral()
            with p.open("r", encoding="utf-8") as fh:
                model = json.load(fh)
            if not isinstance(model, dict):
                log.warning("scorer_weights_malformed", path=str(p), reason="not_object")
                return cls.neutral()
            return cls(model)
        except Exception as exc:  # noqa: BLE001 — fail-soft, never break the scan
            log.warning("scorer_weights_load_failed", path=str(p), error=str(exc))
            return cls.neutral()

    # -- scoring ------------------------------------------------------------

    def _z(self, cell: Mapping[str, Any], factor: str, value: Optional[float]) -> float:
        """Standardize ``value`` against the cell's per-factor (mean, std).

        Returns 0.0 when the value is missing/non-finite or the cell lacks norm
        stats for the factor — an unmeasured factor contributes nothing rather
        than a fabricated push toward any rule.
        """
        if value is None:
            return 0.0
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(v):
            return 0.0
        norm = cell.get("norm") if isinstance(cell, Mapping) else None
        stats = norm.get(factor) if isinstance(norm, Mapping) else None
        if not isinstance(stats, Mapping):
            return 0.0
        try:
            mean = float(stats.get("mean", 0.0))
            std = float(stats.get("std", 0.0))
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(std) or std <= 0.0:
            return 0.0
        z = (v - mean) / std
        return z if math.isfinite(z) else 0.0

    def score_rule(self, cell_key: str, rule: str, factors: Mapping[str, Any]) -> float:
        """Linear score for ``rule`` in ``cell_key`` given a factor surface.

        ``score = base_winrate + Σ_f weight[f] * z_f``. With no cell/rule model the
        score is 0.0 (neutral) so the precedence tie-break decides — i.e. an
        untrained scorer exactly reproduces the router.
        """
        cell = self._cells.get(cell_key)
        if not isinstance(cell, Mapping):
            return 0.0
        rules = cell.get("rules")
        rule_model = rules.get(rule) if isinstance(rules, Mapping) else None
        if not isinstance(rule_model, Mapping):
            return 0.0
        try:
            score = float(rule_model.get("base_winrate", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        weights = rule_model.get("weights")
        if isinstance(weights, Mapping):
            for f in FACTORS:
                try:
                    w = float(weights.get(f, 0.0))
                except (TypeError, ValueError):
                    continue
                if w == 0.0 or not math.isfinite(w):
                    continue
                score += w * self._z(cell, f, factors.get(f))
        return score if math.isfinite(score) else 0.0

    @staticmethod
    def oracle_denied(
        rule: str,
        oracle_edge: Optional[float],
        oracle_edge_status: Optional[str],
    ) -> bool:
        """ADDITIVE Oracle deny-gate (WARP-66). True → rule denied regardless of score.

        Denies only when the Oracle actually produced an edge
        (``status == 'computed'``) AND that edge is below the rule's per-preset
        threshold. Fail-open: a non-computed status, a missing edge, or an unknown
        rule never denies (the live advisory / risk gate remain the backstop).
        """
        if oracle_edge_status != ORACLE_STATUS_COMPUTED:
            return False
        if oracle_edge is None:
            return False
        threshold = ORACLE_DENY_THRESHOLDS.get(rule)
        if threshold is None:
            return False
        try:
            edge = float(oracle_edge)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(edge):
            return False
        return edge < threshold

    def rank(
        self,
        cell_key: Optional[str],
        factors: Mapping[str, Any],
        candidate_rules: Sequence[str],
        *,
        oracle_edge: Optional[float] = None,
        oracle_edge_status: Optional[str] = None,
    ) -> list[ScoredRule]:
        """Rank ``candidate_rules`` for a market: non-denied by score desc, then denied.

        Ties (and the all-neutral untrained case) break by the WARP-71 precedence
        ladder, so an untrained scorer reproduces the router exactly. ``cell_key``
        of ``None`` (asset/timeframe unknown) yields all-neutral scores.
        """
        # De-dup while preserving the caller's order; unknown rules are dropped.
        seen: set[str] = set()
        rules: list[str] = []
        for r in candidate_rules:
            if r in RULE_PRECEDENCE and r not in seen:
                seen.add(r)
                rules.append(r)

        def _precedence(rule: str) -> int:
            try:
                return RULE_PRECEDENCE.index(rule)
            except ValueError:
                return len(RULE_PRECEDENCE)

        scored: list[ScoredRule] = []
        for r in rules:
            denied = self.oracle_denied(r, oracle_edge, oracle_edge_status)
            score = self.score_rule(cell_key, r, factors) if cell_key else 0.0
            scored.append(
                ScoredRule(
                    rule=r,
                    score=score,
                    denied=denied,
                    reason="oracle_deny" if denied else "ok",
                )
            )

        # Sort: not-denied first; within each group highest score first; ties
        # broken by precedence (lower index = higher priority).
        scored.sort(
            key=lambda s: (s.denied, -s.score, _precedence(s.rule))
        )
        return scored

    def select(
        self,
        cell_key: Optional[str],
        factors: Mapping[str, Any],
        candidate_rules: Sequence[str],
        *,
        oracle_edge: Optional[float] = None,
        oracle_edge_status: Optional[str] = None,
    ) -> Optional[str]:
        """The top non-denied rule, or ``None`` when every candidate is denied/empty."""
        ranked = self.rank(
            cell_key,
            factors,
            candidate_rules,
            oracle_edge=oracle_edge,
            oracle_edge_status=oracle_edge_status,
        )
        for s in ranked:
            if not s.denied:
                return s.rule
        return None


# ---------------------------------------------------------------------------
# Metadata adapters (shadow wiring reads candidate.metadata; A/B reads DB rows)
# ---------------------------------------------------------------------------


def factors_from_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the 7-factor surface from ``factor_<name>`` candidate-metadata keys."""
    return {f: metadata.get(f"factor_{f}") for f in FACTORS}


def factors_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the 7-factor surface from a ``factor_vectors`` DB row."""
    return {f: row.get(f) for f in FACTORS}


# ---------------------------------------------------------------------------
# Flag accessors (lazy config import; fail-soft to the directive defaults)
# ---------------------------------------------------------------------------


def shadow_enabled() -> bool:
    """``SCORER_SHADOW_ENABLED`` (default True). Fail-soft to True."""
    try:
        from ...config import get_settings

        return bool(getattr(get_settings(), "SCORER_SHADOW_ENABLED", True))
    except Exception:  # noqa: BLE001 — config read must never break the scan
        return True


def active() -> bool:
    """``SCORER_ACTIVE`` (default False). Fail-soft to False (router controls)."""
    try:
        from ...config import get_settings

        return bool(getattr(get_settings(), "SCORER_ACTIVE", False))
    except Exception:  # noqa: BLE001
        return False


_DEFAULT_SCORER: Optional[StrategyScorer] = None


def get_scorer(*, reload: bool = False) -> StrategyScorer:
    """Process-wide scorer singleton loaded from the default weights file.

    Loaded once and reused across scan ticks (the model is static between
    offline training runs). ``reload=True`` forces a re-read (test convenience /
    post-retrain refresh).
    """
    global _DEFAULT_SCORER
    if _DEFAULT_SCORER is None or reload:
        _DEFAULT_SCORER = StrategyScorer.from_file()
    return _DEFAULT_SCORER


__all__ = [
    "RULE_PRECEDENCE",
    "FACTORS",
    "ORACLE_DENY_THRESHOLDS",
    "ORACLE_STATUS_COMPUTED",
    "MODEL_SCHEMA_VERSION",
    "ScoredRule",
    "StrategyScorer",
    "normalize_cell_key",
    "rule_entry_side",
    "winning_side",
    "rule_won",
    "factors_from_metadata",
    "factors_from_row",
    "shadow_enabled",
    "active",
    "get_scorer",
]
