# PARK+

**PARK+ — Intelligent Parking & Vehicle Security Management System**  
**Park Smart. Stay Secure.**

PARK+ is a local-network parking management prototype. A Flask application serves a vanilla HTML/CSS/JavaScript admin console and REST API, stores data in SQLite, and communicates with an ESP32 gate controller. The controller reads RFID cards, operates a servo barrier, and reports two IR parking sensors.

The admin console is organized into three areas:

1. **Overview & Parking** — live dashboard, parking slots, sessions, and physical gate status.
2. **Customer Registry** — customers, vehicles, RFID cards, subscriptions, and transaction ledger.
3. **Security & System** — incidents, helpdesk, ESP32 device status, analytics/CSV reports, and settings.

## Features

- Session-based admin login and logout.
- Customer, vehicle, RFID-card, subscription, parking-session, incident, ticket, and device management.
- Permanent customer deletion with confirmation, including linked parking and subscription records; deletion is blocked while a vehicle is actively parked or has a pending gate entry.
- Two seeded parking slots, P01 and P02.
- RFID entry/exit authorization, IR-detected slot assignment, and subscription-time accounting.
- Admin-initiated RFID reader capture: request a scan, present a tag to the ESP32 RC522 reader, and have the UID filled into the card form automatically.
- ESP32 heartbeat, ultrasonic telemetry, and servo gate control.
- Dashboard KPI cards, live slot status, Chart.js charts, and recent RFID activity.
- Analytics overview and CSV exports.
- SQLite persistence with only the admin, parking slots, subscription plans, and system settings initialized automatically.
- ESP32 firmware and wiring instructions in [esp32/README_ESP32.md](esp32/README_ESP32.md).

## Technology

- **Frontend:** HTML5, CSS3, vanilla JavaScript, Fetch API, locally served Chart.js.
- **Backend:** Python 3, Flask, Flask-CORS, SQLite.
- **Hardware:** ESP32, RC522, two digital IR obstacle sensors, SG90 servo, I2C LCD, and buzzer.
- **ML examples:** optional scripts in `ml/` using Pandas, NumPy, and scikit-learn.

## Requirements

- Windows 10/11 (commands below use PowerShell).
- Python 3.10 or newer.
- A browser on the same machine or trusted local network.
- Optional: Arduino IDE and an ESP32 board for hardware operation.

The Flask server, SQLite database, frontend assets, and Chart.js library run locally; the application does not need internet connectivity after dependencies are installed. Chart.js is bundled under `frontend/static/vendor/`; its MIT license is included alongside the bundle.

## Quick start (Windows PowerShell)

Run commands from the project root:

```powershell
cd D:\PARK+
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
Copy-Item .env.example backend\.env
```

Edit `backend\.env` before first initialization. Set unique values for at least:

```dotenv
SECRET_KEY=use-a-long-random-value
DEVICE_SHARED_SECRET=use-a-different-random-value
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@parkplus.local
ADMIN_PASSWORD=choose-a-strong-initial-password
ADMIN_NAME=PARK+ Administrator
```

Then initialize the database and start the application:

