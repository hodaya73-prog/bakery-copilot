"""Security plumbing: response headers, a request size guard, the login throttle and the security log.

Each piece answers an item in SecurityProblems.md and is described in SecuritySolutions.md. The two
middlewares are plain ASGI (not Starlette's BaseHTTPMiddleware) on purpose: the chat streams its reply and
relies on noticing when the browser goes away, and BaseHTTPMiddleware would sit in the middle of that.
"""
from __future__ import annotations

import json
import logging
import math
import re
import sys
import time
from collections import defaultdict, deque

# ---------------------------------------------------------------------------
# Response headers (SP-07; the policy is also the second wall behind SP-01)
# ---------------------------------------------------------------------------

# Only this site may supply scripts, styles, fonts, images (and data: images for the invoice preview) or take
# requests; nothing may be framed, and no inline script runs. Needs: no inline <script>, no style="" attribute,
# no third-party host. tests/test_frontend_static.py keeps the page that way.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    """Adds the security headers to every HTTP response (and leaves any header the app set itself alone)."""

    def __init__(self, app, *, hsts: bool = False):
        self.app = app
        self.headers: list[tuple[bytes, bytes]] = [
            (b"content-security-policy", CSP.encode()),
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"no-referrer"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
            (b"cross-origin-opener-policy", b"same-origin"),
        ]
        if hsts:  # only over HTTPS, i.e. in production
            self.headers.append((b"strict-transport-security", b"max-age=31536000"))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                existing = {name.lower() for name, _ in message.get("headers", [])}
                extra = [(n, v) for n, v in self.headers if n not in existing]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ---------------------------------------------------------------------------
# Request size (SP-03)
# ---------------------------------------------------------------------------

class RequestSizeLimitMiddleware:
    """Refuses an oversized request from its headers alone, before a byte of the body is read.

    FastAPI reads and validates the whole body before a route's sign-in check runs, so without this a caller
    who is not signed in could make the server hold a very large body. A body must declare its length
    (browsers always do); a chunked body, which has no declared length, is refused.
    """

    def __init__(self, app, *, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {name.lower(): value for name, value in scope.get("headers", [])}
            if b"transfer-encoding" in headers:
                await self._refuse(send, 411, "Send the request with a Content-Length.")
                return
            declared = headers.get(b"content-length")
            if declared is not None:
                if not declared.isdigit():
                    await self._refuse(send, 400, "Bad Content-Length.")
                    return
                if int(declared) > self.max_bytes:
                    await self._refuse(send, 413, "Request is too large.")
                    return
        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------------------
# Login throttle (SP-02)
# ---------------------------------------------------------------------------

class LoginThrottle:
    """Counts wrong passwords per client address in a sliding window and blocks an address that hits the limit.

    In memory, so it starts empty after a restart, and it assumes one running copy of the app. Good enough
    for one small service; with several replicas the count would have to live in the database.
    """

    def __init__(self, max_failures: int = 8, window_seconds: int = 600, clock=time.monotonic):
        self.max_failures = max_failures
        self.window = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float] | None:
        times = self._failures.get(key)
        if times is None:
            return None
        while times and now - times[0] >= self.window:
            times.popleft()
        if not times:
            del self._failures[key]
            return None
        return times

    def blocked_for(self, key: str) -> int:
        """Seconds until this address may try again; 0 when it may try now."""
        now = self._clock()
        times = self._prune(key, now)
        if times is not None and len(times) >= self.max_failures:
            return max(1, math.ceil(self.window - (now - times[0])))
        return 0

    def record_failure(self, key: str) -> None:
        now = self._clock()
        if len(self._failures) > 5000:  # many different addresses: forget the ones whose window has passed
            for stale in list(self._failures):
                self._prune(stale, now)
        times = self._failures[key]
        times.append(now)
        while len(times) > self.max_failures:
            times.popleft()

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)

    def reset(self) -> None:
        self._failures.clear()


login_throttle = LoginThrottle()


def client_ip(request) -> str:
    """The caller's address. Behind Railway's proxy the real address is the LAST entry of X-Forwarded-For
    (the proxy appends it); entries before it are whatever the caller claimed, so they are ignored."""
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if parts:
        return parts[-1][:64]
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Security log (SP-17)
# ---------------------------------------------------------------------------

logger = logging.getLogger("bakery.security")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s security %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

_PLAIN = re.compile(r"^[\w.:@/-]{1,64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f  ]")


def _value(v) -> str:
    """A log value on one line: control characters (newlines) removed, long values cut, odd values quoted."""
    s = _CONTROL.sub(" ", str(v))[:80]
    return s if _PLAIN.match(s) else repr(s)


def log_event(event: str, **fields) -> None:
    """One line: `event key=value ...`. Never pass a password or a token."""
    logger.info(event + "".join(f" {k}={_value(v)}" for k, v in fields.items()))
