"""Verify a fraud webhook read from stdin.

    cat captured-webhook.json | \
      LUNIXI_WEBHOOK_SECRET=whsec_... \
      LUNIXI_WEBHOOK_SIGNATURE='v2=...' \
      LUNIXI_WEBHOOK_TIMESTAMP='2026-10-11T08:30:00.000Z' \
      LUNIXI_WEBHOOK_EVENT_ID='...' \
      python samples/06-fraud/verify_webhook.py

Reading the body from stdin as bytes is the point: the signature covers the
exact bytes that arrived, so a framework that parses JSON first must be made to
hand over the raw body.
"""

from __future__ import annotations

import os
import sys

from lunixi import FRAUD_EVENT_TYPES, WebhookVerificationError, WebhookVerifier


def main() -> int:
    secret = os.environ.get("LUNIXI_WEBHOOK_SECRET")
    if not secret:
        sys.exit("Set LUNIXI_WEBHOOK_SECRET first.")

    raw_body = sys.stdin.buffer.read()
    headers = {
        "X-Lunixi-Signature": os.environ.get("LUNIXI_WEBHOOK_SIGNATURE", ""),
        "X-Lunixi-Signature-Timestamp": os.environ.get("LUNIXI_WEBHOOK_TIMESTAMP", ""),
        "X-Lunixi-Event-Id": os.environ.get("LUNIXI_WEBHOOK_EVENT_ID", ""),
        "X-Lunixi-Event-Type": os.environ.get("LUNIXI_WEBHOOK_EVENT_TYPE", ""),
    }

    try:
        event = WebhookVerifier(secret).verify(raw_body, headers)
    except WebhookVerificationError as error:
        # Fail-closed: answer 4xx and do nothing with the payload.
        print(f"REJECTED: {error}")
        return 1

    print(f"VERIFIED   id={event.id}")
    print(f"           type={event.type}")
    print(f"           timestamp={event.timestamp}")
    print(f"           fraud event? {event.type in FRAUD_EVENT_TYPES}")
    print(f"           data keys: {', '.join(sorted(event.data))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
