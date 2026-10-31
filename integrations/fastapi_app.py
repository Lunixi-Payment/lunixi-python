"""Run: uvicorn --factory integrations.fastapi_app:create_app (behind HTTPS)."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from lunixi import LunixiClient, LunixiError

from .common import (
    Orders,
    Settings,
    callback_post_allowed,
    checkout_page,
    require_csrf,
    security_headers,
)


def create_app(
    settings: Optional[Settings] = None, client: Optional[LunixiClient] = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    orders = Orders(settings, client)
    app = FastAPI(debug=False, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.orders = orders
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="lunixi_checkout",
        same_site="lax",
        https_only=True,
        max_age=3600,
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=[urlsplit(settings.public_origin).hostname]
    )

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        response = await call_next(request)
        for key, value in security_headers().items():
            response.headers.setdefault(key, value)
        return response

    @app.get("/assets/lunixi-logo.svg")
    def logo():
        return FileResponse(
            Path(__file__).resolve().parents[1] / ".github/assets/lunixi-logo.svg",
            media_type="image/svg+xml",
        )

    @app.get("/claim/{token}")
    def claim(token: str, request: Request):
        try:
            key, owner = orders.claim(token)
            request.session.clear()
            request.session.update(owner=owner, order=key, csrf=secrets.token_urlsafe(32))
            return RedirectResponse("/checkout/" + key, status_code=303)
        except LunixiError:
            return JSONResponse({"error": "checkout_unavailable"}, status_code=403)

    @app.get("/checkout/{key}")
    def checkout(key: str, request: Request):
        try:
            row = orders.owned(key, request.session.get("owner"))
            nonce = secrets.token_urlsafe(18)
            return HTMLResponse(
                checkout_page(
                    key,
                    request.session["csrf"],
                    settings.locale,
                    complete=orders.complete(key, request.session.get("owner")),
                    hold=bool(row["fulfillment_hold"]),
                    nonce=nonce,
                ),
                headers=security_headers(nonce, settings.form_action_origins),
            )
        except (LunixiError, KeyError):
            return JSONResponse({"error": "checkout_unavailable"}, status_code=403)

    @app.post("/checkout/{key}")
    async def begin(key: str, request: Request):
        try:
            require_csrf(request.session, request.headers.get("x-csrf-token"))
            result = await run_in_threadpool(orders.start, key, request.session.get("owner"))
            return JSONResponse(result)
        except LunixiError:
            return JSONResponse({"error": "checkout_unavailable"}, status_code=409)

    @app.get("/status/{key}")
    def status(key: str, request: Request):
        try:
            return JSONResponse(orders.status(key, request.session.get("owner")))
        except LunixiError:
            return JSONResponse({"complete": False}, status_code=202)

    @app.api_route("/return/{key}", methods=["GET", "POST"])
    def returned(key: str, request: Request):
        if request.method == "POST":
            if not callback_post_allowed(request.headers.get("content-length")):
                return JSONResponse({"error": "callback_too_large"}, status_code=413)
            # Do not inspect session, body, order, or gateway on the cross-site hop.
            return RedirectResponse("/return/" + key, status_code=303)
        if request.method == "GET":
            try:
                orders.owned(key, request.session.get("owner"))
                orders.service.reconcile(key, orders.apply)
            except LunixiError:
                pass
        # Cross-site POST may have no SameSite cookie. It only leads to an owned GET.
        return RedirectResponse("/checkout/" + key, status_code=303)

    @app.post("/webhook")
    async def webhook(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1024 * 1024:
                return JSONResponse({"error": "webhook_too_large"}, status_code=413)
        try:
            await run_in_threadpool(orders.webhook, bytes(raw), dict(request.headers))
            return HTMLResponse("", status_code=204)
        except Exception:
            return JSONResponse({"error": "retry_delivery"}, status_code=503)

    return app
