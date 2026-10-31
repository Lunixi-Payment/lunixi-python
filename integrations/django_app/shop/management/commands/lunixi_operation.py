from django.core.management.base import BaseCommand

from integrations.django_app.shop.models import Order
from integrations.django_app.shop.service import get_orders
from lunixi.commerce import minor_units


class Command(BaseCommand):
    help = "Server-operator capture/refund/void with a durable operation ID."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["capture", "refund", "void"])
        parser.add_argument("--order-id", required=True)
        parser.add_argument("--operation-id", required=True)
        parser.add_argument("--amount")

    def handle(self, *args, **options):
        orders = get_orders()
        order = Order.objects.get(pk=options["order_id"])
        amount = (
            None if options["action"] == "void" else minor_units(options["amount"], order.currency)
        )
        orders.service.mutate(
            str(order.pk), options["operation_id"], options["action"], amount, orders.apply
        )
        status = orders.service.operation_status(str(order.pk), options["operation_id"])
        self.stdout.write(status["state"])
        if status["state"] != "confirmed":
            raise SystemExit(2)
