# PARK+ : ESP32 IoT Gate & Dual-Slot Controller Setup

## 1. Hardware Bill of Materials (BOM)
| Component | Quantity | Purpose |
| :--- | :--- | :--- |
| **ESP32 NodeMCU / DevKit V1** | 1 | Microcontroller & Wi-Fi Gateway |
| **RC522 RFID SPI Reader (13.56 MHz)** | 1 | Vehicle Tag Identification at Entry Gate |
| **HC-SR04 Ultrasonic Sensors** | 2 | Real-time vehicle presence detection for Slots P01 & P02 |
| **SG90 9g Micro Servo Motor** | 1 | Physical gate boom barrier actuator |
| **I2C 16x2 LCD Display (0x27 / 0x3F)** | 1 | Driver guidance & status display |
| **Piezo Buzzer (5V)** | 1 | Audio feedback for grant/denial/alerts |
| **Jumper Wires & Breadboard** | - | Interconnections |

---

## 2. Pinout Wiring Matrix

### A. RC522 RFID Reader (SPI Interface)
| RC522 Pin | ESP32 GPIO | Description |
| :--- | :--- | :--- |
| **VCC** | 3.3V (Do NOT use 5V) | Power supply |
| **RST** | GPIO 26 | Reset |
| **GND** | GND | Ground |
| **MISO** | GPIO 19 | SPI MISO |
| **MOSI** | GPIO 23 | SPI MOSI |
| **SCK** | GPIO 18 | SPI Clock |
| **SDA / SS** | GPIO 5 | Chip Select |

### B. Ultrasonic Sensors (HC-SR04)
| Sensor | Pin | ESP32 GPIO |
| :--- | :--- | :--- |
| **Slot P01** | TRIG | GPIO 12 |
| **Slot P01** | ECHO | GPIO 13 |
| **Slot P02** | TRIG | GPIO 27 |
| **Slot P02** | ECHO | GPIO 14 |
| *Both* | VCC / GND | 5V / GND |

### C. Gate Barrier Servo & Buzzer
| Component | Pin | ESP32 GPIO |
| :--- | :--- | :--- |
| **SG90 Servo** | Signal (Orange/Yellow) | GPIO 4 |
| **SG90 Servo** | Power (Red) & GND (Brown) | 5V & GND |
| **Piezo Buzzer** | Positive (+) | GPIO 15 |
| **Piezo Buzzer** | Negative (-) | GND |

### D. I2C LCD Display (16x2)
| LCD Pin | ESP32 GPIO |
| :--- | :--- |
| **SDA** | GPIO 21 |
| **SCL** | GPIO 22 |
| **VCC / GND** | 5V / GND |

---

## 3. Required Arduino IDE Libraries
Install these libraries via **Tools -> Manage Libraries...**:
1. `ArduinoJson` (by Benoit Blanchon, Version 6.x or 7.x)
2. `MFRC522` (by GithubCommunity)
3. `ESP32Servo` (by Kevin Harrington)
4. `LiquidCrystal_I2C` (by Marco Schwartz)

---

## 4. Local Network & Backend Server Configuration
1. Find your host computer's IPv4 address on the local Wi-Fi:
   ```powershell
   ipconfig
   # Look for "IPv4 Address", e.g., 192.168.1.100
   ```
2. Open `ParkPlus_ESP32.ino` and update:
   ```cpp
   const char* WIFI_SSID     = "Your_WiFi_Name";
   const char* WIFI_PASSWORD = "Your_WiFi_Password";
   const char* SERVER_BASE_URL = "http://192.168.1.100:5000"; // Your PC's LAN IP
   ```
3. Connect the ESP32 via micro-USB, select the board **ESP32 Dev Module**, and click **Upload**.
4. Open the Serial Monitor at `115200 baud` to verify Wi-Fi association and initial heartbeat transmission.

The ESP32 makes HTTP requests to the Flask backend; it does not run a web server, and the backend does not need to initiate a connection to the ESP32. The configured backend address must be reachable from the ESP32's network. In this local setup, use the PC's LAN IP and allow the configured port through its firewall. Different Wi-Fi networks work only when routing or a VPN connects them. For public remote access, use a production HTTPS backend and add TLS support to the firmware; do not expose Flask's development server directly to the internet.

## 5. Admin-Initiated RFID Tag Capture

The admin console can request a one-time tag read from **Customer Registry → RFID Cards → Register RFID Card → Read tag with RC522**. While the request is pending, the firmware polls the capture endpoint and treats the next card presentation as a registration read. It sends the UID to the backend without authorizing entry or moving the barrier. A request expires after 90 seconds.

