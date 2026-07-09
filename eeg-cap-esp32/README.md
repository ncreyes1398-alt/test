# ESP32 EEG Cap

An 8-channel EEG acquisition firmware for ESP32 + ADS1299, streaming live
data over Wi-Fi to a PC for visualization/analysis. This is a starting
point for a research-grade cap (10-20 electrode layout), not a certified
medical device.

## Hardware

| Component | Notes |
|---|---|
| ESP32-WROOM dev board | 3.3V logic, hardware SPI, Wi-Fi |
| ADS1299 breakout board | 24-bit, 8-channel biopotential ADC. Buy a breakout (e.g. Protocentral) rather than hand-soldering the raw 0.4mm-pitch TQFP. |
| 8x EEG electrodes + 2 (reference/bias) | Ag/AgCl wet electrodes for best signal quality, or gold-plated dry comb electrodes for faster setup |
| Elastic 10-20 system EEG cap | Holds electrodes at standard scalp positions |
| 3.7V LiPo battery + 3.3V regulator | **Battery power only while worn — see Safety below** |

### Wiring (ADS1299 <-> ESP32)

| ADS1299 pin | ESP32 pin | Notes |
|---|---|---|
| CS | GPIO5 | |
| DRDY | GPIO4 | data-ready interrupt, active low |
| RESET | GPIO16 | |
| START | GPIO17 | |
| SCLK | GPIO18 | hardware VSPI |
| DIN (MOSI) | GPIO23 | hardware VSPI |
| DOUT (MISO) | GPIO19 | hardware VSPI |
| DVDD/AVDD | 3.3V | |
| DGND/AGND | GND | |

Pins are defined at the top of `firmware/src/main.cpp` if you need to
change them for your board layout.

## Safety

This connects electrodes directly to a person's scalp. Read before building:

- **Battery power only while electrodes are attached to someone.** Never
  have the ESP32 on USB power (connected to a mains-powered, earthed
  computer) while a person is wired to the electrodes — that path can
  carry leakage current from the computer's power supply through the
  person. USB is fine for flashing firmware with no electrodes connected.
- Not a medical device. Do not use on anyone with epilepsy/seizure
  history, a pacemaker/implanted device, or broken scalp skin without
  guidance from a qualified professional.
- Keep to low-voltage, battery-derived power throughout — no direct
  mains connection anywhere in the signal path.

## Firmware

Built with [PlatformIO](https://platformio.org/).

```
firmware/
  platformio.ini
  src/main.cpp          -- Wi-Fi + TCP streaming loop
  lib/ADS1299/           -- ADS1299 SPI driver
  include/secrets.h.example
```

### Setup

1. Install PlatformIO (VS Code extension, or `pip install platformio`).
2. Copy the Wi-Fi credentials template and fill it in:
   ```
   cp firmware/include/secrets.h.example firmware/include/secrets.h
   # edit firmware/include/secrets.h with your WIFI_SSID / WIFI_PASSWORD
   ```
   (`secrets.h` is gitignored so it never gets committed.)
3. Connect the ESP32 over USB and build/upload:
   ```
   cd firmware
   pio run -t upload
   pio device monitor
   ```
4. The serial monitor will print the ESP32's IP address once it's on
   Wi-Fi and the ADS1299 has initialized. If you see "ADS1299 not
   detected", double check the SPI wiring and that the board has power.

### What the firmware does

- Resets and configures the ADS1299 for 8 channels, gain x24, internal
  reference, 250 samples/sec, with the bias-drive signal derived from all
  8 channels for noise rejection (the same pattern OpenBCI's Cyton
  firmware uses).
- On each `DRDY` interrupt-ready sample, reads the 27-byte SPI frame,
  converts each channel to microvolts, and — if a receiver is connected —
  sends it as a 37-byte binary frame over a TCP socket on port 3399.

You can change the sample rate via `ads.setSampleRateCode(...)` in
`main.cpp` (250 SPS is a reasonable default for general EEG; go higher if
you need to study faster phenomena like SSVEP above ~40Hz).

## PC-side receiver

`tools/receiver.py` connects to the ESP32's TCP stream, live-plots all 8
channels (stacked, EEG-style), and can optionally log to CSV.

```
pip install matplotlib
python tools/receiver.py --host <esp32-ip-from-serial-monitor>
python tools/receiver.py --host <esp32-ip> --csv session.csv
```

## Suggested next steps

1. **Bench-test without electrodes first**: short CH1IN to ground via the
   ADS1299's internal test signal (MUX bits) to confirm you're getting
   clean data before ever putting it on a scalp.
2. **Verify per-channel impedance** once electrodes are on — the
   ADS1299 has built-in lead-off detection registers (`LOFF`,
   `LOFF_SENSP/N`) not yet wired up in this driver; worth adding before
   relying on channel quality.
3. **Band-power / feature extraction**: once raw streaming works, add
   FFT-based band power (delta/theta/alpha/beta/gamma) either on the
   ESP32 or in a Python post-processing script — useful for
   attention/relaxation-style feedback.
4. **Consider Lab Streaming Layer (LSL)** if you want to feed this into
   existing EEG analysis tools (OpenViBE, MNE-Python, BCI2000) instead of
   the custom TCP protocol here.
