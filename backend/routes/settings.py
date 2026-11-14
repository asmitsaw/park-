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
    threshold_key = "unscanned_departure_alert_minutes"
    if threshold_key in data:
        raw_threshold = data[threshold_key]
        if isinstance(raw_threshold, bool) or not str(raw_threshold).strip().isdigit():
            return jsonify({
                "success": False,
                "error": "Departure alert threshold must be a whole number of minutes."
            }), 400
        threshold = int(raw_threshold)
        if not 1 <= threshold <= 1440:
            return jsonify({
                "success": False,
                "error": "Departure alert threshold must be between 1 and 1440 minutes."
            }), 400
        data[threshold_key] = threshold

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

