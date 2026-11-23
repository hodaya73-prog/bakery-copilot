# Security problems

A review of Bakery Copilot against the OWASP Top 10:2025, done on 2026-11-23 at commit `80cb6a5` (branch `conversations-user-name-view`). It lists every weakness found, where it is in the code, and the fix. Line numbers are for that commit and will drift as the code changes; search for the function name if a line has moved.

**Status.** Eleven items were fixed on 2026-11-23 on the `security-fixes` branch (SP-01, SP-02, SP-03, SP-05, SP-07, SP-08, SP-09, SP-10, SP-11, SP-19, SP-22) and one is partly fixed (SP-17). How each was fixed, and how it was checked, is in [SecuritySolutions.md](SecuritySolutions.md). Every other item is still open. The descriptions below are the problems as they were found; a ticked box means the problem no longer exists in the code. Tick the box and name the commit when another one is fixed.

## How this was checked

- Read all of `app/`, `static/`, `.github/workflows/ci.yml`, `requirements.txt` and the deploy docs.
- Dependency audit of `requirements.txt` with `pip-audit`: no known vulnerabilities on 2026-11-23.
- Git history scanned for key-like strings and committed `.env` files: none found.
- The running app (a local copy of this exact code) was probed for exposed paths, response headers, CORS, login behaviour and large requests. One finding (SP-01) was confirmed by running it.

**Not checked.** The Railway deployment was no longer available on the day of the review, so these are unverified: headers added by Railway's edge (such as HSTS), the production cookie flags (read from the code only), and database roles and encryption at rest on Railway.

## Summary

| ID | Severity | OWASP 2025 | Problem |
|---|---|---|---|
| SP-01 | High | A05 Injection | The bot's reply is put into the page as unsanitised HTML (cross-site scripting) |
| SP-02 | High | A06, A07 | No limit on login attempts |
| SP-03 | High | A06 Insecure Design | Large requests are read in full before sign-in; the image field has no size limit |
| SP-04 | High | A07, A01 | One shared password; anyone can sign in as any name |
| SP-05 | Medium | A07, A02 | No password rules, and the defaults fail open |
| SP-06 | Medium | A04, A07 | Sessions last 72 hours and logout does not cancel them |
| SP-07 | Medium | A02 Misconfiguration | No security headers |
| SP-11 | Medium | A03, A08 | A script loads from a CDN with no integrity check |
| SP-14 | Medium | A06 Insecure Design | Per-user limits are bypassed by new names; one user can use up the shared daily budget |
| SP-16 | Medium | A05, A06 | Prompt injection can misuse the tools; no human approval step |
| SP-17 | Medium | A09 Logging | Failed logins and limit hits are not logged; nothing raises an alert |
| SP-08 | Low | A02 | `/openapi.json` is public |
| SP-09 | Low | A02 | `/health` shows internals without sign-in |
| SP-10 | Low | A01 | The cron secret is compared in a way that is not constant-time |
| SP-12 | Low | A03 | Indirect dependencies are not pinned; `pytest` ships to production |
| SP-13 | Low | A03 | CI actions are pinned by tag; no Dependabot |
| SP-15 | Low | A07 | Look-alike names count as different users |
| SP-18 | Low | A08 | The `railway up` deploy route skips the CI gate |
| SP-19 | Low | A10 | A failed log insert can break a reply and lose its run record |
| SP-20 | Low | A10 | A failed digest webhook returns a 500 |
| SP-21 | Low | A10 | Upstream and tool error text reaches users and the model |
| SP-22 | Low | A05 | Some invoice fields are not escaped in the invoices panel |
| SP-23 | Low | A01 | Every signed-in user sees all invoices and the global spend |
| SP-24 | Low | A06 | Old conversations are not deleted automatically |
| SP-25 | Info | A04 | Conversations are stored as plain text |
| SP-26 | Info | A05 | `%` and `_` typed in a search are treated as wildcards |
| SP-27 | Info | A05 | Startup migration builds SQL from fixed names with f-strings |

---

## A01 Broken Access Control

**Already defended.** Every `/api/*` route needs the session cookie. Reading or continuing a conversation checks that you own it and answers 404 for someone else's (`app/main.py` `list_messages`, `chat`). `POST /internal/digest` needs `X-Cron-Secret` (401 without it). Path traversal out of `/static` returns 404.

