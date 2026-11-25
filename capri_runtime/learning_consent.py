"""Authenticated host-side consent capture and HMAC evidence verification.

The embedding application must supply real authentication and an explicit,
session-bound confirmation callback. This module is not a UI or identity
provider; it turns that trusted host decision into evidence LearningStore can
verify without persisting the subject's identity.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from capri_core.learning import LearningConsent
from capri_core.validation import contains_surrogate

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_POLICY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_EVIDENCE = re.compile(r"^capri-consent:v1:([0-9a-f]{32}):([0-9a-f]{64})$")


class LearningConsentAuthorityError(ValueError):
    """A consent request could not be authenticated or safely attested."""


class HostLearningConsentAuthority:
    """Create and verify host-authenticated learning-consent evidence.

    Keep this object and its key in trusted server-side code. Never expose its
    issue method or signing key to model output, browser-supplied fields, or
    untrusted plugins. The confirmation callback must only return the literal
    boolean True after validating an explicit affirmative action bound to the
    authenticated session, exact scope and policy version (including the
    application's CSRF/request-integrity controls).

    The signature contains no principal ID or other subject identifier. Replay
    of a captured evidence string against changed consent fields fails; replay
    of the exact consent record is rejected by LearningStore's primary key.
    """

    def __init__(
        self,
        signing_key: bytes,
        authenticate: Callable[[Any], str | None],
        confirm_explicit_consent: Callable[[str, str, str], bool],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise LearningConsentAuthorityError("consent signing key must contain at least 32 bytes")
        if not callable(authenticate) or not callable(confirm_explicit_consent):
            raise LearningConsentAuthorityError("trusted host authentication and confirmation callbacks are required")
        self._key = bytes(signing_key)
        self._authenticate = authenticate
        self._confirm = confirm_explicit_consent
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _payload(consent_id: str, scope: str, policy_version: str,
                 granted_at: str, nonce: str) -> bytes:
        return json.dumps(
            {
                "consent_id": consent_id,
                "granted_at": granted_at,
                "nonce": nonce,
                "policy_version": policy_version,
                "scope": scope,
                "version": 1,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")

    @staticmethod
    def _valid_identity(value: Any) -> bool:
        return (
            isinstance(value, str) and bool(value.strip()) and len(value) <= 256
            and not contains_surrogate(value)
        )

    def issue(
        self,
        credential: Any,
        *,
        consent_id: str,
        scope: str = "curated_training_examples",
        policy_version: str,
    ) -> LearningConsent:
        """Issue evidence only after host authentication and explicit confirmation."""
        if not isinstance(consent_id, str) or not _IDENTIFIER.fullmatch(consent_id):
            raise LearningConsentAuthorityError("consent_id is invalid")
        if scope != "curated_training_examples":
            raise LearningConsentAuthorityError("unsupported learning-consent scope")
        if not isinstance(policy_version, str) or not _POLICY.fullmatch(policy_version):
            raise LearningConsentAuthorityError("policy_version is invalid")
        try:
            principal_id = self._authenticate(credential)
        except Exception:
            raise LearningConsentAuthorityError("consent authentication failed") from None
        if not self._valid_identity(principal_id):
            raise LearningConsentAuthorityError("consent authentication failed")
        try:
            confirmed = self._confirm(principal_id, scope, policy_version)
        except Exception:
            raise LearningConsentAuthorityError("explicit consent confirmation failed") from None
        if confirmed is not True:
            raise LearningConsentAuthorityError("explicit affirmative consent is required")

        try:
            now = self._clock()
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("clock must be timezone-aware")
            granted_at = now.astimezone(timezone.utc).isoformat()
        except Exception:
            raise LearningConsentAuthorityError("consent clock is invalid") from None
        nonce = uuid4().hex
        payload = self._payload(consent_id, scope, policy_version, granted_at, nonce)
        signature = hmac.new(self._key, payload, hashlib.sha256).hexdigest()
        evidence_ref = f"capri-consent:v1:{nonce}:{signature}"
        return LearningConsent(consent_id, scope, policy_version, evidence_ref, granted_at)

    def verify(self, consent: LearningConsent) -> bool:
        """Verify that this authority issued evidence for these exact fields."""
        if type(consent) is not LearningConsent:
            return False
        match = _EVIDENCE.fullmatch(consent.evidence_ref) if isinstance(consent.evidence_ref, str) else None
        if match is None:
            return False
        nonce, supplied = match.groups()
        try:
            payload = self._payload(
                consent.consent_id, consent.scope, consent.policy_version,
                consent.granted_at, nonce,
            )
        except (AttributeError, TypeError, ValueError, UnicodeError):
            return False
        expected = hmac.new(self._key, payload, hashlib.sha256).hexdigest()
        return secrets.compare_digest(expected, supplied)
