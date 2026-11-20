import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from integrations.common import Settings
from integrations.django_app.shop.models import Order, Stock
from lunixi.commerce import minor_units


class Command(BaseCommand):
    help = "Create one native customer order for a trusted existing user."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--amount", default="19.90")
        parser.add_argument("--currency", default="TRY")
        parser.add_argument(
            "--order-details",
            required=True,
            help="JSON file with the customer's buyer, billingAddress, basketItems (and shippingAddress for shipped goods); every payment requires them",
        )

    def handle(self, *args, **options):
        user = get_user_model().objects.get(username=options["username"])
        with open(options["order_details"], encoding="utf-8") as handle:
            details = json.load(handle)
        stock, _ = Stock.objects.get_or_create(sku="sample-product", defaults={"quantity": 100})
        order = Order.objects.create(
            owner=user,
            stock=stock,
            amount=minor_units(options["amount"], options["currency"]),
            currency=options["currency"],
            order_details=details,
        )
        self.stdout.write(Settings.from_env().public_origin + "/checkout/" + str(order.pk))
