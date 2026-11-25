"""Host-authenticated attestations for immutable strategy evidence manifests.

The host must independently validate the source manifest before issuance and
revalidate it by digest during candidate admission. This module signs that
validation result; it does not manufacture evidence or classify tasks itself.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Callable
from uuid import uuid4

from .strategy_store import (
    StrategyAuthorizationError,
    StrategyEvidenceContext,
    StrategyStoreError,
)
from .tools import ApprovalMacProvider

_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
_SCHEMA = re.compile(r"^capri\.strategy-cohort\.v[0-9]+$")
_TOKEN = re.compile(
    r"^capri-strategy-evidence:v1:"
    r"([A-Za-z0-9][A-Za-z0-9_.-]{0,63}):"
    r"([0-9a-f]{64}):([0-9a-f]{32}):([0-9a-f]{64})$"
)


def _text(value: object, label: str, limit: int = 512) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > limit:
        raise StrategyAuthorizationError(f"{label} is invalid")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise StrategyAuthorizationError(f"{label} is invalid")
    return value


def _validate_context(context: StrategyEvidenceContext, *, token: bool) -> None:
    if type(context) is not StrategyEvidenceContext:
        raise StrategyAuthorizationError("a typed strategy evidence context is required")
    _text(context.principal_id, "principal_id", 256)
    if not _IDENTIFIER.fullmatch(_text(context.strategy_class, "strategy_class", 64)):
        raise StrategyAuthorizationError("strategy_class is invalid")
    if not _IDENTIFIER.fullmatch(_text(context.baseline_id, "baseline_id", 64)):
        raise StrategyAuthorizationError("baseline_id is invalid")
    if not _IDENTIFIER.fullmatch(_text(context.candidate_id, "candidate_id", 64)):
        raise StrategyAuthorizationError("candidate_id is invalid")
    if context.baseline_id == context.candidate_id:
        raise StrategyAuthorizationError("baseline and candidate must differ")
    for label, value in (
        ("baseline_version", context.baseline_version),
        ("candidate_version", context.candidate_version),
    ):
        if not _VERSION.fullmatch(_text(value, label, 64)) or value == "unversioned":
            raise StrategyAuthorizationError(f"{label} is invalid")
    if type(context.cohort_sha256) is not str or not _SHA256.fullmatch(context.cohort_sha256):
        raise StrategyAuthorizationError("cohort fingerprint is invalid")
    if type(context.cohort_schema) is not str or not _SCHEMA.fullmatch(context.cohort_schema):
        raise StrategyAuthorizationError("cohort schema is invalid")
    if type(context.matched_pairs) is not int or not 20 <= context.matched_pairs <= 20_000:
        raise StrategyAuthorizationError("matched_pairs is outside the supported range")
    if token:
        _text(context.evidence_manifest_ref, "evidence attestation", 256)
    else:
        _text(context.evidence_manifest_ref, "evidence manifest reference", 512)


def _payload(
    context: StrategyEvidenceContext,
    key_id: str,
    manifest_sha256: str,
    nonce: str,
) -> bytes:
    data = {
        "domain": "capri.strategy-evidence-attestation.v1",
        "key_id": key_id,
        "manifest_sha256": manifest_sha256,
        "nonce": nonce,
        "principal_id": context.principal_id,
        "strategy_class": context.strategy_class,
        "baseline_id": context.baseline_id,
        "baseline_version": context.baseline_version,
        "candidate_id": context.candidate_id,
        "candidate_version": context.candidate_version,
        "cohort_sha256": context.cohort_sha256,
        "cohort_schema": context.cohort_schema,
        "matched_pairs": context.matched_pairs,
    }
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


class HostStrategyEvidenceAuthority:
    """Issue and verify host attestations for independently checked evidence.

    The host authenticator, manifest attestor, verifier, and MAC provider must
    remain outside model-visible tools. The attestor returns the SHA-256 digest
    of a durable immutable manifest only after validating its provenance,
    principal, strategy versions, exact cohort fingerprint, and host-derived
    task-family labels. The verifier must reopen that manifest by digest and
    repeat the same binding checks.
    """

    def __init__(
        self,
        mac_provider: ApprovalMacProvider,
        authenticate_collector: Callable[[Any], str | None],
        attest_manifest: Callable[[StrategyEvidenceContext], str | None],
        verify_manifest: Callable[[StrategyEvidenceContext, str], bool],
    ) -> None:
        if not (
            callable(getattr(mac_provider, "sign", None))
            and callable(getattr(mac_provider, "verify", None))
            and isinstance(getattr(mac_provider, "active_key_id", None), str)
        ):
            raise StrategyStoreError("a trusted evidence MAC provider is required")
        if not all(callable(item) for item in (
            authenticate_collector, attest_manifest, verify_manifest,
        )):
            raise StrategyStoreError("host authentication and manifest callbacks are required")
        self._mac = mac_provider
        self._authenticate = authenticate_collector
        self._attest = attest_manifest
        self._verify_manifest = verify_manifest

    def issue(
        self, credential: Any, context: StrategyEvidenceContext,
    ) -> str:
        """Authenticate the collector, validate a source manifest, and sign its digest."""
        _validate_context(context, token=False)
        try:
            principal_id = self._authenticate(credential)
        except Exception:
            raise StrategyAuthorizationError("evidence collector authentication failed") from None
        if type(principal_id) is not str or principal_id != context.principal_id:
            raise StrategyAuthorizationError("evidence collector principal does not match the manifest")
        try:
            manifest_sha256 = self._attest(context)
        except Exception:
            raise StrategyAuthorizationError("source evidence attestation failed") from None
        if type(manifest_sha256) is not str or not _SHA256.fullmatch(manifest_sha256):
            raise StrategyAuthorizationError("source manifest is not authenticated and immutable")
        try:
            key_id = self._mac.active_key_id
        except Exception:
            raise StrategyAuthorizationError("active evidence MAC key is unavailable") from None
        if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
            raise StrategyAuthorizationError("active evidence MAC key identifier is invalid")
        nonce = uuid4().hex
        try:
            tag = self._mac.sign(key_id, _payload(context, key_id, manifest_sha256, nonce))
        except Exception:
            raise StrategyAuthorizationError("evidence signing provider is unavailable") from None
        if type(tag) is not bytes or len(tag) != 32:
            raise StrategyAuthorizationError("evidence signing provider returned an invalid MAC")
        return (
            f"capri-strategy-evidence:v1:{key_id}:"
            f"{manifest_sha256}:{nonce}:{tag.hex()}"
        )

    def verify(self, context: StrategyEvidenceContext) -> bool:
        """Verify the host MAC and re-open the exact immutable manifest by digest."""
        try:
            _validate_context(context, token=True)
            match = _TOKEN.fullmatch(context.evidence_manifest_ref)
            if match is None:
                return False
            key_id, manifest_sha256, nonce, encoded_tag = match.groups()
            tag = bytes.fromhex(encoded_tag)
            result = self._mac.verify(
                key_id, _payload(context, key_id, manifest_sha256, nonce), tag,
            )
            if result is not True:
                return False
            manifest_context = replace(
                context, evidence_manifest_ref=f"sha256:{manifest_sha256}",
            )
            verified = self._verify_manifest(manifest_context, manifest_sha256)
            return verified is True
        except Exception:
            return False
