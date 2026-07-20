import csv
import io
import os
import random
from datetime import datetime
from functools import wraps

import click
from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, send_file, flash, session, g
)
import barcode
from barcode.writer import ImageWriter
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdf_canvas
from werkzeug.security import generate_password_hash, check_password_hash

import db as data
import storage
from print_service import print_label

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BARCODE_DIR = os.path.join(BASE_DIR, "static", "barcodes")
os.makedirs(BARCODE_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = "dev-key-change-if-you-deploy-this-publicly"

ITEM_PREFIX = "ITM"
BOX_PREFIX = "BOX"

PASSWORD_WORDS = [
    "amber", "birch", "cedar", "delta", "ember", "flint", "grove", "haven",
    "ivory", "jade", "kite", "lumen", "maple", "north", "onyx", "pixel",
    "quartz", "raven", "storm", "tide", "umbra", "violet", "willow", "zephyr",
]


def today():
    return datetime.now().strftime("%Y-%m-%d")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def generate_password():
    w1, w2 = random.sample(PASSWORD_WORDS, 2)
    number = random.randint(10, 99)
    special = random.choice("!@#$%&*?")
    return f"{w1.capitalize()}{w2.capitalize()}{number}{special}"


# ---------- DB helpers ----------

def get_db():
    if "db" not in g:
        g.db = data.get_connection()
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = data.get_connection()
    data.init_schema(conn)
    conn.close()


def bootstrap():
    """Full app startup: DB schema + Supabase storage bucket, both idempotent."""
    init_db()
    storage.ensure_bucket()


# ---------- auth helpers ----------

def get_current_user():
    if "user_id" not in session:
        return None
    return data.get_user_by_id(get_db(), session["user_id"])


def effective_user_id():
    """User id whose inventory the request should operate on: normally the
    logged-in user, but an admin drilled into another account via
    /admin/users/<id> operates on that account instead."""
    view_id = session.get("view_as_user_id")
    if view_id:
        current = get_current_user()
        if current and current["is_admin"]:
            return view_id
    return session["user_id"]


def acting_admin_id():
    """The admin's own id when acting on someone else's inventory, else None."""
    view_id = session.get("view_as_user_id")
    if view_id and view_id != session["user_id"]:
        return session["user_id"]
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        user = get_current_user()
        if not user or not user["is_admin"]:
            return "Forbidden", 403
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_view_context():
    if "user_id" not in session:
        return {}
    viewing_id = session.get("view_as_user_id")
    viewing_user = None
    if viewing_id and viewing_id != session["user_id"]:
        viewing_user = data.get_user_by_id(get_db(), viewing_id)
    return {"current_user": get_current_user(), "viewing_user": viewing_user}


# ---------- misc helpers ----------

def generate_barcode_image(code_value):
    """Creates a Code128 PNG for the given value in static/barcodes/, returns filename."""
    code128 = barcode.get_barcode_class("code128")
    writer = ImageWriter()
    writer.set_options({
        "module_height": 12.0,
        "font_size": 8,
        "text_distance": 3,
        "quiet_zone": 2,
    })
    filename_no_ext = os.path.join(BARCODE_DIR, code_value)
    saved_path = code128(code_value, writer=writer).save(filename_no_ext)
    return os.path.basename(saved_path)


# ---------- Auth routes ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = data.get_user_by_username(db, username)
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.")
            return redirect(url_for("login"))
        session.clear()
        session["user_id"] = user["id"]
        next_url = request.args.get("next")
        return redirect(next_url or url_for("index"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        user = get_current_user()

        if not check_password_hash(user["password_hash"], current_password):
            flash("Current password is incorrect.")
            return redirect(url_for("account"))
        if not new_password or new_password != confirm_password:
            flash("New password and confirmation must match.")
            return redirect(url_for("account"))

        data.update_password(get_db(), user["id"], generate_password_hash(new_password))
        flash("Password updated.")
        return redirect(url_for("account"))
    return render_template("account.html")


# ---------- CLI ----------

@app.cli.command("create-user")
@click.argument("username")
@click.option("--admin", "is_admin", is_flag=True, default=False, help="Grant admin privileges.")
def create_user_cmd(username, is_admin):
    """Creates a new account with a randomly generated password, shown once."""
    conn = data.get_connection()
    data.init_schema(conn)
    if data.get_user_by_username(conn, username):
        click.echo(f"Username '{username}' already exists.")
        conn.close()
        return
    password = generate_password()
    password_hash = generate_password_hash(password)
    data.create_user(conn, username, password_hash, is_admin, today())
    conn.close()
    click.echo(f"Created user '{username}'.")
    click.echo(f"Password (shown once, will not be recoverable): {password}")


# ---------- Core pages ----------

@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/api/lookup/<barcode_value>")
@login_required
def api_lookup(barcode_value):
    db = get_db()
    uid = effective_user_id()
    item = data.get_item_by_barcode(db, uid, barcode_value)

    if item is None:
        return jsonify({"state": "not_in_inventory", "barcode": barcode_value})

    payload = {
        "state": item["status"],
        "barcode": item["barcode"],
        "name": item["name"],
        "category": item["category_name"] or "Uncategorized",
        "photo_path": item["photo_path"],
    }
    if item["status"] == "packed":
        payload["box_number"] = item["box_number"]
        payload["box_barcode"] = item["box_barcode"]
    return jsonify(payload)


# ---------- Items ----------

@app.route("/add", methods=["GET", "POST"])
@login_required
def add_item():
    db = get_db()
    uid = effective_user_id()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category_name = request.form.get("category", "").strip()

        if not name:
            flash("Item name is required.")
            return redirect(url_for("add_item"))

        category_id = data.get_or_create_category(db, uid, category_name) if category_name else None

        photo_path = None
        photo = request.files.get("photo")
        if photo and photo.filename:
            photo_path = storage.upload_photo(uid, photo)

        code_value = data.next_barcode(db, uid, ITEM_PREFIX, "items")
        generate_barcode_image(code_value)
        print_label(code_value)  # stubbed until printer is connected

        data.create_item(db, uid, code_value, name, category_id, photo_path, today())
        data.log_activity(db, uid, "item_added", code_value, f"Added item '{name}'",
                           acting_admin_id(), now())
        return redirect(url_for("item_detail", barcode_value=code_value))

    categories = data.list_categories(db, uid)
    return render_template("add.html", categories=categories)


@app.route("/item/<barcode_value>")
@login_required
def item_detail(barcode_value):
    db = get_db()
    uid = effective_user_id()
    item = data.get_item_by_barcode(db, uid, barcode_value)
    if item is None:
        return render_template("not_found.html", barcode_value=barcode_value), 404
    if not os.path.exists(os.path.join(BARCODE_DIR, f"{item['barcode']}.png")):
        generate_barcode_image(item["barcode"])
    return render_template("item.html", item=item)


@app.route("/item/<barcode_value>/delete", methods=["POST"])
@login_required
def delete_item_route(barcode_value):
    db = get_db()
    uid = effective_user_id()
    item = data.get_item_by_barcode(db, uid, barcode_value)
    if item is None:
        return render_template("not_found.html", barcode_value=barcode_value), 404

    data.delete_item(db, uid, item["id"])
    data.log_activity(db, uid, "item_deleted", barcode_value, f"Deleted item '{item['name']}'",
                       acting_admin_id(), now())
    flash(f"Deleted '{item['name']}'.")
    return redirect(url_for("inventory"))


@app.route("/item/<barcode_value>/reprint", methods=["POST"])
@login_required
def reprint_item(barcode_value):
    db = get_db()
    uid = effective_user_id()
    item = data.get_item_by_barcode(db, uid, barcode_value)
    if item is None:
        return render_template("not_found.html", barcode_value=barcode_value), 404
    generate_barcode_image(item["barcode"])
    print_label(item["barcode"])
    flash(f"Reprinted label for '{item['name']}'.")
    return redirect(url_for("inventory"))


@app.route("/inventory")
@login_required
def inventory():
    db = get_db()
    uid = effective_user_id()

    q = request.args.get("q", "").strip()
    category_id = request.args.get("category_id", "").strip()
    status = request.args.get("status", "").strip()
    box_id = request.args.get("box_id", "").strip()

    items = data.list_items(
        db, uid,
        q=q or None,
        category_id=int(category_id) if category_id else None,
        status=status or None,
        box_id=int(box_id) if box_id else None,
    )
    categories = data.list_categories(db, uid)
    boxes = data.list_boxes(db, uid)
    return render_template(
        "inventory.html", items=items, q=q, categories=categories, boxes=boxes,
        selected_category=category_id, selected_status=status, selected_box=box_id,
    )


# ---------- Boxes ----------

@app.route("/add_box", methods=["GET", "POST"])
@login_required
def add_box():
    db = get_db()
    uid = effective_user_id()

    if request.method == "POST":
        number = request.form.get("number", "").strip()
        category_name = request.form.get("category", "").strip()

        if not number:
            flash("Box number is required.")
            return redirect(url_for("add_box"))

        category_id = data.get_or_create_category(db, uid, category_name) if category_name else None

        code_value = data.next_barcode(db, uid, BOX_PREFIX, "boxes")
        generate_barcode_image(code_value)
        print_label(code_value)  # stubbed until printer is connected

        data.create_box(db, uid, code_value, number, category_id, today())
        data.log_activity(db, uid, "box_added", code_value, f"Added box '{number}'",
                           acting_admin_id(), now())
        return redirect(url_for("box_detail", barcode_value=code_value))

    categories = data.list_categories(db, uid)
    return render_template("add_box.html", categories=categories)


@app.route("/box/<barcode_value>")
@login_required
def box_detail(barcode_value):
    db = get_db()
    uid = effective_user_id()
    box = data.get_box_by_barcode(db, uid, barcode_value)
    if box is None:
        return render_template("not_found.html", barcode_value=barcode_value), 404
    if not os.path.exists(os.path.join(BARCODE_DIR, f"{box['barcode']}.png")):
        generate_barcode_image(box["barcode"])
    contents = data.box_contents(db, uid, box["id"])
    return render_template("box.html", box=box, contents=contents)


@app.route("/box/<barcode_value>/delete", methods=["POST"])
@login_required
def delete_box_route(barcode_value):
    db = get_db()
    uid = effective_user_id()
    box = data.get_box_by_barcode(db, uid, barcode_value)
    if box is None:
        return render_template("not_found.html", barcode_value=barcode_value), 404

    unpacked_count = data.delete_box(db, uid, box["id"])
    data.log_activity(
        db, uid, "box_deleted", barcode_value,
        f"Deleted box '{box['number']}' ({unpacked_count} item(s) auto-unpacked)",
        acting_admin_id(), now(),
    )
    flash(f"Deleted box '{box['number']}'.")
    return redirect(url_for("boxes_list"))


@app.route("/boxes")
@login_required
def boxes_list():
    db = get_db()
    uid = effective_user_id()
    boxes = data.list_boxes(db, uid)
    return render_template("boxes.html", boxes=boxes)


# ---------- Categories ----------

@app.route("/categories", methods=["GET", "POST"])
@login_required
def categories_page():
    db = get_db()
    uid = effective_user_id()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Category name is required.")
        elif data.get_category_by_name(db, uid, name):
            flash("A category with that name already exists.")
        else:
            data.create_category(db, uid, name)
            data.log_activity(db, uid, "category_created", None, f"Created category '{name}'",
                               acting_admin_id(), now())
        return redirect(url_for("categories_page"))

    categories = data.list_categories(db, uid)
    return render_template("categories.html", categories=categories)


@app.route("/categories/<int:category_id>/rename", methods=["POST"])
@login_required
def rename_category_route(category_id):
    db = get_db()
    uid = effective_user_id()
    category = data.get_category(db, uid, category_id)
    if category is None:
        flash("Category not found.")
        return redirect(url_for("categories_page"))

    new_name = request.form.get("name", "").strip()
    if not new_name:
        flash("Category name is required.")
        return redirect(url_for("categories_page"))

    data.rename_category(db, uid, category_id, new_name)
    flash(f"Renamed category to '{new_name}'.")
    return redirect(url_for("categories_page"))


@app.route("/categories/<int:category_id>/delete", methods=["POST"])
@login_required
def delete_category_route(category_id):
    db = get_db()
    uid = effective_user_id()
    category = data.get_category(db, uid, category_id)
    if category is None:
        flash("Category not found.")
        return redirect(url_for("categories_page"))

    affected = data.delete_category(db, uid, category_id)
    data.log_activity(
        db, uid, "category_deleted", None,
        f"Deleted category '{category['name']}' ({affected} item/box reassigned to Uncategorized)",
        acting_admin_id(), now(),
    )
    flash(f"Deleted category '{category['name']}'.")
    return redirect(url_for("categories_page"))


# ---------- Packing ----------

@app.route("/pack")
@login_required
def pack_page():
    return render_template("pack.html")


@app.route("/api/pack", methods=["POST"])
@login_required
def api_pack():
    db = get_db()
    uid = effective_user_id()
    payload = request.get_json(silent=True) or {}
    item_barcode = (payload.get("item_barcode") or "").strip().upper()
    box_barcode = (payload.get("box_barcode") or "").strip().upper()

    item = data.get_item_by_barcode(db, uid, item_barcode)
    if item is None:
        return jsonify({"status": "unknown_item", "barcode": item_barcode})

    box = data.get_box_by_barcode(db, uid, box_barcode)
    if box is None:
        return jsonify({"status": "unknown_box", "barcode": box_barcode})

    data.pack_item(db, uid, item["id"], box["id"])
    data.log_activity(
        db, uid, "item_packed", item_barcode,
        f"Packed '{item['name']}' into box '{box['number']}'", acting_admin_id(), now(),
    )
    return jsonify({
        "status": "packed", "item_name": item["name"],
        "box_number": box["number"], "box_barcode": box["barcode"],
    })


@app.route("/api/unpack", methods=["POST"])
@login_required
def api_unpack():
    db = get_db()
    uid = effective_user_id()
    payload = request.get_json(silent=True) or {}
    item_barcode = (payload.get("item_barcode") or "").strip().upper()

    item = data.get_item_by_barcode(db, uid, item_barcode)
    if item is None:
        return jsonify({"status": "unknown_item", "barcode": item_barcode})

    data.unpack_item(db, uid, item["id"])
    data.log_activity(db, uid, "item_unpacked", item_barcode, f"Unpacked '{item['name']}'",
                       acting_admin_id(), now())
    return jsonify({"status": "unpacked", "item_name": item["name"]})


# ---------- Admin ----------

@app.route("/admin/users")
@admin_required
def admin_users():
    db = get_db()
    users = data.list_users(db)
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/create", methods=["POST"])
@admin_required
def admin_create_user():
    db = get_db()
    username = request.form.get("username", "").strip()
    is_admin = request.form.get("is_admin") == "on"

    if not username:
        flash("Username is required.")
        return redirect(url_for("admin_users"))
    if data.get_user_by_username(db, username):
        flash("That username is already taken.")
        return redirect(url_for("admin_users"))

    password = generate_password()
    password_hash = generate_password_hash(password)
    data.create_user(db, username, password_hash, is_admin, today())
    flash(f"Created account '{username}'. Password (shown once): {password}")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>")
@admin_required
def admin_view_user(user_id):
    target = data.get_user_by_id(get_db(), user_id)
    if target is None:
        return "Not found", 404
    session["view_as_user_id"] = user_id
    return redirect(url_for("index"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    db = get_db()
    admin_user = get_current_user()
    target = data.get_user_by_id(db, user_id)

    if target is None:
        flash("Account not found.")
        return redirect(url_for("admin_users"))
    if target["id"] == admin_user["id"]:
        flash("You can't delete your own account.")
        return redirect(url_for("admin_users"))

    username = target["username"]
    data.delete_user_cascade(db, user_id)
    data.log_activity(
        db, admin_user["id"], "user_deleted", None,
        f"Deleted user account '{username}' (id={user_id}) and all its items, boxes, "
        f"categories, and activity log entries",
        None, now(),
    )
    flash(f"Deleted account '{username}' and all associated data.")
    return redirect(url_for("admin_users"))


@app.route("/admin/exit_view")
@login_required
def admin_exit_view():
    session.pop("view_as_user_id", None)
    return redirect(url_for("admin_users"))


# ---------- Activity log ----------

@app.route("/activity")
@login_required
def activity_log_page():
    db = get_db()
    uid = effective_user_id()
    entries = data.list_activity(db, uid)
    return render_template("activity.html", entries=entries)


# ---------- Export ----------

@app.route("/export")
@login_required
def export():
    db = get_db()
    uid = effective_user_id()
    fmt = request.args.get("format", "csv").lower()
    items = data.list_items(db, uid)

    if fmt == "pdf":
        return export_pdf(items)
    return export_csv(items)


def export_csv(items):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Name", "Category", "Barcode", "Status", "Box", "Date Added"])
    for item in items:
        writer.writerow([
            item["name"],
            item["category_name"] or "Uncategorized",
            item["barcode"],
            item["status"],
            item["box_number"] or "",
            item["date_added"],
        ])
    mem = io.BytesIO(buf.getvalue().encode("utf-8"))
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="inventory_export.csv")


def export_pdf(items):
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    headers = ["Name", "Category", "Barcode", "Status", "Box", "Date Added"]
    col_x = [0.5, 2.2, 3.7, 5.0, 5.9, 6.8]

    def draw_header(y):
        c.setFont("Helvetica-Bold", 8)
        for x, h in zip(col_x, headers):
            c.drawString(x * inch, y, h)
        return y - 0.2 * inch

    c.setFont("Helvetica-Bold", 14)
    c.drawString(0.5 * inch, height - 0.75 * inch, "Inventory Export")
    y = draw_header(height - 1.1 * inch)

    c.setFont("Helvetica", 8)
    for item in items:
        if y < 0.75 * inch:
            c.showPage()
            c.setFont("Helvetica-Bold", 14)
            c.drawString(0.5 * inch, height - 0.75 * inch, "Inventory Export (cont.)")
            y = draw_header(height - 1.1 * inch)
            c.setFont("Helvetica", 8)

        row = [
            item["name"][:22],
            (item["category_name"] or "Uncategorized")[:14],
            item["barcode"],
            item["status"],
            (item["box_number"] or "-")[:10],
            item["date_added"] or "",
        ]
        for x, val in zip(col_x, row):
            c.drawString(x * inch, y, str(val))
        y -= 0.2 * inch

    c.save()
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name="inventory_export.pdf")


# ---------- Label printing / PDF sheet ----------

@app.route("/labels")
@login_required
def labels_page():
    db = get_db()
    uid = effective_user_id()
    items = data.list_items(db, uid)
    boxes = data.list_boxes(db, uid)
    return render_template("labels.html", items=items, boxes=boxes)


@app.route("/labels/generate", methods=["POST"])
@login_required
def generate_labels_pdf():
    """Builds a printable PDF sheet of barcode labels (Avery 5160 layout: 3 cols x 10 rows)."""
    db = get_db()
    uid = effective_user_id()
    item_ids = request.form.getlist("item_ids")
    box_ids = request.form.getlist("box_ids")

    rows = []
    for iid in item_ids:
        item = data.get_item_by_id(db, uid, int(iid))
        if item:
            rows.append({"label": item["name"], "barcode": item["barcode"]})
    for bid in box_ids:
        box = data.get_box_by_id(db, uid, int(bid))
        if box:
            rows.append({"label": box["number"], "barcode": box["barcode"]})
    if not item_ids and not box_ids:
        rows = [{"label": i["name"], "barcode": i["barcode"]} for i in data.list_items(db, uid)]
        rows += [{"label": b["number"], "barcode": b["barcode"]} for b in data.list_boxes(db, uid)]

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=letter)

    label_w = 2.625 * inch
    label_h = 1.0 * inch
    margin_left = 0.19 * inch
    margin_top = 0.5 * inch
    cols, rows_per_page = 3, 10

    col = row = 0
    for entry in rows:
        img_path = os.path.join(BARCODE_DIR, f"{entry['barcode']}.png")
        if not os.path.exists(img_path):
            generate_barcode_image(entry["barcode"])

        x = margin_left + col * label_w
        y = letter[1] - margin_top - (row + 1) * label_h

        c.setFont("Helvetica-Bold", 7)
        c.drawString(x + 4, y + label_h - 12, entry["label"][:28])

        img_w = label_w - 12
        img_h = label_h - 24
        c.drawImage(img_path, x + 6, y + 4, width=img_w, height=img_h,
                    preserveAspectRatio=True, anchor='sw')

        col += 1
        if col >= cols:
            col = 0
            row += 1
        if row >= rows_per_page:
            row = 0
            col = 0
            c.showPage()

    c.save()
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name="labels.pdf")


if __name__ == "__main__":
    bootstrap()
    # ssl_context="adhoc" (needs pyOpenSSL) serves a self-signed HTTPS cert so
    # phone browsers on the LAN treat this as a secure context -- required
    # for camera access (getUserMedia) from any device other than localhost.
    app.run(debug=True, host="0.0.0.0", port=5000, ssl_context="adhoc")
