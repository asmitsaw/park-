import uuid
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify
from backend.database import get_db, get_utc_now_iso, dict_from_row
from backend.routes.auth import admin_required

subscriptions_bp = Blueprint("subscriptions", __name__, url_prefix="/api/subscriptions")

@subscriptions_bp.route("", methods=["GET"])
@admin_required
def get_subscriptions():
    db = get_db()
    cur = db.cursor()

    user_id = request.args.get("user_id")
    status = request.args.get("status")

    query = """
        SELECT s.*, u.full_name as customer_name, u.email as customer_email, u.phone as customer_phone,
               p.name as plan_name, p.plan_type, p.plan_code
        FROM subscriptions s
        JOIN users u ON s.user_id = u.id
        JOIN subscription_plans p ON s.plan_id = p.id
        WHERE 1=1
    """
    params = []
    if user_id:
        query += " AND s.user_id = ?"
        params.append(user_id)
    if status:
        query += " AND s.status = ?"
        params.append(status)

    query += " ORDER BY s.id DESC"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    return jsonify({"success": True, "subscriptions": dict_from_row(rows)})

@subscriptions_bp.route("/plans", methods=["GET"])
@admin_required
def get_plans():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT p.*, (SELECT COUNT(*) FROM subscriptions s WHERE s.plan_id = p.id) as subscriber_count
        FROM subscription_plans p 
        ORDER BY p.id ASC
    """)
    plans = cur.fetchall()
    return jsonify({"success": True, "plans": dict_from_row(plans)})

@subscriptions_bp.route("/plans", methods=["POST"])
@admin_required
def create_plan():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    plan_type = data.get("plan_type", "prepaid").strip().lower()
    duration_days = int(data.get("duration_days", 30))
    hours = float(data.get("allocated_hours", 10.0))
    price_inr = float(data.get("price_inr", 499.0))
    description = data.get("description", "").strip()

    if not name or hours <= 0 or price_inr < 0 or duration_days <= 0:
        return jsonify({"success": False, "error": "Invalid plan parameters. Check name, hours, validity, and price."}), 400

    if plan_type not in ("monthly", "prepaid"):
        return jsonify({"success": False, "error": "Plan type must be 'monthly' or 'prepaid'."}), 400

    allocated_seconds = int(hours * 3600)
    price_paise = int(round(price_inr * 100))
    plan_code = f"{plan_type.upper()}-{int(hours)}H-{uuid.uuid4().hex[:4].upper()}"

    db = get_db()
    cur = db.cursor()
    utc_now = get_utc_now_iso()

    cur.execute("""
        INSERT INTO subscription_plans (plan_code, name, plan_type, duration_days, allocated_seconds, price_paise, description, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
    """, (plan_code, name, plan_type, duration_days, allocated_seconds, price_paise, description, utc_now, utc_now))
    plan_id = cur.lastrowid
    db.commit()

    return jsonify({"success": True, "message": "Subscription plan created.", "plan_id": plan_id}), 201

@subscriptions_bp.route("/assign", methods=["POST"])
@admin_required
def assign_subscription():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    plan_id = data.get("plan_id")
    auto_renew = 1 if data.get("auto_renew") else 0

    if not user_id or not plan_id:
        return jsonify({"success": False, "error": "Customer and subscription plan must be specified."}), 400

    db = get_db()
    cur = db.cursor()

    # Verify user
    cur.execute("SELECT id, full_name, account_status FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        return jsonify({"success": False, "error": "Customer not found."}), 404
    if user["account_status"] != "active":
        return jsonify({"success": False, "error": f"Cannot assign plan: customer account is {user['account_status']}."}), 400

    # Verify plan
    cur.execute("SELECT * FROM subscription_plans WHERE id = ? AND is_active = 1", (plan_id,))
    plan = cur.fetchone()
    if not plan:
        return jsonify({"success": False, "error": "Active subscription plan not found."}), 404

    utc_now = get_utc_now_iso()
    start_date = utc_now
    expiry_date = (datetime.now(timezone.utc) + timedelta(days=plan["duration_days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    sub_code = f"SUB-{datetime.now(timezone.utc).strftime('%Y%m')}-{uuid.uuid4().hex[:4].upper()}"

    try:
        # Create subscription
        cur.execute("""
            INSERT INTO subscriptions 
            (subscription_code, user_id, plan_id, total_allocated_seconds, remaining_balance_seconds, consumed_seconds, price_paid_paise, start_date, expiry_date, status, auto_renew, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 'active', ?, ?, ?)
        """, (sub_code, user_id, plan_id, plan["allocated_seconds"], plan["allocated_seconds"], plan["price_paise"], start_date, expiry_date, auto_renew, utc_now, utc_now))
        sub_id = cur.lastrowid

        # Immutable ledger transaction entry
        txn_code = f"TXN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
        cur.execute("""
            INSERT INTO subscription_transactions 
            (transaction_code, subscription_id, user_id, transaction_type, seconds_amount, balance_after_seconds, amount_paise, description, created_at)
            VALUES (?, ?, ?, 'credit', ?, ?, ?, ?, ?)
        """, (txn_code, sub_id, user_id, plan["allocated_seconds"], plan["allocated_seconds"], plan["price_paise"], f"Purchased {plan['name']} ({plan['allocated_seconds']}s credited)", utc_now))

        db.commit()

        return jsonify({
            "success": True,
            "message": f"Assigned '{plan['name']}' to {user['full_name']}.",
            "subscription_id": sub_id,
            "subscription_code": sub_code,
            "allocated_seconds": plan["allocated_seconds"],
            "expiry_date": expiry_date
        }), 201
    except Exception as ex:
        db.rollback()
        return jsonify({"success": False, "error": str(ex)}), 500

@subscriptions_bp.route("/<int:sub_id>/status", methods=["PATCH"])
@admin_required
def update_subscription_status(sub_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status", "").strip().lower()

    if status not in ("active", "expired", "exhausted", "cancelled"):
        return jsonify({"success": False, "error": "Invalid status."}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM subscriptions WHERE id = ?", (sub_id,))
    if not cur.fetchone():
        return jsonify({"success": False, "error": "Subscription not found."}), 404

    utc_now = get_utc_now_iso()
    cur.execute("UPDATE subscriptions SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now, sub_id))
    db.commit()

    return jsonify({"success": True, "message": f"Subscription status updated to {status}."})

@subscriptions_bp.route("/<int:sub_id>/transactions", methods=["GET"])
@admin_required
def get_subscription_transactions(sub_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT t.*, u.full_name as customer_name, ps.session_code
        FROM subscription_transactions t
        JOIN users u ON t.user_id = u.id
        LEFT JOIN parking_sessions ps ON t.parking_session_id = ps.id
        WHERE t.subscription_id = ?
        ORDER BY t.id DESC
    """, (sub_id,))
    txns = cur.fetchall()
    return jsonify({"success": True, "transactions": dict_from_row(txns)})

@subscriptions_bp.route("/transactions", methods=["GET"])
@admin_required
def get_all_transactions():
    db = get_db()
    cur = db.cursor()
    limit = int(request.args.get("limit", 100))
    cur.execute("""
        SELECT t.*, u.full_name as customer_name, u.customer_code, s.subscription_code, ps.session_code
        FROM subscription_transactions t
        JOIN users u ON t.user_id = u.id
        JOIN subscriptions s ON t.subscription_id = s.id
        LEFT JOIN parking_sessions ps ON t.parking_session_id = ps.id
        ORDER BY t.id DESC
        LIMIT ?
    """, (limit,))
    txns = cur.fetchall()
    return jsonify({"success": True, "transactions": dict_from_row(txns)})

