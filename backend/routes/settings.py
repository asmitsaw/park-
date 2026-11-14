from flask import Blueprint, request, jsonify
from backend.database import get_db, get_utc_now_iso, dict_from_row
from backend.routes.auth import admin_required

settings_bp = Blueprint("settings", __name__, url_prefix="/api/settings")

@settings_bp.route("", methods=["GET"])
@admin_required
def get_settings():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM system_settings ORDER BY key ASC")
    rows = cur.fetchall()
    return jsonify({"success": True, "settings": dict_from_row(rows)})

@settings_bp.route("", methods=["PUT"])
@admin_required
def update_settings():
    data = request.get_json(silent=True) or {}
    db = get_db()
    cur = db.cursor()
    utc_now = get_utc_now_iso()

    for k, v in data.items():
        cur.execute("""
            INSERT INTO system_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """, (k, str(v), utc_now))

    db.commit()
    return jsonify({"success": True, "message": "System settings updated successfully."})

