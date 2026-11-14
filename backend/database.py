import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from flask import g, current_app
from werkzeug.security import generate_password_hash
from backend.config import Config, BACKEND_DIR

SCHEMA_FILE = BACKEND_DIR / "schema.sql"

def get_utc_now_iso():
    """Return current timestamp in UTC ISO-8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def get_db_connection(db_path=None):
    """
    Establish and return a new SQLite connection with strict settings:
    - Foreign key enforcement enabled
    - Row factory set to sqlite3.Row
    """
    if db_path is None:
        db_path = Config.DB_PATH
    
    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        timeout=15.0
    )
    conn.row_factory = sqlite3.Row
    # CRITICAL: Always enforce SQLite Foreign Keys on every connection
    conn.execute("PRAGMA foreign_keys = ON;")
    # WAL mode for better concurrency and reliability
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def get_db():
    """Flask application context database connection getter."""
    if "db" not in g:
        g.db = get_db_connection()
    return g.db

def close_db(e=None):
    """Flask teardown handler to close active connection."""
    db = g.pop("db", None)
    if db is not None:
        db.close()

def dict_from_row(row):
    """Convert an sqlite3.Row or list of rows to plain Python dict(s)."""
    if row is None:
        return None
    if isinstance(row, list):
        return [dict(r) for r in row]
    return dict(row)

def init_db(db_path=None, force=False):
    """
    Initialize SQLite database from schema.sql and seed core foundation data.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    try:
        if force:
            cursor.execute("PRAGMA foreign_keys = OFF;")
            # Drop all existing tables safely if force=True
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            tables = cursor.fetchall()
            for t in tables:
                cursor.execute(f"DROP TABLE IF EXISTS {t['name']};")
            cursor.execute("PRAGMA foreign_keys = ON;")

        # Execute schema
        with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
            cursor.executescript(f.read())
        
        utc_now = get_utc_now_iso()

        # 1. Seed Configurable Initial Admin
        cursor.execute("SELECT id FROM admins WHERE username = ?", (Config.ADMIN_USERNAME,))
        admin = cursor.fetchone()
        if not admin:
            hashed_pw = generate_password_hash(Config.ADMIN_PASSWORD, method="scrypt")
            cursor.execute("""
                INSERT INTO admins (username, email, password_hash, full_name, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'superadmin', 1, ?, ?)
            """, (Config.ADMIN_USERNAME, Config.ADMIN_EMAIL, hashed_pw, Config.ADMIN_NAME, utc_now, utc_now))

        # 2. Seed Default Parking Slots (P01 and P02)
        slots_to_seed = [
            ("P01", "standard", 0, None, 25.0, "healthy"),
            ("P02", "standard", 0, None, 25.0, "healthy")
        ]
        for slot_code, s_type, is_occ, cur_veh, dist, health in slots_to_seed:
            cursor.execute("SELECT id FROM parking_slots WHERE slot_code = ?", (slot_code,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO parking_slots (slot_code, slot_type, is_occupied, current_vehicle_id, last_distance_cm, last_sensor_status, last_status_change, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (slot_code, s_type, is_occ, cur_veh, dist, health, utc_now, utc_now))

        # 3. Seed Standard Subscription Plans
        plans_to_seed = [
            # code, name, type, days, allocated_seconds, price_paise, description
            ("MONTHLY-60H", "Monthly Standard (60 Hours)", "monthly", 30, 60 * 3600, 149900, "Ideal for daily commuters with 60 hours parking quota per month."),
            ("MONTHLY-120H", "Monthly Executive (120 Hours)", "monthly", 30, 120 * 3600, 249900, "For corporate and intensive usage with 120 hours parking allowance."),
            ("PREPAID-10H", "Prepaid Flexi 10 Hours", "prepaid", 60, 10 * 3600, 39900, "Pay-as-you-go pack with 10 hours of parking valid for 60 days."),
            ("PREPAID-20H", "Prepaid Flexi 20 Hours", "prepaid", 90, 20 * 3600, 69900, "Popular flexi pack with 20 hours parking valid for 90 days."),
            ("PREPAID-50H", "Prepaid Bulk 50 Hours", "prepaid", 180, 50 * 3600, 149900, "High savings bulk pack with 50 hours parking valid for 180 days.")
        ]
        for plan in plans_to_seed:
            cursor.execute("SELECT id FROM subscription_plans WHERE plan_code = ?", (plan[0],))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO subscription_plans (plan_code, name, plan_type, duration_days, allocated_seconds, price_paise, description, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """, (*plan, utc_now, utc_now))

        # 4. Seed System Settings
        settings_to_seed = [
            ("min_parking_allowance_seconds", str(Config.MIN_PARKING_ALLOWANCE_SECONDS), "Minimum subscription balance in seconds required to authorize vehicle entry"),
            ("overage_rate_per_hour_paise", str(Config.OVERAGE_RATE_PER_HOUR_PAISE), "Hourly rate in paise charged for parking exceeding subscription balance"),
            ("device_heartbeat_timeout_seconds", str(Config.DEVICE_HEARTBEAT_TIMEOUT_SECONDS), "Threshold in seconds after which an IoT device is classified as offline"),
            ("slot_distance_threshold_cm", str(Config.SLOT_DISTANCE_THRESHOLD_CM), "Distance threshold in cm: below this distance slot is occupied"),
            ("unscanned_departure_alert_minutes", str(Config.UNSCANNED_DEPARTURE_ALERT_MINUTES), "Minutes a slot must remain empty without an RFID exit scan before sending a departure alert"),
            ("system_mode", "production", "Operating mode of the system: production or simulation"),
            ("auto_gate_open_seconds", "6", "Duration in seconds gate barrier remains raised before automatic lowering")
        ]
        for key, val, desc in settings_to_seed:
            cursor.execute("SELECT key FROM system_settings WHERE key = ?", (key,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO system_settings (key, value, description, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (key, val, desc, utc_now))

        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

