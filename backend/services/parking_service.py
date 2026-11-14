import uuid
from datetime import datetime, timedelta, timezone
from backend.database import get_utc_now_iso, dict_from_row
from backend.services.subscription_service import check_customer_subscription_for_entry, debit_parking_duration
from backend.services.security_service import (
    check_unscanned_departure,
    create_security_event_if_not_duplicate,
)

def process_rfid_entry(db, card_uid, device_code="PARKPLUS_GATE_01"):
    """
    Validate gate entry and queue the vehicle for slot assignment by IR telemetry.
    """
    cur = db.cursor()
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    utc_now = get_utc_now_iso()
    normalized_uid = card_uid.strip().upper()

    # 1. Lookup RFID Card
    cur.execute("""
        SELECT r.*, u.full_name, u.email, u.account_status, v.registration_number, v.vehicle_type, v.status as vehicle_status
        FROM rfid_cards r
        LEFT JOIN users u ON r.user_id = u.id
        LEFT JOIN vehicles v ON r.vehicle_id = v.id
        WHERE r.card_uid = ? COLLATE NOCASE
    """, (normalized_uid,))
    card = cur.fetchone()

    # Denial: Unregistered Card
    if not card:
        cur.execute("""
            INSERT INTO rfid_scan_logs (card_uid, device_code, scan_type, is_authorized, denial_reason, scanned_at)
            VALUES (?, ?, 'entry_gate', 0, 'Unregistered RFID UID scanned at entry', ?)
        """, (normalized_uid, device_code, utc_now))
        
        # Trigger security alert for unregistered card
        create_security_event_if_not_duplicate(
            db=db,
            event_type="unregistered_rfid",
            severity="medium",
            description=f"Unregistered RFID card UID '{normalized_uid}' scanned at {device_code}.",
            device_code=device_code,
            cooldown_minutes=2
        )
        db.commit()
        return {
            "authorized": False,
            "reason": "Unregistered RFID Card. Access denied.",
            "card_uid": normalized_uid
        }

    # Denial: Card inactive or blocked
    if card["status"] != "active":
        cur.execute("""
            INSERT INTO rfid_scan_logs (card_uid, device_code, scan_type, is_authorized, user_id, vehicle_id, denial_reason, scanned_at)
            VALUES (?, ?, 'entry_gate', 0, ?, ?, ?, ?)
        """, (normalized_uid, device_code, card["user_id"], card["vehicle_id"], f"Card status is '{card['status']}'", utc_now))
        
        create_security_event_if_not_duplicate(
            db=db,
            event_type="invalid_rfid",
            severity="medium",
            description=f"Attempted entry with {card['status']} card '{normalized_uid}' by user {card['full_name'] or 'N/A'}.",
            user_id=card["user_id"],
            vehicle_id=card["vehicle_id"],
            device_code=device_code,
            cooldown_minutes=3
        )
        db.commit()
        return {
            "authorized": False,
            "reason": f"Card is {card['status']}. Access denied.",
            "card_uid": normalized_uid
        }

    # Denial: No customer assigned
    if not card["user_id"] or not card["account_status"]:
        cur.execute("""
            INSERT INTO rfid_scan_logs (card_uid, device_code, scan_type, is_authorized, denial_reason, scanned_at)
            VALUES (?, ?, 'entry_gate', 0, 'Card is not associated with an active customer', ?)
        """, (normalized_uid, device_code, utc_now))
        db.commit()
        return {
            "authorized": False,
            "reason": "Card is unassigned. Please link to a customer.",
            "card_uid": normalized_uid
        }

    # Denial: Customer account inactive or suspended
    if card["account_status"] != "active":
        cur.execute("""
            INSERT INTO rfid_scan_logs (card_uid, device_code, scan_type, is_authorized, user_id, vehicle_id, denial_reason, scanned_at)
            VALUES (?, ?, 'entry_gate', 0, ?, ?, ?, ?)
        """, (normalized_uid, device_code, card["user_id"], card["vehicle_id"], f"Customer account is {card['account_status']}", utc_now))
        db.commit()
        return {
            "authorized": False,
            "reason": f"Customer account is {card['account_status']}.",
            "card_uid": normalized_uid
        }

    # Denial: Vehicle missing or inactive
    vehicle_id = card["vehicle_id"]
    if not vehicle_id:
        # Check if user has an active vehicle registered
        cur.execute("SELECT id, registration_number FROM vehicles WHERE user_id = ? AND status = 'active' LIMIT 1", (card["user_id"],))
        alt_v = cur.fetchone()
        if alt_v:
            vehicle_id = alt_v["id"]
        else:
            cur.execute("""
                INSERT INTO rfid_scan_logs (card_uid, device_code, scan_type, is_authorized, user_id, denial_reason, scanned_at)
                VALUES (?, ?, 'entry_gate', 0, ?, 'No active vehicle registered for customer', ?)
            """, (normalized_uid, device_code, card["user_id"], utc_now))
            db.commit()
            return {
                "authorized": False,
                "reason": "No registered active vehicle linked to customer profile.",
                "card_uid": normalized_uid
            }

    # Denial: Vehicle already has an active parking session
    cur.execute("""
        SELECT id, slot_id, session_code FROM parking_sessions
        WHERE vehicle_id = ? AND status = 'active'
    """, (vehicle_id,))
    active_sess = cur.fetchone()
    if active_sess:
        cur.execute("""
            INSERT INTO rfid_scan_logs (card_uid, device_code, scan_type, is_authorized, user_id, vehicle_id, denial_reason, scanned_at)
            VALUES (?, ?, 'entry_gate', 0, ?, ?, 'Vehicle already recorded inside parking lot', ?)
        """, (normalized_uid, device_code, card["user_id"], vehicle_id, utc_now))
        db.commit()
        return {
            "authorized": False,
            "reason": f"Vehicle is already inside (Session: {active_sess['session_code']}).",
            "card_uid": normalized_uid
        }

    # 3. Check Subscription Balance
    has_sub, sub_msg, sub_data = check_customer_subscription_for_entry(db, card["user_id"])
    if not has_sub:
        cur.execute("""
            INSERT INTO rfid_scan_logs (card_uid, device_code, scan_type, is_authorized, user_id, vehicle_id, denial_reason, scanned_at)
            VALUES (?, ?, 'entry_gate', 0, ?, ?, ?, ?)
        """, (normalized_uid, device_code, card["user_id"], vehicle_id, sub_msg, utc_now))
        db.commit()
        return {
            "authorized": False,
            "reason": sub_msg,
            "card_uid": normalized_uid
        }

    cur.execute("""
        UPDATE pending_gate_entries
        SET status = 'expired', completed_at = ?
        WHERE device_code = ? AND status = 'pending' AND expires_at <= ?
    """, (utc_now, device_code, utc_now))
    cur.execute("""
        SELECT id, remaining_seconds
        FROM pending_gate_entries
        WHERE device_code = ? AND status = 'pending' AND expires_at > ?
          AND (rfid_card_id = ? OR vehicle_id = ?)
        ORDER BY id DESC
        LIMIT 1
    """, (device_code, utc_now, card["id"], vehicle_id))
    existing_pending = cur.fetchone()
    if existing_pending:
        db.commit()
        return {
            "authorized": True,
            "pending_assignment": True,
            "pending_entry_id": existing_pending["id"],
            "message": "Entry is authorized and waiting for an IR sensor to detect the vehicle.",
            "customer_name": card["full_name"],
            "vehicle_reg": card["registration_number"],
            "remaining_seconds": existing_pending["remaining_seconds"]
        }

    cur.execute("""
        SELECT id FROM pending_gate_entries
        WHERE device_code = ? AND status = 'pending' AND expires_at > ?
        ORDER BY id ASC
        LIMIT 1
    """, (device_code, utc_now))
    other_pending = cur.fetchone()
    if other_pending:
        cur.execute("""
            INSERT INTO rfid_scan_logs
                (card_uid, device_code, scan_type, is_authorized, user_id, vehicle_id, denial_reason, scanned_at)
            VALUES (?, ?, 'entry_gate', 0, ?, ?, 'Another vehicle is waiting for IR slot assignment', ?)
        """, (normalized_uid, device_code, card["user_id"], vehicle_id, utc_now))
        db.commit()
        return {
            "authorized": False,
            "reason": "Another vehicle is waiting for an IR slot assignment. Please wait and scan again.",
            "card_uid": normalized_uid
        }

    cur.execute("SELECT COUNT(*) AS available FROM parking_slots WHERE is_occupied = 0")
    available_slots = cur.fetchone()["available"]
    cur.execute("""
        SELECT COUNT(*) AS pending FROM pending_gate_entries
        WHERE device_code = ? AND status = 'pending' AND expires_at > ?
    """, (device_code, utc_now))
    pending_count = cur.fetchone()["pending"]
    if available_slots <= pending_count:
        cur.execute("""
            INSERT INTO rfid_scan_logs (card_uid, device_code, scan_type, is_authorized, user_id, vehicle_id, denial_reason, scanned_at)
            VALUES (?, ?, 'entry_gate', 0, ?, ?, 'No unreserved sensor-detected parking slot is available', ?)
        """, (normalized_uid, device_code, card["user_id"], vehicle_id, utc_now))
        db.commit()
        return {
            "authorized": False,
            "reason": "Parking is full or all available slots are awaiting sensor assignment.",
            "card_uid": normalized_uid
        }

    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute("""
        INSERT INTO pending_gate_entries
            (device_code, rfid_card_id, user_id, vehicle_id, requested_at, expires_at, remaining_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        device_code, card["id"], card["user_id"], vehicle_id, utc_now,
        expires_at, sub_data["remaining_balance_seconds"]
    ))
    pending_entry_id = cur.lastrowid

    cur.execute("""
        INSERT INTO rfid_scan_logs (card_uid, device_code, scan_type, is_authorized, user_id, vehicle_id, scanned_at)
        VALUES (?, ?, 'entry_gate', 1, ?, ?, ?)
    """, (normalized_uid, device_code, card["user_id"], vehicle_id, utc_now))

    db.commit()

    return {
        "authorized": True,
        "pending_assignment": True,
        "pending_entry_id": pending_entry_id,
        "message": "Entry authorized. Park in an available slot; IR will assign the detected slot.",
        "customer_name": card["full_name"],
        "vehicle_reg": card["registration_number"],
        "remaining_seconds": sub_data["remaining_balance_seconds"]
    }

def _assign_pending_entry_to_slot(db, device_code, slot_id, slot_code, utc_now):
    cur = db.cursor()
    cur.execute("""
        SELECT id FROM parking_sessions
        WHERE slot_id = ? AND status = 'active'
        LIMIT 1
    """, (slot_id,))
    if cur.fetchone():
        return None

    cur.execute("""
        SELECT pe.*, u.full_name, v.registration_number
        FROM pending_gate_entries pe
        JOIN users u ON u.id = pe.user_id
        JOIN vehicles v ON v.id = pe.vehicle_id
        WHERE pe.device_code = ? AND pe.status = 'pending' AND pe.expires_at > ?
        ORDER BY pe.id ASC
        LIMIT 1
    """, (device_code, utc_now))
    pending = cur.fetchone()
    if not pending:
        return None

    cur.execute("""
        SELECT id FROM parking_sessions
        WHERE vehicle_id = ? AND status = 'active'
        LIMIT 1
    """, (pending["vehicle_id"],))
    if cur.fetchone():
        cur.execute("""
            UPDATE pending_gate_entries
            SET status = 'cancelled', completed_at = ?
            WHERE id = ?
        """, (utc_now, pending["id"]))
        return None

    session_code = f"SES-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:4].upper()}"
    cur.execute("""
        INSERT INTO parking_sessions
            (session_code, slot_id, vehicle_id, user_id, rfid_card_id, entry_time, status, entry_device, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
    """, (
        session_code, slot_id, pending["vehicle_id"], pending["user_id"],
        pending["rfid_card_id"], utc_now, device_code, utc_now, utc_now
    ))
    session_id = cur.lastrowid

    cur.execute("""
        UPDATE parking_slots
        SET is_occupied = 1, current_vehicle_id = ?, current_session_id = ?,
            last_status_change = ?, updated_at = ?
        WHERE id = ?
    """, (pending["vehicle_id"], session_id, utc_now, utc_now, slot_id))
    cur.execute("""
        UPDATE pending_gate_entries
        SET status = 'assigned', assigned_session_id = ?, completed_at = ?
        WHERE id = ? AND status = 'pending'
    """, (session_id, utc_now, pending["id"]))
    cur.execute("""
        UPDATE rfid_cards SET last_used_at = ?, updated_at = ? WHERE id = ?
    """, (utc_now, utc_now, pending["rfid_card_id"]))
    return {
        "session_code": session_code,
        "entry_time": utc_now,
        "customer_name": pending["full_name"],
        "vehicle_reg": pending["registration_number"],
        "slot_code": slot_code,
        "remaining_seconds": pending["remaining_seconds"]
    }

def process_rfid_exit(db, card_uid, device_code="PARKPLUS_GATE_01"):
    """
    Handles gate exit scan:
    1. Verifies active parking session associated with the card or customer's vehicle
    2. Authorizes barrier to open
    3. Confirms exit and debits balance
    """
    cur = db.cursor()
    utc_now = get_utc_now_iso()
    normalized_uid = card_uid.strip().upper()

    # Find active session by RFID card UID or user's vehicle
    cur.execute("""
        SELECT s.*, r.card_uid, u.full_name, v.registration_number, p.slot_code
        FROM parking_sessions s
        JOIN parking_slots p ON s.slot_id = p.id
        JOIN users u ON s.user_id = u.id
        JOIN vehicles v ON s.vehicle_id = v.id
        LEFT JOIN rfid_cards r ON s.rfid_card_id = r.id
        WHERE (r.card_uid = ? COLLATE NOCASE OR s.user_id IN (SELECT user_id FROM rfid_cards WHERE card_uid = ? COLLATE NOCASE))
          AND s.status = 'active'
        ORDER BY s.id DESC
        LIMIT 1
    """, (normalized_uid, normalized_uid))
    active_session = cur.fetchone()

    if not active_session:
        cur.execute("""
            INSERT INTO rfid_scan_logs (card_uid, device_code, scan_type, is_authorized, denial_reason, scanned_at)
            VALUES (?, ?, 'exit_gate', 0, 'No active parking session found for this card at exit', ?)
        """, (normalized_uid, device_code, utc_now))
        db.commit()
        return {
            "authorized": False,
            "reason": "No active parking session found for this vehicle. Exit denied.",
            "card_uid": normalized_uid
        }

    # Finalize exit
    debit_summary = debit_parking_duration(db, active_session["id"], exit_time_iso=utc_now)

    # Close session
    cur.execute("""
        UPDATE parking_sessions 
        SET exit_time = ?, duration_seconds = ?, status = 'completed', exit_device = ?, billed_amount_paise = ?, updated_at = ?
        WHERE id = ?
    """, (utc_now, debit_summary["duration_seconds"], device_code, debit_summary["overage_paise"], utc_now, active_session["id"]))
    cur.execute("DELETE FROM parking_departure_watches WHERE session_id = ?", (active_session["id"],))

    # Free up slot
    cur.execute("""
        UPDATE parking_slots 
        SET is_occupied = 0, current_vehicle_id = NULL, current_session_id = NULL, last_status_change = ?, updated_at = ?
        WHERE id = ?
    """, (utc_now, utc_now, active_session["slot_id"]))

    # Log successful exit scan
    cur.execute("""
        INSERT INTO rfid_scan_logs (card_uid, device_code, scan_type, is_authorized, user_id, vehicle_id, scanned_at)
        VALUES (?, ?, 'exit_gate', 1, ?, ?, ?)
    """, (normalized_uid, device_code, active_session["user_id"], active_session["vehicle_id"], utc_now))

    db.commit()

    return {
        "authorized": True,
        "message": f"Exit verified for {active_session['registration_number']}. Thank you for parking with PARK+!",
        "customer_name": active_session["full_name"],
        "vehicle_reg": active_session["registration_number"],
        "slot_code": active_session["slot_code"],
        "session_code": active_session["session_code"],
        "entry_time": active_session["entry_time"],
        "exit_time": utc_now,
        "duration_seconds": debit_summary["duration_seconds"],
        "balance_after_seconds": debit_summary["balance_after_seconds"],
        "overage_paise": debit_summary["overage_paise"]
    }

def process_sensor_telemetry(db, device_code, slot_code, distance_cm, occupied, sensor_health="healthy"):
    """
    Update a sensor slot, assign the oldest pending gate entry on a rising edge,
    and check for a vehicle that left without an RFID exit scan.
    """
    cur = db.cursor()
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    utc_now = get_utc_now_iso()

    cur.execute("SELECT * FROM parking_slots WHERE slot_code = ?", (slot_code,))
    slot = cur.fetchone()
    if not slot:
        raise ValueError(f"Slot {slot_code} does not exist.")

    slot_id = slot["id"]
    cur.execute("""
        SELECT occupied FROM sensor_logs
        WHERE slot_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (slot_id,))
    previous_sensor_reading = cur.fetchone()
    was_sensor_occupied = bool(previous_sensor_reading and previous_sensor_reading["occupied"])
    sensor_is_healthy = sensor_health.lower() in ("healthy", "ok")

    cur.execute("""
        UPDATE pending_gate_entries
        SET status = 'expired', completed_at = ?
        WHERE device_code = ? AND status = 'pending' AND expires_at <= ?
    """, (utc_now, device_code, utc_now))

    assigned_session = None
    if sensor_is_healthy and occupied and not was_sensor_occupied:
        assigned_session = _assign_pending_entry_to_slot(
            db, device_code, slot_id, slot_code, utc_now
        )

    cur.execute("""
        SELECT id, vehicle_id FROM parking_sessions
        WHERE slot_id = ? AND status = 'active'
        ORDER BY id DESC
        LIMIT 1
    """, (slot_id,))
    active_session = cur.fetchone()

    if sensor_is_healthy:
        slot_occupied = bool(occupied or active_session)
        current_vehicle_id = active_session["vehicle_id"] if active_session else None
        current_session_id = active_session["id"] if active_session else None
    else:
        slot_occupied = bool(slot["is_occupied"])
        current_vehicle_id = slot["current_vehicle_id"]
        current_session_id = slot["current_session_id"]
    last_status_change = (
        utc_now if bool(slot["is_occupied"]) != slot_occupied else slot["last_status_change"]
    )

    _, alert_desc, security_alert_new = check_unscanned_departure(
        db=db,
        slot_id=slot_id,
        slot_code=slot_code,
        is_occupied_sensor=occupied,
        sensor_health=sensor_health,
        device_code=device_code
    )

    # Update slot real-time status
    cur.execute("""
        UPDATE parking_slots 
        SET is_occupied = ?, current_vehicle_id = ?, current_session_id = ?,
            last_distance_cm = ?, last_sensor_status = ?, last_status_change = ?, updated_at = ?
        WHERE id = ?
    """, (
        int(slot_occupied), current_vehicle_id, current_session_id,
        distance_cm, sensor_health, last_status_change, utc_now, slot_id
    ))

    # Log raw sensor reading
    cur.execute("""
        INSERT INTO sensor_logs (slot_id, device_code, distance_cm, occupied, sensor_health, logged_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (slot_id, device_code, distance_cm, 1 if occupied else 0, sensor_health, utc_now))

    db.commit()

    return {
        "slot_code": slot_code,
        "distance_cm": distance_cm,
        "occupied": occupied,
        "sensor_health": sensor_health,
        "security_alert": alert_desc,
        "security_alert_new": security_alert_new,
        "departure_alert": alert_desc,
        "assigned_session": assigned_session
    }