### SP-04 One shared password; anyone can sign in as any name (High)
- **Where:** `app/auth.py:25` (`password_ok`), `app/auth.py:64` (`get_or_create_user`), `app/main.py:103` (`login`).
- **Problem:** identity is only the typed name. Anyone who knows the team password can type another person's name and read that person's conversations.
- **Fix:** give each person their own password or one-time sign-in link, or keep conversations free of anything private and record this as an accepted risk in `architecture.md`.
- [ ] fixed

### SP-10 Cron secret compared with `!=` (Low)
- **Where:** `app/main.py:199`.
- **Problem:** a plain string comparison can leak the secret's length and content through timing.
- **Fix:** use `hmac.compare_digest`, as `app/auth.py` already does for the password.
- [x] fixed on the security-fixes branch; see SecuritySolutions.md (SP-10)

### SP-23 Everyone sees all invoices and the global spend (Low)
- **Where:** `app/main.py:183` (`/api/invoices`), `app/main.py:190` (`/api/stats`).
- **Problem:** any signed-in user can read every invoice and the day's total spend. This suits a small team but is not per person.
- **Fix:** accept and document it, or filter by role once there are real accounts.
- [ ] fixed

## A02 Security Misconfiguration

**Already defended.** The session cookie is `HttpOnly`, `SameSite=Lax` and, in production, `Secure`. There is no CORS, so other origins get no permission. The interactive docs are off. Production refuses to start without `APP_PASSWORD`, `APP_SECRET` and `ANTHROPIC_API_KEY`. The Railway database has no public address.

### SP-07 No security headers (Medium)
- **Where:** `app/main.py` (no middleware sets any).
- **Problem:** the app sends none of `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` or `Strict-Transport-Security`. The page can be framed by another site, and nothing limits what scripts may run (which makes SP-01 worse).
- **Fix:** add the headers in one place. Start with a strict `Content-Security-Policy` (`default-src 'self'`, no inline scripts), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and HSTS. Do not use a middleware that wraps the streaming chat response without testing disconnects (see SP-19).
- [x] fixed on the security-fixes branch; see SecuritySolutions.md (SP-07)

### SP-08 `/openapi.json` is public (Low)
- **Where:** `app/main.py:47` (`docs_url=None, redoc_url=None` but `openapi_url` is left on).
- **Problem:** it lists every endpoint and field to anyone.
- **Fix:** pass `openapi_url=None`.
- [x] fixed on the security-fixes branch; see SecuritySolutions.md (SP-08)

### SP-09 `/health` shows internals without sign-in (Low)
- **Where:** `app/main.py:81`.
- **Problem:** it returns the environment name, model, provider and database type.
- **Fix:** return only `{"status": "ok"}` publicly; keep the detail in the deploy log. Railway only needs the status code.
- [x] fixed on the security-fixes branch; see SecuritySolutions.md (SP-09)

### SP-05 No password rules; defaults fail open (Medium)
- **Where:** `app/config.py:93` (`APP_ENV` defaults to `local`), `app/config.py:112` (`app_password or "bakery"`), `app/config.py:113` (random secret if missing).
- **Problem:** if `APP_ENV` is ever missing in production, the app starts silently with the password `bakery`. Any password, however short, is accepted at setup.
- **Fix:** treat a missing `APP_ENV` as production, allow the `bakery` fallback only when `APP_ENV=local` is set on purpose, and require at least 16 characters for the password in production at startup.
- [x] fixed on the security-fixes branch; see SecuritySolutions.md (SP-05)

## A03 Software Supply Chain Failures

**Already defended.** The direct packages in `requirements.txt` are pinned exactly. `pip-audit` found no known vulnerabilities (2026-11-23). The font is served from this repo, not a third party. No secrets were ever committed.

### SP-11 A CDN script with no integrity check (Medium)
- **Where:** `static/index.html:8` (`marked` 12.0.2 from `cdnjs.cloudflare.com`).
- **Problem:** if that CDN or the file were tampered with, attacker code would run in every user's session.
- **Fix:** copy `marked.min.js` into `static/` and load it from there, or add `integrity="sha384-…"` and `crossorigin="anonymous"`.
- [x] fixed on the security-fixes branch; see SecuritySolutions.md (SP-11)