Use firmware version `1.1.0` or newer for this feature. Set `DEVICE_SECRET` in the sketch to the same value as `DEVICE_SHARED_SECRET` in `backend\.env`. Keep the ESP32 and host on a trusted network that allows the ESP32 to reach the backend.

## 6. IR-Based Slot Assignment

An entry RFID scan authorizes the gate but does not reserve P01 or P02. The backend waits up to five minutes for a healthy IR sensor to change from empty to occupied, then assigns that detected slot and starts the parking session. Only one vehicle per gate device can wait for slot detection at a time; a later entry scan is denied until the pending vehicle is assigned or expires. The LCD shows that the driver should park in an IR-monitored slot.

The firmware samples IR locally every 500 ms, sends occupancy changes immediately, and refreshes unchanged empty-slot status every 30 seconds for the departure-alert timer. Routine sensor reports are deferred while an RFID scan request is pending.

## 7. Electrical and Pin Notes

- Power the RC522 from **3.3V**, not 5V.
- ESP32 GPIO inputs are not 5V tolerant. Use a level shifter or resistor divider on each HC-SR04 ECHO line.
- RFID reset uses GPIO 26. The I2C LCD SCL uses GPIO 22; these pins must remain separate.
- Power the servo from a separate, regulated 5V supply; do not power it from the ESP32 3.3V pin. Connect the servo supply ground to ESP32 ground, keep the RC522 on a stable 3.3V supply, and place a 470-1000 uF capacitor across the servo supply near the servo to reduce motor-noise dips.

For application setup, environment variables, API details, and troubleshooting, see the project [README](../README.md).















































































































final code last which has server issue but ok

/*
  PARK+ ESP32 GATE CONTROLLER - IR SENSOR EDITION
  Compatible with the uploaded Flask/SQLite API routes.

  Libraries (Arduino Library Manager):
    - ArduinoJson (6.x or 7.x)
    - MFRC522
    - ESP32Servo
    - LiquidCrystal_I2C

  IMPORTANT:
    1. Fill WIFI_SSID, WIFI_PASSWORD and DEVICE_SECRET below.
    2. SERVER_BASE_URL should use the PC's LAN IPv4, not localhost.
    3. This firmware uses the existing /api/parking/gate/scan,
       /api/slots/update,
       /api/rfid/capture/pending and /api/rfid/capture/result routes.
    4. The uploaded backend's slot API is ultrasonic-oriented. To preserve
       compatibility, distance_cm is sent as a nominal indicator (10 cm when
       occupied, 30 cm when empty); it is NOT a measured distance. Backend
       should eventually be updated to store sensor_type='ir'.
    5. Digital IR modules cannot reliably report a disconnected/fault state.
*/

#include <WiFi.h>
#include <WiFiClient.h>
#include <HTTPClient.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <ArduinoJson.h>
#include <SPI.h>
#include <MFRC522.h>
#include <ESP32Servo.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// ---------------- USER CONFIGURATION ----------------
const char* WIFI_SSID = "Asmit's F55";
const char* WIFI_PASSWORD = "12345678";
const char* SERVER_BASE_URL = "http://172.19.79.180:5000";
const char* DEVICE_CODE     = "PARKPLUS_GATE_01";
const char* FIRMWARE_VER    = "2.0.0-IR";
const char* DEVICE_SECRET   = "YOUR_DEVICE_SHARED_SECRET";

// ---------------- PIN CONFIGURATION -----------------
// Original peripheral wiring recovered from the user's uploaded sketch.
// IR OUT pins remain GPIO 34 and 35 as used by the currently running IR build.
#define RFID_SS_PIN   21
#define RFID_RST_PIN  22
#define RFID_SCK_PIN  18
#define RFID_MISO_PIN 19
#define RFID_MOSI_PIN 23

#define SERVO_PIN     13
#define BUZZER_PIN    27
#define LCD_SDA_PIN   25
#define LCD_SCL_PIN   26
#define IR_PIN_P01    34
#define IR_PIN_P02    35

// Most LM393 IR obstacle modules pull OUT LOW when an object is detected.
// If your module behaves opposite to the test you ran, change LOW to HIGH.
#define IR_ACTIVE_STATE LOW

