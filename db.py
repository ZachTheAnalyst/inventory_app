"""
Thin data-access layer. All SQL lives here so route code in app.py never
touches SQL directly. Connects to Postgres using the DATABASE_URL
environment variable.
"""

import os

import psycopg2
import psycopg2.extras


class _PGConnection:
    """Wraps a psycopg2 connection so the query functions below can call
    conn.execute(query, params) and get a cursor back, matching the
    convenience style sqlite3.Connection used to provide (psycopg2 has no
    such shortcut -- it requires an explicit cursor)."""

    def __init__(self, dsn):
        self._conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, query, params=()):
        cur = self._conn.cursor()
        cur.execute(query, params)
        return cur

    def executescript(self, script):
        cur = self._conn.cursor()
        cur.execute(script)
        cur.close()

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_connection(dsn=None):
    """Connects to Postgres using `dsn`, or the DATABASE_URL environment
    variable if `dsn` isn't given (a standard postgres:// / postgresql://
    connection string)."""
    dsn = dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set -- point it at a "
            "postgres:// connection string before starting the app."
        )
    return _PGConnection(dsn)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    date_created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS boxes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    barcode TEXT NOT NULL,
    number TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    date_created TEXT NOT NULL,
    UNIQUE(user_id, barcode)
);

CREATE TABLE IF NOT EXISTS items (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    barcode TEXT NOT NULL,
    name TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'not_packed',
    box_id INTEGER REFERENCES boxes(id) ON DELETE SET NULL,
    photo_path TEXT,
    date_added TEXT NOT NULL,
    UNIQUE(user_id, barcode)
);

CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    action TEXT NOT NULL,
    target_barcode TEXT,
    detail TEXT,
    performed_by_user_id INTEGER REFERENCES users(id),
    timestamp TEXT NOT NULL
);
"""


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()


# ---------- users ----------

def create_user(db, username, password_hash, is_admin, date_created):
    cur = db.execute(
        """INSERT INTO users (username, password_hash, is_admin, date_created)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (username, password_hash, 1 if is_admin else 0, date_created),
    )
    new_id = cur.fetchone()["id"]
    db.commit()
    return new_id


def get_user_by_username(db, username):
    return db.execute("SELECT * FROM users WHERE username = %s", (username,)).fetchone()


def get_user_by_id(db, user_id):
    return db.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()


def list_users(db):
    return db.execute("SELECT * FROM users ORDER BY id").fetchall()


def update_password(db, user_id, password_hash):
    db.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))
    db.commit()


def delete_user_cascade(db, user_id):
    """Permanently deletes a user account and everything scoped to it: items,
    boxes, categories, and their own activity log entries. All the FKs back
    to users(id) are NOT NULL with no ON DELETE clause, so those rows have to
    go before the user row does. Any activity_log rows in OTHER accounts
    where this user was the acting admin (performed_by_user_id) are kept,
    just with that reference nulled out -- same "keep the row, drop the
    now-dangling reference" approach already used for deleted items/boxes."""
    db.execute("DELETE FROM items WHERE user_id = %s", (user_id,))
    db.execute("DELETE FROM boxes WHERE user_id = %s", (user_id,))
    db.execute("DELETE FROM categories WHERE user_id = %s", (user_id,))
    db.execute("DELETE FROM activity_log WHERE user_id = %s", (user_id,))
    db.execute(
        "UPDATE activity_log SET performed_by_user_id = NULL WHERE performed_by_user_id = %s",
        (user_id,),
    )
    db.execute("DELETE FROM users WHERE id = %s", (user_id,))
    db.commit()


# ---------- categories ----------

def list_categories(db, user_id):
    return db.execute(
        "SELECT * FROM categories WHERE user_id = %s ORDER BY name", (user_id,)
    ).fetchall()


def get_category(db, user_id, category_id):
    return db.execute(
        "SELECT * FROM categories WHERE user_id = %s AND id = %s", (user_id, category_id)
    ).fetchone()


