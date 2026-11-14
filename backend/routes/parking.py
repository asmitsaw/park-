from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, session
from backend.database import get_db, dict_from_row
from backend.config import Config
from backend.routes.auth import admin_required
from backend.services.parking_service import process_rfid_entry, process_rfid_exit, process_sensor_telemetry
from backend.services.telegram_service import (
    escape_telegram_html,
    format_duration,
    format_telegram_time,
    notify_security_event,
    send_telegram_message,
)

parking_bp = Blueprint("parking", __name__, url_prefix="/api")

def verify_device_auth(req):
    """
    Validates device authentication secret passed in headers or body.
    If not provided and session is authenticated admin, allow as manual simulation.
    """
    token = req.headers.get("X-Device-Token") or (req.get_json(silent=True) or {}).get("device_secret")
    if token and token == Config.DEVICE_SHARED_SECRET:
        return True
    return False

@parking_bp.route("/parking/slots", methods=["GET"])
@admin_required
def get_slots():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT p.*, v.registration_number, v.vehicle_type, v.model as vehicle_model,
               u.full_name as customer_name, u.phone as customer_phone,
               s.entry_time, s.session_code
        FROM parking_slots p
        LEFT JOIN vehicles v ON p.current_vehicle_id = v.id
        LEFT JOIN users u ON v.user_id = u.id
        LEFT JOIN parking_sessions s ON p.current_session_id = s.id
        ORDER BY p.slot_code ASC
    """)
    slots = cur.fetchall()
    res = [dict_from_row(s) for s in slots]
    
    # Calculate live elapsed seconds
    now_dt = datetime.now(timezone.utc)
    for s in res:
        if s["is_occupied"] and s["entry_time"]:
            try:
                entry_dt = datetime.fromisoformat(s["entry_time"].replace("Z", "+00:00"))
                s["duration_seconds"] = int((now_dt - entry_dt).total_seconds())
            except Exception:
                s["duration_seconds"] = 0
        else:
            s["duration_seconds"] = 0

    return jsonify({"success": True, "slots": res})

@parking_bp.route("/parking/sessions", methods=["GET"])
@admin_required
def get_sessions():
    db = get_db()
    cur = db.cursor()

    status = request.args.get("status")
    slot_code = request.args.get("slot")
    search = request.args.get("search", "").strip()
    limit = int(request.args.get("limit", 100))

    query = """
        SELECT s.*, p.slot_code, v.registration_number, v.model as vehicle_model,
               u.full_name as customer_name, u.customer_code, r.card_uid
        FROM parking_sessions s
        JOIN parking_slots p ON s.slot_id = p.id
        JOIN vehicles v ON s.vehicle_id = v.id
        JOIN users u ON s.user_id = u.id
        LEFT JOIN rfid_cards r ON s.rfid_card_id = r.id
        WHERE 1=1
    """
    params = []

    if status:
        query += " AND s.status = ?"
        params.append(status)
    if slot_code:
        query += " AND p.slot_code = ?"
        params.append(slot_code)
    if search:
        query += " AND (v.registration_number LIKE ? OR u.full_name LIKE ? OR s.session_code LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])

    query += " ORDER BY s.id DESC LIMIT ?"
    params.append(limit)

    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    res = [dict_from_row(r) for r in rows]

    now_dt = datetime.now(timezone.utc)
    for r in res:
        if r["status"] == "active" and r["entry_time"]:
            try:
                entry_dt = datetime.fromisoformat(r["entry_time"].replace("Z", "+00:00"))
                r["live_duration_seconds"] = int((now_dt - entry_dt).total_seconds())
            except Exception:
                r["live_duration_seconds"] = r["duration_seconds"]
        else:
            r["live_duration_seconds"] = r["duration_seconds"]

    return jsonify({"success": True, "sessions": res})

def device_or_admin_allowed():
    return verify_device_auth(request) or "admin_id" in session

@parking_bp.route("/parking/gate/scan", methods=["POST"])
def gate_scan():
    """Single RFID endpoint: determine whether this card is entering or exiting."""
    if not device_or_admin_allowed():
        return jsonify({"authorized": False, "reason": "Device authentication required."}), 401

    data = request.get_json(silent=True) or {}
    device_code = (data.get("device_code") or "PARKPLUS_GATE_01").strip()
    rfid_uid = (data.get("rfid_uid") or "").strip().upper()
    if not rfid_uid:
        return jsonify({"authorized": False, "reason": "Missing rfid_uid"}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT 1
        FROM parking_sessions s
        JOIN rfid_cards r ON r.id = s.rfid_card_id
        WHERE r.card_uid = ? COLLATE NOCASE AND s.status = 'active'
        LIMIT 1
    """, (rfid_uid,))
    has_active_session = cur.fetchone() is not None

    if has_active_session:
        result = process_rfid_exit(db, rfid_uid, device_code)
        action = "exit"
    else:
        result = process_rfid_entry(db, rfid_uid, device_code)
        action = "entry"

    result["action"] = action
    if result.get("authorized"):
        if action == "entry" and result.get("pending_assignment"):
            message = None
        elif action == "entry":
            message = (
                "<b>✅ PARK+ PARKING STARTED</b>\n\n"
                f"<b>Customer:</b> {escape_telegram_html(result.get('customer_name'))}\n"
                f"<b>Vehicle:</b> {escape_telegram_html(result.get('vehicle_reg'))}\n"
                f"<b>Parking slot:</b> {escape_telegram_html(result.get('slot_code'))}\n"
                f"<b>Start time:</b> {format_telegram_time(result.get('entry_time'))}\n"
                f"<b>Session:</b> {escape_telegram_html(result.get('session_code'))}\n"
                "<b>Subscription balance before parking:</b> "
                f"{format_duration(result.get('remaining_seconds', 0))}"
            )
        else:
            message = (
                "<b>🏁 PARK+ PARKING SESSION COMPLETED</b>\n\n"
                f"<b>Customer:</b> {escape_telegram_html(result.get('customer_name'))}\n"
                f"<b>Vehicle:</b> {escape_telegram_html(result.get('vehicle_reg'))}\n"
                f"<b>Parking slot:</b> {escape_telegram_html(result.get('slot_code'))}\n"
                f"<b>Start time:</b> {format_telegram_time(result.get('entry_time'))}\n"
                f"<b>Exit time:</b> {format_telegram_time(result.get('exit_time'))}\n"
                f"<b>Parking duration:</b> {format_duration(result.get('duration_seconds', 0))}\n"
                "<b>Subscription time remaining:</b> "
                f"{format_duration(result.get('balance_after_seconds', 0))}\n"
                f"<b>Overage charge:</b> ₹{result.get('overage_paise', 0) / 100:.2f}"
            )
        if message:
            send_telegram_message(message)
    else:
        notify_security_event(
            "rfid_access_denied",
            "medium",
            f"RFID UID {rfid_uid} was denied at {device_code}. Reason: {result.get('reason', 'Unknown')}"
        )
    return jsonify(result), (200 if result.get("authorized") else 403)