```powershell
python -m backend.init_db
python run.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The app redirects to the login page. Use the `ADMIN_USERNAME` and `ADMIN_PASSWORD` values configured in `backend\.env`.

`run.py` also initializes the schema automatically, so running `python run.py` is enough for a first launch. The explicit initialization command is useful when setting up the project or confirming the database is ready.

### Environment variables

`backend/config.py` loads `backend\.env`. Supported variables include:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Flask session signing key. Keep it private and stable between restarts. |
| `DB_PATH` | Optional SQLite path. By default, the database is `backend\instance\parksentinel.db`. |
| `DEVICE_SHARED_SECRET` | Shared secret for device-authenticated RFID capture requests/results. Configure the same value in the ESP32 sketch. |
| `ADMIN_USERNAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAME` | Initial admin seed account. These values seed an admin only when that username does not already exist. |
| `MIN_PARKING_ALLOWANCE_SECONDS` | Minimum remaining subscription time required for entry. |
| `OVERAGE_RATE_PER_HOUR_PAISE` | Overage rate, in paise per hour. |
| `DEVICE_HEARTBEAT_TIMEOUT_SECONDS` | Time after which a device heartbeat is considered stale. |
| `SLOT_DISTANCE_THRESHOLD_CM` | Sensor distance at or below which a slot is considered occupied. |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token. Keep it only in a local environment file; rotate it if exposed. |
| `TELEGRAM_CHAT_ID` | Telegram user or group chat ID that receives PARK+ notifications. |
| `PORT` | Optional HTTP port used by `run.py`; defaults to `5000`. |

Changing the seed admin variables does **not** change an account already stored in the database. Do not use the example placeholder values as production secrets. The included `.env.example` is a template, not a credential file.

### Database and seed data

The default SQLite file is `backend\instance\parksentinel.db`. Normal initialization is non-destructive: it creates missing tables and seeds the admin, two parking slots, subscription plans, and system settings. It does not create sample devices, customers, vehicles, RFID cards, or subscriptions. Existing database records are left unchanged; an ESP32 heartbeat creates its device record automatically.

To intentionally reset and reseed the database:

```powershell
python -m backend.init_db --force
```

**Warning:** `--force` drops existing application tables and deletes the database's stored customers, vehicles, RFID cards, subscriptions, sessions, incidents, and logs. Back up the database first if its data matters.

## Admin RFID card registration

1. Open **Customer Registry → RFID Cards → Register RFID Card**.
2. Optionally select the customer and vehicle for the card.
3. Select **Read tag with RC522**.
4. Present the physical tag to the ESP32's RC522 reader while the request is pending.
5. The captured UID is inserted into the read-only UID field. Complete the other fields and save the card.

The scan is one-shot and times out after 90 seconds. The console waits for the ESP32 to acknowledge the request before asking you to present the tag. Closing the registration modal cancels an outstanding request. In capture mode, the ESP32 sends the UID to the capture API and **does not authorize parking or move the barrier**. The reader and server must be reachable on the same network, and the ESP32 must be running firmware with capture support (version 1.1.0 or newer in this project).

## IR-based parking slot assignment

An entry RFID scan authorizes the vehicle and opens the gate, but does not choose P01 or P02 or start a parking session. The backend waits up to five minutes for a healthy slot sensor to change from empty to occupied, then assigns that detected slot and starts the session at the sensor detection time. Only one vehicle per gate device may wait for detection at a time; subsequent entry scans are denied until the pending vehicle is assigned or expires. If the timeout expires, no slot or parking session is created.

## ESP32 setup

See [esp32/README_ESP32.md](esp32/README_ESP32.md) for the bill of materials, pin table, library list, wiring guidance, Wi-Fi setup, and firmware workflow.

At minimum, edit `esp32\ParkPlus_ESP32.ino`:

- Set `WIFI_SSID` and `WIFI_PASSWORD`.
- Set `SERVER_BASE_URL` to the host computer's LAN address, for example `http://192.168.1.25:5000`; do not use `localhost`.
- Set `DEVICE_SECRET` to the same value as `DEVICE_SHARED_SECRET` in `backend\.env`.

Start the Flask app before uploading/running the board. The ESP32 is an HTTP client that sends requests to Flask; it does not host a web server, and the PC does not need to connect back to the ESP32. With the current `run.py` setup and private LAN `SERVER_BASE_URL`, the board and host must be on networks that can route to each other (usually the same Wi-Fi/LAN); client isolation or firewall rules must not block that traffic.

The ESP32 can join a different Wi-Fi network only if that network can reach the backend. For remote access, use a properly secured production backend over HTTPS with TLS support added to the firmware, or a suitably secured VPN/routed connection. Do not expose Flask's development server directly to the public internet.

## REST API overview

Admin JSON APIs use the Flask session cookie created by `/api/auth/login`. Device capture endpoints use `X-Device-Token`. Typical errors are JSON with an `error` field and an appropriate HTTP status.

| Area | Routes |
| --- | --- |
| Authentication | `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` |
| Dashboard | `GET /api/dashboard/summary`, `/charts`, `/activity` |
| Customers | `/api/users` and `/api/users/<id>` (GET/POST/PUT/DELETE); DELETE with `{"purge_history": true}` removes linked customer history but is refused for active parking or pending gate entries |
| Vehicles | `/api/vehicles` and `/api/vehicles/<id>` |
| RFID cards and scans | `/api/rfid/cards`, `/register`, `/scans`, `/unregistered`, `/<card_id>/status` |
| RFID reader capture | Admin: `POST /api/rfid/capture/request`, `GET /api/rfid/capture/request/<id>`, `POST /api/rfid/capture/request/<id>/cancel`; device: `GET /api/rfid/capture/pending?device_code=PARKPLUS_GATE_01`, `POST /api/rfid/capture/result` |
| Subscriptions | `/api/subscriptions`, `/api/subscriptions/plans`, `/api/subscriptions/assign`, `/api/subscriptions/transactions` |
| Parking and sensors | `/api/parking/slots`, `/api/parking/sessions`, `/api/parking/gate/scan` (combined entry/exit), `/api/parking/entry`, `/api/parking/exit/authorize`, `/api/parking/exit/confirm`, `/api/slots/update` |
| Security and support | `/api/security/events`, `/api/helpdesk/tickets` |
| Devices | `/api/devices`, `POST /api/devices/heartbeat` |
| Analytics and settings | `/api/analytics/overview`, `/api/analytics/export/csv`, `/api/settings` |

The complete route list is available by running the app and inspecting its Flask URL map. The ESP32 sketch demonstrates the request JSON formats for telemetry, heartbeats, and RFID capture.

