-- ============================================================================
-- PARK+ : Intelligent Parking & Vehicle Security Management System
-- SQLite Database Schema: parksentinel.db
-- Version: 1.0.0
-- ============================================================================

PRAGMA foreign_keys = ON;

-- 1. Admins Table
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'superadmin', -- 'superadmin', 'operator', 'security_officer'
    is_active INTEGER NOT NULL DEFAULT 1,
    last_login TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- 2. Users (Customers) Table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_code TEXT NOT NULL UNIQUE,     -- e.g. 'CUST-0001'
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phone TEXT NOT NULL,
    address TEXT,
    account_status TEXT NOT NULL DEFAULT 'active', -- 'active', 'inactive', 'suspended'
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- 3. Vehicles Table
CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    registration_number TEXT NOT NULL UNIQUE COLLATE NOCASE, -- e.g. 'KA-01-AB-1234'
    vehicle_type TEXT NOT NULL DEFAULT 'car',                 -- 'car', 'bike', 'suv', 'ev'
    model TEXT,
    color TEXT,
    status TEXT NOT NULL DEFAULT 'active',                   -- 'active', 'inactive'
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
);

-- 4. RFID Cards Table
CREATE TABLE IF NOT EXISTS rfid_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_uid TEXT NOT NULL UNIQUE COLLATE NOCASE,           -- e.g. 'A1B2C3D4' (normalized hex uppercase)
    user_id INTEGER,                                        -- Assigned customer (nullable if unassigned)
    vehicle_id INTEGER,                                     -- Optional vehicle binding
    card_label TEXT,                                        -- Friendly name or physical badge number
    status TEXT NOT NULL DEFAULT 'active',                  -- 'active', 'inactive', 'blocked'
    issue_date TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    last_used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL
);

-- 5a. Admin-Initiated RFID Reader Capture Requests
CREATE TABLE IF NOT EXISTS rfid_capture_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'ready', 'captured', 'expired', 'cancelled'
    card_uid TEXT,
    requested_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    completed_at TEXT,
    created_by INTEGER,
    FOREIGN KEY (created_by) REFERENCES admins(id) ON DELETE SET NULL
);

-- 5. RFID Scan Logs
CREATE TABLE IF NOT EXISTS rfid_scan_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_uid TEXT NOT NULL COLLATE NOCASE,
    device_code TEXT NOT NULL,
    scan_type TEXT NOT NULL DEFAULT 'entry_gate',           -- 'entry_gate', 'exit_gate', 'manual_audit'
    is_authorized INTEGER NOT NULL DEFAULT 0,
    user_id INTEGER,
    vehicle_id INTEGER,
    denial_reason TEXT,
    raw_payload TEXT,
    scanned_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL
);

-- 6. Parking Slots Table
CREATE TABLE IF NOT EXISTS parking_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_code TEXT NOT NULL UNIQUE,                         -- 'P01', 'P02'
    slot_type TEXT NOT NULL DEFAULT 'standard',             -- 'standard', 'ev', 'accessible'
    is_occupied INTEGER NOT NULL DEFAULT 0,
    current_vehicle_id INTEGER,
    current_session_id INTEGER,
    last_distance_cm REAL,
    last_sensor_status TEXT NOT NULL DEFAULT 'healthy',     -- 'healthy', 'warning', 'offline'
    last_status_change TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (current_vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL
);

-- 7. Parking Sessions Table
CREATE TABLE IF NOT EXISTS parking_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_code TEXT NOT NULL UNIQUE,                      -- e.g. 'SES-20261114-001'
    slot_id INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    rfid_card_id INTEGER,
    entry_time TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    exit_time TEXT,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',                  -- 'active', 'completed', 'overstay', 'cancelled'
    entry_device TEXT NOT NULL DEFAULT 'PARKPLUS_GATE_01',
    exit_device TEXT,
    billed_amount_paise INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (slot_id) REFERENCES parking_slots(id) ON DELETE RESTRICT,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE RESTRICT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (rfid_card_id) REFERENCES rfid_cards(id) ON DELETE SET NULL
);