@parking_bp.route("/parking/entry", methods=["POST"])
def parking_entry():
    """
    Entry authorization endpoint. Called by ESP32 or Admin Simulation.
    Body: { "device_code": "PARKPLUS_GATE_01", "rfid_uid": "A1B2C3D4", "event_id": "optional-id" }
    """
    if not device_or_admin_allowed():
        return jsonify({"authorized": False, "reason": "Device authentication required."}), 401
    data = request.get_json(silent=True) or {}
    device_code = data.get("device_code", "PARKPLUS_GATE_01")
    rfid_uid = data.get("rfid_uid", "").strip().upper()

    if not rfid_uid:
        return jsonify({"authorized": False, "reason": "Missing rfid_uid"}), 400

    db = get_db()
    result = process_rfid_entry(db, rfid_uid, device_code)

    status_code = 200 if result.get("authorized") else 403
    return jsonify(result), status_code

@parking_bp.route("/parking/exit/authorize", methods=["POST"])
def parking_exit_auth():
    """
    Exit authorization endpoint. Called by ESP32 or Admin Simulation.
    Body: { "device_code": "PARKPLUS_GATE_01", "rfid_uid": "A1B2C3D4" }
    """
    if not device_or_admin_allowed():
        return jsonify({"authorized": False, "reason": "Device authentication required."}), 401
    data = request.get_json(silent=True) or {}
    device_code = data.get("device_code", "PARKPLUS_GATE_01")
    rfid_uid = data.get("rfid_uid", "").strip().upper()

    if not rfid_uid:
        return jsonify({"authorized": False, "reason": "Missing rfid_uid"}), 400

    db = get_db()
    result = process_rfid_exit(db, rfid_uid, device_code)

    status_code = 200 if result.get("authorized") else 403
    return jsonify(result), status_code

