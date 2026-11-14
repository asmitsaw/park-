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
const unsigned long SENSOR_INTERVAL_MS = 1000;
const unsigned long CAPTURE_POLL_INTERVAL_MS = 1200;
const unsigned long HTTP_TIMEOUT_MS = 5000;
const unsigned long BARRIER_OPEN_MS = 4500; // prototype timer; not a safety sensor
const unsigned long RFID_COOLDOWN_MS = 1800;
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
long activeCaptureRequestId = -1;
bool slotP01Occupied = false;
bool slotP02Occupied = false;
bool barrierIsOpen = false;
unsigned long barrierOpenedAt = 0;

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

void openBarrier() {
  barrierServo.write(SERVO_OPEN_ANGLE);
  barrierIsOpen = true;
  barrierOpenedAt = millis();
}
void closeBarrier() {
  barrierServo.write(SERVO_CLOSE_ANGLE);
  barrierIsOpen = false;
}
void maintainBarrier() {
  // Demo-only timed closure. Add a physical passage/obstruction safety sensor
  // before using a real barrier; never let a timer close onto a vehicle/person.
  if (barrierIsOpen && millis() - barrierOpenedAt >= BARRIER_OPEN_MS) closeBarrier();
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

int requestJson(const String& path, const String& payload, bool isPost, String& response) {
  if (!wifiReady()) return -1;
  WiFiClient client;
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(client, endpoint(path))) return -2;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_SECRET);
  int code = isPost ? http.POST(payload) : http.GET();
  response = http.getString();
  http.end();
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

void sendSlotTelemetry(const char* slotCode, bool occupied, bool& previousState) {
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
  Serial.printf("[SLOT %s] %s | IR | HTTP %d\n",
                slotCode, occupied ? "OCCUPIED" : "EMPTY", code);

  if (code >= 200 && code < 300) {
    previousState = occupied;
    StaticJsonDocument<768> result;
    if (deserializeJson(result, response) == DeserializationError::Ok) {
      const char* alert = result["data"]["security_alert"] | "";
      if (strlen(alert) > 0) {
        Serial.printf("[SECURITY ALERT] %s\n", alert);
        beepWarning();
      }
    }
  } else {
    Serial.printf("[API ERROR] Slot update: %s\n", response.c_str());
    beepWarning();
  }
}

void readAndSendSlots() {
  // Stagger reads slightly to avoid simultaneous IR module switching noise.
  bool p01 = readIRStable(IR_PIN_P01);
  bool p02;
  sendSlotTelemetry("P01", p01, slotP01Occupied);
  delay(80);
  p02 = readIRStable(IR_PIN_P02);
  sendSlotTelemetry("P02", p02, slotP02Occupied);
}

void pollRfidCapture() {
  String response;
  String path = String("/api/rfid/capture/pending?device_code=") + DEVICE_CODE;
  int code = requestJson(path, "", false, response);
  if (code != 200) {
    Serial.printf("[RFID CAPTURE POLL] HTTP %d %s\\n", code, response.c_str());
    return;
  }
  Serial.printf("[RFID CAPTURE POLL] HTTP 200 %s\\n", response.c_str());

  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, response) != DeserializationError::Ok) return;
  if (doc["capture_requested"] == true) {
    long receivedRequestId = doc["request_id"] | -1;
    if (receivedRequestId != activeCaptureRequestId) {
      Serial.printf("[RFID CAPTURE] Request acknowledged. ID=%ld\\n", receivedRequestId);
    }
    activeCaptureRequestId = receivedRequestId;
    lcd.clear();
    lcd.setCursor(0, 0); lcd.print("ADMIN TAG CAPTURE");
    lcd.setCursor(0, 1); lcd.print("Present RFID Tag");
  } else {
    if (activeCaptureRequestId != -1) Serial.println("[RFID CAPTURE] Request no longer pending.");
    activeCaptureRequestId = -1;
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
  int code = requestJson("/api/rfid/capture/result", payload, true, response);
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

void handleGateScan(const String& uid) {
  lcd.clear(); lcd.setCursor(0, 0); lcd.print("RFID SCANNED");
  lcd.setCursor(0, 1); lcd.print(uid.substring(0, 16));

  StaticJsonDocument<256> doc;
  doc["device_code"] = DEVICE_CODE;
  doc["rfid_uid"] = uid;
  String payload, response;
  serializeJson(doc, payload);

  // The combined route determines entry vs exit from this card's active session.
  int code = requestJson("/api/parking/gate/scan", payload, true, response);
  String reason, vehicle, slot, action;
  bool authorized = (code == 200) && parseAuthorized(response, reason, vehicle, slot, action);

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
    sendHeartbeat();
  } else {
    Serial.println("\n[WIFI] Connection failed");
    lcd.clear(); lcd.print("WiFi unavailable");
    lcd.setCursor(0, 1); lcd.print("Check settings");
  }
  lastHeartbeatAt = millis();
  lastSensorAt = millis();
  lastCapturePollAt = millis();
  delay(900);
  showReady();
  Serial.println("[SYSTEM] PARK+ IR ready");
}

void loop() {
  unsigned long now = millis();
  maintainBarrier();

  if (now - lastHeartbeatAt >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatAt = now;
    sendHeartbeat();
  }
  if (now - lastSensorAt >= SENSOR_INTERVAL_MS) {
    lastSensorAt = now;
    readAndSendSlots();
  }
  if (now - lastCapturePollAt >= CAPTURE_POLL_INTERVAL_MS) {
    lastCapturePollAt = now;
    pollRfidCapture();
  }

  if (now - lastRfidAt < RFID_COOLDOWN_MS) return;
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;

  String uid = readCardUid();
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  lastRfidAt = millis();
  Serial.printf("[RFID] Card UID: %s\n", uid.c_str());

  if (activeCaptureRequestId > 0) submitRfidCapture(uid);
  else handleGateScan(uid);
}