-- A gate-authorized vehicle is matched to its actual slot by the first IR occupancy edge.
CREATE TABLE IF NOT EXISTS pending_gate_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_code TEXT NOT NULL,
    rfid_card_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    requested_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    remaining_seconds INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'assigned', 'expired', 'cancelled'
    assigned_session_id INTEGER,
    completed_at TEXT,
    FOREIGN KEY (rfid_card_id) REFERENCES rfid_cards(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_session_id) REFERENCES parking_sessions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_pending_gate_entries_device
    ON pending_gate_entries(device_code, status, expires_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_gate_entries_one_per_device
    ON pending_gate_entries(device_code)
    WHERE status = 'pending';

-- Tracks sensor occupancy for an active session so an unscanned departure can be delayed.
CREATE TABLE IF NOT EXISTS parking_departure_watches (
    session_id INTEGER PRIMARY KEY,
    slot_id INTEGER NOT NULL,
    occupied_observed_at TEXT NOT NULL,
    empty_since TEXT,
    alert_sent_at TEXT,
    FOREIGN KEY (session_id) REFERENCES parking_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (slot_id) REFERENCES parking_slots(id) ON DELETE CASCADE
);

-- 8. Sensor Logs Table
CREATE TABLE IF NOT EXISTS sensor_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id INTEGER NOT NULL,
    device_code TEXT NOT NULL,
    distance_cm REAL NOT NULL,
    occupied INTEGER NOT NULL,
    sensor_health TEXT NOT NULL DEFAULT 'healthy',
    raw_reading TEXT,
    logged_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (slot_id) REFERENCES parking_slots(id) ON DELETE CASCADE
);

-- 9. Security Events Table
CREATE TABLE IF NOT EXISTS security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_code TEXT NOT NULL UNIQUE,                        -- e.g. 'SEC-20261114-001'
    event_type TEXT NOT NULL,                               -- 'unauthorized_departure', 'unexpected_vacancy', 'invalid_rfid', 'unregistered_rfid', 'sensor_malfunction', 'device_offline', 'suspicious_activity'
    severity TEXT NOT NULL DEFAULT 'medium',                -- 'low', 'medium', 'high', 'critical'
    status TEXT NOT NULL DEFAULT 'open',                    -- 'open', 'investigating', 'resolved', 'dismissed'
    slot_id INTEGER,
    vehicle_id INTEGER,
    user_id INTEGER,
    device_code TEXT,
    description TEXT NOT NULL,
    investigation_notes TEXT,
    resolved_at TEXT,
    resolved_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (slot_id) REFERENCES parking_slots(id) ON DELETE SET NULL,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- 10. Helpdesk Tickets Table
CREATE TABLE IF NOT EXISTS helpdesk_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_code TEXT NOT NULL UNIQUE,                       -- e.g. 'TKT-1001'
    user_id INTEGER,
    related_security_event_id INTEGER,
    subject TEXT NOT NULL,
    description TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',                -- 'low', 'medium', 'high', 'urgent'
    status TEXT NOT NULL DEFAULT 'open',                    -- 'open', 'in_progress', 'waiting', 'resolved', 'closed'
    admin_response TEXT,
    assigned_to TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (related_security_event_id) REFERENCES security_events(id) ON DELETE SET NULL
);

-- 11. Devices Table
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_code TEXT NOT NULL UNIQUE,                       -- e.g. 'PARKPLUS_GATE_01'
    device_name TEXT NOT NULL,
    device_type TEXT NOT NULL DEFAULT 'gate_controller',    -- 'gate_controller', 'slot_sensor', 'all_in_one'
    ip_address TEXT,
    firmware_version TEXT NOT NULL DEFAULT '1.0.0',
    status TEXT NOT NULL DEFAULT 'offline',                 -- 'online', 'offline', 'warning'
    last_heartbeat TEXT,
    config_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- 12. Device Events Table (for idempotency and audit)
CREATE TABLE IF NOT EXISTS device_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_code TEXT NOT NULL,
    event_type TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    payload TEXT,
    logged_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- 13. Subscription Plans Table
