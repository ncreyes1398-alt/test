// ESP32 EEG cap firmware
// Reads 8 channels from an ADS1299 biopotential ADC over SPI and streams
// them as binary frames over a TCP socket for a PC-side receiver
// (see tools/receiver.py) to plot/log/process.

#include <Arduino.h>
#include <SPI.h>
#include <WiFi.h>
#include "ADS1299.h"
#include "secrets.h" // defines WIFI_SSID / WIFI_PASSWORD, gitignored

// ---- Pin assignments (adjust to match your wiring) ----
static constexpr int8_t PIN_CS = 5;
static constexpr int8_t PIN_DRDY = 4;
static constexpr int8_t PIN_RESET = 16;
static constexpr int8_t PIN_START = 17;
// Hardware SPI (VSPI) default pins: SCK=18, MISO=19, MOSI=23

static constexpr uint16_t TCP_PORT = 3399;

// Frame format sent to the receiver, one per sample:
//   [0]      0xA0 marker
//   [1..4]   uint32 LE sample counter
//   [5..36]  8 x float32 LE, microvolts
static constexpr uint8_t FRAME_MARKER = 0xA0;
static constexpr size_t FRAME_SIZE = 1 + 4 + ADS1299::NUM_CHANNELS * sizeof(float);

ADS1299 ads(PIN_CS, PIN_DRDY, PIN_RESET, PIN_START);
WiFiServer tcpServer(TCP_PORT);
WiFiClient client;
uint32_t sampleCounter = 0;

void connectWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.printf("Connecting to WiFi '%s'", WIFI_SSID);
    while (WiFi.status() != WL_CONNECTED) {
        delay(300);
        Serial.print('.');
    }
    Serial.printf("\nConnected. IP address: %s\n", WiFi.localIP().toString().c_str());
}

void setup() {
    Serial.begin(115200);
    delay(200);

    SPI.begin(); // uses default VSPI pins (SCK18/MISO19/MOSI23)

    if (!ads.begin()) {
        Serial.println("ADS1299 not detected - check wiring/power. Halting.");
        while (true) delay(1000);
    }
    Serial.println("ADS1299 initialized (8ch, gain x24, 250 SPS).");

    connectWiFi();
    tcpServer.begin();
    Serial.printf("TCP server listening on port %u\n", TCP_PORT);

    ads.startConversion();
}

void sendFrame(const float microvolts[ADS1299::NUM_CHANNELS]) {
    uint8_t buf[FRAME_SIZE];
    buf[0] = FRAME_MARKER;
    memcpy(&buf[1], &sampleCounter, sizeof(sampleCounter));
    memcpy(&buf[5], microvolts, ADS1299::NUM_CHANNELS * sizeof(float));
    client.write(buf, FRAME_SIZE);
    sampleCounter++;
}

void loop() {
    if (!client || !client.connected()) {
        WiFiClient newClient = tcpServer.available();
        if (newClient) {
            client = newClient;
            Serial.println("Receiver connected.");
        }
    }

    float microvolts[ADS1299::NUM_CHANNELS];
    if (ads.readSampleIfReady(microvolts)) {
        if (client && client.connected()) {
            sendFrame(microvolts);
        }
    }
}
