# CLAUDE.md — Dorm Inventory System

## What this project is
A Flask barcode inventory app: log items and boxes with generated barcodes, scan items into boxes, look items up later by scan or search, and eventually share it with other people under their own accounts.

Read `SPEC.md` in this same directory before making any changes — it's the source of truth for data model, routes, and flows. This file is conventions only; `SPEC.md` is what to build.

## Tech stack
- **Backend:** Flask (Python), no other web framework
- **Database:** Postgres via `psycopg2`, connecting through the `DATABASE_URL` environment variable (no default/fallback — the app raises clearly if it's unset). All SQL lives in `db.py`; route code in `app.py` never touches SQL directly.
- **Barcodes:** `python-barcode` (Code128), `reportlab` for the printable label PDF sheet — both already used in the existing scaffold, keep using them rather than swapping libraries.
- **Auth:** Flask's built-in `session`, `werkzeug.security.generate_password_hash` / `check_password_hash`. No JWTs, no third-party auth libraries — this is a small personal-scale app.
- **Frontend:** server-rendered Jinja templates + vanilla JS for scan-input handling (no React/build step) — matches the existing scaffold's `templates/` structure.

## Existing code to build on, not replace
This repo already has a working scaffold: `app.py`, `print_service.py`, `templates/`, `static/style.css`. Extend it — don't restructure into a different framework or folder layout without a clear reason tied to something in `SPEC.md`.

`print_service.py` is intentionally stubbed (no physical printer connected yet). Don't try to "finish" it by wiring in real printer code — leave the stub and its commented-out real implementation as-is unless `SPEC.md` says otherwise.

## Conventions
- Barcodes: `ITM######` for items, `BOX######` for boxes, zero-padded to 6 digits, sequential per user (not globally).
- Never store a password in plain text, ever, even temporarily in a log or print statement beyond the one-time creation display.
- Every query that touches `items`, `boxes`, `categories`, or `activity_log` must be scoped to the logged-in user's `user_id` — this is a hard rule, not a nice-to-have. When in doubt, add the filter.
- Every mutating action (add/pack/unpack/delete/category change) writes an `activity_log` row in the same request, not asynchronously.
- Keep routes thin — validation and business logic can live in route functions for now (this is a small app), but don't duplicate the same query logic across multiple routes; factor repeated queries into helper functions.

## Testing expectations
After implementing each flow in `SPEC.md`, verify it with Flask's test client (`app.test_client()`) before moving to the next flow — don't wait until the whole app is built to test. The original scaffold was verified this way (add item → add box → pack → lookup states → detail pages); follow the same pattern for new flows (auth, admin, categories, delete, unpack, export).

## Explicitly out of scope for this build
- Wiring `print_service.py` to a real printer (no printer owned yet)
- Deploying to Render/Supabase/etc. (Postgres itself is in use locally via `DATABASE_URL`, but hosting/deployment is still a separate step)
- Self-service signup — accounts are always admin-created
