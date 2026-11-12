"""Lunixi product category codes for ``basketItems[].productCategory``.

Payment methods with legal installment limits (e.g. shopping loan) and other
platform features use them. The field is optional on every endpoint that takes
basket items; the gateway answers an unknown code with 400. The dictionary only
grows by appending, so the codes are plain strings and the SDK does not check a
value against :attr:`ProductCategory.ALL` before sending: a newer code can be sent
before this SDK declares a constant for it.
"""

from __future__ import annotations

from typing import Tuple

__all__ = ["ProductCategory"]


class ProductCategory:
    """Product category codes known to this SDK version, in dictionary order."""

    MOBILE_PHONE = "MOBILE_PHONE"
    TABLET = "TABLET"
    COMPUTER = "COMPUTER"
    TV_AUDIO = "TV_AUDIO"
    WHITE_GOODS = "WHITE_GOODS"
    SMALL_APPLIANCE = "SMALL_APPLIANCE"
    CAMERA = "CAMERA"
    GAME_CONSOLE = "GAME_CONSOLE"
    WEARABLE = "WEARABLE"
    ELECTRONICS_ACCESSORY = "ELECTRONICS_ACCESSORY"
    ELECTRONICS_OTHER = "ELECTRONICS_OTHER"
    GOLD = "GOLD"
    JEWELRY = "JEWELRY"
    WATCH = "WATCH"
    APPAREL = "APPAREL"
    SHOES_BAGS = "SHOES_BAGS"
    COSMETICS = "COSMETICS"
    FURNITURE = "FURNITURE"
    HOME_LIVING = "HOME_LIVING"
    GROCERY = "GROCERY"
    BOOKS_MEDIA = "BOOKS_MEDIA"
    TOYS = "TOYS"
    SPORTS_OUTDOOR = "SPORTS_OUTDOOR"
    PET_SUPPLIES = "PET_SUPPLIES"
    AUTO_PARTS = "AUTO_PARTS"
    MUSICAL_INSTRUMENT = "MUSICAL_INSTRUMENT"
    MICROMOBILITY = "MICROMOBILITY"
    VEHICLE = "VEHICLE"
    TRANSPORT_TICKET = "TRANSPORT_TICKET"
    EVENT_TICKET = "EVENT_TICKET"
    ACCOMMODATION = "ACCOMMODATION"
    TRAVEL_PACKAGE = "TRAVEL_PACKAGE"
    HEALTH_SERVICE = "HEALTH_SERVICE"
    EDUCATION = "EDUCATION"
    SHIPPING_SERVICE = "SHIPPING_SERVICE"
    DIGITAL_GOODS = "DIGITAL_GOODS"
    GIFT_CARD = "GIFT_CARD"
    SUBSCRIPTION = "SUBSCRIPTION"
    SERVICE_OTHER = "SERVICE_OTHER"
    OTHER = "OTHER"

    ALL: Tuple[str, ...] = (
        MOBILE_PHONE,
        TABLET,
        COMPUTER,
        TV_AUDIO,
        WHITE_GOODS,
        SMALL_APPLIANCE,
        CAMERA,
        GAME_CONSOLE,
        WEARABLE,
        ELECTRONICS_ACCESSORY,
        ELECTRONICS_OTHER,
        GOLD,
        JEWELRY,
        WATCH,
        APPAREL,
        SHOES_BAGS,
        COSMETICS,
        FURNITURE,
        HOME_LIVING,
        GROCERY,
        BOOKS_MEDIA,
        TOYS,
        SPORTS_OUTDOOR,
        PET_SUPPLIES,
        AUTO_PARTS,
        MUSICAL_INSTRUMENT,
        MICROMOBILITY,
        VEHICLE,
        TRANSPORT_TICKET,
        EVENT_TICKET,
        ACCOMMODATION,
        TRAVEL_PACKAGE,
        HEALTH_SERVICE,
        EDUCATION,
        SHIPPING_SERVICE,
        DIGITAL_GOODS,
        GIFT_CARD,
        SUBSCRIPTION,
        SERVICE_OTHER,
        OTHER,
    )
