"""Response-envelope reading, including the two traps it exists to close."""

from __future__ import annotations

from lunixi.http.envelope import Page, data_of, is_success, items_of, page_info_of

from .support.recording_transport import envelope, error_envelope


class TestSuccessFlag:
    def test_there_is_no_success_field_on_the_wire(self):
        """🔴 The defect this module prevents.

        A client written against `response["success"]` reads None on EVERY
        response — never an error, just a value that is always falsy. The
        envelope carries the outcome in `status` as the string "success".
        """
        body = envelope({"id": "dec_1"})
        assert "success" not in body
        assert body["status"] == "success"
        assert body.get("success") is None
        assert is_success(body) is True

    def test_a_failure_envelope_is_not_a_success(self):
        assert is_success(error_envelope("FRAUD_CHANNEL_NOT_DECLARABLE", "nope")) is False

    def test_the_partial_status_is_not_a_success(self):
        # A partial batch is not a success: some rows were rejected.
        assert is_success({"status": "partial", "data": {}}) is False

    def test_a_payload_without_a_status_is_treated_as_a_success(self):
        # A failure always carries a status, so a bare payload passes through.
        assert is_success({"id": "dec_1"}) is True


class TestDataUnwrapping:
    def test_the_payload_is_unwrapped(self):
        assert data_of(envelope({"decision": "allow"})) == {"decision": "allow"}

    def test_a_bare_payload_passes_through(self):
        assert data_of({"decision": "allow"}) == {"decision": "allow"}

    def test_an_explicit_null_payload_stays_null(self):
        """An endpoint that answers with no payload answers None.

        Falling back to the envelope here would hand the caller `status` and
        `timestamp` as though they were data.
        """
        assert data_of(envelope(None)) is None

    def test_an_array_payload_is_returned_as_a_list(self):
        assert data_of(envelope([{"id": "a"}])) == [{"id": "a"}]


class TestPageInfo:
    def test_page_info_is_read_from_the_envelope_level(self):
        """🔴 `pageInfo` is a SIBLING of `data`, not nested inside it.

        List endpoints return `data` as a bare array, so paging metadata
        cannot live inside it. Reading `data["pageInfo"]` on such a response
        finds nothing and every list looks like a single final page.
        """
        body = envelope(
            [{"id": "a"}, {"id": "b"}],
            pageInfo={"hasMore": True, "nextCursor": "cur_2", "totalCount": None},
        )
        page = Page(body)

        assert isinstance(body["data"], list)
        assert page.items == [{"id": "a"}, {"id": "b"}]
        assert page.has_more is True
        assert page.next_cursor == "cur_2"
        assert page.total_count is None

    def test_the_transitional_copy_inside_data_is_still_read(self):
        body = envelope({"items": [{"id": "a"}], "pageInfo": {"hasMore": False, "nextCursor": None}})
        page = Page(body)
        assert page.items == [{"id": "a"}]
        assert page.has_more is False
        assert page.next_cursor is None

    def test_the_envelope_level_wins_over_the_copy_inside_data(self):
        body = envelope(
            {"items": [], "pageInfo": {"hasMore": False, "nextCursor": None}},
            pageInfo={"hasMore": True, "nextCursor": "cur_canonical"},
        )
        assert Page(body).next_cursor == "cur_canonical"

    def test_an_unpaged_response_yields_no_cursor_rather_than_raising(self):
        page = Page(envelope([{"id": "a"}]))
        assert page.has_more is False
        assert page.next_cursor is None
        assert page.total_count is None

    def test_an_empty_cursor_string_reads_as_the_last_page(self):
        page = Page(envelope([], pageInfo={"hasMore": False, "nextCursor": ""}))
        assert page.next_cursor is None

    def test_total_count_is_none_unless_the_server_counted(self):
        assert Page(envelope([], pageInfo={"totalCount": None})).total_count is None
        assert Page(envelope([], pageInfo={"totalCount": 42})).total_count == 42

    def test_a_boolean_is_not_read_as_a_total_count(self):
        # bool is a subclass of int in Python; True must not become 1 rows.
        assert Page(envelope([], pageInfo={"totalCount": True})).total_count is None

    def test_page_info_of_returns_an_empty_mapping_when_absent(self):
        assert page_info_of(envelope({"id": "a"})) == {}


class TestItems:
    def test_a_bare_array_payload_yields_its_rows(self):
        assert items_of(envelope([{"id": "a"}])) == [{"id": "a"}]

    def test_a_collection_key_yields_its_rows(self):
        assert items_of(envelope({"items": [{"id": "a"}]})) == [{"id": "a"}]
        assert items_of(envelope({"rows": [{"id": "b"}]})) == [{"id": "b"}]

    def test_an_unrecognised_shape_yields_an_empty_list(self):
        # An empty list is a valid answer; raising here would turn "no rows"
        # into a crash.
        assert items_of(envelope({"somethingElse": 1})) == []


class TestPageProtocol:
    def test_a_page_is_iterable_and_sized(self):
        page = Page(envelope([{"id": "a"}, {"id": "b"}]))
        assert len(page) == 2
        assert [row["id"] for row in page] == ["a", "b"]
