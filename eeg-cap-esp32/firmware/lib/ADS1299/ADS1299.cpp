#include "ADS1299.h"

// ---- Commands (ADS1299 datasheet Table 12) ----
static constexpr uint8_t CMD_WAKEUP = 0x02;
static constexpr uint8_t CMD_STANDBY = 0x04;
static constexpr uint8_t CMD_RESET = 0x06;
static constexpr uint8_t CMD_START = 0x08;
static constexpr uint8_t CMD_STOP = 0x0A;
static constexpr uint8_t CMD_RDATAC = 0x10;
static constexpr uint8_t CMD_SDATAC = 0x11;
static constexpr uint8_t CMD_RREG = 0x20;
static constexpr uint8_t CMD_WREG = 0x40;

// ---- Registers (ADS1299 datasheet Table 13) ----
static constexpr uint8_t REG_ID = 0x00;
static constexpr uint8_t REG_CONFIG1 = 0x01;
static constexpr uint8_t REG_CONFIG2 = 0x02;
static constexpr uint8_t REG_CONFIG3 = 0x03;
static constexpr uint8_t REG_CH1SET = 0x05; // CH2SET..CH8SET follow sequentially
static constexpr uint8_t REG_BIAS_SENSP = 0x0D;
static constexpr uint8_t REG_BIAS_SENSN = 0x0E;

ADS1299::ADS1299(int8_t csPin, int8_t drdyPin, int8_t resetPin, int8_t startPin,
                  SPIClass &spi)
    : _cs(csPin), _drdy(drdyPin), _reset(resetPin), _start(startPin), _spi(&spi) {
    for (uint8_t i = 0; i < NUM_CHANNELS; i++) _gainCode[i] = 6; // 24x default
}

void ADS1299::csLow() { digitalWrite(_cs, LOW); }
void ADS1299::csHigh() { digitalWrite(_cs, HIGH); }

void ADS1299::sendCommand(uint8_t cmd) {
    csLow();
    _spi->beginTransaction(_spiSettings);
    _spi->transfer(cmd);
    _spi->endTransaction();
    csHigh();
}

void ADS1299::writeRegister(uint8_t reg, uint8_t value) {
    csLow();
    _spi->beginTransaction(_spiSettings);
    _spi->transfer(CMD_WREG | reg);
    _spi->transfer(0x00); // number of registers to write minus 1
    _spi->transfer(value);
    _spi->endTransaction();
    csHigh();
}

uint8_t ADS1299::readRegister(uint8_t reg) {
    csLow();
    _spi->beginTransaction(_spiSettings);
    _spi->transfer(CMD_RREG | reg);
    _spi->transfer(0x00);
    uint8_t value = _spi->transfer(0x00);
    _spi->endTransaction();
    csHigh();
    return value;
}

bool ADS1299::begin(uint32_t sclkHz) {
    pinMode(_cs, OUTPUT);
    pinMode(_reset, OUTPUT);
    pinMode(_start, OUTPUT);
    pinMode(_drdy, INPUT);
    csHigh();
    digitalWrite(_start, LOW);

    // ADS1299 max SPI clock is ~20MHz; keep it conservative for
    // breadboard wiring / long ribbon cables to the cap.
    _spiSettings = SPISettings(sclkHz, MSBFIRST, SPI_MODE1);

    // Hardware reset pulse (datasheet: hold low >= 2 tCLK, here we
    // hold well beyond that since tCLK is on the order of nanoseconds).
    digitalWrite(_reset, HIGH);
    delay(10);
    digitalWrite(_reset, LOW);
    delayMicroseconds(10);
    digitalWrite(_reset, HIGH);
    delay(10);

    sendCommand(CMD_SDATAC); // stop continuous read mode so we can access registers

    uint8_t id = readRegister(REG_ID);
    if ((id & 0x1F) != 0x1E) { // upper bits vary by revision; lower 5 bits are the family ID
        return false;
    }

    // CONFIG3: enable internal reference buffer + internally-generated
    // bias reference + bias amplifier. 0xEC is the commonly used value
    // for boards driving BIAS from the electrodes (matches OpenBCI Cyton).
    writeRegister(REG_CONFIG3, 0xEC);
    delay(1);

    // All channels: gain 24x, normal electrode input, routed through
    // SRB2 so they contribute to the bias-drive reference.
    for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
        enableChannel(ch, true);
        setChannelGain(ch, 6); // 24x
    }

    // Derive BIAS drive signal from all 8 channels.
    writeRegister(REG_BIAS_SENSP, 0xFF);
    writeRegister(REG_BIAS_SENSN, 0xFF);

    setSampleRateCode(0b110); // 250 SPS default; call again after begin() to change

    return true;
}

void ADS1299::setSampleRateCode(uint8_t drBits) {
    // CONFIG1: bit7 must be 1, bit4 must be 1 (single-device, non-daisy),
    // bits[2:0] select data rate.
    writeRegister(REG_CONFIG1, 0x90 | (drBits & 0x07));
}

void ADS1299::setChannelGain(uint8_t channel, uint8_t gainCode) {
    if (channel >= NUM_CHANNELS) return;
    _gainCode[channel] = gainCode & 0x07;
    // CHnSET: bit7 PD (0=on), bits[6:4] GAIN, bit3 SRB2 (1=connected),
    // bits[2:0] MUX (000 = normal electrode input).
    uint8_t value = ((_gainCode[channel] & 0x07) << 4) | (1 << 3);
    writeRegister(REG_CH1SET + channel, value);
}

void ADS1299::enableChannel(uint8_t channel, bool enabled) {
    if (channel >= NUM_CHANNELS) return;
    uint8_t value = ((_gainCode[channel] & 0x07) << 4) | (1 << 3);
    if (!enabled) value |= (1 << 7); // PD bit powers the channel down
    writeRegister(REG_CH1SET + channel, value);
}

void ADS1299::startConversion() {
    sendCommand(CMD_RDATAC);
    digitalWrite(_start, HIGH);
}

void ADS1299::stopConversion() {
    digitalWrite(_start, LOW);
    sendCommand(CMD_SDATAC);
}

float ADS1299::lsbVolts(uint8_t channel) const {
    static const float gainLUT[8] = {1, 2, 4, 6, 8, 12, 24, 24};
    float gain = gainLUT[_gainCode[channel] & 0x07];
    // Full-scale range is +-VREF/gain; 24-bit two's complement code.
    return (2.0f * VREF / gain) / 16777215.0f; // 2^24 - 1
}

bool ADS1299::readSampleIfReady(float outMicrovolts[NUM_CHANNELS]) {
    if (digitalRead(_drdy) != LOW) return false;

    // Frame = 3 status bytes + 3 bytes/channel * 8 channels = 27 bytes.
    uint8_t raw[27];
    csLow();
    _spi->beginTransaction(_spiSettings);
    for (uint8_t i = 0; i < 27; i++) raw[i] = _spi->transfer(0x00);
    _spi->endTransaction();
    csHigh();

    for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
        uint8_t *b = &raw[3 + ch * 3];
        int32_t code = (int32_t)((uint32_t)b[0] << 16 | (uint32_t)b[1] << 8 | b[2]);
        if (code & 0x00800000) code |= 0xFF000000; // sign-extend 24-bit -> 32-bit
        outMicrovolts[ch] = code * lsbVolts(ch) * 1e6f;
    }
    return true;
}
