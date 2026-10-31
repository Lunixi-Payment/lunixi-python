"""Real loopback HTTP through each native framework, with no browser session."""

from __future__ import annotations

import http.client
import socket
import threading
import time
from contextlib import contextmanager
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


@contextmanager
def live_wsgi(app):
    def tls_terminated(environ, start_response):
        # Test-only trusted TLS termination; production must use an HTTPS proxy.
        environ["wsgi.url_scheme"] = "https"
        environ["HTTPS"] = "on"
        return app(environ, start_response)

    server = make_server("127.0.0.1", 0, tls_terminated, handler_class=QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@contextmanager
def live_asgi(app):
    import uvicorn

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    config = uvicorn.Config(
        app, log_level="critical", access_log=False, lifespan="off", ws="none", proxy_headers=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive()


def post(port, body):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(
            "POST",
            "/return/native-order-123?redirect=https://evil.invalid",
            body,
            headers={
                "Host": "testserver",
                "Origin": "https://pay.lunixi.com",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        response = connection.getresponse()
        return (
            response.status,
            {key.lower(): value for key, value in response.getheaders()},
            response.read(),
        )
    finally:
        connection.close()


@pytest.mark.parametrize("kind", ["flask", "fastapi", "django"])
def test_native_http_sessionless_post_only_redirects_without_db_or_gateway(
    kind, payment_setup, monkeypatch
):
    orders, gateway = payment_setup
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("A callback POST must not access order/database/gateway state.")

    if kind == "django":
        from django.core.wsgi import get_wsgi_application
        from django.db.backends.utils import CursorWrapper

        from integrations.django_app.shop import views

        monkeypatch.setattr(views, "get_orders", forbidden)
        monkeypatch.setattr(CursorWrapper, "execute", forbidden)
        app = get_wsgi_application()
        server = live_wsgi(app)
    else:
        if kind == "flask":
            from integrations.flask_app import create_app
        else:
            from integrations.fastapi_app import create_app
        app = create_app(orders.settings, orders.service.client)
        native = app.extensions["lunixi_orders"] if kind == "flask" else app.state.orders
        monkeypatch.setattr(native, "owned", forbidden)
        monkeypatch.setattr(native.store, "connect", forbidden)
        monkeypatch.setattr(native.service, "reconcile", forbidden)
        server = live_wsgi(app) if kind == "flask" else live_asgi(app)

    with server as port:
        for body in [b"", b"status=success&order_id=999&paymentId=pi_forged", b"x" * 65536]:
            status, headers, response = post(port, body)
            assert status == 303
            assert headers["location"] == "/return/native-order-123"
            assert headers["cache-control"] == "no-store"
            assert b"pi_forged" not in response
            assert b"evil.invalid" not in response
            assert "set-cookie" not in headers
        status, _, _ = post(port, b"x" * 65537)
        assert status == 413
    assert calls == []
    assert gateway.calls == []
