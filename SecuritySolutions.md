# Security solutions

What was done about the problems listed in [SecurityProblems.md](SecurityProblems.md). The fixes were made on 2026-11-23 on the `security-fixes` branch, test first: each fix has a test that failed before the change and passes after it. The full suite is 92 tests (the 52 that existed before, plus 40 new ones).

IDs (SP-01 …) are the same as in `SecurityProblems.md`.

## Fixed

| ID | Severity | Problem | Fix in one line |
|---|---|---|---|
| SP-01 | High | The bot's reply was put in the page as raw HTML (cross-site scripting) | Replies go through `static/render.js`, which escapes everything first |
| SP-22 | Low | Some invoice fields were not escaped | Every invoice field is escaped |
| SP-11 | Medium | A script loaded from a CDN with no integrity check | The CDN script is gone; nothing loads from another site |
| SP-07 | Medium | No security headers | Strict headers on every response, including a Content-Security-Policy |
| SP-02 | High | Unlimited login attempts | 8 wrong passwords in 10 minutes block that address for the rest of the window |
| SP-03 | High | Huge requests were read before sign-in | Refused from the headers, before any body is read |
| SP-05 | Medium | No password rules; defaults failed open | Production needs 16+ characters; a missing `APP_ENV` now means production |
| SP-17 | Medium | Failed logins and limit hits were not logged | They are logged, one line each (the alert is still open) |
| SP-08 | Low | `/openapi.json` was public | Switched off |
| SP-09 | Low | `/health` showed internals | Public `/health` says only `ok`; detail needs the cron secret |
| SP-10 | Low | Cron secret compared with `!=` | Constant-time comparison |
| SP-19 | Low | A failed log insert could break a reply | The log row is written separately and can fail alone |

### SP-01 and SP-22: replies can no longer run script

- **Before:** `marked` turned the reply into HTML and the page inserted it unchanged, so HTML in a reply, including an event handler, ran as script.
- **Now:** `static/render.js` (`SafeMarkdown.render`) HTML-escapes the whole reply first and only then adds the few tags it supports (paragraphs, bold, italic, code, headings, lists, tables, quotes, rules, links). Raw HTML in a reply shows up as visible text. Links are kept only for `http(s)` and `mailto` and open with `rel="noopener noreferrer"`; `javascript:`, `data:` and relative links lose their link and keep their text; images are never loaded.
- **Also:** `static/app.js` uses it for every reply and error message, and the invoices panel escapes the date, amount, currency and status (SP-22).
- **Files:** `static/render.js` (new), `static/app.js`, `static/index.html`.
- **Checked by:** `tests/js/render_check.js`, run by `tests/test_render_js.py`: 16 checks with Node, covering hostile input (image and script tags, event handlers, `javascript:` and `data:` links in several spellings, a quote breaking out of a link, half-written streaming replies) and ordinary replies (formatting, lists, tables, Hebrew). The same attack text that ran script before was sent again in the real browser and stayed inert.
- **Limit:** the renderer supports a deliberate subset of Markdown. A reply using something outside it (nested lists, footnotes) shows it as plain text.

### SP-11: nothing loads from another site

- **Before:** `index.html` loaded `marked` from `cdnjs.cloudflare.com` without an integrity hash.
- **Now:** the library is no longer used, so there is no third-party script, no new dependency and nothing to pin.
- **Checked by:** `tests/test_frontend_static.py` fails if the page ever loads a script, style or image from another host, has an inline script, an inline handler or a `style=` attribute, or mentions `marked`.

### SP-07: security headers

