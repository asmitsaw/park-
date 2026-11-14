import csv
import io
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, Response
from backend.database import get_db, dict_from_row
from backend.routes.auth import admin_required

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")

@analytics_bp.route("/overview", methods=["GET"])
@admin_required
def get_overview():
    db = get_db()
    cur = db.cursor()

    days = int(request.args.get("days", 30))
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Total sessions in period
    cur.execute("SELECT COUNT(*) as count FROM parking_sessions WHERE entry_time >= ?", (cutoff_iso,))
    total_sessions = cur.fetchone()["count"]

    # 2. Average parking duration (for completed sessions)
    cur.execute("""
        SELECT AVG(duration_seconds) as avg_duration,
               MIN(duration_seconds) as min_duration,
               MAX(duration_seconds) as max_duration
        FROM parking_sessions 
        WHERE status = 'completed' AND entry_time >= ?
    """, (cutoff_iso,))
    dur_stats = cur.fetchone()
    avg_duration_sec = int(dur_stats["avg_duration"] or 0)

    # 3. Total subscription revenue (all credit transactions + overages in paise)
    cur.execute("""
        SELECT SUM(amount_paise) as total_paise
        FROM subscription_transactions
        WHERE created_at >= ?
    """, (cutoff_iso,))
    total_paise = cur.fetchone()["total_paise"] or 0

    # 4. Active vs Expired subscriptions
    cur.execute("SELECT status, COUNT(*) as count FROM subscriptions GROUP BY status")
    sub_counts = {r["status"]: r["count"] for r in cur.fetchall()}

    # 5. Peak Parking Hours (00 to 23)
    cur.execute("""
        SELECT strftime('%H', entry_time) as hour, COUNT(*) as count
        FROM parking_sessions
        WHERE entry_time >= ?
        GROUP BY hour
        ORDER BY hour ASC
    """, (cutoff_iso,))
    hourly_rows = cur.fetchall()
    hourly_map = {f"{h:02d}": 0 for h in range(24)}
    for r in hourly_rows:
        if r["hour"] in hourly_map:
            hourly_map[r["hour"]] = r["count"]

    # 6. Slot utilization
    cur.execute("""
        SELECT p.slot_code, COUNT(s.id) as sessions, SUM(s.duration_seconds) as total_seconds
        FROM parking_slots p
        LEFT JOIN parking_sessions s ON p.id = s.slot_id AND s.entry_time >= ?
        GROUP BY p.id
    """, (cutoff_iso,))
    slot_stats = cur.fetchall()

    return jsonify({
        "success": True,
        "metrics": {
            "timeframe_days": days,
            "total_sessions": total_sessions,
            "avg_duration_seconds": avg_duration_sec,
            "avg_duration_formatted": f"{avg_duration_sec // 3600}h {(avg_duration_sec % 3600) // 60}m",
            "total_revenue_inr": total_paise / 100.0,
            "subscription_breakdown": sub_counts,
        },
        "peak_hours": {
            "hours": list(hourly_map.keys()),
            "counts": list(hourly_map.values())
        },
        "slot_stats": dict_from_row(slot_stats)
    })

@analytics_bp.route("/export/csv", methods=["GET"])
@admin_required
def export_csv():
    report_type = request.args.get("type", "sessions")  # 'sessions' or 'transactions'
    db = get_db()
    cur = db.cursor()

    output = io.StringIO()
    writer = csv.writer(output)

    if report_type == "transactions":
        writer.writerow(["Transaction Code", "Subscription Code", "Customer Name", "Type", "Seconds Amount", "Balance After (s)", "Amount (INR)", "Date", "Description"])
        cur.execute("""
            SELECT t.transaction_code, s.subscription_code, u.full_name, t.transaction_type, 
                   t.seconds_amount, t.balance_after_seconds, t.amount_paise, t.created_at, t.description
            FROM subscription_transactions t
            JOIN users u ON t.user_id = u.id
            JOIN subscriptions s ON t.subscription_id = s.id
            ORDER BY t.id DESC
        """)
        for r in cur.fetchall():
            writer.writerow([r[0], r[1], r[2], r[3], r[4], r[5], f"{r[6]/100.0:.2f}", r[7], r[8]])
        filename = f"parkplus_transactions_{datetime.now().strftime('%Y%m%d')}.csv"
    else:
        writer.writerow(["Session Code", "Slot", "Customer", "Vehicle", "RFID UID", "Entry Time", "Exit Time", "Duration (s)", "Status", "Billed (INR)"])
        cur.execute("""
            SELECT s.session_code, p.slot_code, u.full_name, v.registration_number, r.card_uid,
                   s.entry_time, s.exit_time, s.duration_seconds, s.status, s.billed_amount_paise
            FROM parking_sessions s
            JOIN parking_slots p ON s.slot_id = p.id
            JOIN users u ON s.user_id = u.id
            JOIN vehicles v ON s.vehicle_id = v.id
            LEFT JOIN rfid_cards r ON s.rfid_card_id = r.id
            ORDER BY s.id DESC
        """)
        for r in cur.fetchall():
            writer.writerow([r[0], r[1], r[2], r[3], r[4] or "N/A", r[5], r[6] or "Active", r[7], r[8], f"{(r[9] or 0)/100.0:.2f}"])
        filename = f"parkplus_parking_sessions_{datetime.now().strftime('%Y%m%d')}.csv"

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

