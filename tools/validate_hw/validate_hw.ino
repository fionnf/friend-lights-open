// ============================================================
//  validate_hw.ino — a second opinion on the radio, in C++
// ============================================================
// This is NOT the firmware. The lamp runs MicroPython; this sketch
// exists for exactly one situation: the lamp's own radio_check.py says
// something is wrong, and you want to know whether it is the hardware
// or the driver. It uses RadioLib — the same library as Seeed's own
// examples for this kit — so if THIS transmits and the firmware does
// not, the fault is in the Python driver and worth reporting; if
// neither transmits, it is the module, the seating, or the antenna.
//
// Arduino IDE setup (once):
//   * Boards manager  ->  esp32 by Espressif  ->  XIAO_ESP32S3
//   * Library manager ->  RadioLib 6.6.0  (the version Seeed pins;
//                         their wiki warns other versions may not build)
//
// Flashing this ERASES MicroPython. Going back is one command:
//   python3 tools/install.py     (reflashes MicroPython + the firmware)
//
// ⚠ Attach the antenna before powering the board. Transmitting into an
//   open connector can damage the radio's power amplifier.

#include <RadioLib.h>

// Module(cs, irq, rst, gpio) — Seeed's pin map for the board-to-board
// kit: NSS 41, DIO1 39, RST 42, BUSY 40. The same pins the MicroPython
// driver probes first.
SX1262 radio = new Module(41, 39, 42, 40);

int counter = 0;

void halt(const char *what, int code) {
  for (;;) {
    Serial.print(what);
    Serial.print(" failed, RadioLib code ");
    Serial.println(code);
    Serial.println("  (codes: RadioLib TypeDef.h — -2 is CHIP_NOT_FOUND,");
    Serial.println("   which means SPI/seating, same as the firmware's");
    Serial.println("   'no SX1262 answered')");
    delay(3000);
  }
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n=== Wio-SX1262 hardware validation (RadioLib) ===");

  // 868.1 MHz, 125 kHz, SF9, CR 4/7, public sync word, 14 dBm,
  // 8-symbol preamble — and the TCXO on DIO3 at 1.8 V, because this
  // module has no crystal. The same bring-up the firmware does.
  int state = radio.begin(868.1, 125.0, 9, 7, 0x34, 14, 8, 1.8);
  if (state != RADIOLIB_ERR_NONE) halt("begin()", state);

  // The antenna switch hangs off DIO2 on this module.
  state = radio.setDio2AsRfSwitch(true);
  if (state != RADIOLIB_ERR_NONE) halt("setDio2AsRfSwitch()", state);

  Serial.println("radio up — transmitting a beacon every 10 s");
  Serial.println("(bare LoRa, not LoRaWAN: gateways hear it but TTN");
  Serial.println(" will not show it. For an end-to-end TTN join test,");
  Serial.println(" use Seeed's LNS example from their wiki — or just");
  Serial.println(" the lamp firmware, which radio_check.py exercises.)");
}

void loop() {
  String msg = "friend-lights hw check #" + String(counter++);
  int state = radio.transmit(msg);
  if (state == RADIOLIB_ERR_NONE) {
    Serial.print("TX ok: ");
    Serial.println(msg);
  } else {
    Serial.print("TX failed, code ");
    Serial.println(state);
  }

  // Listen between beacons; another lamp's check (or any 868.1/SF9
  // traffic) proves receive too.
  String rx;
  state = radio.receive(rx, 10000000);   // 10 s, microseconds
  if (state == RADIOLIB_ERR_NONE) {
    Serial.print("RX: '");
    Serial.print(rx);
    Serial.print("'  RSSI ");
    Serial.print(radio.getRSSI());
    Serial.print(" dBm, SNR ");
    Serial.print(radio.getSNR());
    Serial.println(" dB");
  }
}
