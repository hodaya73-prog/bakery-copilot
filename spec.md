# spec.md — Bakery Copilot

A chat app for one bakery chain: staff ask about sales and log supplier invoices by sending a photo. The same four layers as the chat products they use every day (UI, backend, model, database), small enough to understand and to run for a few dollars a month.

## 1. Users

- Dana (owner) and three staff. Ten people at most.
- From phones in the shops and the office laptop. Hebrew and English.
- Access: one shared team password plus a typed name. Not a public app. Not multi-tenant.

## 2. Jobs

1. **Answer a sales question** from the sales database: best sellers, revenue by branch or period, item counts, trends. Every number comes from the data, never from memory.
2. **Log an invoice** from a photo or typed details: supplier, number, amount, date. One invoice becomes one row. An unreadable amount is never guessed.
3. **Keep every conversation** so a user can come back to it.
4. **Send a morning digest**: yesterday's invoices, what needs a look, chat spend.

## 3. Not in v1

Multi-tenant. Public sign-up. Payments or bank actions. Editing or deleting invoices from the chat. Mobile app. Voice. Exporting reports. Anything that writes to the sales data.

## 4. Speed, per job

| Job | Answer | Mechanism |
|---|---|---|
| Chat reply | starts within 2 s, streams | server-sent events from the backend |
| Invoice from a photo | within one turn (seconds) | same turn; the model reads the image and calls the tool |
| Morning digest | by 07:45 | scheduled job, no one waits |

## 5. Data

- **Kept**: users (name only), chats and messages (text; images are not stored), a readable `conversations` log (one row per question: name, message, time entered, time reply sent), invoices, one run record per model turn (tokens, cost, tools, status), the sales dataset (read-only, 29,115 lines).
- **Retention**: conversations 90 days (manual purge in v1). Runs kept for the digest and the bill.
- **Sensitive**: supplier names and amounts are business data; the team password and the API key are secrets and live only in Variables.

## 6. Limits

- Per user: 30 messages per hour. Images under 5 MB.
- Per app: $3.00 of model spend per local day; past that the chat says "back tomorrow".
- Invoices over ₪5,000 are logged and flagged for Dana; nothing is paid or acted on.
- History resent per turn: last 20 messages.

## 7. Done — twelve checks a stranger can run

1. Open the URL, enter a name and the password, see an empty chat.
2. Wrong password is refused.
3. "What sold best in the last week of August 2026?" streams an answer that names a product and the dates used, after a visible `sales_query` call.
4. "Revenue by branch for August 2026" gives one number per branch.
5. Attach a clear invoice photo: one row appears under Invoices with status *logged*.
6. Attach the same photo again: still one row; the reply says it already exists.
7. Attach a photo with an unreadable total: a row with status *needs a look* and no amount.
8. An invoice over ₪5,000 shows the *flag* badge.
9. "Delete all invoices from March" is refused, with a pointer to Dana.
10. The 31st message within an hour is refused with a clear message.
11. `/health` returns 200 on the deployed URL; the morning digest arrives on the webhook.
12. `pytest` is green, and `python -m evals.run` passes at least 80% of the cases (CI's `--baseline 0.8`).
