"""The decision endpoint, the decision logs and the request field contract."""

from __future__ import annotations

import pytest

from lunixi.errors import ConfigurationError, ValidationError
from lunixi.fraud.evaluate_request import ALLOWED_FIELDS, FIELD_MAP, to_evaluate_body
from lunixi.fraud.taxonomy import (
    INTEGRATION_MODE_STANDALONE,
    AuthMode,
    Channel,
    Decision,
    OperationKind,
    ProductContext,
    Stage,
    Surface,
)

from .support.recording_transport import envelope, error_envelope, json_response


class TestEvaluateRequestMapping:
    def test_python_names_are_mapped_to_the_wire_names(self):
        body = to_evaluate_body(
            {
                "integration_mode": INTEGRATION_MODE_STANDALONE,
                "transaction_ref": "order-1",
                "operation_kind": OperationKind.CARD_SALE,
                "auth_mode_requested": AuthMode.THREE_D,
                "sub_merchant_ref": "sub_88",
            }
        )
        assert body == {
            "integrationMode": "standalone",
            "transactionRef": "order-1",
            "operationKind": "card_sale",
            "authModeRequested": "3d",
            "subMerchantRef": "sub_88",
        }

    def test_the_camel_case_spelling_from_the_api_reference_is_accepted(self):
        assert to_evaluate_body({"transactionRef": "order-1"}) == {"transactionRef": "order-1"}

    def test_none_values_are_dropped_rather_than_sent_as_null(self):
        assert to_evaluate_body({"transaction_ref": "o1", "payment_id": None}) == {
            "transactionRef": "o1"
        }

    def test_an_unknown_field_fails_locally_and_names_the_key(self):
        """The gateway answers 400 without saying which key was wrong."""
        with pytest.raises(ConfigurationError) as caught:
            to_evaluate_body({"transaction_ref": "o1", "amuont": 100})
        assert "amuont" in str(caught.value)

    def test_tenant_id_is_not_an_accepted_field(self):
        """🔴 The tenant is stamped from the access token.

        The gateway accepts the key for backwards compatibility but IGNORES
        its value. Publishing it here would imply a caller can choose their own
        tenant — they cannot, and an integration built on that belief would
        silently send a value that does nothing.
        """
        assert "tenant_id" not in FIELD_MAP
        assert "tenantId" not in FIELD_MAP.values()
        with pytest.raises(ConfigurationError, match="tenant_id"):
            to_evaluate_body({"tenant_id": "tenant_other"})

    def test_engine_internal_rule_groups_are_not_an_accepted_field(self):
        with pytest.raises(ConfigurationError, match="ruleGroups"):
            to_evaluate_body({"ruleGroups": []})

    def test_a_non_mapping_request_is_refused(self):
        with pytest.raises(ConfigurationError, match="must be a mapping"):
            to_evaluate_body(["channel"])  # type: ignore[arg-type]

    def test_the_wire_field_order_follows_the_field_map(self):
        body = to_evaluate_body({"payment": {}, "channel": Channel.STANDALONE_API})
        assert list(body) == ["channel", "payment"]

    def test_every_allowed_field_is_a_python_name(self):
        assert set(ALLOWED_FIELDS) == set(FIELD_MAP)
        for name in ALLOWED_FIELDS:
            assert name.lower() == name


class TestClosedDictionaries:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("channel", Channel.MERCHANT_FORM),
            ("channel", Channel.STANDALONE_API),
            ("surface", Surface.FORM_GATE),
            ("stage", Stage.PRE_AUTHORIZATION),
            ("operation_kind", OperationKind.W2W_TRANSFER),
            ("auth_mode_applied", AuthMode.TWO_D),
            ("product_context", ProductContext.DIRECT_API),
            ("integration_mode", INTEGRATION_MODE_STANDALONE),
        ],
    )
    def test_a_declarable_value_passes(self, field, value):
        assert to_evaluate_body({field: value})[FIELD_MAP[field]] == value

    @pytest.mark.parametrize(
        "field,value",
        [
            # The platform's own channels are not declarable from outside:
            # declaring one would trigger flows bound to a platform channel.
            ("channel", "lunixi_checkout"),
            ("channel", "wallet"),
            ("channel", "direct_api"),
            # The internal integration mode belongs to the platform's senders.
            ("integration_mode", "gateway_integrated"),
            # Unbilled-lane contexts are rejected from outside.
            ("product_context", "simulation"),
            ("product_context", "post_hoc_backfill"),
            ("product_context", "manual_review"),
            ("surface", "checkout"),
            ("stage", "authorisation"),
            ("auth_mode_requested", "3ds"),
        ],
    )
    def test_a_non_declarable_value_fails_locally(self, field, value):
        with pytest.raises(ConfigurationError, match=field):
            to_evaluate_body({field: value})


