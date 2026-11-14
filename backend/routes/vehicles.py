from flask import Blueprint, request, jsonify
from backend.database import get_db, get_utc_now_iso, dict_from_row
from backend.routes.auth import admin_required

vehicles_bp = Blueprint("vehicles", __name__, url_prefix="/api/vehicles")

@vehicles_bp.route("", methods=["GET"])
@admin_required
def get_vehicles():
    db = get_db()
    cur = db.cursor()

    search = request.args.get("search", "").strip()
    v_type = request.args.get("type", "").strip()
    user_id = request.args.get("user_id", "").strip()

    query = """
        SELECT v.*, u.full_name as customer_name, u.customer_code, u.phone as customer_phone,
               (SELECT card_uid FROM rfid_cards r WHERE r.vehicle_id = v.id LIMIT 1) as linked_card_uid,
               (SELECT COUNT(*) FROM parking_sessions ps WHERE ps.vehicle_id = v.id) as total_sessions
        FROM vehicles v
        JOIN users u ON v.user_id = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += " AND (v.registration_number LIKE ? OR v.model LIKE ? OR u.full_name LIKE ?)"
        like_term = f"%{search}%"
        params.extend([like_term, like_term, like_term])

    if v_type:
        query += " AND v.vehicle_type = ?"
        params.append(v_type)

    if user_id:
        query += " AND v.user_id = ?"
        params.append(user_id)

    query += " ORDER BY v.id DESC"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    return jsonify({"success": True, "vehicles": dict_from_row(rows)})

@vehicles_bp.route("/<int:vehicle_id>", methods=["GET"])
@admin_required
def get_vehicle_detail(vehicle_id):
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        SELECT v.*, u.full_name as customer_name, u.email as customer_email, u.phone as customer_phone
        FROM vehicles v
        JOIN users u ON v.user_id = u.id
        WHERE v.id = ?
    """, (vehicle_id,))
    v = cur.fetchone()
    if not v:
        return jsonify({"success": False, "error": "Vehicle not found"}), 404

    cur.execute("""
        SELECT ps.*, sl.slot_code
        FROM parking_sessions ps
        JOIN parking_slots sl ON ps.slot_id = sl.id
        WHERE ps.vehicle_id = ?
        ORDER BY ps.id DESC
        LIMIT 20
    """, (vehicle_id,))
    history = cur.fetchall()

    return jsonify({
        "success": True,
        "vehicle": dict_from_row(v),
        "parking_history": dict_from_row(history)
    })

@vehicles_bp.route("", methods=["POST"])
@admin_required
def create_vehicle():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    reg_no = data.get("registration_number", "").strip().upper()
    v_type = data.get("vehicle_type", "car").strip().lower()
    model = data.get("model", "").strip()
    color = data.get("color", "").strip()

    if not user_id or not reg_no:
        return jsonify({"success": False, "error": "Customer selection and vehicle registration number are required."}), 400

    db = get_db()
    cur = db.cursor()

    # Check customer
    cur.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cur.fetchone():
        return jsonify({"success": False, "error": "Selected customer does not exist."}), 404

    # Check unique registration number
    cur.execute("SELECT id FROM vehicles WHERE registration_number = ? COLLATE NOCASE", (reg_no,))
    if cur.fetchone():
        return jsonify({"success": False, "error": f"Vehicle with registration '{reg_no}' is already registered."}), 400

    utc_now = get_utc_now_iso()
    cur.execute("""
        INSERT INTO vehicles (user_id, registration_number, vehicle_type, model, color, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
    """, (user_id, reg_no, v_type, model, color, utc_now, utc_now))
    veh_id = cur.lastrowid
    db.commit()

    return jsonify({"success": True, "message": "Vehicle registered successfully.", "vehicle_id": veh_id}), 201

@vehicles_bp.route("/<int:vehicle_id>", methods=["PUT"])
@admin_required
def update_vehicle(vehicle_id):
    data = request.get_json(silent=True) or {}
    reg_no = data.get("registration_number", "").strip().upper()
    v_type = data.get("vehicle_type", "car").strip().lower()
    model = data.get("model", "").strip()
    color = data.get("color", "").strip()
    status = data.get("status", "active")

    if not reg_no:
        return jsonify({"success": False, "error": "Registration number cannot be empty."}), 400

    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT id FROM vehicles WHERE id = ?", (vehicle_id,))
    if not cur.fetchone():
        return jsonify({"success": False, "error": "Vehicle not found."}), 404

    # Unique check across others
    cur.execute("SELECT id FROM vehicles WHERE registration_number = ? COLLATE NOCASE AND id != ?", (reg_no, vehicle_id))
    if cur.fetchone():
        return jsonify({"success": False, "error": "Registration number is already registered to another vehicle."}), 400

    utc_now = get_utc_now_iso()
    cur.execute("""
        UPDATE vehicles 
        SET registration_number = ?, vehicle_type = ?, model = ?, color = ?, status = ?, updated_at = ?
        WHERE id = ?
    """, (reg_no, v_type, model, color, status, utc_now, vehicle_id))
    db.commit()

    return jsonify({"success": True, "message": "Vehicle details updated successfully."})

@vehicles_bp.route("/<int:vehicle_id>", methods=["DELETE"])
@admin_required
def delete_vehicle(vehicle_id):
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,))
    veh = cur.fetchone()
    if not veh:
        return jsonify({"success": False, "error": "Vehicle not found"}), 404

    # Check if vehicle has active session
    cur.execute("SELECT id FROM parking_sessions WHERE vehicle_id = ? AND status = 'active'", (vehicle_id,))
    if cur.fetchone():
        return jsonify({"success": False, "error": "Cannot delete vehicle while it is parked in an active session."}), 400

    try:
        # Nullify any linked rfid card
        cur.execute("UPDATE rfid_cards SET vehicle_id = NULL WHERE vehicle_id = ?", (vehicle_id,))
        # Soft delete or hard delete if no sessions
        cur.execute("SELECT COUNT(*) as count FROM parking_sessions WHERE vehicle_id = ?", (vehicle_id,))
        count = cur.fetchone()["count"]
        if count > 0:
            # Soft delete to preserve historical integrity
            utc_now = get_utc_now_iso()
            cur.execute("UPDATE vehicles SET status = 'inactive', updated_at = ? WHERE id = ?", (utc_now, vehicle_id))
            msg = "Vehicle marked as inactive (preserved for session history)."
        else:
            cur.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
            msg = "Vehicle deleted permanently."
        db.commit()
        return jsonify({"success": True, "message": msg})
    except Exception as ex:
        db.rollback()
        return jsonify({"success": False, "error": str(ex)}), 500

