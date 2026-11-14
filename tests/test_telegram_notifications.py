import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from backend.app import create_app
from backend.config import Config
from backend.database import get_db_connection, get_utc_now_iso, init_db
from backend.services.parking_service import process_sensor_telemetry
from backend.services.telegram_service import (
    format_telegram_time,
    notify_security_event,
    send_telegram_message,
)


class TelegramParkingNotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = Config.DB_PATH
        Config.DB_PATH = os.path.join(cls.temp_dir.name, "test.db")
        cls.app = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})

    @classmethod
    def tearDownClass(cls):
        Config.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def setUp(self):
        init_db(db_path=Config.DB_PATH, force=True)
        self.client = self.app.test_client()

    def create_test_customer(self, suffix=""):
        db = get_db_connection(Config.DB_PATH)
        now = get_utc_now_iso()
        customer_code = f"TEST-CUSTOMER{suffix}"
        email = f"test{suffix.lower()}@example.com"
        registration_number = f"TEST-{suffix or '001'}"
        card_uid = "AB12CD34" if not suffix else "CD34EF56"
        subscription_code = f"TEST-SUB{suffix}"
        user_id = db.execute("""
            INSERT INTO users (customer_code, full_name, email, phone, created_at, updated_at)
            VALUES (?, 'Test Customer', ?, '0000000000', ?, ?)
        """, (customer_code, email, now, now)).lastrowid
        vehicle_id = db.execute("""
            INSERT INTO vehicles (user_id, registration_number, model, created_at, updated_at)
            VALUES (?, ?, 'Test Vehicle', ?, ?)
        """, (user_id, registration_number, now, now)).lastrowid
        card_id = db.execute("""
            INSERT INTO rfid_cards (card_uid, user_id, vehicle_id, card_label, created_at, updated_at)
            VALUES (?, ?, ?, 'Test Tag', ?, ?)
        """, (card_uid, user_id, vehicle_id, now, now)).lastrowid
        plan = db.execute(
            "SELECT id, allocated_seconds, price_paise FROM subscription_plans WHERE plan_code = 'MONTHLY-60H'"
        ).fetchone()
        db.execute("""
            INSERT INTO subscriptions (
                subscription_code, user_id, plan_id, total_allocated_seconds,
                remaining_balance_seconds, price_paid_paise, start_date, expiry_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '2099-01-01T00:00:00Z')
        """, (subscription_code, user_id, plan["id"], plan["allocated_seconds"],
              plan["allocated_seconds"], plan["price_paise"], now))
        db.commit()
        db.close()
        return card_id, card_uid

    def device_headers(self):
        return {"X-Device-Token": Config.DEVICE_SHARED_SECRET}

    def start_parking_session(self, card_uid="AB12CD34"):
        with patch("backend.routes.parking.send_telegram_message"):
            response = self.client.post(
                "/api/parking/gate/scan",
                json={"device_code": "PARKPLUS_GATE_01", "rfid_uid": card_uid},
                headers=self.device_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["authorized"])
        self.assertTrue(response.get_json()["pending_assignment"])
        db = get_db_connection(Config.DB_PATH)
        process_sensor_telemetry(
            db, "PARKPLUS_GATE_01", "P01", 10.0, True
        )
        db.close()

    def test_initialization_does_not_create_demo_records(self):
        db = get_db_connection(Config.DB_PATH)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM rfid_cards").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM devices").fetchone()[0], 0)
        alert_setting = db.execute("""
            SELECT value FROM system_settings
            WHERE key = 'unscanned_departure_alert_minutes'
        """).fetchone()
        self.assertEqual(alert_setting["value"], "3")
        db.close()

    def test_telegram_time_uses_indian_standard_time(self):
        self.assertEqual(
            format_telegram_time("2026-11-14T16:00:00Z"),
            "14 Nov 2026, 09:30 PM IST",
        )

    def test_dashboard_contains_security_threshold_control(self):
        db = get_db_connection(Config.DB_PATH)
        admin_id = db.execute("SELECT id FROM admins LIMIT 1").fetchone()["id"]
        db.close()
        with self.client.session_transaction() as session:
            session["admin_id"] = admin_id

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="departureAlertMinutes"', response.data)
        self.assertIn(b"/static/js/app.js?v=20261114.2", response.data)

    def test_security_notification_escapes_html_in_customer_supplied_text(self):
        with patch("backend.services.telegram_service.send_telegram_message") as send_message:
            notify_security_event("suspicious_activity", "high", "Vehicle <AB&12>")

        message = send_message.call_args.args[0]
        self.assertIn("PARK+ SECURITY ALERT</b>", message)
        self.assertIn("Vehicle &lt;AB&amp;12&gt;", message)
        self.assertIn("<b>Time:</b>", message)

    def test_telegram_messages_use_html_parse_mode(self):
        response = Mock()
        response.json.return_value = {"ok": True}
        with patch.object(Config, "TELEGRAM_BOT_TOKEN", "test-token"), \
             patch.object(Config, "TELEGRAM_CHAT_ID", "1234"), \
             patch("backend.services.telegram_service.requests.post", return_value=response) as post:
            self.assertTrue(send_telegram_message("<b>PARK+</b>"))

        self.assertEqual(post.call_args.kwargs["json"]["parse_mode"], "HTML")

    def test_security_threshold_setting_api_validates_and_saves_minutes(self):
        db = get_db_connection(Config.DB_PATH)
        admin_id = db.execute("SELECT id FROM admins LIMIT 1").fetchone()["id"]
        db.close()
        with self.client.session_transaction() as session:
            session["admin_id"] = admin_id

        valid = self.client.put(
            "/api/settings",
            json={"unscanned_departure_alert_minutes": 1},
        )
        invalid = self.client.put(
            "/api/settings",
            json={"unscanned_departure_alert_minutes": 0},
        )

        self.assertEqual(valid.status_code, 200)
        self.assertEqual(invalid.status_code, 400)
        db = get_db_connection(Config.DB_PATH)
        self.assertEqual(
            db.execute("""
                SELECT value FROM system_settings
                WHERE key = 'unscanned_departure_alert_minutes'
            """).fetchone()["value"],
            "1",
        )
        db.close()

    def test_entry_and_exit_telegram_messages_include_session_and_subscription_details(self):
        self.create_test_customer()
        db = get_db_connection(Config.DB_PATH)
        process_sensor_telemetry(db, "PARKPLUS_GATE_01", "P01", 10.0, True)
        process_sensor_telemetry(db, "PARKPLUS_GATE_01", "P02", 30.0, False)
        db.close()

        with patch("backend.routes.parking.send_telegram_message") as send_message:
            entry = self.client.post(
                "/api/parking/gate/scan",
                json={"device_code": "PARKPLUS_GATE_01", "rfid_uid": "AB12CD34"},
                headers=self.device_headers(),
            )
            self.assertEqual(entry.status_code, 200)
            self.assertTrue(entry.get_json()["pending_assignment"])
            send_message.assert_not_called()
            db = get_db_connection(Config.DB_PATH)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM parking_sessions").fetchone()[0], 0)
            db.close()
            sensor_response = self.client.post(
                "/api/slots/update",
                json={
                    "device_code": "PARKPLUS_GATE_01",
                    "slot_code": "P02",
                    "occupied": True,
                    "sensor_health": "healthy",
                    "distance_cm": 10,
                },
                headers=self.device_headers(),
            )
            self.assertEqual(sensor_response.status_code, 200)
            self.assertEqual(
                sensor_response.get_json()["data"]["assigned_session"]["slot_code"],
                "P02",
            )
            entry_message = send_message.call_args.args[0]
            self.assertIn("PARKING STARTED", entry_message)
            self.assertIn("<b>Parking slot:</b> P02", entry_message)
            self.assertIn("Start time:", entry_message)
            self.assertIn("Subscription balance before parking:", entry_message)

            exit_response = self.client.post(
                "/api/parking/gate/scan",
                json={"device_code": "PARKPLUS_GATE_01", "rfid_uid": "AB12CD34"},
                headers=self.device_headers(),
            )
            self.assertEqual(exit_response.status_code, 200)
            exit_message = send_message.call_args.args[0]
            self.assertIn("PARKING SESSION COMPLETED", exit_message)
            self.assertIn("Exit time:", exit_message)
            self.assertIn("Parking duration:", exit_message)
            self.assertIn("Subscription time remaining:", exit_message)

    def test_ir_transition_assigns_the_sensor_detected_slot_not_p01(self):
        self.create_test_customer()
        db = get_db_connection(Config.DB_PATH)
        process_sensor_telemetry(db, "PARKPLUS_GATE_01", "P01", 10.0, True)
        process_sensor_telemetry(db, "PARKPLUS_GATE_01", "P02", 30.0, False)
        db.close()

        with patch("backend.routes.parking.send_telegram_message") as send_message:
            response = self.client.post(
                "/api/parking/gate/scan",
                json={"device_code": "PARKPLUS_GATE_01", "rfid_uid": "AB12CD34"},
                headers=self.device_headers(),
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["pending_assignment"])
            send_message.assert_not_called()

            response = self.client.post(
                "/api/slots/update",
                json={
                    "device_code": "PARKPLUS_GATE_01",
                    "slot_code": "P02",
                    "occupied": True,
                    "sensor_health": "healthy",
                    "distance_cm": 10,
                },
                headers=self.device_headers(),
            )
            self.assertEqual(response.status_code, 200)
            assigned = response.get_json()["data"]["assigned_session"]
            self.assertEqual(assigned["slot_code"], "P02")
            self.assertIn("<b>Parking slot:</b> P02", send_message.call_args.args[0])

        db = get_db_connection(Config.DB_PATH)
        row = db.execute("""
            SELECT p.slot_code FROM parking_sessions s
            JOIN parking_slots p ON p.id = s.slot_id
        """).fetchone()
        self.assertEqual(row["slot_code"], "P02")
        db.close()

    def test_only_one_vehicle_waits_for_slot_detection_at_a_time(self):
        self.create_test_customer()
        self.create_test_customer("2")
        with patch("backend.routes.parking.notify_security_event"):
            first = self.client.post(
                "/api/parking/gate/scan",
                json={"device_code": "PARKPLUS_GATE_01", "rfid_uid": "AB12CD34"},
                headers=self.device_headers(),
            )
            second = self.client.post(
                "/api/parking/gate/scan",
                json={"device_code": "PARKPLUS_GATE_01", "rfid_uid": "CD34EF56"},
                headers=self.device_headers(),
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 403)
        db = get_db_connection(Config.DB_PATH)
        self.assertEqual(
            db.execute("""
                SELECT COUNT(*) FROM pending_gate_entries
                WHERE status = 'pending'
            """).fetchone()[0],
            1,
        )
        db.close()

    def test_pending_entry_expires_after_five_minutes(self):
        self.create_test_customer()
        entry = self.client.post(
            "/api/parking/gate/scan",
            json={"device_code": "PARKPLUS_GATE_01", "rfid_uid": "AB12CD34"},
            headers=self.device_headers(),
        )
        self.assertTrue(entry.get_json()["pending_assignment"])
        db = get_db_connection(Config.DB_PATH)
        db.execute(
            "UPDATE pending_gate_entries SET expires_at = '2000-01-01T00:00:00Z'"
        )
        db.commit()
        db.close()

        with patch("backend.routes.parking.send_telegram_message"):
            response = self.client.post(
                "/api/slots/update",
                json={
                    "device_code": "PARKPLUS_GATE_01",
                    "slot_code": "P01",
                    "occupied": True,
                    "sensor_health": "healthy",
                    "distance_cm": 10,
                },
                headers=self.device_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["data"]["assigned_session"])
        db = get_db_connection(Config.DB_PATH)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM parking_sessions").fetchone()[0], 0)
        self.assertEqual(
            db.execute("SELECT status FROM pending_gate_entries").fetchone()["status"],
            "expired",
        )
        db.close()

    def test_unscanned_departure_alert_waits_three_minutes_and_sends_once(self):
        self.create_test_customer()
        self.start_parking_session()
        db = get_db_connection(Config.DB_PATH)
        process_sensor_telemetry(db, "PARKPLUS_GATE_01", "P01", 10.0, True)
        process_sensor_telemetry(db, "PARKPLUS_GATE_01", "P01", 30.0, False)
        db.execute(
            "UPDATE parking_departure_watches SET empty_since = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=3, seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),)
        )
        db.commit()
        db.close()

        payload = {
            "device_code": "PARKPLUS_GATE_01",
            "slot_code": "P01",
            "sensor_type": "ir",
            "occupied": False,
            "sensor_health": "healthy",
            "distance_cm": 30,
        }
        with patch("backend.routes.parking.send_telegram_message") as send_message:
            response = self.client.post(
                "/api/slots/update", json=payload, headers=self.device_headers()
            )
            self.assertEqual(response.status_code, 200)
            send_message.assert_called_once()
            self.assertIn("UNCONFIRMED DEPARTURE", send_message.call_args.args[0])
            self.assertIn("TEST-001", send_message.call_args.args[0])
            self.assertIn("Alert threshold: 3 minutes.", send_message.call_args.args[0])
            self.assertIn("IST", send_message.call_args.args[0])

            self.client.post("/api/slots/update", json=payload, headers=self.device_headers())
            send_message.assert_called_once()

    def test_security_threshold_can_be_changed_to_one_minute(self):
        self.create_test_customer()
        self.start_parking_session()
        db = get_db_connection(Config.DB_PATH)
        process_sensor_telemetry(db, "PARKPLUS_GATE_01", "P01", 10.0, True)
        process_sensor_telemetry(db, "PARKPLUS_GATE_01", "P01", 30.0, False)
        db.execute("""
            UPDATE system_settings SET value = '1'
            WHERE key = 'unscanned_departure_alert_minutes'
        """)
        db.execute(
            "UPDATE parking_departure_watches SET empty_since = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1, seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),)
        )
        db.commit()
        db.close()

        with patch("backend.routes.parking.send_telegram_message") as send_message:
            response = self.client.post(
                "/api/slots/update",
                json={
                    "device_code": "PARKPLUS_GATE_01",
                    "slot_code": "P01",
                    "occupied": False,
                    "sensor_health": "healthy",
                    "distance_cm": 30,
                },
                headers=self.device_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Alert threshold: 1 minute.", send_message.call_args.args[0])

    def test_empty_slot_without_prior_occupied_read_does_not_trigger_departure_alert(self):
        self.create_test_customer()
        with patch("backend.routes.parking.send_telegram_message"):
            entry = self.client.post(
                "/api/parking/gate/scan",
                json={"device_code": "PARKPLUS_GATE_01", "rfid_uid": "AB12CD34"},
                headers=self.device_headers(),
            )
        self.assertEqual(entry.status_code, 200)
        self.assertTrue(entry.get_json()["pending_assignment"])
        with patch("backend.routes.parking.send_telegram_message") as send_message:
            response = self.client.post(
                "/api/slots/update",
                json={
                    "device_code": "PARKPLUS_GATE_01",
                    "slot_code": "P01",
                    "occupied": False,
                    "sensor_health": "healthy",
                    "distance_cm": 30,
                },
                headers=self.device_headers(),
            )
            self.assertEqual(response.status_code, 200)
            send_message.assert_not_called()
        db = get_db_connection(Config.DB_PATH)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM parking_sessions").fetchone()[0], 0)
        db.close()

    def test_rfid_exit_cancels_pending_departure_alert(self):
        self.create_test_customer()
        self.start_parking_session()
        db = get_db_connection(Config.DB_PATH)
        process_sensor_telemetry(db, "PARKPLUS_GATE_01", "P01", 10.0, True)
        process_sensor_telemetry(db, "PARKPLUS_GATE_01", "P01", 30.0, False)
        db.execute(
            "UPDATE parking_departure_watches SET empty_since = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),)
        )
        db.commit()
        db.close()

        with patch("backend.routes.parking.send_telegram_message") as send_message:
            response = self.client.post(
                "/api/parking/gate/scan",
                json={"device_code": "PARKPLUS_GATE_01", "rfid_uid": "AB12CD34"},
                headers=self.device_headers(),
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("PARKING SESSION COMPLETED", send_message.call_args.args[0])

            send_message.reset_mock()
            self.client.post(
                "/api/slots/update",
                json={
                    "device_code": "PARKPLUS_GATE_01",
                    "slot_code": "P01",
                    "occupied": False,
                    "sensor_health": "healthy",
                    "distance_cm": 30,
                },
                headers=self.device_headers(),
            )
            send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