@parking_bp.route("/parking/exit/confirm", methods=["POST"])
def parking_exit_confirm():
    """
    Confirmation that vehicle has safely cleared the gate barrier.
    """
    data = request.get_json(silent=True) or {}
    session_code = data.get("session_code")
    device_code = data.get("device_code", "PARKPLUS_GATE_01")

    return jsonify({
        "success": True,
        "message": "Vehicle departure confirmed at exit barrier.",
        "device_code": device_code,
        "session_code": session_code
    })

@parking_bp.route("/slots/update", methods=["POST"])
def update_slot_sensor():
    """
    ESP32 Ultrasonic sensor telemetry endpoint.
    Body:
    {
      "device_code": "PARKPLUS_GATE_01",
      "slot_code": "P01",
      "distance_cm": 12.4,
      "occupied": true,
      "sensor_health": "healthy"
    }
    """
    if not device_or_admin_allowed():
        return jsonify({"success": False, "error": "Device authentication required."}), 401
    data = request.get_json(silent=True) or {}
    device_code = data.get("device_code", "PARKPLUS_GATE_01")
    slot_code = data.get("slot_code")
    distance_cm = float(data.get("distance_cm", 25.0))
    occupied = bool(data.get("occupied", distance_cm <= Config.SLOT_DISTANCE_THRESHOLD_CM))
    sensor_health = data.get("sensor_health", "healthy")

    if not slot_code:
        return jsonify({"success": False, "error": "Missing slot_code"}), 400

    db = get_db()
    try:
        prior = db.execute("SELECT last_sensor_status FROM parking_slots WHERE slot_code = ?", (slot_code,)).fetchone()
        previous_health = (prior["last_sensor_status"] or "healthy").lower() if prior else "unknown"
        current_health = sensor_health.lower()
        res = process_sensor_telemetry(db, device_code, slot_code, distance_cm, occupied, sensor_health)
        if current_health not in ("healthy", "ok") and previous_health in ("healthy", "ok", "unknown"):
            notify_security_event("sensor_malfunction", "high", f"Sensor {slot_code} reported health={sensor_health}, distance={distance_cm} cm on {device_code}.")
        elif current_health in ("healthy", "ok") and previous_health not in ("healthy", "ok", "unknown"):
            send_telegram_message(
                "<b>🟢 PARK+ SENSOR RECOVERED</b>\n\n"
                f"<b>Slot:</b> {escape_telegram_html(slot_code)}\n"
                f"<b>Device:</b> {escape_telegram_html(device_code)}\n"
                f"<b>Time:</b> {format_telegram_time(datetime.now(timezone.utc).isoformat())}"
            )
        if res.get("assigned_session"):
            assigned = res["assigned_session"]
            send_telegram_message(
                "<b>✅ PARK+ PARKING STARTED</b>\n\n"
                f"<b>Customer:</b> {escape_telegram_html(assigned['customer_name'])}\n"
                f"<b>Vehicle:</b> {escape_telegram_html(assigned['vehicle_reg'])}\n"
                f"<b>Parking slot:</b> {escape_telegram_html(assigned['slot_code'])}\n"
                f"<b>Start time:</b> {format_telegram_time(assigned['entry_time'])}\n"
                f"<b>Session:</b> {escape_telegram_html(assigned['session_code'])}\n"
                "<b>Subscription balance before parking:</b> "
                f"{format_duration(assigned['remaining_seconds'])}"
            )
        if res.get("departure_alert"):
            send_telegram_message(
                "<b>🚨 PARK+ UNCONFIRMED DEPARTURE</b>\n\n"
                f"{escape_telegram_html(res['departure_alert'])}\n\n"
                "Please scan the RFID tag at the exit to close this parking session."
            )
        return jsonify({"success": True, "data": res})
    except Exception as ex:
        return jsonify({"success": False, "error": str(ex)}), 400