def get_category_by_name(db, user_id, name):
    return db.execute(
        "SELECT * FROM categories WHERE user_id = %s AND name = %s", (user_id, name)
    ).fetchone()


def create_category(db, user_id, name):
    cur = db.execute(
        "INSERT INTO categories (user_id, name) VALUES (%s, %s) RETURNING id", (user_id, name)
    )
    new_id = cur.fetchone()["id"]
    db.commit()
    return new_id


def get_or_create_category(db, user_id, name):
    name = name.strip()
    if not name:
        return None
    existing = get_category_by_name(db, user_id, name)
    if existing:
        return existing["id"]
    return create_category(db, user_id, name)


def rename_category(db, user_id, category_id, new_name):
    db.execute(
        "UPDATE categories SET name = %s WHERE user_id = %s AND id = %s",
        (new_name, user_id, category_id),
    )
    db.commit()


def delete_category(db, user_id, category_id):
    """Deletes the category and reassigns its items/boxes to Uncategorized (null). Returns affected count."""
    items_affected = db.execute(
        "SELECT COUNT(*) AS c FROM items WHERE user_id = %s AND category_id = %s",
        (user_id, category_id),
    ).fetchone()["c"]
    boxes_affected = db.execute(
        "SELECT COUNT(*) AS c FROM boxes WHERE user_id = %s AND category_id = %s",
        (user_id, category_id),
    ).fetchone()["c"]

    db.execute(
        "UPDATE items SET category_id = NULL WHERE user_id = %s AND category_id = %s",
        (user_id, category_id),
    )
    db.execute(
        "UPDATE boxes SET category_id = NULL WHERE user_id = %s AND category_id = %s",
        (user_id, category_id),
    )
    db.execute(
        "DELETE FROM categories WHERE user_id = %s AND id = %s", (user_id, category_id)
    )
    db.commit()
    return items_affected + boxes_affected


# ---------- barcodes ----------

def next_barcode(db, user_id, prefix, table):
    """Generates the next sequential per-user barcode, e.g. ITM000001 / BOX000001."""
    row = db.execute(
        f"SELECT COUNT(*) AS c FROM {table} WHERE user_id = %s", (user_id,)
    ).fetchone()
    n = row["c"] + 1
    while True:
        candidate = f"{prefix}{n:06d}"
        exists = db.execute(
            f"SELECT 1 FROM {table} WHERE user_id = %s AND barcode = %s", (user_id, candidate)
        ).fetchone()
        if not exists:
            return candidate
        n += 1


# ---------- items ----------

ITEM_SELECT = """
    SELECT items.*, categories.name AS category_name,
           boxes.number AS box_number, boxes.barcode AS box_barcode
    FROM items
    LEFT JOIN categories ON items.category_id = categories.id
    LEFT JOIN boxes ON items.box_id = boxes.id
"""


def create_item(db, user_id, barcode, name, category_id, photo_path, date_added):
    cur = db.execute(
        """INSERT INTO items (user_id, barcode, name, category_id, status, box_id, photo_path, date_added)
           VALUES (%s, %s, %s, %s, 'not_packed', NULL, %s, %s) RETURNING id""",
        (user_id, barcode, name, category_id, photo_path, date_added),
    )
    new_id = cur.fetchone()["id"]
    db.commit()
    return new_id


def get_item_by_barcode(db, user_id, barcode):
    return db.execute(
        ITEM_SELECT + " WHERE items.user_id = %s AND items.barcode = %s", (user_id, barcode)
    ).fetchone()


def get_item_by_id(db, user_id, item_id):
    return db.execute(
        ITEM_SELECT + " WHERE items.user_id = %s AND items.id = %s", (user_id, item_id)
    ).fetchone()


