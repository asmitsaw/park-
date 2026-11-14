import os
import tempfile
import unittest

from backend.app import create_app
from backend.config import Config
from backend.database import get_db_connection, init_db


class SubscriptionPlanTests(unittest.TestCase):
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

    def test_create_plan_saves_requested_plan_details(self):
        response = self.client.post("/api/subscriptions/plans", json={
            "name": "Weekend Commuter",
            "plan_type": "prepaid",
            "duration_days": 45,
            "allocated_hours": 12,
            "price_inr": 499.99,
            "description": "Parking time valid for 45 days.",
        })

        self.assertEqual(response.status_code, 201)
        db = get_db_connection(Config.DB_PATH)
        plan = db.execute(
            "SELECT * FROM subscription_plans WHERE id = ?",
            (response.get_json()["plan_id"],),
        ).fetchone()
        self.assertEqual(plan["name"], "Weekend Commuter")
        self.assertEqual(plan["plan_type"], "prepaid")
        self.assertEqual(plan["duration_days"], 45)
        self.assertEqual(plan["allocated_seconds"], 12 * 3600)
        self.assertEqual(plan["price_paise"], 49999)
        self.assertEqual(plan["description"], "Parking time valid for 45 days.")
        db.close()


if __name__ == "__main__":
    unittest.main()
