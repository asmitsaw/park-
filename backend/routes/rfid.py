import hmac
import re
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, session
from backend.database import get_db, get_utc_now_iso, dict_from_row
from backend.config import Config
from backend.routes.auth import admin_required
from backend.services.parking_service import process_rfid_entry, process_rfid_exit

rfid_bp = Blueprint("rfid", __name__, url_prefix="/api/rfid")

def device_authenticated():
    token = request.headers.get("X-Device-Token", "")
    return hmac.compare_digest(token, Config.DEVICE_SHARED_SECRET)


@rfid_bp.route("/cards", methods=["GET"])
@admin_required
def get_cards():
    db = get_db()
    cur = db.cursor()

    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()

    query = """
        SELECT r.*, u.full_name as customer_name, u.customer_code, v.registration_number, v.model as vehicle_model,
               (SELECT COUNT(*) FROM rfid_scan_logs sl WHERE sl.card_uid = r.card_uid) as total_scans
        FROM rfid_cards r
        LEFT JOIN users u ON r.user_id = u.id
        LEFT JOIN vehicles v ON r.vehicle_id = v.id
        WHERE 1=1
    """
    params = []

    if search:
        query += " AND (r.card_uid LIKE ? OR r.card_label LIKE ? OR u.full_name LIKE ? OR v.registration_number LIKE ?)"
        like_term = f"%{search}%"
        params.extend([like_term, like_term, like_term, like_term])

    if status:
        query += " AND r.status = ?"
        params.append(status)

    query += " ORDER BY r.id DESC"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    return jsonify({"success": True, "cards": dict_from_row(rows)})

@rfid_bp.route("/register", methods=["POST"])
@admin_required
def register_card():
    data = request.get_json(silent=True) or {}
    card_uid = data.get("card_uid", "").strip().upper()
    card_label = data.get("card_label", "").strip()
    user_id = data.get("user_id") or None
    vehicle_id = data.get("vehicle_id") or None
    status = data.get("status", "active")

    if not card_uid:
        return jsonify({"success": False, "error": "Card UID is required."}), 400

    # Basic format check (hex characters)
    if not re.fullmatch(r"[0-9A-Fa-f]{4,16}", card_uid):
        return jsonify({"success": False, "error": "Invalid RFID UID format. Expected 4 to 16 hexadecimal characters."}), 400

    db = get_db()
    cur = db.cursor()

    # Check duplicate card UID
    cur.execute("SELECT id FROM rfid_cards WHERE card_uid = ? COLLATE NOCASE", (card_uid,))
    if cur.fetchone():
        return jsonify({"success": False, "error": f"Card with UID '{card_uid}' is already registered in the system."}), 400

    # If vehicle_id provided, ensure it belongs to user_id
    if vehicle_id and user_id:
        cur.execute("SELECT id FROM vehicles WHERE id = ? AND user_id = ?", (vehicle_id, user_id))
        if not cur.fetchone():
            return jsonify({"success": False, "error": "The selected vehicle does not belong to the selected customer."}), 400

    utc_now = get_utc_now_iso()
    cur.execute("""
        INSERT INTO rfid_cards (card_uid, user_id, vehicle_id, card_label, status, issue_date, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (card_uid, user_id, vehicle_id, card_label or f"Tag {card_uid}", status, utc_now, utc_now, utc_now))
    card_id = cur.lastrowid
    db.commit()

    return jsonify({"success": True, "message": "RFID card registered successfully.", "card_id": card_id}), 201

@rfid_bp.route("/capture/request", methods=["POST"])
@admin_required
def request_rfid_capture():
    data = request.get_json(silent=True) or {}
    device_code = data.get("device_code", "PARKPLUS_GATE_01")
    if not isinstance(device_code, str) or not device_code.strip():
        return jsonify({"success": False, "error": "A valid device_code is required."}), 400
    device_code = device_code.strip()

    db = get_db()
    cur = db.cursor()
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute("""
        UPDATE rfid_capture_requests
        SET status = 'expired', completed_at = ?
        WHERE status IN ('pending', 'ready') AND expires_at <= ?
    """, (now_iso, now_iso))
    cur.execute("""
        SELECT id FROM rfid_capture_requests
        WHERE device_code = ? AND status IN ('pending', 'ready') AND expires_at > ?
        ORDER BY id DESC LIMIT 1
    """, (device_code, now_iso))
    existing = cur.fetchone()
    if existing:
        db.commit()
        return jsonify({
            "success": False,
            "error": "An RFID capture is already waiting for this reader.",
            "request_id": existing["id"]
        }), 409

    expires_at = (now + timedelta(seconds=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute("""
        INSERT INTO rfid_capture_requests (device_code, status, requested_at, expires_at, created_by)
        VALUES (?, 'pending', ?, ?, ?)
    """, (device_code, now_iso, expires_at, session["admin_id"]))
    request_id = cur.lastrowid
    db.commit()
    return jsonify({
        "success": True,
        "request_id": request_id,
        "status": "pending",
        "expires_at": expires_at
    }), 202

@rfid_bp.route("/capture/request/<int:request_id>", methods=["GET"])
@admin_required
def get_rfid_capture_status(request_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM rfid_capture_requests WHERE id = ?", (request_id,))
    capture = cur.fetchone()
    if not capture:
        return jsonify({"success": False, "error": "RFID capture request not found."}), 404

    status = capture["status"]
    if status in ("pending", "ready") and capture["expires_at"] <= get_utc_now_iso():
        cur.execute("""
            UPDATE rfid_capture_requests
            SET status = 'expired', completed_at = ?
            WHERE id = ? AND status IN ('pending', 'ready')
        """, (get_utc_now_iso(), request_id))
        db.commit()
        status = "expired"

    return jsonify({
        "success": True,
        "request_id": request_id,
        "status": status,
        "card_uid": capture["card_uid"] if status == "captured" else None,
        "expires_at": capture["expires_at"]
    })

@rfid_bp.route("/capture/request/<int:request_id>/cancel", methods=["POST"])
@admin_required
def cancel_rfid_capture(request_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE rfid_capture_requests
        SET status = 'cancelled', completed_at = ?
        WHERE id = ? AND status IN ('pending', 'ready')
    """, (get_utc_now_iso(), request_id))
    if not cur.rowcount:
        cur.execute("SELECT status FROM rfid_capture_requests WHERE id = ?", (request_id,))
        capture = cur.fetchone()
        if not capture:
            return jsonify({"success": False, "error": "RFID capture request not found."}), 404
        return jsonify({"success": False, "error": "Only active RFID capture requests can be cancelled."}), 409

    db.commit()
    return jsonify({"success": True, "status": "cancelled"})

