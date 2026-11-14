from datetime import datetime, timezone, timedelta
import hmac
from flask import Blueprint, request, jsonify
from backend.database import get_db, get_utc_now_iso, dict_from_row
from backend.config import Config
from backend.routes.auth import admin_required
from backend.services.telegram_service import send_telegram_message

devices_bp = Blueprint("devices", __name__, url_prefix="/api/devices")

@devices_bp.route("", methods=["GET"])
@admin_required
def get_devices():
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT value FROM system_settings WHERE key = 'device_heartbeat_timeout_seconds'")
    timeout_row = cur.fetchone()
    timeout_sec = int(timeout_row["value"]) if timeout_row else Config.DEVICE_HEARTBEAT_TIMEOUT_SECONDS

    cur.execute("SELECT * FROM devices ORDER BY id ASC")
    devices = cur.fetchall()
    res = []
    
    now_dt = datetime.now(timezone.utc)
    utc_now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    for d in devices:
        item = dict_from_row(d)
        is_online = False
        seconds_ago = None

        if item["last_heartbeat"]:
            try:
                hb_dt = datetime.fromisoformat(item["last_heartbeat"].replace("Z", "+00:00"))
                seconds_ago = int((now_dt - hb_dt).total_seconds())
                is_online = seconds_ago <= timeout_sec
            except Exception:
                is_online = False

        computed_status = "online" if is_online else "offline"
        if computed_status != item["status"]:
            previous_status = item["status"]
            cur.execute("UPDATE devices SET status = ?, updated_at = ? WHERE id = ?", (computed_status, utc_now_iso, item["id"]))
            item["status"] = computed_status
            if computed_status == "offline" and previous_status != "offline":
                send_telegram_message(
                    f"🔴 PARK+ DEVICE OFFLINE\nDevice: {item['device_code']}\n"
                    f"Last heartbeat: {item.get('last_heartbeat') or 'Never'}"
                )

        item["is_online"] = is_online
        item["last_seen_seconds_ago"] = seconds_ago
        res.append(item)

    db.commit()
    return jsonify({"success": True, "devices": res, "heartbeat_timeout_seconds": timeout_sec})

@devices_bp.route("/heartbeat", methods=["POST"])
def heartbeat():
    supplied = request.headers.get("X-Device-Token", "")
    if not hmac.compare_digest(supplied, Config.DEVICE_SHARED_SECRET):
        return jsonify({"success": False, "error": "Valid device authentication is required."}), 401
    data = request.get_json(silent=True) or {}
    device_code = data.get("device_code", "PARKPLUS_GATE_01").strip()
    fw_ver = data.get("firmware_version", "1.0.0").strip()
    ip_addr = data.get("ip_address") or request.remote_addr

    if not device_code:
        return jsonify({"success": False, "error": "Missing device_code"}), 400

    db = get_db()
    cur = db.cursor()
    utc_now = get_utc_now_iso()

    cur.execute("SELECT id, status FROM devices WHERE device_code = ?", (device_code,))
    dev = cur.fetchone()
    was_offline = bool(dev and dev["status"] == "offline")
    if dev:
        cur.execute("""
            UPDATE devices 
            SET last_heartbeat = ?, status = 'online', firmware_version = ?, ip_address = ?, updated_at = ?
            WHERE id = ?
        """, (utc_now, fw_ver, ip_addr, utc_now, dev["id"]))
    else:
        cur.execute("""
            INSERT INTO devices (device_code, device_name, device_type, ip_address, firmware_version, status, last_heartbeat, created_at, updated_at)
            VALUES (?, ?, 'gate_controller', ?, ?, 'online', ?, ?, ?)
        """, (device_code, f"Device {device_code}", ip_addr, fw_ver, utc_now, utc_now, utc_now))

    db.commit()

    if was_offline:
        send_telegram_message(f"🟢 PARK+ DEVICE ONLINE\nDevice: {device_code}\nIP: {ip_addr}\nFirmware: {fw_ver}")

    return jsonify({
        "success": True,
        "message": f"Heartbeat acknowledged for {device_code}",
        "server_time": utc_now,
        "status": "online"
    })