// ---------------- TIMING / BEHAVIOUR -----------------
const unsigned long HEARTBEAT_INTERVAL_MS = 25000;
const unsigned long SENSOR_SAMPLE_INTERVAL_MS = 500;
const unsigned long EMPTY_SLOT_REPORT_INTERVAL_MS = 30000;
const unsigned long SENSOR_RETRY_INTERVAL_MS = 5000;
const unsigned long CAPTURE_POLL_INTERVAL_MS = 5000;
const unsigned long HTTP_TIMEOUT_MS = 3000;
const unsigned long BARRIER_OPEN_MS = 4500; // prototype timer; not a safety sensor
const unsigned long RFID_RECOVERY_DELAY_MS = 300;
const unsigned long RFID_COOLDOWN_MS = 1000;
const int SERVO_OPEN_ANGLE = 90;
const int SERVO_CLOSE_ANGLE = 0;
const uint8_t IR_SAMPLE_COUNT = 7;
const uint8_t IR_REQUIRED_ACTIVE = 5;

MFRC522 rfid(RFID_SS_PIN, RFID_RST_PIN);
Servo barrierServo;
LiquidCrystal_I2C lcd(0x27, 16, 2);

unsigned long lastHeartbeatAt = 0;
unsigned long lastSensorAt = 0;
unsigned long lastCapturePollAt = 0;
unsigned long lastRfidAt = 0;
volatile long activeCaptureRequestId = -1;
volatile bool rfidRequestPending = false;
bool slotP01Occupied = false;
bool slotP02Occupied = false;
bool slotP01TelemetryInitialized = false;
bool slotP02TelemetryInitialized = false;
bool barrierIsOpen = false;
volatile bool pendingSecurityAlertBeep = false;
unsigned long barrierOpenedAt = 0;
bool rfidRecoveryPending = false;
unsigned long rfidRecoveryAt = 0;
unsigned long lastP01TelemetryAt = 0;
unsigned long lastP02TelemetryAt = 0;
unsigned long retryP01TelemetryAt = 0;
unsigned long retryP02TelemetryAt = 0;
SemaphoreHandle_t networkMutex = nullptr;

String endpoint(const String& path) { return String(SERVER_BASE_URL) + path; }

void beepSuccess() {
  tone(BUZZER_PIN, 1900, 110); delay(130);
  tone(BUZZER_PIN, 2450, 130);
}
void beepDenied() {
  tone(BUZZER_PIN, 500, 220); delay(250);
  tone(BUZZER_PIN, 380, 260);
}
void beepWarning() { tone(BUZZER_PIN, 1100, 160); }

void showReady() {
  lcd.clear();
  lcd.setCursor(0, 0); lcd.print("PARK+ GATE READY");
  lcd.setCursor(0, 1); lcd.print("Scan RFID Card");
}

void scheduleRfidRecovery() {
  rfidRecoveryAt = millis() + RFID_RECOVERY_DELAY_MS;
  rfidRecoveryPending = true;
}

void serviceRfidRecovery() {
  if (!rfidRecoveryPending || (long)(millis() - rfidRecoveryAt) < 0) return;

  rfidRecoveryPending = false;
  rfid.PCD_Init();
  delay(50);
  Serial.println("[RFID] RC522 reinitialized after servo movement");
}

void openBarrier() {
  barrierServo.write(SERVO_OPEN_ANGLE);
  barrierIsOpen = true;
  barrierOpenedAt = millis();
  scheduleRfidRecovery();
}
void closeBarrier() {
  barrierServo.write(SERVO_CLOSE_ANGLE);
  barrierIsOpen = false;
}
void maintainBarrier() {
  // Demo-only timed closure. Add a physical passage/obstruction safety sensor
  // before using a real barrier; never let a timer close onto a vehicle/person.
  if (barrierIsOpen && millis() - barrierOpenedAt >= BARRIER_OPEN_MS) {
    closeBarrier();
    scheduleRfidRecovery();
  }
}

bool wifiReady() {
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 8000) delay(250);
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WIFI] Reconnected: %s\n", WiFi.localIP().toString().c_str());
    return true;
  }
  Serial.println("[WIFI] Reconnection failed");
  return false;
}

int requestJson(const String& path, const String& payload, bool isPost,
                String& response, bool rfidPriority = false) {
  if (!rfidPriority && rfidRequestPending) return -4;
  if (!networkMutex || xSemaphoreTake(networkMutex, portMAX_DELAY) != pdTRUE) return -3;
  if (!rfidPriority && rfidRequestPending) {
    xSemaphoreGive(networkMutex);
    return -4;
  }
  if (!wifiReady()) {
    xSemaphoreGive(networkMutex);
    return -1;
  }

  WiFiClient client;
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(client, endpoint(path))) {
    xSemaphoreGive(networkMutex);
    return -2;
  }
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_SECRET);
  int code = isPost ? http.POST(payload) : http.GET();
  response = http.getString();
  http.end();
  xSemaphoreGive(networkMutex);
  return code;
}

