# SPEC.md — Dorm Inventory System

Read `CLAUDE.md` first for conventions. This file is what to build.

## Goal
Extend the existing Flask scaffold (`app.py`, `print_service.py`, `templates/`) to add: user accounts (admin-created only), categories, box packing/unpacking, item deletion, an admin panel, an activity log, and CSV/PDF export.

## Out of scope
- Real printer integration (`print_service.py` stays stubbed)
- Production deployment / Postgres migration
- Self-service account signup

---

## Data model

### `users`
- `id` integer PK
- `username` text unique
- `password_hash` text
- `is_admin` boolean
- `date_created` date

### `categories`
- `id` integer PK
- `user_id` FK → users
- `name` text
- Unique constraint on (`user_id`, `name`) — no duplicate category names within one user's account

### `items`
- `id` integer PK
- `user_id` FK → users
- `barcode` text, unique per user, format `ITM######`
- `name` text
- `category_id` FK → categories, nullable (null = "Uncategorized")
- `status` text, enum: `not_packed` | `packed`
- `box_id` FK → boxes, nullable
- `photo_path` text, nullable
- `date_added` date

### `boxes`
- `id` integer PK
- `user_id` FK → users
- `barcode` text, unique per user, format `BOX######`
- `number` text (e.g. "Box 04")
- `category_id` FK → categories, nullable
- `date_created` date

### `activity_log`
- `id` integer PK
- `user_id` FK → users (whose inventory this happened in — even if admin performed it)
- `action` text, enum: `item_added` | `box_added` | `item_packed` | `item_unpacked` | `item_deleted` | `box_deleted` | `category_created` | `category_deleted`
- `target_barcode` text, nullable (barcode no longer resolvable after a delete, but the string is kept)
- `detail` text — short human-readable description
- `performed_by_user_id` FK → users, nullable — set when an admin acted on someone else's behalf; null when the account owner did it themselves
- `timestamp` datetime

---

## Routes / interfaces

### Auth
- `GET/POST /login` — username + password form
- `GET /logout`
- `GET/POST /account` — change own password (requires login)
- CLI command: `flask create-user <username>` — generates account + random password (two words + number + special character), prints it once, hashes and stores it

### Items
- `GET /` — scan/lookup page
- `GET /api/lookup/<barcode>` — JSON: `not_in_inventory` | item with `status: not_packed` | item with `status: packed` + box info
- `GET/POST /add` — add item (name, category, photo)
- `GET /item/<barcode>` — item detail
- `POST /item/<barcode>/delete` — permanent delete, logs `item_deleted`
- `GET /inventory` — search/browse, filterable by name/category/status/box, each row has Reprint + Delete actions

### Boxes
- `GET/POST /add_box` — add box (number, category)
- `GET /box/<barcode>` — box detail + contents list
- `GET /boxes` — all boxes

### Categories
- `GET/POST /categories` — list + create
- `POST /categories/<id>/rename`
- `POST /categories/<id>/delete` — auto-reassigns affected items/boxes' `category_id` to null ("Uncategorized"), logs `category_deleted`

### Packing
- `POST /api/pack` — body: `{item_barcode, box_barcode}`. Sets item's `box_id`, `status` → `packed`, logs `item_packed`
- `POST /api/unpack` — body: `{item_barcode}`. Clears `box_id`, `status` → `not_packed`, logs `item_unpacked`
- UI flow for pack: scan item → tap "Box" button → scan box → calls `/api/pack`
- UI flow for unpack: scan box → open its contents → find/scan the item within it → calls `/api/unpack`

### Labels
- `GET /labels` — select items/boxes to print
- `POST /labels/generate` — PDF, Avery 5160 layout (3×10), name above barcode image, code printed under the barcode (already implemented — extend, don't rewrite)

### Records
- `GET /activity` — activity log for the logged-in user (or, for admin viewing another account, that account's log)
- `GET /export` — CSV or PDF of full inventory: name, category, barcode, status, box, date added

### Admin
- `GET /admin/users` — list all accounts (admin only)
- `POST /admin/users/create` — creates account, generates password, returns/displays it once
- `GET /admin/users/<id>` — that user's inventory, viewed the same as their own screens
- Admin actions taken from this view (pack/unpack/delete) call the same routes as normal, but set `performed_by_user_id` on the resulting `activity_log` row to the admin's own `id`

---

## Flow details

**Add item:** name + category (existing or new, created inline) + photo (browser camera capture, not just file upload) → generate `ITM######` barcode → insert with `status = not_packed` → log `item_added`.

**Add box:** number + category → generate `BOX######` barcode → log `box_added`.

**Pack:** scan item, tap "Box", scan box → `/api/pack` → log `item_packed` with which box in `detail`.

**Unpack:** scan box → shows contents → find/scan item within it → `/api/unpack` → item stays in inventory, `status` reverts → log `item_unpacked`.

**Delete item:** search or scan → confirm → permanently removed → log `item_deleted` (row persists in `activity_log` after the item itself is gone).

**Delete box:** any items with that `box_id` get `box_id = null`, `status = not_packed` automatically, in the same transaction as the box delete → log `box_deleted` with a count of how many items were auto-unpacked.

**Scan/lookup display order:** photo, name, category, status (+ box if packed), barcode. Unknown barcode → explicit "not found" state, not a blank or broken result.

**Unknown barcode scanned anywhere (pack, unpack, lookup):** show a clear "not recognized" message rather than failing silently.

---

## Verification

Implement and verify each of these in order, using `app.test_client()` — don't move to the next until the current one passes:

1. `flask create-user testuser` creates an account; password is shown once and is not recoverable afterward; login with it works.
2. Add a category, add an item under it, add a box under it — all three appear correctly scoped to that user only.
3. A second user account cannot see the first user's items/boxes/categories via any route.
4. Pack flow: scan item → Box button → scan box → item shows `packed` status with correct box on lookup.
5. Unpack flow: item returns to `not_packed`, still exists in inventory.
6. Delete item: gone from inventory, but an `item_deleted` row exists in `activity_log`.
7. Delete box with items still in it: those items auto-revert to `not_packed`; `box_deleted` log entry notes the count.
8. Delete a category in use: affected items/boxes fall back to null/"Uncategorized" rather than erroring.
9. Scan an unrecognized barcode at the lookup page: get the explicit "not found" state, not a 500 or blank page.
10. Admin logs in, opens `/admin/users`, drills into a user, packs an item on their behalf: `activity_log` row has `user_id` = that user, `performed_by_user_id` = admin.
11. `/export` produces a CSV/PDF containing every item with correct status and box.
12. `/labels/generate` still produces a correct PDF sheet after all the above changes (regression check on existing functionality).
