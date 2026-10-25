"""Ask whether one card payment is fraudulent, and act on the answer.

The caller runs its own payment flow and applies the decision inside its own
authorization step. Run it with the environment described in
`samples/_common/bootstrap.py`.
"""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "_common"))

from bootstrap import build_client  # noqa: E402

from lunixi import Channel, OperationKind, Stage, Surface  # noqa: E402
from lunixi import INTEGRATION_MODE_STANDALONE, ProductContext  # noqa: E402


def main() -> int:
    client = build_client()
    order_reference = f"order-{uuid.uuid4().hex[:12]}"

    decision = client.fraud().evaluate(
        integration_mode=INTEGRATION_MODE_STANDALONE,
        product_context=ProductContext.DIRECT_API,
        channel=Channel.STANDALONE_API,
        surface=Surface.TRANSACTION,
        stage=Stage.PRE_AUTHORIZATION,
        operation_kind=OperationKind.CARD_SALE,
        transaction_ref=order_reference,
        payment={
            "amount": "149.90",
            "currency": "TRY",
            "installment": 1,
            # Never send a full card number or a CVC to this endpoint. The
            # engine reads the BIN and the last four digits; the rest adds
            # cardholder data to a request that does not need it.
            "binNumber": "454671",
            "lastFourDigits": "0987",
        },
        customer={
            "id": "cus_88",
            "email": "buyer@example.com",
            "ipAddress": "203.0.113.42",
        },
        device={"userAgent": "Mozilla/5.0", "fingerprint": "fp_demo_0001"},
    )

    print(f"transaction : {order_reference}")
    print(f"decision    : {decision.decision}")
    print(f"risk score  : {decision.risk_score}")
    print(f"reasons     : {', '.join(decision.reasons) or '-'}")
    print(f"trace id    : {decision.trace_id}")

    # Four outcomes, four different actions. `allow` is the only one that
    # authorizes: `force_3d` asks for a 3-D Secure retry and `review` asks for
    # a human, so folding either into "not blocked" loses the instruction.
    if decision.blocked:
        print("\n→ Refuse the order.")
    elif decision.requires_three_d:
        print("\n→ Re-run this payment with 3-D Secure.")
    elif decision.requires_review:
        print("\n→ Hold the order and queue it for review.")
    elif decision.allowed:
        print("\n→ Authorize the payment.")
    else:
        # An unrecognised value means the dictionary grew. Treat it as a hold
        # rather than as an allow.
        print("\n→ Unknown outcome; holding the order.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