### SP-12 Indirect dependencies are not pinned; `pytest` ships to production (Low)
- **Where:** `requirements.txt` (only direct packages; `pytest==9.1.1` on line 9).
- **Problem:** packages such as `starlette` and `pydantic` float to the newest version at each build, so builds are not reproducible and a bad release is picked up automatically. A test tool is installed in the production image.
- **Fix:** keep a lock file with hashes (`pip install --require-hashes`) and move `pytest` to a separate `requirements-dev.txt`.
- [ ] fixed

### SP-13 CI actions pinned by tag; no Dependabot (Low)
- **Where:** `.github/workflows/ci.yml:13`, `:14`, `:34`, `:35` (`actions/checkout@v4`, `actions/setup-python@v5`).
- **Problem:** a tag can be moved to different code.
- **Fix:** pin each action to a full commit hash and enable Dependabot for `pip` and `github-actions`.
- [ ] fixed

## A04 Cryptographic Failures

**Already defended.** The session cookie is signed with HMAC-SHA256 (`app/auth.py:36`), checked in constant time, and expires. The password is compared in constant time. Invoice photos are never stored. In production, the cookie is only sent over HTTPS.

### SP-06 Sessions last 72 hours and logout does not cancel them (Medium)
- **Where:** `app/main.py:113` (`logout` only deletes the cookie), `app/auth.py:42` and `:48` (`make_token`, `read_token`), `app/config.py:127` (`SESSION_HOURS` 72).
- **Problem:** a copied cookie keeps working until it expires, even after the user logs out. Changing `APP_SECRET` is the only way to cancel all sessions.
- **Fix:** keep sessions in a database table that can be revoked on logout, or shorten the lifetime to a few hours.
- [ ] fixed

### SP-25 Conversations are stored as plain text (Info)
- **Where:** the `messages` and `conversations` tables in `app/db.py`.
- **Problem:** protection at rest depends on the hosting provider's database encryption.
- **Fix:** confirm the provider encrypts the volume; avoid storing anything sensitive in chats.
- [ ] checked

## A05 Injection

**Already defended.** All database access goes through SQLAlchemy with bound parameters. The `sales_query` tool never takes SQL from the model; its metric and grouping come from fixed lists (`app/tools/sales.py:16-17`). There is no `eval`, `exec`, `pickle` or shell call in the app. User-typed text and conversation titles are escaped before display.

### SP-01 Unsanitised HTML in the bot's reply (High)
- **Where:** `static/app.js:17-19` (`render`, uses `marked`), `:145`, `:148`, `:152` (the reply is assigned to `innerHTML`), `static/index.html:8`.
- **Problem:** the reply is turned from Markdown into HTML and inserted as is. HTML in a reply, including an event handler, runs as script in the page. This was reproduced on a local copy. The reply comes from the model, so the realistic route is prompt injection, for example hostile text inside an invoice photo. The script then runs in a staff member's browser and can call the API as them. The session cookie is `HttpOnly`, so it cannot be read.
- **Fix, in order:** (1) a strict Content-Security-Policy that blocks inline scripts (SP-07); (2) sanitise the output with a maintained sanitiser (a new dependency, so agree it first) or stop `marked` from passing raw HTML through; (3) never insert replies with `innerHTML` without sanitising. Add a test that a reply containing HTML is shown as text.
- [x] fixed on the security-fixes branch; see SecuritySolutions.md (SP-01)

### SP-22 Some invoice fields are not escaped (Low)
- **Where:** `static/app.js:163` (`invoice_date`, `amount`, `currency`, `status` are inserted unescaped; supplier and invoice number are escaped).
- **Problem:** the model fills `currency` (cut to three characters) and a future change could widen these fields.
- **Fix:** run every field through `escapeHtml`, or build the table with `textContent`.
- [x] fixed on the security-fixes branch; see SecuritySolutions.md (SP-22)

