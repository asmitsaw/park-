import uuid
from flask import Blueprint, request, jsonify, session
from backend.database import get_db, get_utc_now_iso, dict_from_row
from backend.routes.auth import admin_required

helpdesk_bp = Blueprint("helpdesk", __name__, url_prefix="/api/helpdesk")

@helpdesk_bp.route("/tickets", methods=["GET"])
@admin_required
def get_tickets():
    db = get_db()
    cur = db.cursor()

    status = request.args.get("status")
    priority = request.args.get("priority")
    search = request.args.get("search", "").strip()

    query = """
        SELECT t.*, u.full_name as customer_name, u.email as customer_email, u.phone as customer_phone,
               se.event_code as related_incident_code
        FROM helpdesk_tickets t
        LEFT JOIN users u ON t.user_id = u.id
        LEFT JOIN security_events se ON t.related_security_event_id = se.id
        WHERE 1=1
    """
    params = []
    if status:
        query += " AND t.status = ?"
        params.append(status)
    if priority:
        query += " AND t.priority = ?"
        params.append(priority)
    if search:
        query += " AND (t.ticket_code LIKE ? OR t.subject LIKE ? OR t.description LIKE ? OR u.full_name LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like, like])

    query += " ORDER BY t.id DESC LIMIT 100"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    return jsonify({"success": True, "tickets": dict_from_row(rows)})

@helpdesk_bp.route("/tickets", methods=["POST"])
@admin_required
def create_ticket():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id") or None
    related_incident_id = data.get("related_security_event_id") or None
    subject = data.get("subject", "").strip()
    description = data.get("description", "").strip()
    priority = data.get("priority", "medium").lower()

    if not subject or not description:
        return jsonify({"success": False, "error": "Subject and description are required."}), 400

    db = get_db()
    cur = db.cursor()
    utc_now = get_utc_now_iso()
    ticket_code = f"TKT-{uuid.uuid4().hex[:6].upper()}"

    cur.execute("""
        INSERT INTO helpdesk_tickets 
        (ticket_code, user_id, related_security_event_id, subject, description, priority, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)
    """, (ticket_code, user_id, related_incident_id, subject, description, priority, utc_now, utc_now))
    tid = cur.lastrowid
    db.commit()

    return jsonify({"success": True, "message": "Ticket created.", "ticket_id": tid, "ticket_code": ticket_code}), 201

@helpdesk_bp.route("/tickets/<int:ticket_id>", methods=["PATCH"])
@admin_required
def update_ticket(ticket_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    priority = data.get("priority")
    admin_response = data.get("admin_response")
    assigned_to = data.get("assigned_to")

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM helpdesk_tickets WHERE id = ?", (ticket_id,))
    ticket = cur.fetchone()
    if not ticket:
        return jsonify({"success": False, "error": "Ticket not found."}), 404

    utc_now = get_utc_now_iso()
    new_status = status or ticket["status"]
    new_priority = priority or ticket["priority"]
    new_response = admin_response if admin_response is not None else ticket["admin_response"]
    new_assigned = assigned_to if assigned_to is not None else ticket["assigned_to"]

    cur.execute("""
        UPDATE helpdesk_tickets
        SET status = ?, priority = ?, admin_response = ?, assigned_to = ?, updated_at = ?
        WHERE id = ?
    """, (new_status, new_priority, new_response, new_assigned, utc_now, ticket_id))
    db.commit()

    return jsonify({"success": True, "message": "Ticket updated successfully."})

