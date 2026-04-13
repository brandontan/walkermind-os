from __future__ import annotations

from dataclasses import replace

from projects.polymarket.polyquantbot.platform.execution.exchange_integration import ExchangeExecutionResult
from projects.polymarket.polyquantbot.platform.execution.secure_signing import (
    SIGNING_BLOCK_AUDIT_MISSING,
    SIGNING_BLOCK_INVALID_EXCHANGE_INPUT_CONTRACT,
    SIGNING_BLOCK_INVALID_SIGNING_SCHEME,
    SIGNING_BLOCK_KEY_ACCESS_DENIED,
    SIGNING_BLOCK_KEY_NOT_REGISTERED,
    SIGNING_BLOCK_OPERATOR_APPROVAL_MISSING,
    SIGNING_BLOCK_SIGNING_DISABLED,
    SIGNING_METHOD_REAL,
    SIGNING_METHOD_SIMULATED,
    SecureSigningEngine,
    SigningExecutionInput,
    SigningPolicyInput,
)

VALID_EXCHANGE_RESULT = ExchangeExecutionResult(
    executed=True,
    success=True,
    blocked_reason=None,
    execution_id="EXE-5-4-001",
    request_payload={"execution_id": "EXE-5-4-001", "order": {"side": "BUY", "size": 1}},
    signed_payload={"execution_id": "EXE-5-4-001", "request": {"side": "BUY", "size": 1}},
    exchange_response={"status": "ok"},
    network_used="https://api.exchange.local/orders",
    signing_used=True,
    simulated=False,
    non_executing=False,
)

VALID_SIGNING_INPUT = SigningExecutionInput(
    exchange_result=VALID_EXCHANGE_RESULT,
    upstream_trace_refs={"phase": "5.4"},
)

VALID_POLICY_INPUT = SigningPolicyInput(
    signing_enabled=True,
    allow_real_signing=True,
    signing_scheme="ed25519",
    allowed_schemes=["ed25519", "secp256k1"],
    key_reference="key-ref-001",
    key_registry_enabled=True,
    key_registered=True,
    key_access_granted=True,
    allow_external_signer=True,
    external_signer_used=False,
    simulated_signing_force=False,
    audit_required=True,
    audit_attached=True,
    operator_approval_required=True,
    operator_approval_present=True,
    policy_trace_refs={"policy": "phase5.4"},
)


def test_phase5_4_valid_execution_and_policy_allow_real_signing() -> None:
    engine = SecureSigningEngine(real_signing_enabled=True)

    build = engine.sign_with_trace(signing_input=VALID_SIGNING_INPUT, policy_input=VALID_POLICY_INPUT)

    assert build.result is not None
    assert build.result.signed is True
    assert build.result.success is True
    assert build.result.blocked_reason is None
    assert build.result.signature is not None
    assert build.result.payload_hash is not None
    assert build.result.signing_method == SIGNING_METHOD_REAL
    assert build.result.simulated is False
    assert build.result.non_executing is False


def test_phase5_4_simulated_signing_path() -> None:
    engine = SecureSigningEngine(real_signing_enabled=False)

    build = engine.sign_with_trace(signing_input=VALID_SIGNING_INPUT, policy_input=VALID_POLICY_INPUT)

    assert build.result is not None
    assert build.result.success is True
    assert build.result.signature == "SIMULATED_SIGNATURE"
    assert build.result.signing_method == SIGNING_METHOD_SIMULATED
    assert build.result.simulated is True
    assert build.result.non_executing is True


def test_phase5_4_signing_disabled_is_blocked() -> None:
    engine = SecureSigningEngine(real_signing_enabled=True)

    build = engine.sign_with_trace(
        signing_input=VALID_SIGNING_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, signing_enabled=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == SIGNING_BLOCK_SIGNING_DISABLED


def test_phase5_4_invalid_signing_scheme_is_blocked() -> None:
    engine = SecureSigningEngine(real_signing_enabled=True)

    build = engine.sign_with_trace(
        signing_input=VALID_SIGNING_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, signing_scheme="rsa"),
    )

    assert build.result is not None
    assert build.result.blocked_reason == SIGNING_BLOCK_INVALID_SIGNING_SCHEME


