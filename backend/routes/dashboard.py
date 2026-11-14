from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify
from backend.database import get_db, dict_from_row
from backend.routes.auth import admin_required

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")

@dashboard_bp.route("/summary", methods=["GET"])
@admin_required
def summary():
    db = get_db()
    cur = db.cursor()
    utc_today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Slot status
    cur.execute("""
        SELECT p.*, v.registration_number, v.model as vehicle_model, u.full_name as customer_name, s.entry_time, s.session_code
        FROM parking_slots p
        LEFT JOIN vehicles v ON p.current_vehicle_id = v.id
        LEFT JOIN users u ON v.user_id = u.id
        LEFT JOIN parking_sessions s ON p.current_session_id = s.id
        ORDER BY p.slot_code ASC
    """)
    slots_rows = cur.fetchall()
    slots = [dict_from_row(s) for s in slots_rows]

    total_slots = len(slots)
    occupied_slots = sum(1 for s in slots if s["is_occupied"])
    available_slots = total_slots - occupied_slots

    # Calculate real-time duration for occupied slots
    now_dt = datetime.now(timezone.utc)
    for s in slots:
        if s["is_occupied"] and s["entry_time"]:
            try:
                entry_dt = datetime.fromisoformat(s["entry_time"].replace("Z", "+00:00"))
                s["duration_seconds"] = int((now_dt - entry_dt).total_seconds())
            except Exception:
                s["duration_seconds"] = 0
        else:
            s["duration_seconds"] = 0

    # 2. Customers
    cur.execute("SELECT COUNT(*) as count FROM users WHERE account_status = 'active'")
    total_active_customers = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) as count FROM users")
    total_customers = cur.fetchone()["count"]

    # 3. Active Subscriptions
    utc_now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute("""
        SELECT COUNT(*) as count FROM subscriptions 
        WHERE status = 'active' AND expiry_date >= ?
    """, (utc_now_iso,))
    active_subscriptions = cur.fetchone()["count"]

    # 4. Vehicles currently parked
    cur.execute("SELECT COUNT(*) as count FROM parking_sessions WHERE status = 'active'")
    vehicles_parked = cur.fetchone()["count"]

    # 5. Today's entries & exits
    cur.execute("SELECT COUNT(*) as count FROM parking_sessions WHERE entry_time >= ?", (utc_today + "T00:00:00Z",))
    today_entries = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) as count FROM parking_sessions WHERE status = 'completed' AND exit_time >= ?", (utc_today + "T00:00:00Z",))
    today_exits = cur.fetchone()["count"]

    # 6. Active security incidents
    cur.execute("SELECT COUNT(*) as count FROM security_events WHERE status IN ('open', 'investigating')")
    active_incidents = cur.fetchone()["count"]

    return jsonify({
        "success": True,
        "kpis": {
            "total_slots": total_slots,
            "available_slots": available_slots,
            "occupied_slots": occupied_slots,
            "total_customers": total_customers,
            "total_active_customers": total_active_customers,
            "active_subscriptions": active_subscriptions,
            "vehicles_currently_parked": vehicles_parked,
            "today_entries": today_entries,
            "today_exits": today_exits,
            "active_security_incidents": active_incidents
        },
        "slots": slots
    })

@dashboard_bp.route("/charts", methods=["GET"])
@admin_required
def charts():
    db = get_db()
    cur = db.cursor()

    # 1. Past 7 days entries vs exits
    now = datetime.now(timezone.utc)
    dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    entries_by_day = []
    exits_by_day = []

    for d in dates:
        start_iso = f"{d}T00:00:00Z"
        end_iso = f"{d}T23:59:59Z"
        
        cur.execute("SELECT COUNT(*) as count FROM parking_sessions WHERE entry_time BETWEEN ? AND ?", (start_iso, end_iso))
        entries_by_day.append(cur.fetchone()["count"])

        cur.execute("SELECT COUNT(*) as count FROM parking_sessions WHERE exit_time BETWEEN ? AND ?", (start_iso, end_iso))
        exits_by_day.append(cur.fetchone()["count"])

    # 2. Subscription plans distribution
    cur.execute("""
        SELECT p.name, COUNT(s.id) as count
        FROM subscription_plans p
        LEFT JOIN subscriptions s ON p.id = s.plan_id
        GROUP BY p.id
    """)
    plans_dist = cur.fetchall()
    plan_labels = [row["name"] for row in plans_dist]
    plan_counts = [row["count"] for row in plans_dist]

    # 3. Security incidents by severity
    cur.execute("""
        SELECT severity, COUNT(*) as count 
        FROM security_events 
        GROUP BY severity
    """)
    sec_rows = cur.fetchall()
    severity_map = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for r in sec_rows:
        if r["severity"] in severity_map:
            severity_map[r["severity"]] = r["count"]

    # 4. Slot utilization
    cur.execute("""
        SELECT p.slot_code, COUNT(s.id) as session_count
        FROM parking_slots p
        LEFT JOIN parking_sessions s ON p.id = s.slot_id
        GROUP BY p.id
    """)
    slot_util = cur.fetchall()

    return jsonify({
        "success": True,
        "daily_trends": {
            "labels": [datetime.strptime(d, "%Y-%m-%d").strftime("%b %d") for d in dates],
            "entries": entries_by_day,
            "exits": exits_by_day
        },
        "subscription_plans": {
            "labels": plan_labels,
            "counts": plan_counts
        },
        "incidents_by_severity": {
            "labels": ["Low", "Medium", "High", "Critical"],
            "counts": [severity_map["low"], severity_map["medium"], severity_map["high"], severity_map["critical"]]
        },
        "slot_utilization": {
            "labels": [r["slot_code"] for r in slot_util],
            "counts": [r["session_count"] for r in slot_util]
        }
    })

@dashboard_bp.route("/activity", methods=["GET"])
@admin_required
def activity():
    db = get_db()
    cur = db.cursor()

    # 1. Latest RFID Scans
    cur.execute("""
        SELECT s.*, u.full_name as customer_name, v.registration_number
        FROM rfid_scan_logs s
        LEFT JOIN users u ON s.user_id = u.id
        LEFT JOIN vehicles v ON s.vehicle_id = v.id
        ORDER BY s.id DESC
        LIMIT 8
    """)
    scans = dict_from_row(cur.fetchall())

    # 2. Recent Active / Closed Sessions
    cur.execute("""
        SELECT s.*, u.full_name as customer_name, v.registration_number, p.slot_code
        FROM parking_sessions s
        JOIN users u ON s.user_id = u.id
        JOIN vehicles v ON s.vehicle_id = v.id
        JOIN parking_slots p ON s.slot_id = p.id
        ORDER BY s.id DESC
        LIMIT 6
    """)
    sessions = dict_from_row(cur.fetchall())

    # 3. Recent Transactions
    cur.execute("""
        SELECT t.*, u.full_name as customer_name
        FROM subscription_transactions t
        JOIN users u ON t.user_id = u.id
        ORDER BY t.id DESC
        LIMIT 6
    """)
    transactions = dict_from_row(cur.fetchall())

    # 4. Recent Security Incidents
    cur.execute("""
        SELECT e.*, p.slot_code, v.registration_number
        FROM security_events e
        LEFT JOIN parking_slots p ON e.slot_id = p.id
        LEFT JOIN vehicles v ON e.vehicle_id = v.id
        ORDER BY e.id DESC
        LIMIT 6
    """)
    incidents = dict_from_row(cur.fetchall())

    return jsonify({
        "success": True,
        "scans": scans,
        "sessions": sessions,
        "transactions": transactions,
        "incidents": incidents
    })

