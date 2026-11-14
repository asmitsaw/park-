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

## 5. Admin-Initiated RFID Tag Capture

The admin console can request a one-time tag read from **Customer Registry → RFID Cards → Register RFID Card → Read tag with RC522**. While the request is pending, the firmware polls the capture endpoint and treats the next card presentation as a registration read. It sends the UID to the backend without authorizing entry or moving the barrier. A request expires after 90 seconds.

Use firmware version `1.1.0` or newer for this feature. Set `DEVICE_SECRET` in the sketch to the same value as `DEVICE_SHARED_SECRET` in `backend\.env`. Keep the ESP32 and host on the same trusted local network.

## 6. IR-Based Slot Assignment

An entry RFID scan authorizes the gate but does not reserve P01 or P02. The backend waits up to five minutes for a healthy IR sensor to change from empty to occupied, then assigns that detected slot and starts the parking session. Only one vehicle per gate device can wait for slot detection at a time; a later entry scan is denied until the pending vehicle is assigned or expires. The LCD shows that the driver should park in an IR-monitored slot.

## 7. Electrical and Pin Notes

- Power the RC522 from **3.3V**, not 5V.
- ESP32 GPIO inputs are not 5V tolerant. Use a level shifter or resistor divider on each HC-SR04 ECHO line.
- RFID reset uses GPIO 26. The I2C LCD SCL uses GPIO 22; these pins must remain separate.
- Power the servo from an appropriate 5V supply and connect the supply ground to ESP32 ground.

For application setup, environment variables, API details, and troubleshooting, see the project [README](../README.md).