CREATE TABLE IF NOT EXISTS subscription_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_code TEXT NOT NULL UNIQUE,                         -- 'MONTHLY-BASIC', 'PREPAID-10H'
    name TEXT NOT NULL,
    plan_type TEXT NOT NULL,                                -- 'monthly', 'prepaid'
    duration_days INTEGER NOT NULL,                         -- validity period in days
    allocated_seconds INTEGER NOT NULL,                     -- e.g. 60 hours = 216000 seconds
    price_paise INTEGER NOT NULL,                           -- e.g. 150000 = 1500.00 INR
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- 14. Subscriptions Table
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_code TEXT NOT NULL UNIQUE,                 -- e.g. 'SUB-202611-001'
    user_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    total_allocated_seconds INTEGER NOT NULL,
    remaining_balance_seconds INTEGER NOT NULL,             -- stored in exact integer seconds
    consumed_seconds INTEGER NOT NULL DEFAULT 0,
    price_paid_paise INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    expiry_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',                  -- 'active', 'expired', 'exhausted', 'cancelled'
    auto_renew INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE RESTRICT
);

-- 15. Subscription Transactions Table (Immutable Financial & Time Ledger)
CREATE TABLE IF NOT EXISTS subscription_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_code TEXT NOT NULL UNIQUE,                  -- e.g. 'TXN-20261114-001'
    subscription_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    parking_session_id INTEGER,
    transaction_type TEXT NOT NULL,                         -- 'credit', 'debit', 'adjustment', 'overage_charge'
    seconds_amount INTEGER NOT NULL,                        -- positive integer
    balance_after_seconds INTEGER NOT NULL,                 -- snapshot of remaining seconds after txn
    amount_paise INTEGER NOT NULL DEFAULT 0,                -- rupee value in paise if monetary
    description TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE RESTRICT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (parking_session_id) REFERENCES parking_sessions(id) ON DELETE SET NULL
);

-- 16. AI Predictions Table (Future Module Readiness)
CREATE TABLE IF NOT EXISTS ai_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    prediction_type TEXT NOT NULL,                          -- 'demand', 'duration', 'anomaly'
    input_features TEXT NOT NULL,                           -- JSON representation of features
    prediction_result TEXT NOT NULL,                        -- JSON representation of output
    confidence_score REAL,
    actual_outcome TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- 17. Audit Logs Table
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    details TEXT,
    ip_address TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (admin_id) REFERENCES admins(id) ON DELETE SET NULL
);

-- 18. System Settings Table
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE AND DATA INTEGRITY
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(account_status);

CREATE INDEX IF NOT EXISTS idx_vehicles_user ON vehicles(user_id);
CREATE INDEX IF NOT EXISTS idx_vehicles_reg ON vehicles(registration_number);

CREATE INDEX IF NOT EXISTS idx_rfid_uid ON rfid_cards(card_uid);
CREATE INDEX IF NOT EXISTS idx_rfid_user ON rfid_cards(user_id);
CREATE INDEX IF NOT EXISTS idx_rfid_status ON rfid_cards(status);
CREATE INDEX IF NOT EXISTS idx_rfid_capture_status ON rfid_capture_requests(status, expires_at);

CREATE INDEX IF NOT EXISTS idx_rfid_scans_card ON rfid_scan_logs(card_uid);
CREATE INDEX IF NOT EXISTS idx_rfid_scans_date ON rfid_scan_logs(scanned_at);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON parking_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_vehicle ON parking_sessions(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_sessions_slot ON parking_sessions(slot_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON parking_sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_entry ON parking_sessions(entry_time);

CREATE INDEX IF NOT EXISTS idx_sensor_slot ON sensor_logs(slot_id);
CREATE INDEX IF NOT EXISTS idx_sensor_date ON sensor_logs(logged_at);

CREATE INDEX IF NOT EXISTS idx_security_status ON security_events(status);
CREATE INDEX IF NOT EXISTS idx_security_severity ON security_events(severity);
CREATE INDEX IF NOT EXISTS idx_security_date ON security_events(created_at);

CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subs_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_subs_expiry ON subscriptions(expiry_date);

CREATE INDEX IF NOT EXISTS idx_sub_txns_sub ON subscription_transactions(subscription_id);
CREATE INDEX IF NOT EXISTS idx_sub_txns_user ON subscription_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_sub_txns_date ON subscription_transactions(created_at);

CREATE INDEX IF NOT EXISTS idx_devices_code ON devices(device_code);
CREATE INDEX IF NOT EXISTS idx_devices_heartbeat ON devices(last_heartbeat);

