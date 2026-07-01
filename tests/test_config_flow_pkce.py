"""Tests for the PKCE helpers in the BMW CarData config flow.

These guard the security fix that replaced a constant, all-zero code
verifier with a cryptographically random one (RFC 7636).
"""

from __future__ import annotations

import base64
import hashlib
import re

from custom_components.bmw_cardata.config_flow import (
    _pkce_code_challenge,
    _pkce_code_verifier,
)

# RFC 7636 unreserved characters for the code verifier.
_VERIFIER_CHARS = re.compile(r"^[A-Za-z0-9\-._~]+$")


def test_verifier_length_within_rfc_bounds() -> None:
    """Verifier must be 43-128 characters (RFC 7636 section 4.1)."""
    verifier = _pkce_code_verifier()
    assert 43 <= len(verifier) <= 128


def test_verifier_uses_only_unreserved_characters() -> None:
    """Verifier must only contain the RFC 7636 unreserved set."""
    assert _VERIFIER_CHARS.match(_pkce_code_verifier())


def test_verifier_is_random_across_calls() -> None:
    """Regression: each call must produce a different, unpredictable value.

    The previous implementation built the verifier from base64(bytes(96)),
    a constant all-zero buffer, so every login used an identical verifier.
    """
    verifiers = {_pkce_code_verifier() for _ in range(100)}
    assert len(verifiers) == 100


def test_verifier_is_not_the_old_constant() -> None:
    """Explicitly reject the exact constant produced by the old code."""
    old_constant = (
        base64.urlsafe_b64encode(bytes(96))[:64].decode("ascii").rstrip("=")
    )
    assert _pkce_code_verifier() != old_constant


def test_challenge_is_s256_of_verifier() -> None:
    """Challenge must be the unpadded base64url SHA-256 of the verifier."""
    verifier = _pkce_code_verifier()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    challenge = _pkce_code_challenge(verifier)
    assert challenge == expected
    assert "=" not in challenge
    assert len(challenge) == 43  # SHA-256 -> 32 bytes -> 43 base64url chars
