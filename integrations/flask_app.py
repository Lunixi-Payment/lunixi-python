"""Run: flask --app integrations.flask_app:create_app run, behind HTTPS."""

from __future__ import annotations

import secrets
from datetime import timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, redirect, request, send_file, session

from lunixi import LunixiClient, LunixiError

from .common import (
    Orders,
    Settings,
    callback_post_allowed,
    checkout_page,
    require_csrf,
    security_headers,
)


def create_app(settings: Optional[Settings] = None, client: Optional[LunixiClient] = None) -> Flask:
    settings = settings or Settings.from_env()
    orders = Orders(settings, client)
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.session_secret,
        SESSION_COOKIE_NAME="lunixi_checkout",
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
        TRUSTED_HOSTS=[urlsplit(settings.public_origin).hostname],
    )
    app.extensions["lunixi_orders"] = orders

    @app.after_request
    def headers(response):
        for key, value in security_headers().items():
            response.headers.setdefault(key, value)
        return response

    @app.get("/assets/lunixi-logo.svg")
    def logo():
        return send_file(
            Path(__file__).resolve().parents[1] / ".github/assets/lunixi-logo.svg",
            mimetype="image/svg+xml",
        )

    @app.get("/claim/<token>")
    def claim(token: str):
        try:
            key, owner = orders.claim(token)
            session.clear()
            session.permanent = True
            session.update(owner=owner, order=key, csrf=secrets.token_urlsafe(32))
            return redirect("/checkout/" + key, code=303)
        except LunixiError:
            return jsonify(error="checkout_unavailable"), 403

    @app.get("/checkout/<key>")
    def checkout(key: str):
        try:
            row = orders.owned(key, session.get("owner"))
            nonce = secrets.token_urlsafe(18)
            return Response(
                checkout_page(
                    key,
                    session["csrf"],
                    settings.locale,
                    complete=orders.complete(key, session.get("owner")),
                    hold=bool(row["fulfillment_hold"]),
                    nonce=nonce,
                ),
                headers=security_headers(nonce),
                mimetype="text/html",
            )
        except (LunixiError, KeyError):
            return jsonify(error="checkout_unavailable"), 403

    @app.post("/checkout/<key>")
    def begin(key: str):
        try:
            require_csrf(session, request.headers.get("X-CSRF-Token"))
            return jsonify(orders.start(key, session.get("owner")))
        except LunixiError:
            return jsonify(error="checkout_unavailable"), 409

    @app.get("/status/<key>")
    def status(key: str):
        try:
            return jsonify(orders.status(key, session.get("owner")))
        except LunixiError:
            return jsonify(complete=False), 202

    @app.route("/return/<key>", methods=["GET", "POST"])
    def returned(key: str):
        if request.method == "POST":
            if not callback_post_allowed(request.headers.get("content-length")):
                return jsonify(error="callback_too_large"), 413
            # Do not inspect session, body, order, or gateway on the cross-site hop.
            return redirect("/return/" + key, code=303)
        if request.method == "GET":
            try:
                orders.owned(key, session.get("owner"))
                orders.service.reconcile(key, orders.apply)
            except LunixiError:
                pass
        return redirect("/checkout/" + key, code=303)

    @app.post("/webhook")
    def webhook():
        raw = request.get_data(cache=False)
        try:
            orders.webhook(raw, dict(request.headers))
            return Response(status=204)
        except Exception:
            return jsonify(error="retry_delivery"), 503

    return app
