from django.core.management.base import BaseCommand

from integrations.django_app.shop.models import Attempt
from integrations.django_app.shop.service import get_orders


class Command(BaseCommand):
    help = "Reconcile persisted payment attempts without initiating new charges."

    def handle(self, *args, **options):
        orders = get_orders()
        failed = 0
        for attempt in Attempt.objects.all().iterator(chunk_size=100):
            if attempt.payload.get("state") not in ("failed", "refunded"):
                try:
                    orders.service.reconcile(str(attempt.order_id), orders.apply)
                except Exception:
                    failed += 1
        self.stdout.write("failed=" + str(failed))
        if failed:
            raise SystemExit(1)
