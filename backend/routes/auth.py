from functools import wraps
from flask import Blueprint, request, jsonify, session
from werkzeug.security import check_password_hash
from backend.database import get_db, get_utc_now_iso, dict_from_row

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        admin_id = session.get("admin_id")
        if not admin_id:
            return jsonify({"success": False, "error": "Authentication required. Please log in as admin."}), 401
        
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id, username, email, full_name, role, is_active FROM admins WHERE id = ?", (admin_id,))
        admin = cur.fetchone()
        if not admin or not admin["is_active"]:
            session.clear()
            return jsonify({"success": False, "error": "Account is inactive or disabled."}), 403
            
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    identifier = data.get("username", "").strip() or data.get("email", "").strip()
    password = data.get("password", "")

    if not identifier or not password:
        return jsonify({"success": False, "error": "Username/email and password are required."}), 400

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        SELECT * FROM admins 
        WHERE (username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE)
    """, (identifier, identifier))
    admin = cur.fetchone()

    if not admin or not check_password_hash(admin["password_hash"], password):
        return jsonify({"success": False, "error": "Invalid credentials. Please verify username/email and password."}), 401

    if not admin["is_active"]:
        return jsonify({"success": False, "error": "This administrator account has been disabled."}), 403

    utc_now = get_utc_now_iso()
    cur.execute("UPDATE admins SET last_login = ?, updated_at = ? WHERE id = ?", (utc_now, utc_now, admin["id"]))
    
    # Audit log
    cur.execute("""
        INSERT INTO audit_logs (admin_id, action, entity_type, entity_id, details, ip_address, created_at)
        VALUES (?, 'ADMIN_LOGIN', 'admin', ?, 'Administrator logged into PARK+ console', ?, ?)
    """, (admin["id"], str(admin["id"]), request.remote_addr, utc_now))
    db.commit()

    session["admin_id"] = admin["id"]
    session["admin_username"] = admin["username"]
    session["admin_name"] = admin["full_name"]
    session["admin_role"] = admin["role"]

    return jsonify({
        "success": True,
        "message": f"Welcome back, {admin['full_name']}!",
        "admin": {
            "id": admin["id"],
            "username": admin["username"],
            "email": admin["email"],
            "full_name": admin["full_name"],
            "role": admin["role"]
        }
    })

@auth_bp.route("/logout", methods=["POST"])
def logout():
    admin_id = session.get("admin_id")
    if admin_id:
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO audit_logs (admin_id, action, entity_type, entity_id, details, ip_address)
            VALUES (?, 'ADMIN_LOGOUT', 'admin', ?, 'Administrator logged out', ?)
        """, (admin_id, str(admin_id), request.remote_addr))
        db.commit()
    session.clear()
    return jsonify({"success": True, "message": "Successfully logged out."})

@auth_bp.route("/me", methods=["GET"])
def me():
    admin_id = session.get("admin_id")
    if not admin_id:
        return jsonify({"authenticated": False}), 401

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, username, email, full_name, role, last_login, created_at FROM admins WHERE id = ?", (admin_id,))
    admin = cur.fetchone()
    if not admin:
        session.clear()
        return jsonify({"authenticated": False}), 401

    return jsonify({
        "authenticated": True,
        "admin": dict_from_row(admin)
    })

