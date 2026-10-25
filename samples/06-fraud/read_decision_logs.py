"""Read back stored decisions, following the cursor."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "_common"))

from bootstrap import build_client  # noqa: E402

from lunixi import Decision  # noqa: E402


def main() -> int:
    client = build_client()
    decisions = client.fraud().decisions

    page = decisions.list(decision=Decision.REVIEW, limit=10)
    print(f"first page : {len(page.items)} row(s), hasMore={page.has_more}")
    # `total_count` is None unless the server actually counted: a filtered
    # count is expensive, so cursor paging leaves it unset.
    print(f"totalCount : {page.total_count}")

    for row in page.items:
        print(f"  {row.get('traceId')}  {row.get('decision')}  {row.get('createdAt')}")

    if page.items:
        trace_id = page.items[0].get("traceId")
        if trace_id:
            detail = decisions.get(trace_id)
            print(f"\nsingle log : {trace_id} → keys: {', '.join(sorted(detail))}")

    # `iterate` follows the cursors for you. Keep a limit on a live account:
    # this walks the whole filtered history.
    print("\nwalking up to 25 rows through the cursor:")
    for index, row in enumerate(decisions.iterate(decision=Decision.REVIEW, limit=10)):
        if index >= 25:
            break
        print(f"  {index + 1:>2}. {row.get('traceId')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
