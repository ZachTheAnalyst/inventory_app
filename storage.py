"""
Thin wrapper around the Supabase Storage REST API for item photo uploads.

Photos used to be saved to the app's local disk (static/photos), but that
disk isn't persistent on Render's free tier -- files get wiped on every
redeploy with no way to regenerate a lost photo (unlike barcode PNGs, which
are always re-derivable from the barcode value). Storing them in Supabase
Storage instead keeps them alive across redeploys.

Uses the service role key so uploads bypass RLS -- this app already gates
access via the Flask session, so a separate per-request Supabase auth token
isn't needed.
"""

import os
import uuid

import requests

BUCKET = "item-photos"

ALLOWED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def _supabase_url():
    url = os.environ.get("SUPABASE_URL")
    if not url:
        raise RuntimeError(
            "SUPABASE_URL environment variable is not set -- it's the project's "
            "API URL (https://<project-ref>.supabase.co), not the Postgres DATABASE_URL."
        )
    return url.rstrip("/")


def _service_role_key():
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY environment variable is not set.")
    return key


def _auth_headers():
    key = _service_role_key()
    return {"Authorization": f"Bearer {key}", "apikey": key}


def ensure_bucket():
    """Creates the item-photos bucket (public read) if it doesn't already exist.
    Idempotent -- safe to call on every app startup."""
    base = _supabase_url()
    headers = _auth_headers()

    resp = requests.get(f"{base}/storage/v1/bucket/{BUCKET}", headers=headers, timeout=10)
    if resp.status_code == 200:
        return

    resp = requests.post(
        f"{base}/storage/v1/bucket",
        headers=headers,
        json={"id": BUCKET, "name": BUCKET, "public": True},
        timeout=10,
    )
    if resp.status_code not in (200, 201) and "already exists" not in resp.text.lower():
        raise RuntimeError(
            f"Failed to create Supabase storage bucket '{BUCKET}': "
            f"{resp.status_code} {resp.text}"
        )


def upload_photo(user_id, file_storage):
    """Uploads a Werkzeug FileStorage to Supabase Storage. Returns its public URL."""
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".jpg"
    object_path = f"{user_id}/{uuid.uuid4().hex}{ext}"

    base = _supabase_url()
    headers = _auth_headers()
    headers["Content-Type"] = file_storage.mimetype or "application/octet-stream"

    resp = requests.post(
        f"{base}/storage/v1/object/{BUCKET}/{object_path}",
        headers=headers,
        data=file_storage.read(),
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to upload photo to Supabase Storage: {resp.status_code} {resp.text}"
        )

    return f"{base}/storage/v1/object/public/{BUCKET}/{object_path}"