### SP-16 Prompt injection can misuse the tools (Medium)
- **Where:** `app/tools/registry.py` (the tool definitions and `execute`), `app/tools/invoices.py:50-85` (`log_invoice`).
- **Problem:** text in a user message or an invoice image can steer the model into calling `log_invoice` with false data. The damage is limited (it can only add invoices, duplicates are blocked, amounts over ₪5,000 are flagged), but no person approves a new row.
- **Fix:** keep the tools write-only for new rows, add a "needs confirmation" status for rows from images, show who logged each row, and cap how many invoices one user can log per hour.
- [ ] fixed

### SP-26 `%` and `_` in a search are wildcards (Info)
- **Where:** `app/tools/invoices.py:92` and `:96`, `app/tools/sales.py:64-68`.
- **Problem:** the values are bound parameters, so there is no injection, but a typed `%` matches everything.
- **Fix:** escape `%` and `_` with `like(..., escape="\\")` if exact matching matters.
- [ ] fixed

### SP-27 Startup migration builds SQL with f-strings (Info)
- **Where:** `app/db.py:206` and `:215`.
- **Problem:** the table names come from a fixed tuple, so it is safe today, but it would become injectable if that tuple ever took outside input.
- **Fix:** keep the names hard-coded, or check them against `Base.metadata.tables`.
- [ ] fixed

## A06 Insecure Design

**Already defended.** Three limits exist: 30 messages per user per hour, a $3 daily cap and a 5 MB image limit (`app/limits.py`). The model can read sales and add invoices but cannot delete or edit anything, and the model loop is capped at six tool rounds (`app/agent.py:39`).

### SP-02 No limit on login attempts (High)
- **Where:** `app/main.py:103` (`login`).
- **Problem:** wrong passwords are answered at full speed with no delay or lockout (40 attempts in about 0.1 second were all answered). With one shared password as the only gate, this is the most direct way in.
- **Fix:** count failed attempts per client address and per name, add a growing delay or a temporary block, and log each failure (SP-17). A long passphrase (SP-05) makes guessing impractical.
- [x] fixed on the security-fixes branch; see SecuritySolutions.md (SP-02)

### SP-03 Large requests are read before sign-in (High)
- **Where:** `app/main.py:60-65` (`ImageIn.data` has no `max_length`), `app/main.py:148-155` (`chat`), `app/limits.py:49` (`check_upload_size` runs after the body is parsed).
- **Problem:** FastAPI reads and validates the whole JSON body before the sign-in check runs. An unauthenticated caller can send very large bodies and use up memory. An 8 MB body was read and parsed before the 401 came back.
- **Fix:** reject oversized requests early by checking `Content-Length` (and the real size while reading), put a `max_length` on the image field of about `max_upload_mb * 4/3`, and move the sign-in check ahead of body parsing, for example as a dependency on the route.
- [x] fixed on the security-fixes branch; see SecuritySolutions.md (SP-03)

### SP-14 Per-user limits can be bypassed; one user can use up the shared budget (Medium)
- **Where:** `app/limits.py:37-47`, `app/auth.py:64` (a new name creates a new user).
- **Problem:** each new typed name gets a fresh 30-message budget, so only the global $3 cap really stops abuse. That cap is shared, so one person can use it up for everyone.
- **Fix:** also limit per client address, add a per-user daily spend limit, and limit how many new names can be created per hour.
- [ ] fixed

### SP-24 Old conversations are not deleted automatically (Low)
- **Where:** `spec.md` (90-day retention, "manual purge in v1").
- **Problem:** data is kept longer than stated unless someone remembers to purge it.
- **Fix:** add a scheduled purge for conversations, messages and log rows older than 90 days.
- [ ] fixed

## A07 Authentication Failures

**Already defended.** The password check is constant-time. A new signed token is issued at each login, and it carries an expiry that is checked on every request. A bad, unsigned or tampered token is rejected (fails closed).

The shared-password problems are listed under SP-02 (no attempt limit), SP-04 (one password for everyone), SP-05 (no password rules) and SP-06 (sessions are not revocable).

### SP-15 Look-alike names count as different users (Low)
- **Where:** `app/auth.py:22` (`_NAME_RE` allows Latin, digits and Hebrew letters), `app/auth.py:29` (`normalise_name`).
- **Problem:** "Dana" and "dana", or a name with a look-alike Hebrew or Latin letter, are separate users. This helps impersonation.
- **Fix:** compare names case-insensitively, normalise Unicode (NFKC), and reject names that mix alphabets.
- [ ] fixed

