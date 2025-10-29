"""Utilities for validating Slack request signatures."""

from __future__ import annotations

import hmac
import time
from hashlib import sha256


SLACK_SIGNATURE_HEADER = "X-Slack-Signature"
SLACK_TIMESTAMP_HEADER = "X-Slack-Request-Timestamp"
VERSION = "v0"
DEFAULT_TOLERANCE = 60 * 5  # five minutes


def compute_signature(signing_secret: str, timestamp: str, body: str) -> str:
    """Return Slack-compatible signature for the provided payload."""

    basestring = f"{VERSION}:{timestamp}:{body}".encode("utf-8")
    secret = signing_secret.encode("utf-8")
    digest = hmac.new(secret, basestring, sha256).hexdigest()
    return f"{VERSION}={digest}"


def is_valid_slack_request(
    *, signing_secret: str, timestamp: str, body: str, signature: str, tolerance: int = DEFAULT_TOLERANCE
) -> bool:
    """Validate Slack signature and timestamp to guard against replay attacks."""

    if not timestamp or not signature:
        return False

    try:
        request_ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    current_ts = int(time.time())
    if abs(current_ts - request_ts) > tolerance:
        return False

    expected = compute_signature(signing_secret, timestamp, body)
    return hmac.compare_digest(expected, signature)
