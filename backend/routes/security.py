import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, session
from backend.database import get_db, get_utc_now_iso, dict_from_row
from backend.routes.auth import admin_required
from backend.services.telegram_service import notify_security_event

security_bp = Blueprint("security", __name__, url_prefix="/api/security")

@security_bp.route("/events", methods=["GET"])
@admin_required
def get_security_events():
    db = get_db()
    cur = db.cursor()

    status = request.args.get("status")
    severity = request.args.get("severity")
    search = request.args.get("search", "").strip()

    query = """
        SELECT e.*, p.slot_code, v.registration_number, u.full_name as customer_name
        FROM security_events e
        LEFT JOIN parking_slots p ON e.slot_id = p.id
        LEFT JOIN vehicles v ON e.vehicle_id = v.id
        LEFT JOIN users u ON e.user_id = u.id
        WHERE 1=1
    """
    params = []
    if status:
        query += " AND e.status = ?"
        params.append(status)
    if severity:
        query += " AND e.severity = ?"
        params.append(severity)
    if search:
        query += " AND (e.event_code LIKE ? OR e.description LIKE ? OR e.event_type LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])

    query += " ORDER BY e.id DESC LIMIT 100"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    return jsonify({"success": True, "events": dict_from_row(rows)})

@security_bp.route("/events", methods=["POST"])
@admin_required
def create_manual_event():
    data = request.get_json(silent=True) or {}
    event_type = data.get("event_type", "suspicious_activity")
    severity = data.get("severity", "medium")
    description = data.get("description", "").strip()
    slot_id = data.get("slot_id") or None
    vehicle_id = data.get("vehicle_id") or None

    if not description:
        return jsonify({"success": False, "error": "Description is required."}), 400

    db = get_db()
    cur = db.cursor()
    utc_now = get_utc_now_iso()
    event_code = f"SEC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:4].upper()}"

    cur.execute("""
        INSERT INTO security_events (event_code, event_type, severity, status, slot_id, vehicle_id, description, created_at, updated_at)
        VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?)
    """, (event_code, event_type, severity, slot_id, vehicle_id, description, utc_now, utc_now))
    eid = cur.lastrowid
    db.commit()
    notify_security_event(event_type, severity, description, event_code)

    return jsonify({"success": True, "message": "Security event logged.", "event_id": eid, "event_code": event_code}), 201

@security_bp.route("/events/<int:event_id>", methods=["PATCH"])
@admin_required
def update_event(event_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    severity = data.get("severity")
    notes = data.get("investigation_notes")

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM security_events WHERE id = ?", (event_id,))
    event = cur.fetchone()
    if not event:
        return jsonify({"success": False, "error": "Event not found"}), 404

    utc_now = get_utc_now_iso()
    admin_name = session.get("admin_name", "Admin")

    new_status = status or event["status"]
    new_severity = severity or event["severity"]
    new_notes = notes if notes is not None else event["investigation_notes"]
    resolved_at = utc_now if new_status in ("resolved", "dismissed") and event["status"] not in ("resolved", "dismissed") else event["resolved_at"]
    resolved_by = admin_name if new_status in ("resolved", "dismissed") else event["resolved_by"]

    cur.execute("""
        UPDATE security_events 
        SET status = ?, severity = ?, investigation_notes = ?, resolved_at = ?, resolved_by = ?, updated_at = ?
        WHERE id = ?
    """, (new_status, new_severity, new_notes, resolved_at, resolved_by, utc_now, event_id))
    db.commit()

    return jsonify({"success": True, "message": f"Security incident {event['event_code']} updated successfully."})



@security_bp.route("/telegram/test", methods=["POST"])
@admin_required
def telegram_test():
    from backend.services.telegram_service import send_telegram_message
    ok = send_telegram_message("🟢 PARK+ Telegram integration test. Your bot is connected.")
    if not ok:
        return jsonify({"success": False, "error": "Telegram message failed. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in backend configuration."}), 503
    return jsonify({"success": True, "message": "Telegram test message sent."})
