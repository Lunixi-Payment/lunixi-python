"""The fraud webhook event types a merchant endpoint can subscribe to.

These are the fraud keys of the platform webhook catalogue, delivered in the
same signed envelope as every other platform webhook and verified with
:class:`~lunixi.webhook.verifier.WebhookVerifier`.

🔴 Fraud has no webhook system of its own: every merchant-facing fraud event
goes through the platform channel. Internal event-bus topic names are NOT
webhook event types and are never delivered to a merchant endpoint, so an
integration must not subscribe to one or expect it to arrive.
"""

from __future__ import annotations

from typing import Tuple

__all__ = ["FraudEvents", "FRAUD_EVENT_TYPES"]


class FraudEvents:
    """Event type constants, in catalogue order."""

    #: An async flow result is ready; correlate it with ``decisionRequestId``.
    #: Advisory — it does NOT change the synchronous decision you already
    #: acted on.
    FLOW_ASYNC_COMPLETED = "fraud.flow.async_completed"

    #: A platform-event node in your own flow fired. ``label`` and ``data``
    #: carry the values you defined in that flow.
    FLOW_ACTION_TRIGGERED = "fraud.flow.action_triggered"

    #: A fraud API quota threshold was reached, or a request was rejected with
    #: 429. Sent once per day and lane, not once per rejected request.
    QUOTA_THRESHOLD_REACHED = "fraud.quota.threshold_reached"

    #: One of your fraud alert rules fired.
    ALERT_TRIGGERED = "fraud.alert.triggered"

    #: An outage affecting fraud evaluation was detected or declared.
    SERVICE_DEGRADED = "fraud.service.degraded"

    #: The outage closed. Carries its duration and how many decisions could
    #: not be checked while it lasted.
    SERVICE_RECOVERED = "fraud.service.recovered"

    #: A scheduled report you configured finished its period and was produced.
    #: It carries NO download link: links are short-lived and are produced from
    #: the console. A report you request manually does not send this event.
    REPORT_READY = "fraud.report.ready"


#: Every fraud webhook event type, in catalogue order.
FRAUD_EVENT_TYPES: Tuple[str, ...] = (
    FraudEvents.FLOW_ASYNC_COMPLETED,
    FraudEvents.FLOW_ACTION_TRIGGERED,
    FraudEvents.QUOTA_THRESHOLD_REACHED,
    FraudEvents.ALERT_TRIGGERED,
    FraudEvents.SERVICE_DEGRADED,
    FraudEvents.SERVICE_RECOVERED,
    FraudEvents.REPORT_READY,
)
