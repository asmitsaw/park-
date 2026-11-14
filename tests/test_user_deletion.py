import os
import tempfile
import unittest

from backend.app import create_app
from backend.config import Config
from backend.database import get_db_connection, get_utc_now_iso, init_db


class CustomerDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = Config.DB_PATH
        Config.DB_PATH = os.path.join(self.temp_dir.name, "test.db")
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})
        init_db(db_path=Config.DB_PATH, force=True)
        db = get_db_connection(Config.DB_PATH)
        admin_id = db.execute("SELECT id FROM admins LIMIT 1").fetchone()["id"]
        db.close()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_id"] = admin_id

    def tearDown(self):
        Config.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def create_customer(self):
        response = self.client.post("/api/users", json={
            "full_name": "Test Customer",
            "email": "customer@example.com",
            "phone": "5550000000",
        })
        self.assertEqual(response.status_code, 201)
        return response.get_json()["user_id"]

    def test_delete_removes_customer_and_associated_vehicle_and_card(self):
        user_id = self.create_customer()
        db = get_db_connection(Config.DB_PATH)
        now = get_utc_now_iso()
        vehicle_id = db.execute("""
            INSERT INTO vehicles (user_id, registration_number, created_at, updated_at)
            VALUES (?, 'TEST-001', ?, ?)
        """, (user_id, now, now)).lastrowid
        db.execute("""
            INSERT INTO rfid_cards (card_uid, user_id, vehicle_id, created_at, updated_at)
            VALUES ('A1B2C3D4', ?, ?, ?, ?)
        """, (user_id, vehicle_id, now, now))
        db.commit()
        db.close()

        response = self.client.delete(f"/api/users/{user_id}")

        self.assertEqual(response.status_code, 200)
        db = get_db_connection(Config.DB_PATH)
        self.assertIsNone(db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone())
        self.assertIsNone(db.execute("SELECT id FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone())
        self.assertIsNone(db.execute("SELECT id FROM rfid_cards WHERE card_uid = 'A1B2C3D4'").fetchone())
        db.close()

    def test_history_requires_explicit_confirmation_before_purge(self):
        user_id = self.create_customer()
        db = get_db_connection(Config.DB_PATH)
        now = get_utc_now_iso()
        plan = db.execute(
            "SELECT id FROM subscription_plans WHERE plan_code = 'MONTHLY-60H'"
        ).fetchone()
        subscription_id = db.execute("""
            INSERT INTO subscriptions (
                subscription_code, user_id, plan_id, total_allocated_seconds,
                remaining_balance_seconds, price_paid_paise, start_date, expiry_date
            ) VALUES ('TEST-SUB-DELETE', ?, ?, 3600, 3600, 100, ?, '2099-01-01T00:00:00Z')
        """, (user_id, plan["id"], now)).lastrowid
        db.execute("""
            INSERT INTO subscription_transactions (
                transaction_code, subscription_id, user_id, transaction_type,
                seconds_amount, balance_after_seconds, amount_paise, description, created_at
            ) VALUES ('TEST-TXN-DELETE', ?, ?, 'credit', 3600, 3600, 100, 'Test credit', ?)
        """, (subscription_id, user_id, now))
        db.commit()
        db.close()

        response = self.client.delete(f"/api/users/{user_id}")

        self.assertEqual(response.status_code, 409)
        self.assertIn("Confirm permanent history deletion", response.get_json()["error"])
        db = get_db_connection(Config.DB_PATH)
        self.assertIsNotNone(db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone())
        self.assertIsNotNone(db.execute("SELECT id FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone())
        self.assertIsNotNone(db.execute("SELECT id FROM subscription_transactions WHERE user_id = ?", (user_id,)).fetchone())
        db.close()

        response = self.client.delete(
            f"/api/users/{user_id}",
            json={"purge_history": True},
        )

        self.assertEqual(response.status_code, 200)
        db = get_db_connection(Config.DB_PATH)
        self.assertIsNone(db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone())
        self.assertIsNone(db.execute("SELECT id FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone())
        self.assertIsNone(db.execute("SELECT id FROM subscription_transactions WHERE user_id = ?", (user_id,)).fetchone())
        db.close()

    def test_purge_removes_completed_parking_and_rfid_history(self):
        user_id = self.create_customer()
        db = get_db_connection(Config.DB_PATH)
        now = get_utc_now_iso()
        vehicle_id = db.execute("""
            INSERT INTO vehicles (user_id, registration_number, created_at, updated_at)
            VALUES (?, 'TEST-HISTORY', ?, ?)
        """, (user_id, now, now)).lastrowid
        card_id = db.execute("""
            INSERT INTO rfid_cards (card_uid, user_id, vehicle_id, created_at, updated_at)
            VALUES ('A1B2C3D4', ?, ?, ?, ?)
        """, (user_id, vehicle_id, now, now)).lastrowid
        slot_id = db.execute("SELECT id FROM parking_slots WHERE slot_code = 'P02'").fetchone()["id"]
        session_id = db.execute("""
            INSERT INTO parking_sessions (
                session_code, slot_id, vehicle_id, user_id, rfid_card_id, status, exit_time
            ) VALUES ('TEST-SESSION-DELETE', ?, ?, ?, ?, 'completed', ?)
        """, (slot_id, vehicle_id, user_id, card_id, now)).lastrowid
        db.execute("""
            INSERT INTO rfid_scan_logs (card_uid, device_code, user_id, vehicle_id)
            VALUES ('A1B2C3D4', 'TEST-DEVICE', ?, ?)
        """, (user_id, vehicle_id))
        db.commit()
        db.close()

        response = self.client.delete(
            f"/api/users/{user_id}",
            json={"purge_history": True},
        )

        self.assertEqual(response.status_code, 200)
        db = get_db_connection(Config.DB_PATH)
        self.assertIsNone(db.execute("SELECT id FROM parking_sessions WHERE id = ?", (session_id,)).fetchone())
        self.assertIsNone(db.execute("SELECT id FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone())
        self.assertIsNone(db.execute("SELECT id FROM rfid_cards WHERE card_uid = 'A1B2C3D4'").fetchone())
        self.assertIsNone(db.execute("SELECT id FROM rfid_scan_logs WHERE card_uid = 'A1B2C3D4'").fetchone())
        db.close()

    def test_purge_is_blocked_while_customer_has_active_parked_vehicle(self):
        user_id = self.create_customer()
        db = get_db_connection(Config.DB_PATH)
        now = get_utc_now_iso()
        vehicle_id = db.execute("""
            INSERT INTO vehicles (user_id, registration_number, created_at, updated_at)
            VALUES (?, 'TEST-ACTIVE', ?, ?)
        """, (user_id, now, now)).lastrowid
        slot_id = db.execute("SELECT id FROM parking_slots WHERE slot_code = 'P02'").fetchone()["id"]
        db.execute("""
            INSERT INTO parking_sessions (session_code, slot_id, vehicle_id, user_id, status)
            VALUES ('TEST-ACTIVE-SESSION', ?, ?, ?, 'active')
        """, (slot_id, vehicle_id, user_id))
        db.execute("""
            UPDATE parking_slots
            SET is_occupied = 1, current_vehicle_id = ?
            WHERE id = ?
        """, (vehicle_id, slot_id))
        db.commit()
        db.close()

        response = self.client.delete(
            f"/api/users/{user_id}",
            json={"purge_history": True},
        )

        self.assertEqual(response.status_code, 409)
        db = get_db_connection(Config.DB_PATH)
        self.assertIsNotNone(db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone())
        self.assertIsNotNone(db.execute("SELECT id FROM parking_sessions WHERE status = 'active'").fetchone())
        db.close()


if __name__ == "__main__":
    unittest.main()
