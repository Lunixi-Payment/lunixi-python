"""Feed transaction events, singly and in a batch.

Events are the history that counting rules read. Both routes are signed per
request; the SDK handles that.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "_common"))

from bootstrap import build_client  # noqa: E402

from lunixi import EVENT_BATCH_LIMIT  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(reference: str) -> dict:
    return {
        # Your own id. A retry with the same value is deduplicated, which is
        # what makes a resend after a timeout safe.
        "eventId": reference,
        "eventType": "card_sale",
        "subjectType": "customer",
        "subjectId": "cus_88",
        "occurredAt": _now(),
        "amount": 14990,
        "currency": "TRY",
    }


def main() -> int:
    client = build_client()
    events = client.fraud().events

    single_reference = f"evt-{uuid.uuid4().hex[:12]}"
    result = events.record(_event(single_reference), idempotency_key=single_reference)
    print(f"single  : eventId={result.event_id} deduplicated={result.deduplicated} "
          f"rowId={result.row_id} matchedFlows={result.matched_flow_count}")

    # Sending the same event again demonstrates the deduplication an
    # at-least-once feed relies on.
    repeat = events.record(_event(single_reference), idempotency_key=single_reference)
    print(f"repeat  : deduplicated={repeat.deduplicated} (safe to resend)")

    batch = [_event(f"evt-{uuid.uuid4().hex[:12]}") for _ in range(5)]
    print(f"\nbatch limit is {EVENT_BATCH_LIMIT} events per call")
    batch_result = events.record_batch(batch, idempotency_key=f"feed-{uuid.uuid4().hex[:8]}")

    print(f"batch   : total={batch_result.total} inserted={batch_result.inserted} "
          f"deduplicated={batch_result.deduplicated} failed={batch_result.failed}")

    # 🔴 A batch answers 200 even when individual events were rejected, so the
    #    status code alone never proves the feed landed. Check the failures.
    failures = batch_result.failures()
    if failures:
        print("\nrejected events — correct the body and resend with the SAME eventId:")
        for failure in failures:
            print(f"  {failure.event_id}: {failure.error}")
    else:
        print("\nevery event in the batch was accepted.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