## Project layout

```text
run.py                         Flask development-server entry point
backend/
  app.py                       Flask app factory, pages, and API registration
  config.py                    Environment and application settings
  database.py                  SQLite connections, schema initialization, seed data
  schema.sql                   Tables, foreign keys, and indexes
  routes/                      REST API blueprints
  services/                    Parking, security, and subscription logic
  instance/parksentinel.db     Default local SQLite database
frontend/
  templates/                   Login and admin console templates
  static/css/style.css         Neo-brutalist responsive design
  static/js/app.js             Vanilla JavaScript admin application
  static/vendor/               Locally served Chart.js and its MIT license
esp32/
  ParkPlus_ESP32.ino           Gate and slot controller firmware
  README_ESP32.md              Hardware and firmware guide
ml/
  train_model.py               Optional model training example
  predict.py                   Optional prediction example
tests/
  test_rfid_capture.py         RFID capture API tests
```

## Tests

Run the RFID capture API tests from the project root:

```powershell
python -m unittest discover -s tests -v
```

These tests use a temporary SQLite database and do not reset the project's normal database.

## Troubleshooting

- **Cannot log in:** confirm `backend\.env` was created before the first DB initialization. Existing seeded admin records keep their original password; resetting the database is destructive.
- **ESP32 is offline:** confirm the host LAN IP, port, Wi-Fi credentials, firewall rule, shared network, and heartbeat requests in the serial monitor.
- **RFID capture waits or expires:** ensure the board is powered, online, running firmware 1.1.0+, using the matching device secret, and that the RC522 is wired correctly.
- **Tag UID is not captured:** verify the RC522 is powered from 3.3V, check SPI pin wiring, and present a compatible 13.56 MHz tag.
- **Sensor data is implausible:** check sensor wiring and use an appropriate level shifter or resistor divider on each HC-SR04 ECHO signal; ESP32 GPIO inputs are not 5V tolerant.
- **Charts are blank:** confirm `frontend\static\vendor\chart.umd.min.js` exists and the browser loaded `/static/vendor/chart.umd.min.js`.
- **Port is already in use:** set `PORT` to another port and update `SERVER_BASE_URL` in the firmware to match.

## Security and prototype limitations

This is a local-network engineering prototype, not a hardened public deployment. Use unique secrets, protect `backend\.env` and the SQLite file, limit network access with the host firewall, and do not expose the Flask development server to the public internet. The admin interface uses cookie-based sessions; use HTTPS and appropriate production hosting before handling real customer data. Review each IoT endpoint's authentication behavior before deploying hardware outside a trusted LAN.



## Telegram bot notifications

Telegram is integrated on the Flask backend. The ESP32 does **not** contain the Telegram bot token and does not contact Telegram directly.

1. In Telegram, open your bot and send `/start`.
2. Revoke any token that was shared, create a replacement with BotFather, and set it as `TELEGRAM_BOT_TOKEN` in `backend\.env`. This file is loaded after the project-root `.env` and overrides it. Do not commit the token or paste it into source code. The existing legacy variable name `telegram_bot_token` is also read.
3. Run this from the project root:
   ```powershell
   python -m backend.telegram_setup
   ```
4. Copy the returned numeric chat ID into `TELEGRAM_CHAT_ID` in `backend\.env`.
5. Restart Flask and test from an authenticated admin session:
   ```javascript
   fetch('/api/security/telegram/test', {
     method: 'POST',
     credentials: 'same-origin'
   }).then(r => r.json()).then(console.log);
   ```

The configured Telegram user/group receives a clearly formatted parking-start message only after the IR sensor assigns the actual slot. Exit messages include start/end times, parking duration, remaining subscription time, and any overage. Telegram timestamps are displayed in Indian Standard Time (IST). If a healthy slot sensor later reports an active session's slot empty, PARK+ sends an unscanned-departure alert after the configured threshold. The default is three minutes; change it under **Security → Empty-slot alert threshold**. The alert is cancelled if the vehicle is observed in the slot again or its RFID exit is recorded. Telegram failures are logged and do not stop parking operations.

The bot must receive `/start` before `getUpdates` can return your personal chat ID. For a group, add the bot to the group, send a message there, and run the setup command again. Set the group chat ID (often a negative number) in `TELEGRAM_CHAT_ID`.

## Updated ESP32 firmware

The updated sketch is `esp32/ParkPlus_ESP32/ParkPlus_ESP32_IR_PinFix_Debug.ino`. It uses IR slot sensors, sends heartbeat and slot telemetry, supports admin RFID capture, and calls `/api/parking/gate/scan` to determine entry versus exit from the card's active session. Configure Wi-Fi credentials, the PC LAN IP, and the same `DEVICE_SHARED_SECRET` used by Flask before uploading. The `distance_cm` telemetry value in this IR firmware is a nominal occupied/empty indicator (10 cm or 30 cm), not a measured distance.