class TestBoundedStrings:
    @pytest.mark.parametrize("field", ["transaction_ref", "subject_id"])
    def test_the_180_character_boundary_is_exact(self, field):
        assert to_evaluate_body({field: "a" * 180})
        with pytest.raises(ConfigurationError, match="at most 180"):
            to_evaluate_body({field: "a" * 181})

    @pytest.mark.parametrize("field", ["transaction_ref", "subject_id"])
    def test_an_empty_or_blank_value_is_refused(self, field):
        for value in ("", "   "):
            with pytest.raises(ConfigurationError, match="non-empty"):
                to_evaluate_body({field: value})

    @pytest.mark.parametrize("character", ["\n", "\t", "\x00", "\x7f"])
    def test_control_characters_are_refused(self, character):
        with pytest.raises(ConfigurationError, match="control characters"):
            to_evaluate_body({"transaction_ref": f"order{character}1"})

    @pytest.mark.parametrize("value", ["sub_88", "sub.88", "a:b", "x@y", "A-1", "a" * 180])
    def test_a_valid_sub_merchant_ref_passes(self, value):
        assert to_evaluate_body({"sub_merchant_ref": value})["subMerchantRef"] == value

    @pytest.mark.parametrize("value", ["sub 88", "sub/88", "sub#88", "", "a" * 181, "sub\n88"])
    def test_an_invalid_sub_merchant_ref_is_refused(self, value):
        with pytest.raises(ConfigurationError, match="sub_merchant_ref"):
            to_evaluate_body({"sub_merchant_ref": value})


class TestEvaluateCall:
    def test_the_route_is_the_documented_decision_path(self, client_factory):
        transport, client = client_factory(json_response(envelope({"decision": "allow"})))
        client.fraud().evaluate(channel=Channel.STANDALONE_API)

        assert transport.last.method == "POST"
        assert transport.last.path == "/api/v1/fraud/decisions/evaluate"

    def test_the_api_v1_prefix_is_part_of_the_path(self, client_factory):
        """⚠️ Without the prefix the whole surface returns 404."""
        transport, client = client_factory(json_response(envelope({"decision": "allow"})))
        client.fraud().evaluate(channel=Channel.STANDALONE_API)
        assert transport.last.path.startswith("/api/v1/")

    def test_the_decision_route_is_bearer_only_and_not_signed(self, client_factory):
        transport, client = client_factory(json_response(envelope({"decision": "allow"})))
        client.fraud().evaluate(channel=Channel.STANDALONE_API)
        assert transport.last.header("Authorization")
        assert transport.last.header("X-Signature") is None

    def test_a_mapping_and_keyword_arguments_both_work(self, client_factory):
        transport, client = client_factory(
            json_response(envelope({"decision": "allow"})),
            json_response(envelope({"decision": "allow"})),
        )
        client.fraud().evaluate({"transaction_ref": "o1"})
        first = transport.last.body
        client.fraud().evaluate(transaction_ref="o1")
        assert transport.last.body == first

    def test_a_field_given_twice_is_refused_rather_than_silently_picking_one(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError, match="transaction_ref"):
            client.fraud().evaluate({"transaction_ref": "a"}, transaction_ref="b")

    def test_a_channel_spoof_surfaces_as_a_validation_error(self, client_factory):
        """A value the SDK does not police still arrives as a typed 400."""
        transport, client = client_factory(
            json_response(
                error_envelope("FRAUD_CHANNEL_NOT_DECLARABLE", "channel is not declarable"),
                status_code=400,
            )
        )
        with pytest.raises(ValidationError) as caught:
            client.api().request(
                "POST", "/api/v1/fraud/decisions/evaluate", {"channel": "lunixi_checkout"}
            )
        assert caught.value.code == "FRAUD_CHANNEL_NOT_DECLARABLE"


