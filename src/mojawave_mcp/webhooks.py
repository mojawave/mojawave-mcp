"""Webhook signature verification for MojaWave events.

MojaWave signs each webhook with an ``X-MojaWave-Signature`` header containing an
HMAC-SHA256 hex digest of the raw request body. Verify against the raw bytes —
parsing to JSON first can alter whitespace and invalidate the check.
"""

from __future__ import annotations

import hashlib
import hmac


def compute_signature(payload: str | bytes, secret: str) -> str:
    """Return the expected HMAC-SHA256 hex signature for ``payload``."""

    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def verify_signature(payload: str | bytes, signature: str | None, secret: str) -> bool:
    """Constant-time check that ``signature`` matches ``payload`` under ``secret``."""

    if not signature:
        return False
    expected = compute_signature(payload, secret)
    return hmac.compare_digest(expected, signature)