def list_items(db, user_id, q=None, category_id=None, status=None, box_id=None):
    query = ITEM_SELECT + " WHERE items.user_id = %s"
    params = [user_id]

    if q:
        query += " AND (items.name ILIKE %s OR items.barcode ILIKE %s)"
        params.append(f"%{q}%")
        params.append(f"%{q}%")
    if category_id is not None:
        query += " AND items.category_id = %s"
        params.append(category_id)
    if status:
        query += " AND items.status = %s"
        params.append(status)
    if box_id is not None:
        query += " AND items.box_id = %s"
        params.append(box_id)

    query += " ORDER BY items.id DESC"
    return db.execute(query, params).fetchall()


def delete_item(db, user_id, item_id):
    db.execute("DELETE FROM items WHERE user_id = %s AND id = %s", (user_id, item_id))
    db.commit()


def pack_item(db, user_id, item_id, box_id):
    db.execute(
        "UPDATE items SET box_id = %s, status = 'packed' WHERE user_id = %s AND id = %s",
        (box_id, user_id, item_id),
    )
    db.commit()


def unpack_item(db, user_id, item_id):
    db.execute(
        "UPDATE items SET box_id = NULL, status = 'not_packed' WHERE user_id = %s AND id = %s",
        (user_id, item_id),
    )
    db.commit()


# ---------- boxes ----------

BOX_SELECT = """
    SELECT boxes.*, categories.name AS category_name
    FROM boxes
    LEFT JOIN categories ON boxes.category_id = categories.id
"""


def create_box(db, user_id, barcode, number, category_id, date_created):
    cur = db.execute(
        """INSERT INTO boxes (user_id, barcode, number, category_id, date_created)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (user_id, barcode, number, category_id, date_created),
    )
    new_id = cur.fetchone()["id"]
    db.commit()
    return new_id


def get_box_by_barcode(db, user_id, barcode):
    return db.execute(
        BOX_SELECT + " WHERE boxes.user_id = %s AND boxes.barcode = %s", (user_id, barcode)
    ).fetchone()


def get_box_by_id(db, user_id, box_id):
    return db.execute(
        BOX_SELECT + " WHERE boxes.user_id = %s AND boxes.id = %s", (user_id, box_id)
    ).fetchone()


def list_boxes(db, user_id):
    return db.execute(
        """SELECT boxes.*, categories.name AS category_name, COUNT(items.id) AS item_count
           FROM boxes
           LEFT JOIN categories ON boxes.category_id = categories.id
           LEFT JOIN items ON items.box_id = boxes.id AND items.user_id = boxes.user_id
           WHERE boxes.user_id = %s
           GROUP BY boxes.id, categories.name ORDER BY boxes.id DESC""",
        (user_id,),
    ).fetchall()


def box_contents(db, user_id, box_id):
    return list_items(db, user_id, box_id=box_id)


def delete_box(db, user_id, box_id):
    """Deletes the box; any items packed in it revert to not_packed. Returns count unpacked."""
    unpacked_count = db.execute(
        "SELECT COUNT(*) AS c FROM items WHERE user_id = %s AND box_id = %s",
        (user_id, box_id),
    ).fetchone()["c"]

    db.execute(
        "UPDATE items SET box_id = NULL, status = 'not_packed' WHERE user_id = %s AND box_id = %s",
        (user_id, box_id),
    )
    db.execute("DELETE FROM boxes WHERE user_id = %s AND id = %s", (user_id, box_id))
    db.commit()
    return unpacked_count


# ---------- activity log ----------

def log_activity(db, user_id, action, target_barcode, detail, performed_by_user_id, timestamp):
    db.execute(
        """INSERT INTO activity_log (user_id, action, target_barcode, detail, performed_by_user_id, timestamp)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (user_id, action, target_barcode, detail, performed_by_user_id, timestamp),
    )
    db.commit()


def list_activity(db, user_id):
    return db.execute(
        """SELECT activity_log.*, performer.username AS performed_by_username
           FROM activity_log
           LEFT JOIN users AS performer ON activity_log.performed_by_user_id = performer.id
           WHERE activity_log.user_id = %s
           ORDER BY activity_log.id DESC""",
        (user_id,),
    ).fetchall()
