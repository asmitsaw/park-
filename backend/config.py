import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory: PARK+
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = Path(__file__).resolve().parent

# Load .env file
load_dotenv(BASE_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env", override=True)

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "parkplus-super-secret-dev-key-change-in-production-2026")
    
    # SQLite Database Path
    DB_PATH = os.getenv("DB_PATH", str(BACKEND_DIR / "instance" / "parksentinel.db"))
    
    # ESP32 Device Authentication Secret
    DEVICE_SHARED_SECRET = os.getenv("DEVICE_SHARED_SECRET", "parkplus-esp32-auth-token-998877")
    
    # Session security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False  # Set to True in HTTPS production
    
    # Admin Seed Credentials
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@parkplus.local")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@12345")
    ADMIN_NAME = os.getenv("ADMIN_NAME", "PARK+ Chief Controller")

    # Business Logic Defaults
    MIN_PARKING_ALLOWANCE_SECONDS = int(os.getenv("MIN_PARKING_ALLOWANCE_SECONDS", "900"))  # 15 minutes minimum
    OVERAGE_RATE_PER_HOUR_PAISE = int(os.getenv("OVERAGE_RATE_PER_HOUR_PAISE", "5000"))   # ₹50 per hour
    DEVICE_HEARTBEAT_TIMEOUT_SECONDS = int(os.getenv("DEVICE_HEARTBEAT_TIMEOUT_SECONDS", "60"))
    SLOT_DISTANCE_THRESHOLD_CM = float(os.getenv("SLOT_DISTANCE_THRESHOLD_CM", "20.0"))    # <= 20cm considered occupied
    UNSCANNED_DEPARTURE_ALERT_MINUTES = 3

    # Telegram notifications (token may be supplied as TELEGRAM_BOT_TOKEN or legacy telegram_bot_token)
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("telegram_bot_token", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

