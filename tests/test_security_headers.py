"""Security headers (app/security.py, SecurityProblems.md SP-07): every response carries them."""
import pytest
from starlette.testclient import TestClient

from app.security import SecurityHeadersMiddleware

PATHS = ["/", "/health", "/api/me", "/static/styles.css", "/static/app.js"]  # page, API, 401, static files


@pytest.mark.parametrize("path", PATHS)
def test_every_response_carries_the_security_headers(client, path):
    r = client.get(path)

    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cross-origin-opener-policy"] == "same-origin"
    assert "camera=()" in r.headers["permissions-policy"]
    assert r.headers["content-security-policy"]


def test_the_content_security_policy_allows_only_this_site_and_no_inline_script():
    from app.security import CSP

    directives = {d.split()[0]: d.split()[1:] for d in CSP.split(";") if d.strip()}

    assert directives["default-src"] == ["'self'"]
    assert directives["script-src"] == ["'self'"]  # no inline script, no eval, no CDN
    assert "'unsafe-inline'" not in CSP and "'unsafe-eval'" not in CSP
    assert "http" not in CSP  # no third-party host is allowed anywhere
    assert directives["object-src"] == ["'none'"]
    assert directives["frame-ancestors"] == ["'none'"]
    assert directives["base-uri"] == ["'none'"]


async def _plain_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"ok"})


def test_hsts_is_sent_only_when_asked_for():
    with_hsts = TestClient(SecurityHeadersMiddleware(_plain_app, hsts=True)).get("/")
    without = TestClient(SecurityHeadersMiddleware(_plain_app, hsts=False)).get("/")

    assert with_hsts.headers["strict-transport-security"].startswith("max-age=")
    assert "strict-transport-security" not in without.headers


def test_headers_do_not_replace_the_ones_the_app_already_set(client):
    r = client.get("/")  # the page sets Cache-Control itself

    assert r.headers["cache-control"] == "no-cache"
