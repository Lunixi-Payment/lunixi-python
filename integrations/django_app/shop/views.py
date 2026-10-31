from __future__ import annotations

import secrets
from pathlib import Path

from django.http import FileResponse, HttpResponse, HttpResponseRedirect, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from integrations.common import (
    DEFAULT_FORM_ACTION_ORIGINS,
    callback_post_allowed,
    checkout_page,
    security_headers,
)
from lunixi import LunixiError

from .service import get_orders


def secure(response, nonce=None, form_origins=DEFAULT_FORM_ACTION_ORIGINS):
    for key, value in security_headers(nonce, form_origins).items():
        response[key] = value
    return response


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def checkout(request, key):
    orders = get_orders()
    try:
        order = orders.owned(key, request.user)
        if request.method == "POST":
            # Native CsrfViewMiddleware validates the token before this view.
            return secure(JsonResponse(orders.start(key, request.user)))
        nonce = secrets.token_urlsafe(18)
        return secure(
            HttpResponse(
                checkout_page(
                    key,
                    get_token(request),
                    orders.settings.locale,
                    complete=orders.complete(key, request.user),
                    hold=order.fulfillment_hold,
                    nonce=nonce,
                )
            ),
            nonce,
            orders.settings.form_action_origins,
        )
    except LunixiError:
        return secure(
            JsonResponse(
                {"error": "checkout_unavailable"}, status=403 if request.method == "GET" else 409
            )
        )


@require_GET
def status(request, key):
    try:
        return secure(JsonResponse(get_orders().status(key, request.user)))
    except LunixiError:
        return secure(JsonResponse({"complete": False}, status=202))


@csrf_exempt
@require_http_methods(["GET", "POST"])
def returned(request, key):
    if request.method == "POST":
        if not callback_post_allowed(request.META.get("CONTENT_LENGTH")):
            return secure(JsonResponse({"error": "callback_too_large"}, status=413))
        # Narrow CSRF exception: no body/session/order/gateway access on this hop.
        return secure(HttpResponseRedirect("/return/" + key, status=303))
    if request.method == "GET":
        try:
            orders = get_orders()
            orders.owned(key, request.user)
            orders.service.reconcile(key, orders.apply)
        except LunixiError:
            pass
    return secure(HttpResponseRedirect("/checkout/" + key, status=303))


@csrf_exempt
@require_POST
def webhook(request):
    try:
        if int(request.META.get("CONTENT_LENGTH") or "0") > 1024 * 1024:
            return secure(JsonResponse({"error": "webhook_too_large"}, status=413))
        raw = request.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return secure(JsonResponse({"error": "webhook_too_large"}, status=413))
        orders = get_orders()
        orders.service.webhook(
            raw, dict(request.headers), orders.settings.webhook_secret, orders.apply
        )
        return secure(HttpResponse(status=204))
    except Exception:
        return secure(JsonResponse({"error": "retry_delivery"}, status=503))


def logo(request):
    return FileResponse(
        (Path(__file__).resolve().parents[3] / ".github/assets/lunixi-logo.svg").open("rb"),
        content_type="image/svg+xml",
    )
