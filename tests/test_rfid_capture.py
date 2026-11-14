import os
import tempfile
import unittest

from backend.app import create_app
from backend.config import Config
from backend.database import get_db_connection, init_db


class RfidCaptureApiTests(unittest.TestCase):
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

    def login(self):
        response = self.client.post("/api/auth/login", json={
            "username": Config.ADMIN_USERNAME,
            "password": Config.ADMIN_PASSWORD,
        })
        self.assertEqual(response.status_code, 200)

    def request_capture(self):
        response = self.client.post("/api/rfid/capture/request")
        self.assertEqual(response.status_code, 202)
        return response.get_json()["request_id"]

    def test_capture_request_requires_admin_and_device_secret(self):
        response = self.client.post("/api/rfid/capture/request")
        self.assertEqual(response.status_code, 401)

        response = self.client.get("/api/rfid/capture/pending")
        self.assertEqual(response.status_code, 401)

        self.login()
        response = self.client.post("/api/rfid/capture/request")
        self.assertEqual(response.status_code, 202)

    def test_reader_result_is_returned_to_admin_and_cannot_be_reused(self):
        self.login()
        request_id = self.request_capture()
        device_headers = {"X-Device-Token": Config.DEVICE_SHARED_SECRET}

        response = self.client.post("/api/rfid/capture/result", json={
            "request_id": request_id,
            "device_code": "PARKPLUS_GATE_01",
            "card_uid": "DEADBEEF",
        }, headers=device_headers)
        self.assertEqual(response.status_code, 409)

        response = self.client.get(
            "/api/rfid/capture/pending?device_code=PARKPLUS_GATE_01",
            headers=device_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["request_id"], request_id)
        response = self.client.get(f"/api/rfid/capture/request/{request_id}")
        self.assertEqual(response.get_json()["status"], "ready")

        response = self.client.post("/api/rfid/capture/result", json={
            "request_id": request_id,
            "device_code": "PARKPLUS_GATE_01",
            "card_uid": "deadbeef",
        }, headers=device_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["card_uid"], "DEADBEEF")

        response = self.client.get(f"/api/rfid/capture/request/{request_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "captured")
        self.assertEqual(response.get_json()["card_uid"], "DEADBEEF")

        response = self.client.post("/api/rfid/capture/result", json={
            "request_id": request_id,
            "device_code": "PARKPLUS_GATE_01",
            "card_uid": "DEADBEEF",
        }, headers=device_headers)
        self.assertEqual(response.status_code, 409)

    def test_invalid_uid_and_cancelled_request_are_rejected(self):
        self.login()
        request_id = self.request_capture()
        device_headers = {"X-Device-Token": Config.DEVICE_SHARED_SECRET}
        self.client.get(
            "/api/rfid/capture/pending?device_code=PARKPLUS_GATE_01",
            headers=device_headers,
        )

        response = self.client.post("/api/rfid/capture/result", json={
            "request_id": request_id,
            "device_code": "PARKPLUS_GATE_01",
            "card_uid": "not-hex",
        }, headers=device_headers)
        self.assertEqual(response.status_code, 400)

        response = self.client.post(f"/api/rfid/capture/request/{request_id}/cancel")
        self.assertEqual(response.status_code, 200)
        response = self.client.get(f"/api/rfid/capture/request/{request_id}")
        self.assertEqual(response.get_json()["status"], "cancelled")

        response = self.client.post("/api/rfid/capture/result", json={
            "request_id": request_id,
            "device_code": "PARKPLUS_GATE_01",
            "card_uid": "DEADBEEF",
        }, headers=device_headers)
        self.assertEqual(response.status_code, 409)

    def test_expired_capture_request_cannot_be_completed(self):
        self.login()
        request_id = self.request_capture()
        db = get_db_connection(Config.DB_PATH)
        db.execute(
            "UPDATE rfid_capture_requests SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00Z", request_id),
        )
        db.commit()
        db.close()

        response = self.client.get(f"/api/rfid/capture/request/{request_id}")
        self.assertEqual(response.get_json()["status"], "expired")

        response = self.client.post("/api/rfid/capture/result", json={
            "request_id": request_id,
            "device_code": "PARKPLUS_GATE_01",
            "card_uid": "DEADBEEF",
        }, headers={"X-Device-Token": Config.DEVICE_SHARED_SECRET})
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
