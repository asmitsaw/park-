import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.app import create_app
from backend.database import init_db

if __name__ == "__main__":
    print("[*] Starting PARK+ - Intelligent Parking & Vehicle Security Management System")
    init_db()
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    print(f"\n[+] PARK+ Web Server ready at http://127.0.0.1:{port}")
    print(f"[+] To access from ESP32, use your machine's LAN IP (e.g., http://172.19.79.180:{port})")
    print("[+] Use the initial admin credentials configured in backend/.env\n")
    app.run(host="0.0.0.0", port=port, debug=False)

