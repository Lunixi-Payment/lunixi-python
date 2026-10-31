"""Operator CLI for the Flask/FastAPI sample database; never a customer endpoint."""

from __future__ import annotations

import argparse
import json

from lunixi.commerce import minor_units

from .common import Orders, Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Lunixi example application operator")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    seed = sub.add_parser("seed")
    seed.add_argument("--customer-id", required=True)
    seed.add_argument("--amount", default="19.90")
    seed.add_argument("--currency", default="TRY")
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--limit", type=int, default=100)
    operation = sub.add_parser("operation")
    operation.add_argument("action", choices=["capture", "refund", "void"])
    operation.add_argument("--order-id", required=True)
    operation.add_argument("--operation-id", required=True)
    operation.add_argument("--amount")
    args = parser.parse_args()
    settings = Settings.from_env()
    orders = Orders(settings)
    if args.command == "init":
        orders.install()
        print("initialized")
    elif args.command == "seed":
        key, token = orders.seed(
            args.customer_id, minor_units(args.amount, args.currency), args.currency
        )
        print(settings.public_origin + "/claim/" + token)
    elif args.command == "reconcile":
        failed = 0
        for key in orders.store.pending_keys(args.limit):
            try:
                orders.service.reconcile(key, orders.apply)
            except Exception:
                failed += 1
        print(json.dumps({"failed": failed}))
        if failed:
            raise SystemExit(1)
    else:
        connection = orders.store.connect()
        try:
            row = connection.execute(
                "SELECT currency FROM sample_order WHERE id=?", (args.order_id,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            parser.error("Unknown native order.")
        amount = None if args.action == "void" else minor_units(args.amount, row["currency"])
        orders.service.mutate(args.order_id, args.operation_id, args.action, amount, orders.apply)
        status = orders.service.operation_status(args.order_id, args.operation_id)
        print(json.dumps({"state": status["state"]}))
        if status["state"] != "confirmed":
            raise SystemExit(2)


if __name__ == "__main__":
    main()
