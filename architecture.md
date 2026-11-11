# architecture.md — Bakery Copilot

The drawing, where each box runs, the limits, and every decision with its reason. Keep it current in the same commit as the change.

## Components

```
 Browser (UI)            Backend (FastAPI, one service)              Anthropic
 static/index.html  --->  /api/chat  --> agent loop --------------->  Claude API
 app.js, styles.css <---  SSE stream <-- text + tool events          (model, per token)
                             |        \
                             |         tools: sales_query · lookup_supplier · log_invoice
                             v
                          Postgres (Railway plugin)  <---  cron service: python -m app.digest (07:30)
                          users · conversations · messages · runs · invoices · suppliers · sales
```

Four layers, one external dependency. Everything on the left and in the middle is ours and runs on Railway; the model is rented per token.

## Flows

- **Chat turn.** UI posts `{conversation_id, message, image?}` → auth cookie checked → three limits checked → user message saved → system prompt (with today's date, the data range and the branch names, all read from the data) + last 20 messages + current message → model stream. Text deltas are forwarded to the UI as they arrive. If the model asks for a tool, the backend runs it, appends the result, and calls the model again (max 6 rounds). At the end: one assistant message, one `runs` row with tokens and cost. A dropped connection saves no partial assistant message; the run is marked `aborted`.
- **Invoice.** The image travels inside the same turn as a content block plus an `image reference` string. The model calls `lookup_supplier`, then `log_invoice` with `source_ref` = that reference. The tool, not the prompt, enforces: duplicate → existing row; unreadable amount → `needs_a_look`; over ₪5,000 → `flagged`.
- **Digest.** The cron service runs `app/digest.py`: reads yesterday's invoices and runs, prints six lines, POSTs them to `DIGEST_WEBHOOK_URL` if set. `POST /internal/digest` with `X-Cron-Secret` does the same by hand.

## Storage

Postgres on Railway (`DATABASE_URL` from the plugin); SQLite locally and in tests. Tables and their keys:

| Table | Key | Notes |
|---|---|---|
| users | name (unique) | typed at login; no passwords per user |
| conversations | id | belongs to one user; title = first message |
| messages | id | role, text only; `has_image` flag; image bytes are never stored |
| runs | id | one per model turn: tokens, cost_usd, tool_calls, status, duration |
| invoices | `source_ref` (unique) · (supplier, invoice_number) | the dedup keys; status logged / needs_a_look; flagged |
| suppliers | id | seeded from data/suppliers.csv |
| sales | id | seeded from data/bakery_sales.csv; read-only through `sales_query` |
| schema_version | version | 1; created with `create_all` at start |
| conversations_with_user | (view) | `conversations` plus `user_name`, right after `user_id`; for people reading the database (Railway's Data tab, psql); nothing in the app reads it; dropped and recreated at every start by `init_db` |

## Model

`claude-opus-5-5`, effort `medium`, max 2,048 output tokens, adaptive thinking (the model's default). Server-side fallbacks on (`fallbacks: "default"`), so a safety refusal on the primary model is retried on a substitute before we show the user anything. System prompt cached (`cache_control`), tools first and stable so the prefix stays cacheable. Change the model or effort in Variables, not in code; run the evals after.

## Limits

| Layer | Number | Where enforced |
|---|---|---|
| Users → us | 30 messages per user per hour; images ≤ 5 MB | `app/limits.py`, before the model is called |
| Us → model | SDK retries with backoff on 429/529 (2 retries) | Anthropic SDK client |
| Us → wallet | $3.00 per local day across the app | `app/limits.py` from the `runs` table |
| Tool loop | max 6 model rounds per turn; tool results truncated at 12,000 chars | `app/agent.py` |

## Hosting

One Railway project, three things in it: the **web service**, built by Railway's default Railpack builder straight from `requirements.txt` with the Python version in `.python-version` (no Dockerfile), the **Postgres plugin**, and the **digest cron service** from the same repo (start command `python -m app.digest`, schedule `30 4 * * *`; Railway cron is UTC, so that is 07:30 Israel in summer and 06:30 in winter). All three are described in one file, `.railway/railway.ts` (Railway's Infrastructure as Code): start commands, the `/health` check, restart policies and the cron schedule. Railway does not read that file at deploy time; `railway config plan` shows the drift between the file and the project, and `railway config apply` applies it. The file does not manage variables: secrets live only in the Variables tab. The npm package under `.railway/` exists only so the CLI can evaluate the file, and it stays out of the repo root so Railpack keeps seeing a Python project. Deploy on push to `main`. Expected hosting cost: $4 to $6 a month (see README); the model bill is separate.

## Secrets

`ANTHROPIC_API_KEY`, `APP_PASSWORD`, `APP_SECRET`, `DATABASE_URL`, `CRON_SECRET`, `DIGEST_WEBHOOK_URL`. Locally in `.env` (gitignored); on Railway in the service's Variables tab, shared with the cron service through a reference variable. `.env.example` lists the names with no values. The grep test in practice.md must come back empty on every commit.

## Observability

- Railway logs per service (requests, errors, startup seed report).
- `runs` table: every model turn with status (`ok`, `refusal`, `error`, `aborted`), tokens and cost. The digest reads it.
- `GET /api/stats`: spend today vs cap, messages this hour.
- `evals/history.csv`: pass rate per run, per git sha, with tokens and cost.

## Decisions

| Date | Decision | Reason | Would change it if |
|---|---|---|---|
| 2026-10-17 | One service serves UI and API | Ten users; a CDN or a second service is cost and a second deploy for nothing | Traffic from the public web, or a separate frontend team |
| 2026-10-17 | Postgres over Airtable | Chat history grows fast; Airtable's record cap and rate limit would be hit within weeks | Non-developers must edit rows by hand daily |
| 2026-10-17 | Structured `sales_query` tool, no SQL from the model | Least access: the model cannot read or change anything but sales; testable | A genuine need for ad-hoc analysis the parameters cannot express |
| 2026-10-17 | Images not stored | Cheaper, smaller database, fewer privacy questions; the row is the record | A requirement to show the original invoice later |
| 2026-10-17 | Shared password + typed name, not accounts | One business, ten people, no admin; per-user limits still work | A second client, or a client who wants per-person access control |
| 2026-10-17 | `create_all` + schema_version, no migration tool yet | Schema v1 has no history to migrate; keep the dependency list short | The first schema change after production data exists → add Alembic |
| 2026-10-17 | Digest as a Railway cron service, not an external pinger | Same repo, same variables, runs for seconds, costs cents | Railway removes cron, or the digest needs to run in several regions |
| 2026-10-27 | Railpack build, no Dockerfile | The Dockerfile only pinned Python and ran pip; Railway's default builder does the same from `requirements.txt` and `.python-version`, one file less to keep current | A system package (apt) or a multi-stage build is needed, or Railway drops Railpack |
| 2026-10-27 | Infrastructure as Code (`.railway/railway.ts`) instead of `railway.json` | Railway deprecated config-as-code files (they stop working on 2026-12-01); one IaC file describes both services, so the cron service needs no config path of its own | Railway changes the IaC format again, or a setting the DSL cannot express |
| 2026-11-04 | Chat history is resent as text only; the system prompt says earlier replies were tool-checked and must not be re-checked or retracted unasked | The first live chats showed the model, seeing its old figures without the tool calls behind them, re-running tools on unrelated turns and telling users their searches "never ran" (issue #2). A prompt rule fixes it with no schema change | The eval `no_recheck_after_off_topic` regresses → store a compact tool trace per message and replay it (a schema change, so add Alembic first) |
| 2026-11-11 | A view `conversations_with_user`, not a `user_name` column on `conversations` | The name already lives in `users`; a view shows it next to `user_id` with no copied data and no table change, so the `create_all` decision above still holds and Alembic is not needed yet | A column is wanted for an app query or an index, or a tool that cannot show views → add the column with Alembic |
| 2026-10-28 | Public repository, history restarted as one commit | No secrets live in the code (they are in Variables) and the dataset is mock data; a fresh history keeps the owner's personal email out, and the old private repo is kept as `bakery-copilot-archive` | Real client data or client-specific configuration has to be committed |