@rfid_bp.route("/capture/pending", methods=["GET"])
def get_pending_rfid_capture():
    if not device_authenticated():
        return jsonify({"success": False, "error": "Valid device authentication is required."}), 401

    device_code = request.args.get("device_code", "PARKPLUS_GATE_01").strip()
    if not device_code:
        return jsonify({"success": False, "error": "Missing device_code."}), 400

    db = get_db()
    cur = db.cursor()
    now = get_utc_now_iso()
    cur.execute("""
        UPDATE rfid_capture_requests
        SET status = 'expired', completed_at = ?
        WHERE status IN ('pending', 'ready') AND expires_at <= ?
    """, (now, now))
    cur.execute("""
        SELECT id FROM rfid_capture_requests
        WHERE device_code = ? AND status IN ('pending', 'ready') AND expires_at > ?
        ORDER BY id DESC LIMIT 1
    """, (device_code, now))
    capture = cur.fetchone()
    if capture:
        cur.execute("""
            UPDATE rfid_capture_requests SET status = 'ready'
            WHERE id = ? AND status = 'pending'
        """, (capture["id"],))
    db.commit()
    return jsonify({
        "success": True,
        "capture_requested": capture is not None,
        "request_id": capture["id"] if capture else None
    })

@rfid_bp.route("/capture/result", methods=["POST"])
def submit_rfid_capture():
    if not device_authenticated():
        return jsonify({"success": False, "error": "Valid device authentication is required."}), 401

    data = request.get_json(silent=True) or {}
    try:
        request_id = int(data.get("request_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "A valid request_id is required."}), 400

    card_uid = data.get("card_uid", "")
    if not isinstance(card_uid, str) or not re.fullmatch(r"[0-9A-Fa-f]{4,16}", card_uid.strip()):
        return jsonify({"success": False, "error": "Invalid RFID UID. Expected 4 to 16 hexadecimal characters."}), 400
    card_uid = card_uid.strip().upper()

    device_code = data.get("device_code", "PARKPLUS_GATE_01")
    if not isinstance(device_code, str) or not device_code.strip():
        return jsonify({"success": False, "error": "A valid device_code is required."}), 400

    db = get_db()
    cur = db.cursor()
    now = get_utc_now_iso()
    cur.execute("""
        UPDATE rfid_capture_requests
        SET status = 'captured', card_uid = ?, completed_at = ?
        WHERE id = ? AND device_code = ? AND status = 'ready' AND expires_at > ?
    """, (card_uid, now, request_id, device_code.strip(), now))
    if not cur.rowcount:
        cur.execute("SELECT status FROM rfid_capture_requests WHERE id = ?", (request_id,))
        capture = cur.fetchone()
        if not capture:
            return jsonify({"success": False, "error": "RFID capture request not found."}), 404
        return jsonify({"success": False, "error": "RFID capture request is no longer pending."}), 409

    db.commit()
    return jsonify({"success": True, "request_id": request_id, "card_uid": card_uid, "status": "captured"})

@rfid_bp.route("/<int:card_id>/status", methods=["PATCH"])
@admin_required
def update_card_status(card_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status", "").strip().lower()

    if status not in ("active", "inactive", "blocked"):
        return jsonify({"success": False, "error": "Invalid status. Allowed values: active, inactive, blocked"}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM rfid_cards WHERE id = ?", (card_id,))
    if not cur.fetchone():
        return jsonify({"success": False, "error": "Card not found"}), 404

    utc_now = get_utc_now_iso()
    cur.execute("UPDATE rfid_cards SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now, card_id))
    db.commit()

    return jsonify({"success": True, "message": f"Card status changed to {status}."})

@rfid_bp.route("/<int:card_id>", methods=["PUT"])
@admin_required
def update_card(card_id):
    data = request.get_json(silent=True) or {}
    card_label = data.get("card_label", "").strip()
    user_id = data.get("user_id") or None
    vehicle_id = data.get("vehicle_id") or None
    status = data.get("status", "active")

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM rfid_cards WHERE id = ?", (card_id,))
    if not cur.fetchone():
        return jsonify({"success": False, "error": "Card not found"}), 404

    utc_now = get_utc_now_iso()
    cur.execute("""
        UPDATE rfid_cards
        SET card_label = ?, user_id = ?, vehicle_id = ?, status = ?, updated_at = ?
        WHERE id = ?
    """, (card_label, user_id, vehicle_id, status, utc_now, card_id))
    db.commit()

    return jsonify({"success": True, "message": "RFID card updated successfully."})

@rfid_bp.route("/scans", methods=["GET"])
@admin_required
def get_scans():
    db = get_db()
    cur = db.cursor()
    
    limit = int(request.args.get("limit", 50))
    query = """
        SELECT s.*, u.full_name as customer_name, v.registration_number
        FROM rfid_scan_logs s
        LEFT JOIN users u ON s.user_id = u.id
        LEFT JOIN vehicles v ON s.vehicle_id = v.id
        ORDER BY s.id DESC
        LIMIT ?
    """
    cur.execute(query, (limit,))
    rows = cur.fetchall()

    return jsonify({"success": True, "scans": dict_from_row(rows)})

@rfid_bp.route("/unregistered", methods=["GET"])
@admin_required
def get_unregistered_scans():
    db = get_db()
    cur = db.cursor()
    
    cur.execute("""
        SELECT card_uid, device_code, denial_reason, scanned_at, COUNT(*) as attempt_count
        FROM rfid_scan_logs
        WHERE is_authorized = 0 AND denial_reason LIKE '%Unregistered%'
        GROUP BY card_uid
        ORDER BY scanned_at DESC
        LIMIT 20
    """)
    rows = cur.fetchall()
    return jsonify({"success": True, "unregistered_scans": dict_from_row(rows)})

@rfid_bp.route("/scan", methods=["POST"])
def simulated_or_direct_scan():
    """
    Scan endpoint accepting both hardware and admin simulator requests.
    """
    data = request.get_json(silent=True) or {}
    card_uid = data.get("rfid_uid", "") or data.get("card_uid", "")
    card_uid = card_uid.strip().upper()
    scan_type = data.get("scan_type", "entry").lower()  # 'entry' or 'exit'
    device_code = data.get("device_code", "PARKPLUS_GATE_01")

    if not card_uid:
        return jsonify({"authorized": False, "reason": "No RFID UID provided"}), 400

    db = get_db()
    if scan_type == "exit":
        result = process_rfid_exit(db, card_uid, device_code)
    else:
        result = process_rfid_entry(db, card_uid, device_code)

    return jsonify(result), (200 if result.get("authorized") else 403)

