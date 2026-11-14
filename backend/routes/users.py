import uuid
from flask import Blueprint, request, jsonify
from backend.database import get_db, get_utc_now_iso, dict_from_row
from backend.routes.auth import admin_required

users_bp = Blueprint("users", __name__, url_prefix="/api/users")

@users_bp.route("", methods=["GET"])
@admin_required
def get_users():
    db = get_db()
    cur = db.cursor()
    
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()

    query = """
        SELECT u.*, 
               (SELECT COUNT(*) FROM vehicles v WHERE v.user_id = u.id) as vehicle_count,
               (SELECT COUNT(*) FROM rfid_cards r WHERE r.user_id = u.id) as card_count,
               (SELECT remaining_balance_seconds FROM subscriptions s 
                WHERE s.user_id = u.id AND s.status = 'active' 
                ORDER BY s.remaining_balance_seconds DESC LIMIT 1) as active_balance_seconds
        FROM users u
        WHERE 1=1
    """
    params = []

    if search:
        query += " AND (u.full_name LIKE ? OR u.email LIKE ? OR u.phone LIKE ? OR u.customer_code LIKE ?)"
        like_term = f"%{search}%"
        params.extend([like_term, like_term, like_term, like_term])

    if status:
        query += " AND u.account_status = ?"
        params.append(status)

    query += " ORDER BY u.id DESC"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    return jsonify({"success": True, "users": dict_from_row(rows)})

@users_bp.route("/<int:user_id>", methods=["GET"])
@admin_required
def get_user_profile(user_id):
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        return jsonify({"success": False, "error": "Customer not found"}), 404

    # Associated Vehicles
    cur.execute("SELECT * FROM vehicles WHERE user_id = ? ORDER BY id DESC", (user_id,))
    vehicles = cur.fetchall()

    # Associated RFID Cards
    cur.execute("""
        SELECT r.*, v.registration_number
        FROM rfid_cards r
        LEFT JOIN vehicles v ON r.vehicle_id = v.id
        WHERE r.user_id = ?
        ORDER BY r.id DESC
    """, (user_id,))
    rfid_cards = cur.fetchall()

    # Subscriptions
    cur.execute("""
        SELECT s.*, p.name as plan_name, p.plan_type
        FROM subscriptions s
        JOIN subscription_plans p ON s.plan_id = p.id
        WHERE s.user_id = ?
        ORDER BY s.id DESC
    """, (user_id,))
    subscriptions = cur.fetchall()

    # Parking History
    cur.execute("""
        SELECT ps.*, v.registration_number, sl.slot_code
        FROM parking_sessions ps
        JOIN vehicles v ON ps.vehicle_id = v.id
        JOIN parking_slots sl ON ps.slot_id = sl.id
        WHERE ps.user_id = ?
        ORDER BY ps.id DESC
        LIMIT 20
    """, (user_id,))
    parking_history = cur.fetchall()

    return jsonify({
        "success": True,
        "user": dict_from_row(user),
        "vehicles": dict_from_row(vehicles),
        "rfid_cards": dict_from_row(rfid_cards),
        "subscriptions": dict_from_row(subscriptions),
        "parking_history": dict_from_row(parking_history)
    })

@users_bp.route("", methods=["POST"])
@admin_required
def create_user():
    data = request.get_json(silent=True) or {}
    full_name = data.get("full_name", "").strip()
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    address = data.get("address", "").strip()
    notes = data.get("notes", "").strip()

    if not full_name or not email or not phone:
        return jsonify({"success": False, "error": "Full name, email, and phone number are required."}), 400

    db = get_db()
    cur = db.cursor()

    # Email uniqueness check
    cur.execute("SELECT id FROM users WHERE email = ? COLLATE NOCASE", (email,))
    if cur.fetchone():
        return jsonify({"success": False, "error": "A customer with this email address already exists."}), 400

    utc_now = get_utc_now_iso()
    customer_code = f"CUST-{uuid.uuid4().hex[:6].upper()}"

    cur.execute("""
        INSERT INTO users (customer_code, full_name, email, phone, address, notes, account_status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
    """, (customer_code, full_name, email, phone, address, notes, utc_now, utc_now))
    user_id = cur.lastrowid
    db.commit()

    return jsonify({
        "success": True,
        "message": "Customer created successfully.",
        "user_id": user_id,
        "customer_code": customer_code
    }), 201

@users_bp.route("/<int:user_id>", methods=["PUT"])
@admin_required
def update_user(user_id):
    data = request.get_json(silent=True) or {}
    full_name = data.get("full_name", "").strip()
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    address = data.get("address", "").strip()
    notes = data.get("notes", "").strip()
    account_status = data.get("account_status", "active")

    if not full_name or not email or not phone:
        return jsonify({"success": False, "error": "Full name, email, and phone number are required."}), 400

    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cur.fetchone():
        return jsonify({"success": False, "error": "Customer not found."}), 404

    # Check email duplicate across other users
    cur.execute("SELECT id FROM users WHERE email = ? COLLATE NOCASE AND id != ?", (email, user_id))
    if cur.fetchone():
        return jsonify({"success": False, "error": "Another customer already uses this email address."}), 400

    utc_now = get_utc_now_iso()
    cur.execute("""
        UPDATE users 
        SET full_name = ?, email = ?, phone = ?, address = ?, notes = ?, account_status = ?, updated_at = ?
        WHERE id = ?
    """, (full_name, email, phone, address, notes, account_status, utc_now, user_id))
    db.commit()

    return jsonify({"success": True, "message": "Customer profile updated successfully."})