void sendHeartbeat() {
  StaticJsonDocument<256> doc;
  doc["device_code"] = DEVICE_CODE;
  doc["firmware_version"] = FIRMWARE_VER;
  doc["ip_address"] = WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : "";
  String payload, response;
  serializeJson(doc, payload);
  int code = requestJson("/api/devices/heartbeat", payload, true, response);
  Serial.printf("[HEARTBEAT] HTTP %d %s\n", code, response.c_str());
}

bool readIRStable(int pin) {
  uint8_t activeCount = 0;
  for (uint8_t i = 0; i < IR_SAMPLE_COUNT; i++) {
    if (digitalRead(pin) == IR_ACTIVE_STATE) activeCount++;
    delay(8);
  }
  return activeCount >= IR_REQUIRED_ACTIVE;
}

bool sendSlotTelemetry(const char* slotCode, bool occupied, bool& previousState) {
  StaticJsonDocument<320> doc;
  doc["device_code"] = DEVICE_CODE;
  doc["slot_code"] = slotCode;
  doc["sensor_type"] = "ir";
  doc["occupied"] = occupied;
  doc["sensor_health"] = "healthy";
  // Compatibility with current backend's float(distance_cm) parser only.
  // This is a nominal occupied/empty indicator, NOT a physical measurement.
  doc["distance_cm"] = occupied ? 10.0 : 30.0;

  String payload, response;
  serializeJson(doc, payload);
  int code = requestJson("/api/slots/update", payload, true, response);
  if (code == -4) return false;
  Serial.printf("[SLOT %s] %s | IR | HTTP %d\n",
                slotCode, occupied ? "OCCUPIED" : "EMPTY", code);

  if (code >= 200 && code < 300) {
    previousState = occupied;
    StaticJsonDocument<768> result;
    if (deserializeJson(result, response) == DeserializationError::Ok) {
      const char* alert = result["data"]["security_alert"] | "";
      if (strlen(alert) > 0) {
        Serial.printf("[SECURITY ALERT] %s\n", alert);
        pendingSecurityAlertBeep = true;
      }
    }
    return true;
  } else {
    Serial.printf("[API ERROR] Slot update: %s\n", response.c_str());
    return false;
  }
}

void updateSlotTelemetry(const char* slotCode, bool occupied, bool& previousState,
                         bool& initialized, unsigned long& lastReportedAt,
                         unsigned long& retryAt) {
  unsigned long now = millis();
  bool stateChanged = !initialized || occupied != previousState;
  bool emptyRefreshDue = initialized && !occupied &&
                         now - lastReportedAt >= EMPTY_SLOT_REPORT_INTERVAL_MS;
  if (!stateChanged && !emptyRefreshDue) return;
  if (retryAt && (long)(now - retryAt) < 0) return;
  if (sendSlotTelemetry(slotCode, occupied, previousState)) {
    initialized = true;
    lastReportedAt = millis();
    retryAt = 0;
  } else if (!rfidRequestPending) {
    retryAt = millis() + SENSOR_RETRY_INTERVAL_MS;
  }
}

void sampleAndReportSlots() {
  bool p01 = readIRStable(IR_PIN_P01);
  bool p02 = readIRStable(IR_PIN_P02);

  updateSlotTelemetry(
    "P01", p01, slotP01Occupied, slotP01TelemetryInitialized,
    lastP01TelemetryAt, retryP01TelemetryAt
  );
  updateSlotTelemetry(
    "P02", p02, slotP02Occupied, slotP02TelemetryInitialized,
    lastP02TelemetryAt, retryP02TelemetryAt
  );
}

void pollRfidCapture() {
  String response;
  String path = String("/api/rfid/capture/pending?device_code=") + DEVICE_CODE;
  int code = requestJson(path, "", false, response);
  if (code != 200) {
    Serial.printf("[RFID CAPTURE POLL] HTTP %d %s\\n", code, response.c_str());
    return;
  }

  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, response) != DeserializationError::Ok) return;
  if (doc["capture_requested"] == true) {
    long receivedRequestId = doc["request_id"] | -1;
    if (receivedRequestId != activeCaptureRequestId) {
      Serial.printf("[RFID CAPTURE] Request acknowledged. ID=%ld\\n", receivedRequestId);
    }
    activeCaptureRequestId = receivedRequestId;
  } else {
    if (activeCaptureRequestId != -1) Serial.println("[RFID CAPTURE] Request no longer pending.");
    activeCaptureRequestId = -1;
  }
}