class TestDecisionResult:
    def _decision(self, client_factory, payload):
        transport, client = client_factory(json_response(envelope(payload)))
        return client.fraud().evaluate(channel=Channel.STANDALONE_API)

    def test_the_payload_is_unwrapped_from_the_envelope(self, client_factory):
        result = self._decision(
            client_factory,
            {
                "decision": "review",
                "riskScore": 72.5,
                "reasons": ["velocity", "new_device"],
                "traceId": "trace_1",
                "decisionRequestId": "dreq_1",
            },
        )
        assert result.decision == "review"
        assert result.risk_score == 72.5
        assert result.reasons == ["velocity", "new_device"]
        assert result.trace_id == "trace_1"
        assert result.decision_request_id == "dreq_1"

    @pytest.mark.parametrize(
        "decision,allowed,blocked,three_d,review",
        [
            (Decision.ALLOW, True, False, False, False),
            (Decision.BLOCK, False, True, False, False),
            (Decision.FORCE_3D, False, False, True, False),
            (Decision.REVIEW, False, False, False, True),
        ],
    )
    def test_each_outcome_maps_to_exactly_one_predicate(
        self, client_factory, decision, allowed, blocked, three_d, review
    ):
        """🔴 `allowed` is NOT the inverse of `blocked`.

        `review` and `force_3d` are neither. Collapsing the four outcomes into
        one boolean is how a force-3D decision ends up approved without the
        3-D Secure step it asked for.
        """
        result = self._decision(client_factory, {"decision": decision})
        assert result.allowed is allowed
        assert result.blocked is blocked
        assert result.requires_three_d is three_d
        assert result.requires_review is review

    def test_a_missing_decision_field_is_neither_allowed_nor_blocked(self, client_factory):
        result = self._decision(client_factory, {})
        assert result.decision is None
        assert result.allowed is False
        assert result.blocked is False

    def test_the_raw_payload_stays_reachable(self, client_factory):
        result = self._decision(client_factory, {"decision": "allow", "extra": {"a": 1}})
        assert result.raw["extra"] == {"a": 1}


class TestDecisionLogs:
    def test_the_list_route_and_filters_are_the_documented_ones(self, client_factory):
        transport, client = client_factory(json_response(envelope([])))
        client.fraud().decisions.list(
            payment_id="pay_1",
            decision=Decision.REVIEW,
            integration_mode="standalone",
            product_context="direct_api",
            limit=50,
            cursor="cur_1",
        )

        path = transport.last.path
        assert path.startswith("/api/v1/fraud/decision-logs?")
        for fragment in (
            "paymentId=pay_1",
            "decision=review",
            "integrationMode=standalone",
            "productContext=direct_api",
            "limit=50",
            "cursor=cur_1",
        ):
            assert fragment in path

    def test_an_unknown_filter_fails_locally(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError, match="merchantId"):
            client.fraud().decisions.list(merchantId="other_merchant")

    def test_the_page_reads_the_sibling_page_info(self, client_factory):
        transport, client = client_factory(
            json_response(
                envelope(
                    [{"traceId": "t1"}],
                    pageInfo={"hasMore": True, "nextCursor": "cur_2", "totalCount": None},
                )
            )
        )
        page = client.fraud().decisions.list(limit=1)
        assert page.items == [{"traceId": "t1"}]
        assert page.has_more is True
        assert page.next_cursor == "cur_2"

    def test_get_percent_encodes_the_trace_id(self, client_factory):
        transport, client = client_factory(json_response(envelope({"traceId": "a/b"})))
        client.fraud().decisions.get("a/b")
        assert transport.last.path == "/api/v1/fraud/decision-logs/a%2Fb"

    def test_get_requires_a_trace_id(self, client_factory):
        transport, client = client_factory()
        for value in ("", "   "):
            with pytest.raises(ConfigurationError, match="trace_id"):
                client.fraud().decisions.get(value)

    def test_latest_for_payment_asks_for_one_row(self, client_factory):
        transport, client = client_factory(json_response(envelope([{"traceId": "t9"}])))
        latest = client.fraud().decisions.latest_for_payment("pay_1")

        assert latest == {"traceId": "t9"}
        assert "limit=1" in transport.last.path
        assert "paymentId=pay_1" in transport.last.path

    def test_latest_for_payment_returns_none_when_there_is_no_decision(self, client_factory):
        transport, client = client_factory(json_response(envelope([])))
        assert client.fraud().decisions.latest_for_payment("pay_1") is None

    def test_iterate_follows_the_cursor_to_the_last_page(self, client_factory):
        transport, client = client_factory(
            json_response(
                envelope([{"traceId": "t1"}], pageInfo={"hasMore": True, "nextCursor": "cur_2"})
            ),
            json_response(
                envelope([{"traceId": "t2"}], pageInfo={"hasMore": False, "nextCursor": None})
            ),
        )
        rows = list(client.fraud().decisions.iterate(limit=1))

        assert [row["traceId"] for row in rows] == ["t1", "t2"]
        assert "cursor=cur_2" in transport.requests[-1].path

    def test_iterate_stops_when_has_more_is_true_but_no_cursor_is_sent(self, client_factory):
        """A truthy `hasMore` with no cursor would otherwise loop forever."""
        transport, client = client_factory(
            json_response(
                envelope([{"traceId": "t1"}], pageInfo={"hasMore": True, "nextCursor": None})
            )
        )
        assert len(list(client.fraud().decisions.iterate())) == 1
