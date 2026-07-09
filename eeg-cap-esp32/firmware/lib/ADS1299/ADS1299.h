#pragma once
#include <Arduino.h>
#include <SPI.h>

// Driver for the TI ADS1299 8-channel, 24-bit biopotential ADC.
// Register map / commands per the ADS1299 datasheet (SBAS499).

class ADS1299 {
public:
    static constexpr uint8_t NUM_CHANNELS = 8;

    ADS1299(int8_t csPin, int8_t drdyPin, int8_t resetPin, int8_t startPin,
            SPIClass &spi = SPI);

    // Resets and configures the chip with a sane default EEG setup:
    // all 8 channels enabled, gain x24, internal reference, bias drive
    // derived from all channels (same pattern used by OpenBCI's Cyton
    // firmware). Call once in setup(). Returns false if the chip ID
    // register doesn't come back as expected (wiring problem).
    bool begin(uint32_t sclkHz = 4000000);

    void startConversion();
    void stopConversion();

    // 000=16kSPS 001=8k 010=4k 011=2k 100=1k 101=500 110=250(default)
    void setSampleRateCode(uint8_t drBits);

    // gainCode: 0=1x 1=2x 2=4x 3=6x 4=8x 5=12x 6=24x(default)
    void setChannelGain(uint8_t channel, uint8_t gainCode);
    void enableChannel(uint8_t channel, bool enabled);

    // Call from loop(); non-blocking. Returns true and fills
    // outMicrovolts[8] when a full sample frame was available.
    bool readSampleIfReady(float outMicrovolts[NUM_CHANNELS]);

    // ISR-safe: attach to DRDY falling edge.
    volatile bool dataReady = false;

private:
    int8_t _cs, _drdy, _reset, _start;
    SPIClass *_spi;
    SPISettings _spiSettings;
    static constexpr float VREF = 4.5f; // internal reference volts
    uint8_t _gainCode[NUM_CHANNELS];

    void sendCommand(uint8_t cmd);
    void writeRegister(uint8_t reg, uint8_t value);
    uint8_t readRegister(uint8_t reg);
    void csLow();
    void csHigh();
    float lsbVolts(uint8_t channel) const;
};