void networkTask(void* parameter) {
  (void)parameter;
  lastHeartbeatAt = millis() - HEARTBEAT_INTERVAL_MS;
  lastSensorAt = millis() - SENSOR_SAMPLE_INTERVAL_MS;
  lastCapturePollAt = millis();

  for (;;) {
    unsigned long now = millis();

    if (!rfidRequestPending && now - lastHeartbeatAt >= HEARTBEAT_INTERVAL_MS) {
      lastHeartbeatAt = now;
      sendHeartbeat();
    }
    if (!rfidRequestPending && now - lastSensorAt >= SENSOR_SAMPLE_INTERVAL_MS) {
      lastSensorAt = now;
      sampleAndReportSlots();
    }
    if (!rfidRequestPending && now - lastCapturePollAt >= CAPTURE_POLL_INTERVAL_MS) {
      lastCapturePollAt = now;
      pollRfidCapture();
    }

    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

String readCardUid() {
  String uid;
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  return uid;
}

void submitRfidCapture(const String& uid) {
  StaticJsonDocument<256> doc;
  doc["request_id"] = activeCaptureRequestId;
  doc["device_code"] = DEVICE_CODE;
  doc["card_uid"] = uid;
  String payload, response;
  serializeJson(doc, payload);
  int code = requestJson("/api/rfid/capture/result", payload, true, response, true);
  Serial.printf("[RFID CAPTURE] HTTP %d %s\n", code, response.c_str());
  if (code == 200) {
    activeCaptureRequestId = -1;
    beepSuccess();
    lcd.clear(); lcd.setCursor(0, 0); lcd.print("TAG CAPTURED");
    lcd.setCursor(0, 1); lcd.print(uid.substring(0, 16));
  } else {
    beepDenied();
    lcd.clear(); lcd.setCursor(0, 0); lcd.print("CAPTURE FAILED");
    lcd.setCursor(0, 1); lcd.print("Check admin page");
  }
  delay(1100);
  showReady();
}

bool parseAuthorized(const String& response, String& reason, String& vehicle,
                     String& slot, String& action) {
  StaticJsonDocument<1024> doc;
  if (deserializeJson(doc, response) != DeserializationError::Ok) {
    reason = "Invalid server reply";
    return false;
  }
  reason = String((const char*)(doc["reason"] | doc["message"] | "Access denied"));
  vehicle = String((const char*)(doc["vehicle_reg"] | "Vehicle"));
  slot = String((const char*)(doc["slot_code"] | "--"));
  action = String((const char*)(doc["action"] | "entry"));
  return doc["authorized"] == true;
}
void checkRfid() {

  static unsigned long lastCheckLog = 0;

  if (millis() - lastRfidAt < RFID_COOLDOWN_MS) {
    return;
  }

  // Check whether the reader detects a new card
  bool cardPresent = rfid.PICC_IsNewCardPresent();

  if (!cardPresent) {
    if (millis() - lastCheckLog >= 3000) {
      Serial.println("[RFID DEBUG] Reader active - no card detected");
      lastCheckLog = millis();
    }
    return;
  }

  Serial.println("[RFID DEBUG] Card detected. Reading UID...");

  if (!rfid.PICC_ReadCardSerial()) {
    Serial.println("[RFID DEBUG] UID reading failed");
    return;
  }

  String uid = readCardUid();

  Serial.printf("[RFID] Card UID: %s\n", uid.c_str());

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  lastRfidAt = millis();

  Serial.println("[RFID DEBUG] Card communication completed");
  rfidRequestPending = true;

  if (activeCaptureRequestId > 0) {
    Serial.println("[RFID DEBUG] Sending card to registration endpoint");
    submitRfidCapture(uid);
  } else {
    Serial.println("[RFID DEBUG] Sending card to gate endpoint");
    handleGateScan(uid);
  }

  rfidRequestPending = false;
  Serial.println("[RFID DEBUG] Scan cycle completed");
}
void handleGateScan(const String& uid) {
  lcd.clear(); lcd.setCursor(0, 0); lcd.print("RFID SCANNED");
  lcd.setCursor(0, 1); lcd.print(uid.substring(0, 16));

  StaticJsonDocument<256> doc;
  doc["device_code"] = DEVICE_CODE;
  doc["rfid_uid"] = uid;
  String payload, response;
  serializeJson(doc, payload);

  // The combined route determines entry vs exit from this card's active session.
  int code = requestJson("/api/parking/gate/scan", payload, true, response, true);
  String reason, vehicle, slot, action;
  bool responseAuthorized = parseAuthorized(response, reason, vehicle, slot, action);
  bool authorized = (code == 200) && responseAuthorized;
  if (code <= 0) reason = "Server unavailable";
  else if (reason.length() == 0) reason = "HTTP " + String(code);

  if (authorized) {
    beepSuccess();
    lcd.clear();
    lcd.setCursor(0, 0); lcd.print(action == "exit" ? "EXIT AUTHORIZED" : "ENTRY APPROVED");
    lcd.setCursor(0, 1);
    if (action == "exit") {
      lcd.print(vehicle.substring(0, 16));
      Serial.printf("[ACCESS GRANTED] exit | %s | slot=%s\n", vehicle.c_str(), slot.c_str());
    } else {
      lcd.print("Park in IR slot");
      Serial.printf("[ACCESS GRANTED] entry | %s | waiting for IR slot assignment\n", vehicle.c_str());
    }
    openBarrier();
  } else {
    beepDenied();
    lcd.clear(); lcd.setCursor(0, 0); lcd.print("ACCESS DENIED");
    lcd.setCursor(0, 1); lcd.print(reason.substring(0, 16));
    Serial.printf("[ACCESS DENIED] gateHTTP=%d reason=%s\n", code, reason.c_str());
  }
  delay(1400);
  showReady();
}



void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n================================");
  Serial.println("       PARK+ SYSTEM START");
  Serial.println("       IR FIRMWARE v2.0");
  Serial.println("================================");

  pinMode(IR_PIN_P01, INPUT);
  pinMode(IR_PIN_P02, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  // Servo must use a stable external regulated 5V supply; share GND with ESP32.
  barrierServo.setPeriodHertz(50);
  barrierServo.attach(SERVO_PIN, 500, 2400);
  closeBarrier();
  Serial.println("[GATE] Barrier closed");

  Wire.begin(LCD_SDA_PIN, LCD_SCL_PIN);
  lcd.init();
  lcd.backlight();
  lcd.clear(); lcd.setCursor(0, 0); lcd.print("PARK+ SYSTEM");
  lcd.setCursor(0, 1); lcd.print("Starting IR...");

  networkMutex = xSemaphoreCreateMutex();
  if (!networkMutex) {
    Serial.println("[ERROR] Could not create network mutex");
    while (true) delay(1000);
  }

  SPI.begin(RFID_SCK_PIN, RFID_MISO_PIN, RFID_MOSI_PIN, RFID_SS_PIN);
  rfid.PCD_Init();
  delay(100);
  Serial.println("[RFID] RC522 initialized");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lcd.clear(); lcd.print("Connecting WiFi");
  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 15000) {
    delay(300); Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WIFI] Connected. IP: %s\n", WiFi.localIP().toString().c_str());
    lcd.clear(); lcd.print("WiFi Connected");
    lcd.setCursor(0, 1); lcd.print(WiFi.localIP().toString());
  } else {
    Serial.println("\n[WIFI] Connection failed");
    lcd.clear(); lcd.print("WiFi unavailable");
    lcd.setCursor(0, 1); lcd.print("Check settings");
  }

  BaseType_t taskCreated = xTaskCreatePinnedToCore(
    networkTask, "networkTask", 8192, nullptr, 1, nullptr, 0
  );
  if (taskCreated != pdPASS) {
    Serial.println("[ERROR] Could not start network task");
    while (true) delay(1000);
  }

  delay(900);
  showReady();
  Serial.println("[SYSTEM] PARK+ IR ready");
}

void loop() {
  serviceRfidRecovery();
  checkRfid();

  maintainBarrier();
  if (pendingSecurityAlertBeep) {
    pendingSecurityAlertBeep = false;
    beepWarning();
  }

  static long displayedCaptureRequestId = -1;
  long captureRequestId = activeCaptureRequestId;
  if (captureRequestId != displayedCaptureRequestId) {
    displayedCaptureRequestId = captureRequestId;
    if (captureRequestId > 0) {
      lcd.clear();
      lcd.setCursor(0, 0); lcd.print("ADMIN TAG CAPTURE");
      lcd.setCursor(0, 1); lcd.print("Present RFID Tag");
    } else {
      showReady();
    }
  }
}