- **Now:** every response carries `Content-Security-Policy` (own site only for scripts, styles, fonts and connections; `data:` images for the invoice preview; no inline script; no framing; no `<base>` or plugins), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy` (camera, microphone, location, payment and USB off) and `Cross-Origin-Opener-Policy: same-origin`. Production adds `Strict-Transport-Security`. A header the app sets itself, such as `Cache-Control`, is left alone.
- **Why plain ASGI:** the chat streams and depends on noticing a closed browser; the middleware in `app/security.py` does not sit in the middle of that the way Starlette's `BaseHTTPMiddleware` would.
- **Checked by:** `tests/test_security_headers.py` (every page, API and static response; the policy has no `unsafe-inline`, no `unsafe-eval` and no outside host; HSTS only when asked). In the browser the page, fonts, wave pattern, croissant, wordmark and chat all work under the policy and the console shows no violations.
- **Limit:** the policy only holds while the page stays free of inline script and `style=` attributes; `tests/test_frontend_static.py` guards that. Railway's own proxy may add headers on top; this was not checked because the old deployment no longer exists.

### SP-02 and SP-17: login throttle and security log

- **Now:** `app/security.py` counts wrong passwords per client address. The 9th wrong attempt inside 10 minutes gets `429` with a `Retry-After`; while blocked, even the right password is refused. A good login clears that address's count. The address is the last entry of `X-Forwarded-For`, which Railway's proxy appends; entries before it are ignored because the caller can forge them.
- **Logging:** one line each for `login_failed` (address and the name typed, never the password), `login_throttled`, `login_ok`, `rate_limit_hit`, `daily_cap_hit`, `cron_secret_rejected`, `health_degraded` and `conversation_log_failed`. Control characters are stripped from every value, so a typed name cannot forge a second log line.
- **Checked by:** `tests/test_login_throttle.py`: the block at the 9th attempt, no entry with the right password while blocked, other addresses unaffected, a forged first address not helping, a good login clearing the count, expiry after the window, no password and no forged line in the log, and the limit and cap events logged.
- **Limits:** (1) the count is in memory, so it resets when the app restarts and assumes one running copy; (2) it trusts the proxy's `X-Forwarded-For`, so if the app were ever exposed without a proxy, an attacker could rotate that header and dodge the throttle; (3) a distributed guessing attempt from many addresses is slowed but not stopped, which is why SP-05 asks for a long password; (4) **there is still no alert**: the lines are in the log, but nothing notifies anyone when they pile up.

### SP-03: large requests are refused before they are read

- **Now:** a request must declare its length, and anything over the upload limit plus 64 KB is answered `413` from the headers alone; a chunked body with no declared length gets `411`. The image field has its own `max_length`, and validation errors no longer echo back what was sent (before, an oversized image or a mistyped password came back in the 422 response).
- **Files:** `app/security.py` (`RequestSizeLimitMiddleware`), `app/main.py`.
- **Checked by:** `tests/test_request_limits.py`: a 20 MB body is refused with 413 before the sign-in check, a chunked body gets 411, an image over the field limit gets 422 with a short body that does not repeat the input, refusals still carry the security headers, and ordinary requests work.
- **Limit:** a signed-out caller can still make the server read a body up to about 7 MB. That is the price of keeping validation in FastAPI; moving the sign-in check ahead of body parsing would remove it.

### SP-05: password rules and safe defaults

- **Now:** in production the app refuses to start unless `APP_PASSWORD` is at least 16 characters. A missing `APP_ENV` now means production, so forgetting it can no longer switch on the built-in dev password `bakery`. `.env.example` sets `APP_ENV=local` for development.
- **Checked by:** `tests/test_config.py`: a short password is refused, a long one accepted, a missing `APP_ENV` is treated as production, and `local` still gives the dev defaults.
- **Do this on Railway:** if the live service has a password shorter than 16 characters, it will not start after this change until you set a longer `APP_PASSWORD` (the deploy guide, section 3.4, shows how).

### SP-08, SP-09 and SP-10: say less, compare safely

- **SP-08:** `/openapi.json` (and `/docs`, `/redoc`) return 404.
- **SP-09:** public `GET /health` returns only `{"status": "ok"}` (or `{"status": "degraded"}` with a 503). A request carrying the right `X-Cron-Secret` gets the detail as before. Every problem is also logged. Railway's health check only needs the status code, so it is unaffected.
- **SP-10:** the cron secret is compared with `hmac.compare_digest`.
- **Checked by:** `tests/test_security_misc.py`. The deploy guide and runbook were updated for the new `/health` output.

### SP-19: logging can no longer break a reply

- **Before:** the `conversations` log row was written in the same step as the run record, so a failure there would have lost the run record and broken the stream.
- **Now:** the run is committed first and the log row is written afterwards on its own; a failure rolls back only that row and is logged as `conversation_log_failed`.
- **Checked by:** `tests/test_security_misc.py` makes the log insert raise and shows the reply still ends with `done` and the run record is saved.

## Still open

These were not part of this round. Details and fixes are in `SecurityProblems.md`.

- **Design changes:** SP-04 (one shared password; anyone can sign in as any name), SP-06 (sessions last 72 hours and logout does not cancel them), SP-14 (per-user limits are bypassed by new names; the daily budget is shared).
- **Defence in depth:** SP-16 (prompt injection can still steer the invoice tool), SP-15 (look-alike names), SP-23 (everyone sees all invoices and the spend), SP-24 (no automatic deletion of old chats), SP-21 (error text reaches users), SP-20 (failed digest webhook returns a 500).
- **Build and supply chain:** SP-12 (indirect packages unpinned; `pytest` in production), SP-13 (CI actions pinned by tag), SP-18 (the `railway up` route skips CI).
- **Partly done:** SP-17 (the alert).
- **Info only:** SP-25, SP-26, SP-27.

## How to check it yourself

```bash
pytest -q                      # 92 tests, model mocked
node tests/js/render_check.js  # the renderer's 16 checks, plain Node
```

Then run the app (`APP_ENV=local`) and look at the response headers of `/`, try `/openapi.json` (404), and send a reply containing HTML in the chat: it must appear as text.
