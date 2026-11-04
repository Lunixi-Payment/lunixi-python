import pytest

from lunixi.errors import ConfigurationError
from lunixi.payments import CreateIntent, validate_enabled_installments


def test_enabled_installments_are_sent_in_ascending_order():
    body = CreateIntent("1000", "TRY", "order", enabled_installments=[3, 1, 2]).to_dict()
    assert body["enabledInstallments"] == [1, 2, 3]


def test_single_payment_only():
    body = CreateIntent("1000", "TRY", "order", enabled_installments=[1]).to_dict()
    assert body["enabledInstallments"] == [1]


def test_none_sends_no_field():
    assert "enabledInstallments" not in CreateIntent("1000", "TRY", "order").to_dict()


def test_caller_list_is_not_reordered():
    counts = [6, 1, 3]
    CreateIntent("1000", "TRY", "order", enabled_installments=counts).to_dict()
    assert counts == [6, 1, 3]


def test_bounds_are_accepted():
    assert validate_enabled_installments([36, 1]) == [1, 36]


@pytest.mark.parametrize(
    "counts",
    [[], [2, 3], [1, 2, 2], [0, 1], [1, -3], [1, 37], [1, 2.0], [1, "3"], [1, None], [True, 2], "1,2,3"],
)
def test_broken_lists_are_refused(counts):
    with pytest.raises(ConfigurationError):
        CreateIntent("1000", "TRY", "order", enabled_installments=counts).to_dict()


def test_duplicate_is_an_error_not_removed():
    with pytest.raises(ConfigurationError, match="more than once"):
        validate_enabled_installments([1, 3, 3])
