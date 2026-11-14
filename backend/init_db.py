import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import init_db

if __name__ == "__main__":
    force_reset = "--force" in sys.argv
    print(f"[*] Initializing PARK+ Database (parksentinel.db) | Force reset: {force_reset} ...")
    try:
        init_db(force=force_reset)
        print("[+] Database successfully initialized with tables, schema, constraints, and seed data.")
    except Exception as ex:
        print(f"[!] Database initialization failed: {ex}")
        sys.exit(1)