def test_phase5_4_key_not_registered_is_blocked() -> None:
    engine = SecureSigningEngine(real_signing_enabled=True)

    build = engine.sign_with_trace(
        signing_input=VALID_SIGNING_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, key_registered=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == SIGNING_BLOCK_KEY_NOT_REGISTERED


def test_phase5_4_key_access_denied_is_blocked() -> None:
    engine = SecureSigningEngine(real_signing_enabled=True)

    build = engine.sign_with_trace(
        signing_input=VALID_SIGNING_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, key_access_granted=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == SIGNING_BLOCK_KEY_ACCESS_DENIED


def test_phase5_4_audit_missing_is_blocked() -> None:
    engine = SecureSigningEngine(real_signing_enabled=True)

    build = engine.sign_with_trace(
        signing_input=VALID_SIGNING_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, audit_attached=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == SIGNING_BLOCK_AUDIT_MISSING


def test_phase5_4_operator_approval_missing_is_blocked() -> None:
    engine = SecureSigningEngine(real_signing_enabled=True)

    build = engine.sign_with_trace(
        signing_input=VALID_SIGNING_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, operator_approval_present=False),
    )

    assert build.result is not None
    assert build.result.blocked_reason == SIGNING_BLOCK_OPERATOR_APPROVAL_MISSING


def test_phase5_4_deterministic_gating() -> None:
    engine = SecureSigningEngine(real_signing_enabled=False)

    first = engine.sign_with_trace(signing_input=VALID_SIGNING_INPUT, policy_input=VALID_POLICY_INPUT)
    second = engine.sign_with_trace(signing_input=VALID_SIGNING_INPUT, policy_input=VALID_POLICY_INPUT)

    assert first == second


def test_phase5_4_invalid_inputs_do_not_crash() -> None:
    engine = SecureSigningEngine(real_signing_enabled=True)

    invalid_signing_input = engine.sign_with_trace(
        signing_input=None,  # type: ignore[arg-type]
        policy_input=VALID_POLICY_INPUT,
    )
    invalid_policy_input = engine.sign_with_trace(
        signing_input=VALID_SIGNING_INPUT,
        policy_input=None,  # type: ignore[arg-type]
    )

    assert invalid_signing_input.result is not None
    assert invalid_signing_input.result.blocked_reason == SIGNING_BLOCK_INVALID_EXCHANGE_INPUT_CONTRACT
    assert invalid_policy_input.result is not None
    assert invalid_policy_input.result.blocked_reason == SIGNING_BLOCK_INVALID_EXCHANGE_INPUT_CONTRACT


def test_phase5_4_signature_output_present_only_when_allowed() -> None:
    engine = SecureSigningEngine(real_signing_enabled=True)

    allowed = engine.sign_with_trace(signing_input=VALID_SIGNING_INPUT, policy_input=VALID_POLICY_INPUT)
    blocked = engine.sign_with_trace(
        signing_input=VALID_SIGNING_INPUT,
        policy_input=replace(VALID_POLICY_INPUT, key_access_granted=False),
    )

    assert allowed.result is not None
    assert blocked.result is not None
    assert allowed.result.signature is not None
    assert blocked.result.signature is None


def test_phase5_4_no_key_exposure_in_output() -> None:
    engine = SecureSigningEngine(real_signing_enabled=True)

    build = engine.sign_with_trace(signing_input=VALID_SIGNING_INPUT, policy_input=VALID_POLICY_INPUT)

    assert build.result is not None
    assert "private" not in (build.result.signature or "").lower()
    assert "secret" not in (build.result.signature or "").lower()
    assert build.result.key_reference == VALID_POLICY_INPUT.key_reference
