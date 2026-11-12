from lunixi import ProductCategory
from lunixi.payments import ProductCategory as PaymentsProductCategory

EXPECTED = (
    "MOBILE_PHONE",
    "TABLET",
    "COMPUTER",
    "TV_AUDIO",
    "WHITE_GOODS",
    "SMALL_APPLIANCE",
    "CAMERA",
    "GAME_CONSOLE",
    "WEARABLE",
    "ELECTRONICS_ACCESSORY",
    "ELECTRONICS_OTHER",
    "GOLD",
    "JEWELRY",
    "WATCH",
    "APPAREL",
    "SHOES_BAGS",
    "COSMETICS",
    "FURNITURE",
    "HOME_LIVING",
    "GROCERY",
    "BOOKS_MEDIA",
    "TOYS",
    "SPORTS_OUTDOOR",
    "PET_SUPPLIES",
    "AUTO_PARTS",
    "MUSICAL_INSTRUMENT",
    "MICROMOBILITY",
    "VEHICLE",
    "TRANSPORT_TICKET",
    "EVENT_TICKET",
    "ACCOMMODATION",
    "TRAVEL_PACKAGE",
    "HEALTH_SERVICE",
    "EDUCATION",
    "SHIPPING_SERVICE",
    "DIGITAL_GOODS",
    "GIFT_CARD",
    "SUBSCRIPTION",
    "SERVICE_OTHER",
    "OTHER",
)


def test_all_lists_the_forty_codes_in_dictionary_order():
    assert ProductCategory.ALL == EXPECTED
    assert len(set(ProductCategory.ALL)) == 40


def test_constants_are_plain_strings_equal_to_their_names():
    for code in EXPECTED:
        assert getattr(ProductCategory, code) == code


def test_payments_package_exports_the_same_holder():
    assert PaymentsProductCategory is ProductCategory
