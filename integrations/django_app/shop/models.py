from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models


def order_id() -> str:
    return "order_" + secrets.token_hex(16)


class Stock(models.Model):
    sku = models.CharField(max_length=100, primary_key=True)
    quantity = models.PositiveIntegerField(default=100)


class Order(models.Model):
    id = models.CharField(max_length=64, primary_key=True, default=order_id)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    stock = models.ForeignKey(Stock, on_delete=models.PROTECT)
    amount = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="TRY")
    state = models.CharField(max_length=32, default="pending")
    captured = models.PositiveBigIntegerField(default=0)
    refunded = models.PositiveBigIntegerField(default=0)
    stock_applied = models.BooleanField(default=False)
    fulfillment_hold = models.BooleanField(default=False)
    next_poll = models.BigIntegerField(default=0)


class Attempt(models.Model):
    order = models.OneToOneField(Order, on_delete=models.PROTECT, primary_key=True)
    payload = models.JSONField()
    payment_id = models.CharField(max_length=200, default="", db_index=True)


class Event(models.Model):
    event_key = models.CharField(max_length=64, primary_key=True)
    payload_hash = models.CharField(max_length=64)


class Outbox(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT)
    event_hash = models.CharField(max_length=64, unique=True)
    state = models.CharField(max_length=16, default="pending")