## A08 Software or Data Integrity Failures

**Already defended.** The cookie cannot be changed without the secret. The app uses JSON only, with no `pickle` or unsigned downloads. The seed data comes from files in the repo. Invoice fields are cleaned before saving (positive amount, three-letter currency, valid date).

### SP-18 The `railway up` route skips the CI gate (Low)
- **Where:** `docs/deploy-railway.md` and the deploy history: `railway up` uploads whatever is on the developer's disk.
- **Problem:** nothing forces the tests to pass, or the code to be reviewed, before it goes live.
- **Fix:** deploy from GitHub after CI is green, or run `pytest` as a required step before every upload.
- [ ] fixed

The unchecked CDN script is SP-11.

## A09 Security Logging and Alerting Failures

**Already defended.** The `runs` table records every model call with its status, cost and any error. Each invoice records who logged it. The `conversations` table is a readable audit trail with the name and times. The morning digest reports runs that were not OK.

### SP-17 Failed logins and limit hits are not logged; no alerts (Medium)
- **Where:** `app/main.py:103-110` (`login`), `app/limits.py:37-47` (rate-limit and cap responses).
- **Problem:** a guessing attack would leave no trace, and hitting a limit is not recorded. The only output is one startup line and the web server's access log, which shows Railway's proxy address, not the visitor's. The digest runs once a day and its webhook is not set.
- **Fix:** log every failed login (time, client address from the forwarded header, name tried; never the password), log limit hits, and send an alert to the digest webhook when failures or errors pass a threshold.
- [ ] partly fixed: failed, throttled and limit-hit events are now logged (SecuritySolutions.md, SP-17); the alert is still open

## A10 Mishandling of Exceptional Conditions

**Already defended.** A failing model turn becomes an error row and a friendly message, and the database is rolled back (`app/agent.py:324`). A dropped connection leaves no half-saved reply, and a test covers it. An unreadable token returns nothing. Bad configuration stops startup. Errors do not show stack traces.

### SP-19 A failed log insert can break a reply (Low)
- **Where:** `app/agent.py:247-262` (`finish_run`, the `conversations` insert at `:257`) and `:324` (the error handler calls `finish_run` again).
- **Problem:** the `conversations` log insert runs inside the code that saves a turn. If it ever fails, the error escapes, the stream breaks, and the run record is lost.
- **Fix:** wrap the log insert in its own try-block (or a savepoint) so logging can never block a reply or the run record.
- [x] fixed on the security-fixes branch; see SecuritySolutions.md (SP-19)

### SP-20 A failed digest webhook returns a 500 (Low)
- **Where:** `app/digest.py:60-61` (`httpx.post` and `raise_for_status`), `app/main.py` (`/internal/digest`).
- **Problem:** a webhook error is not caught, so the endpoint and the cron run end with an error instead of reporting "built but not sent".
- **Fix:** catch the error, log it, and return `{"sent": false}`.
- [ ] fixed

### SP-21 Upstream and tool error text reaches users and the model (Low)
- **Where:** `app/agent.py:199-200` (`_friendly` returns the upstream message for a rejected request), `app/tools/registry.py:88-89` (exception text is returned to the model).
- **Problem:** internal detail can be repeated to users.
- **Fix:** show a generic message to users and log the detail.
- [ ] fixed

---

## Suggested order of work

1. SP-07 then SP-01: security headers with a strict Content-Security-Policy, then sanitise the reply output.
2. SP-02, SP-05 and SP-17: limit and log login attempts, and require a long password.
3. SP-03: cap request size before sign-in.
4. SP-11, SP-08, SP-09 and SP-10: self-host `marked`, hide `/openapi.json`, trim `/health`, constant-time secret check.
5. SP-04, SP-06 and SP-14: the larger design changes (per-person sign-in, revocable sessions, per-address limits).
6. Everything else as time allows.

Each fix should follow `practice.md`: a failing test first, a branch and pull request, and an `architecture.md` update when a decision changes.
