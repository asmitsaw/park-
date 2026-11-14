import uuid
from datetime import datetime, timezone, timedelta
from backend.database import get_utc_now_iso

def create_security_event_if_not_duplicate(db, event_type, severity, description, slot_id=None, vehicle_id=None, user_id=None, device_code=None, cooldown_minutes=5):
    """
    Creates a new security incident with event deduplication.
    If an open/investigating event of the same event_type exists for the same slot/device
    within the cooldown window, it updates the existing event rather than creating duplicates.
    """
    cur = db.cursor()
    utc_now = get_utc_now_iso()
    cooldown_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Check for duplicate open or investigating event
    query = """
        SELECT id, event_code, description, created_at 
        FROM security_events 
        WHERE event_type = ? 
          AND status IN ('open', 'investigating')
          AND updated_at >= ?
    """
    params = [event_type, cooldown_cutoff]

    if slot_id is not None:
        query += " AND slot_id = ?"
        params.append(slot_id)
    if device_code is not None:
        query += " AND device_code = ?"
        params.append(device_code)

    cur.execute(query, tuple(params))
    existing = cur.fetchone()

    if existing:
        # Deduplication match: update existing event timestamp and append note
        note_append = f" [Repeated occurrence at {utc_now}]"
        cur.execute("""
            UPDATE security_events 
            SET updated_at = ?, 
                description = description || ?
            WHERE id = ?
        """, (utc_now, note_append, existing["id"]))
        return existing["id"], False

    # Create new security incident
    event_code = f"SEC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:4].upper()}"
    cur.execute("""
        INSERT INTO security_events 
        (event_code, event_type, severity, status, slot_id, vehicle_id, user_id, device_code, description, created_at, updated_at)
        VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?)
    """, (event_code, event_type, severity, slot_id, vehicle_id, user_id, device_code, description, utc_now, utc_now))
    
    event_id = cur.lastrowid
    return event_id, True

def check_unscanned_departure(db, slot_id, slot_code, is_occupied_sensor, sensor_health, device_code):
    """Alert once when a previously observed active car is absent for five minutes."""
    cur = db.cursor()
    utc_now = get_utc_now_iso()

    cur.execute("""
        SELECT s.id, s.user_id, s.vehicle_id, s.entry_time, u.full_name, v.registration_number
        FROM parking_sessions s
        JOIN users u ON u.id = s.user_id
        JOIN vehicles v ON v.id = s.vehicle_id
        WHERE s.slot_id = ? AND s.status = 'active'
        ORDER BY s.id DESC
        LIMIT 1
    """, (slot_id,))
    active_session = cur.fetchone()

    if not active_session:
        cur.execute("DELETE FROM parking_departure_watches WHERE slot_id = ?", (slot_id,))
        return None, None, False

    cur.execute("""
        SELECT occupied_observed_at, empty_since, alert_sent_at
        FROM parking_departure_watches
        WHERE session_id = ?
    """, (active_session["id"],))
    watch = cur.fetchone()

    if sensor_health.lower() not in ("healthy", "ok"):
        if watch:
            cur.execute(
                "UPDATE parking_departure_watches SET empty_since = NULL WHERE session_id = ?",
                (active_session["id"],)
            )
        return None, None, False

    if is_occupied_sensor:
        cur.execute("""
            INSERT INTO parking_departure_watches
                (session_id, slot_id, occupied_observed_at, empty_since, alert_sent_at)
            VALUES (?, ?, ?, NULL, NULL)
            ON CONFLICT(session_id) DO UPDATE SET
                occupied_observed_at = excluded.occupied_observed_at,
                empty_since = NULL,
                alert_sent_at = NULL
        """, (active_session["id"], slot_id, utc_now))
        return None, None, False

    if not watch:
        return None, None, False
    if watch["empty_since"] is None:
        cur.execute(
            "UPDATE parking_departure_watches SET empty_since = ? WHERE session_id = ?",
            (utc_now, active_session["id"])
        )
        return None, None, False
    if watch["alert_sent_at"] is not None:
        return None, None, False

    alert_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if watch["empty_since"] > alert_cutoff:
        return None, None, False

    cur.execute("""
        UPDATE parking_departure_watches
        SET alert_sent_at = ?
        WHERE session_id = ? AND alert_sent_at IS NULL
    """, (utc_now, active_session["id"]))
    if not cur.rowcount:
        return None, None, False

    desc = (
        f"Vehicle {active_session['registration_number']} ({active_session['full_name']}) "
        f"in Slot {slot_code} has been absent since {watch['empty_since']} "
        f"without an RFID exit scan. Parking started at {active_session['entry_time']}."
    )
    event_id, _ = create_security_event_if_not_duplicate(
        db=db,
        event_type="unauthorized_departure",
        severity="critical",
        description=desc,
        slot_id=slot_id,
        vehicle_id=active_session["vehicle_id"],
        user_id=active_session["user_id"],
        device_code=device_code,
        cooldown_minutes=5
    )
    return event_id, desc, True

