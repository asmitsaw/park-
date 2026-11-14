import math
import uuid
from datetime import datetime, timezone
from backend.database import get_db, get_utc_now_iso

def get_system_setting(db, key, default):
    cur = db.cursor()
    cur.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
    row = cur.fetchone()
    return row["value"] if row else str(default)

def check_customer_subscription_for_entry(db, user_id):
    """
    Validates whether the customer has an active subscription with enough balance
    to authorize a parking entry.
    """
    cur = db.cursor()
    utc_now = get_utc_now_iso()
    min_allowance = int(get_system_setting(db, "min_parking_allowance_seconds", 900))

    # Find the best active subscription for user
    cur.execute("""
        SELECT s.*, p.name as plan_name, p.plan_type
        FROM subscriptions s
        JOIN subscription_plans p ON s.plan_id = p.id
        WHERE s.user_id = ? 
          AND s.status = 'active'
          AND s.expiry_date >= ?
        ORDER BY s.remaining_balance_seconds DESC, s.expiry_date ASC
        LIMIT 1
    """, (user_id, utc_now))
    sub = cur.fetchone()

    if not sub:
        # Check if user has an expired subscription
        cur.execute("""
            SELECT id FROM subscriptions
            WHERE user_id = ? AND status = 'active' AND expiry_date < ?
        """, (user_id, utc_now))
        expired = cur.fetchall()
        for exp in expired:
            cur.execute("UPDATE subscriptions SET status = 'expired', updated_at = ? WHERE id = ?", (utc_now, exp["id"]))
        db.commit()
        return False, "No valid or active subscription found. Please renew or purchase a plan.", None

    if sub["remaining_balance_seconds"] < min_allowance:
        return False, f"Insufficient balance ({sub['remaining_balance_seconds']}s remaining). Minimum {min_allowance}s required for entry.", dict(sub)

    return True, "Subscription valid", dict(sub)

def debit_parking_duration(db, session_id, exit_time_iso=None):
    """
    Deducts parking duration in seconds from the customer's subscription balance.
    If duration exceeds balance, the remaining seconds are deducted to 0 and the
    excess is calculated as an overage charge.
    Never blocks vehicle exit due to balance insufficiency.
    """
    cur = db.cursor()
    if exit_time_iso is None:
        exit_time_iso = get_utc_now_iso()

    cur.execute("SELECT * FROM parking_sessions WHERE id = ?", (session_id,))
    session = cur.fetchone()
    if not session:
        raise ValueError(f"Session {session_id} not found")

    entry_dt = datetime.fromisoformat(session["entry_time"].replace("Z", "+00:00"))
    exit_dt = datetime.fromisoformat(exit_time_iso.replace("Z", "+00:00"))
    
    # Calculate duration in seconds
    duration_seconds = max(1, int((exit_dt - entry_dt).total_seconds()))

    user_id = session["user_id"]
    overage_rate_hourly = int(get_system_setting(db, "overage_rate_per_hour_paise", 5000))

    # Find the subscription used for entry or active one
    cur.execute("""
        SELECT * FROM subscriptions 
        WHERE user_id = ? AND status = 'active'
        ORDER BY remaining_balance_seconds DESC
        LIMIT 1
    """, (user_id,))
    sub = cur.fetchone()

    txn_code = f"TXN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    overage_paise = 0
    balance_after = 0
    sub_id = None

    if sub:
        sub_id = sub["id"]
        rem_balance = sub["remaining_balance_seconds"]
        consumed = sub["consumed_seconds"]

        if rem_balance >= duration_seconds:
            balance_after = rem_balance - duration_seconds
            new_consumed = consumed + duration_seconds
            
            cur.execute("""
                UPDATE subscriptions 
                SET remaining_balance_seconds = ?, consumed_seconds = ?, updated_at = ?
                WHERE id = ?
            """, (balance_after, new_consumed, exit_time_iso, sub_id))

            cur.execute("""
                INSERT INTO subscription_transactions 
                (transaction_code, subscription_id, user_id, parking_session_id, transaction_type, seconds_amount, balance_after_seconds, amount_paise, description, created_at)
                VALUES (?, ?, ?, ?, 'debit', ?, ?, 0, ?, ?)
            """, (txn_code, sub_id, user_id, session_id, duration_seconds, balance_after, f"Parking debit for session {session['session_code']} ({duration_seconds}s)", exit_time_iso))
        else:
            # Overdraft / Overage situation
            excess_seconds = duration_seconds - rem_balance
            balance_after = 0
            new_consumed = consumed + rem_balance

            # Calculate overage in paise based on ceil of hours
            excess_hours = math.ceil(excess_seconds / 3600.0)
            overage_paise = int(excess_hours * overage_rate_hourly)

            cur.execute("""
                UPDATE subscriptions 
                SET remaining_balance_seconds = 0, consumed_seconds = ?, status = 'exhausted', updated_at = ?
                WHERE id = ?
            """, (new_consumed, exit_time_iso, sub_id))

            # Record debit for the remaining balance
            if rem_balance > 0:
                cur.execute("""
                    INSERT INTO subscription_transactions 
                    (transaction_code, subscription_id, user_id, parking_session_id, transaction_type, seconds_amount, balance_after_seconds, amount_paise, description, created_at)
                    VALUES (?, ?, ?, ?, 'debit', ?, 0, 0, ?, ?)
                """, (f"{txn_code}-A", sub_id, user_id, session_id, rem_balance, f"Quota exhausted for session {session['session_code']}", exit_time_iso))

            # Record overage transaction
            cur.execute("""
                INSERT INTO subscription_transactions 
                (transaction_code, subscription_id, user_id, parking_session_id, transaction_type, seconds_amount, balance_after_seconds, amount_paise, description, created_at)
                VALUES (?, ?, ?, ?, 'overage_charge', ?, 0, ?, ?, ?)
            """, (txn_code, sub_id, user_id, session_id, excess_seconds, overage_paise, f"Overage charge for {excess_seconds}s ({excess_hours}h @ ₹{overage_rate_hourly/100:.2f}/h)", exit_time_iso))

    else:
        # User has no active subscription at exit time (e.g. expired during long parking)
        # Apply full duration overage rate
        billed_hours = math.ceil(duration_seconds / 3600.0)
        overage_paise = int(billed_hours * overage_rate_hourly)

        # Look for most recent subscription to associate transaction with
        cur.execute("SELECT id FROM subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
        last_sub = cur.fetchone()
        sub_id = last_sub["id"] if last_sub else 1

        cur.execute("""
            INSERT INTO subscription_transactions 
            (transaction_code, subscription_id, user_id, parking_session_id, transaction_type, seconds_amount, balance_after_seconds, amount_paise, description, created_at)
            VALUES (?, ?, ?, ?, 'overage_charge', ?, 0, ?, ?, ?)
        """, (txn_code, sub_id, user_id, session_id, duration_seconds, overage_paise, f"Uncovered parking duration ({duration_seconds}s, ₹{overage_paise/100:.2f})", exit_time_iso))

    return {
        "duration_seconds": duration_seconds,
        "balance_after_seconds": balance_after,
        "overage_paise": overage_paise,
        "transaction_code": txn_code
    }

