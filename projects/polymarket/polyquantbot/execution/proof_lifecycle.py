from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ValidationProof:
    proof_id: str
    condition_id: str
    side: str
    price_snapshot: float
    size: float
    created_at: float
    ttl_seconds: int
    expires_at: float
    context_hash: str
    status: str


@dataclass(frozen=True)
class TTLResolver:
    fast_min_seconds: int = 5
    fast_max_seconds: int = 10
    normal_min_seconds: int = 15
    normal_max_seconds: int = 30
    volatility_anchor: float = 0.10

    def resolve(self, *, market_type: str, volatility_proxy: float | None = None) -> int:
        normalized_market_type = str(market_type).strip().lower()
        if normalized_market_type == "fast":
            min_seconds = self.fast_min_seconds
            max_seconds = self.fast_max_seconds
        else:
            min_seconds = self.normal_min_seconds
            max_seconds = self.normal_max_seconds
        if max_seconds < min_seconds:
            max_seconds = min_seconds
        if volatility_proxy is None:
            return int(max_seconds)
        bounded_proxy = max(0.0, float(volatility_proxy))
        anchor = max(self.volatility_anchor, 1e-6)
        ratio = max(0.0, min(1.0, bounded_proxy / anchor))
        ttl_window = max_seconds - min_seconds
        ttl = int(round(max_seconds - (ttl_window * ratio)))
        return max(min_seconds, min(max_seconds, ttl))


class ValidationProofRegistry:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        parent = os.path.dirname(self._db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS validation_proofs (
                    proof_id TEXT PRIMARY KEY,
                    condition_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price_snapshot REAL NOT NULL,
                    size REAL NOT NULL,
                    created_at REAL NOT NULL,
                    ttl_seconds INTEGER NOT NULL,
                    expires_at REAL NOT NULL,
                    context_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    consumed_at REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_validation_proofs_expires_at ON validation_proofs (expires_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_validation_proofs_status ON validation_proofs (status)"
            )
            conn.commit()
        self._initialized = True

    def store(self, proof: ValidationProof) -> None:
        self.initialize()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO validation_proofs (
                    proof_id,
                    condition_id,
                    side,
                    price_snapshot,
                    size,
                    created_at,
                    ttl_seconds,
                    expires_at,
                    context_hash,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proof.proof_id,
                    proof.condition_id,
                    proof.side,
                    float(proof.price_snapshot),
                    float(proof.size),
                    float(proof.created_at),
                    int(proof.ttl_seconds),
                    float(proof.expires_at),
                    proof.context_hash,
                    proof.status,
                ),
            )
            conn.commit()

    def get(self, proof_id: str) -> ValidationProof | None:
        self.initialize()
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT proof_id, condition_id, side, price_snapshot, size, created_at,
                       ttl_seconds, expires_at, context_hash, status
                FROM validation_proofs
                WHERE proof_id = ?
                """,
                (proof_id,),
            ).fetchone()
        if row is None:
            return None
        return ValidationProof(
            proof_id=str(row[0]),
            condition_id=str(row[1]),
            side=str(row[2]),
            price_snapshot=float(row[3]),
            size=float(row[4]),
            created_at=float(row[5]),
            ttl_seconds=int(row[6]),
            expires_at=float(row[7]),
            context_hash=str(row[8]),
            status=str(row[9]),
        )

    def mark_expired_if_created(self, proof_id: str) -> bool:
        return self._update_status_if_created(proof_id=proof_id, next_status="EXPIRED")

    def consume_if_created(self, proof_id: str) -> bool:
        self.initialize()
        with sqlite3.connect(self._db_path, timeout=5.0, isolation_level="IMMEDIATE") as conn:
            cursor = conn.execute(
                """
                UPDATE validation_proofs
                SET status = 'CONSUMED', consumed_at = ?
                WHERE proof_id = ? AND status = 'CREATED'
                """,
                (time.time(), proof_id),
            )
            conn.commit()
            return cursor.rowcount == 1

    def _update_status_if_created(self, *, proof_id: str, next_status: str) -> bool:
        self.initialize()
        with sqlite3.connect(self._db_path, timeout=5.0, isolation_level="IMMEDIATE") as conn:
            cursor = conn.execute(
                """
                UPDATE validation_proofs
                SET status = ?
                WHERE proof_id = ? AND status = 'CREATED'
                """,
                (next_status, proof_id),
            )
            conn.commit()
            return cursor.rowcount == 1


class ProofVerifier:
    def __init__(self, registry: ValidationProofRegistry) -> None:
        self._registry = registry

    def verify_and_consume(
        self,
        *,
        proof_id: str,
        condition_id: str,
        side: str,
        price_snapshot: float,
        size: float,
        now_ts: float | None = None,
    ) -> tuple[bool, str]:
        proof = self._registry.get(proof_id)
        if proof is None:
            return False, "not_found"
        if proof.status != "CREATED":
            return False, f"status_{proof.status.lower()}"

        current_time = float(now_ts) if now_ts is not None else time.time()
        if current_time > proof.expires_at:
            self._registry.mark_expired_if_created(proof.proof_id)
            return False, "expired"

        normalized_side = str(side).strip().upper()
        if (
            proof.condition_id != condition_id
            or proof.side != normalized_side
            or abs(proof.price_snapshot - float(price_snapshot)) > 1e-9
            or abs(proof.size - float(size)) > 1e-9
        ):
            return False, "context_mismatch"

        expected_context_hash = compute_context_hash(
            condition_id=condition_id,
            side=normalized_side,
            price_snapshot=float(price_snapshot),
            size=float(size),
            created_at=proof.created_at,
        )
        if not hmac.compare_digest(proof.context_hash, expected_context_hash):
            return False, "context_hash_mismatch"

        if not self._registry.consume_if_created(proof.proof_id):
            return False, "already_consumed"
        return True, "verified"


def compute_context_hash(
    *,
    condition_id: str,
    side: str,
    price_snapshot: float,
    size: float,
    created_at: float,
) -> str:
    payload = json.dumps(
        {
            "condition_id": condition_id,
            "side": str(side).strip().upper(),
            "price_snapshot": round(float(price_snapshot), 10),
            "size": round(float(size), 10),
            "created_at": round(float(created_at), 6),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def new_validation_proof(
    *,
    condition_id: str,
    side: str,
    price_snapshot: float,
    size: float,
    ttl_seconds: int,
    created_at: float | None = None,
    proof_id: str | None = None,
) -> ValidationProof:
    issued_at = float(created_at) if created_at is not None else time.time()
    normalized_side = str(side).strip().upper()
    resolved_proof_id = str(proof_id or uuid.uuid4())
    context_hash = compute_context_hash(
        condition_id=condition_id,
        side=normalized_side,
        price_snapshot=float(price_snapshot),
        size=float(size),
        created_at=issued_at,
    )
    return ValidationProof(
        proof_id=resolved_proof_id,
        condition_id=condition_id,
        side=normalized_side,
        price_snapshot=float(price_snapshot),
        size=float(size),
        created_at=issued_at,
        ttl_seconds=int(ttl_seconds),
        expires_at=issued_at + int(ttl_seconds),
        context_hash=context_hash,
        status="CREATED",
    )