@users_bp.route("/<int:user_id>/status", methods=["PATCH"])
@admin_required
def change_status(user_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status", "").strip().lower()

    if status not in ("active", "inactive", "suspended"):
        return jsonify({"success": False, "error": "Invalid status. Allowed values: active, inactive, suspended"}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cur.fetchone():
        return jsonify({"success": False, "error": "Customer not found"}), 404

    utc_now = get_utc_now_iso()
    cur.execute("UPDATE users SET account_status = ?, updated_at = ? WHERE id = ?", (status, utc_now, user_id))
    db.commit()

    return jsonify({"success": True, "message": f"Customer status changed to {status}."})

@users_bp.route("/<int:user_id>", methods=["DELETE"])
@admin_required
def delete_user(user_id):
    data = request.get_json(silent=True) or {}
    purge_history = data.get("purge_history") is True
    db = get_db()
    cur = db.cursor()
    cur.execute("BEGIN IMMEDIATE")

    cur.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cur.fetchone():
        db.rollback()
        return jsonify({"success": False, "error": "Customer not found."}), 404

    cur.execute("""
        SELECT id FROM parking_sessions
        WHERE (user_id = ? OR vehicle_id IN (
            SELECT id FROM vehicles WHERE user_id = ?
        )) AND status IN ('active', 'overstay')
        LIMIT 1
    """, (user_id, user_id))
    if cur.fetchone():
        db.rollback()
        return jsonify({
            "success": False,
            "error": "Cannot delete a customer with a vehicle in an active parking session. Complete the RFID exit first."
        }), 409

    cur.execute("""
        SELECT id FROM parking_slots
        WHERE is_occupied = 1 AND current_vehicle_id IN (
            SELECT id FROM vehicles WHERE user_id = ?
        )
        LIMIT 1
    """, (user_id,))
    if cur.fetchone():
        db.rollback()
        return jsonify({
            "success": False,
            "error": "Cannot delete a customer while one of their vehicles is detected in an occupied parking slot."
        }), 409

    cur.execute("""
        SELECT id FROM pending_gate_entries
        WHERE user_id = ? AND status = 'pending'
        LIMIT 1
    """, (user_id,))
    if cur.fetchone():
        db.rollback()
        return jsonify({
            "success": False,
            "error": "Cannot delete a customer with a pending gate entry. Wait for it to expire, then try again."
        }), 409

    cur.execute("""
        SELECT 1
        WHERE EXISTS (
            SELECT 1 FROM parking_sessions
            WHERE user_id = ? OR vehicle_id IN (
                SELECT id FROM vehicles WHERE user_id = ?
            )
        )
        OR EXISTS (SELECT 1 FROM subscriptions WHERE user_id = ?)
        OR EXISTS (
            SELECT 1 FROM subscription_transactions
            WHERE user_id = ? OR subscription_id IN (
                SELECT id FROM subscriptions WHERE user_id = ?
            )
        )
        LIMIT 1
    """, (user_id, user_id, user_id, user_id, user_id))
    has_history = cur.fetchone() is not None
    if has_history and not purge_history:
        db.rollback()
        return jsonify({
            "success": False,
            "error": "This customer has parking or subscription history. Confirm permanent history deletion to continue."
        }), 409

    cur.execute("""
        DELETE FROM rfid_scan_logs
        WHERE user_id = ?
           OR vehicle_id IN (SELECT id FROM vehicles WHERE user_id = ?)
           OR card_uid IN (
               SELECT card_uid FROM rfid_cards
               WHERE user_id = ?
                  OR vehicle_id IN (SELECT id FROM vehicles WHERE user_id = ?)
           )
    """, (user_id, user_id, user_id, user_id))
    cur.execute("""
        DELETE FROM subscription_transactions
        WHERE user_id = ?
           OR subscription_id IN (
               SELECT id FROM subscriptions WHERE user_id = ?
           )
           OR parking_session_id IN (
               SELECT id FROM parking_sessions
               WHERE user_id = ? OR vehicle_id IN (
                   SELECT id FROM vehicles WHERE user_id = ?
               )
           )
    """, (user_id, user_id, user_id, user_id))
    cur.execute("""
        DELETE FROM parking_sessions
        WHERE user_id = ? OR vehicle_id IN (
            SELECT id FROM vehicles WHERE user_id = ?
        )
    """, (user_id, user_id))
    cur.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
    cur.execute("""
        DELETE FROM rfid_cards
        WHERE user_id = ?
           OR vehicle_id IN (SELECT id FROM vehicles WHERE user_id = ?)
    """, (user_id, user_id))
    cur.execute("DELETE FROM vehicles WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()

    return jsonify({
        "success": True,
        "message": "Customer, vehicles, RFID cards and scans, parking sessions, subscriptions, and transaction history deleted. Security events and support tickets were retained without the customer link."
    })

