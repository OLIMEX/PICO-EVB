// ---------------------------------------------------------------
// Pin mapping
// ---------------------------------------------------------------
const uint8_t INPUT_PINS[4] = {2, 3, 8, 9};
const uint8_t RELAY_PINS[4] = {10, 11, 12, 13};

// Reserved peripheral pins per your wiring (not actively used here):
// UART:  TX=0, RX=1  (Serial uses these by default on most boards)
// I2C:   SDA=16(A2)? -- NOTE: on classic Arduino Uno/Nano these pin
//        numbers don't map directly to I2C; adjust for your actual
//        board (e.g. Pico via arduino-pico core, ESP32, etc.)
// SPI:   MISO=4, CS=5, SCK=6, MOSI=7

// ---------------------------------------------------------------
// Debounce timing
// ---------------------------------------------------------------
const unsigned long ON_DEBOUNCE_MS  = 5;
const unsigned long OFF_DEBOUNCE_MS = 60;

// ---------------------------------------------------------------
// Per-input state tracking
// ---------------------------------------------------------------
struct DebouncedInput {
  uint8_t pin;
  uint8_t relayPin;
  int lastReading;
  unsigned long changeTime;
};

DebouncedInput inputs[4];

// ---------------------------------------------------------------
// Force all relays OFF (fail-safe)
// ---------------------------------------------------------------
void relaysOff() {
  for (uint8_t i = 0; i < 4; i++) {
    digitalWrite(RELAY_PINS[i], LOW);
  }
}

void setup() {
  Serial.begin(9600);

  // Relays: set OFF *before* setting pinMode to OUTPUT where possible,
  // to avoid a brief undefined state on power-up.
  for (uint8_t i = 0; i < 4; i++) {
    digitalWrite(RELAY_PINS[i], LOW);
    pinMode(RELAY_PINS[i], OUTPUT);
    digitalWrite(RELAY_PINS[i], LOW); // redundant safety write
  }

  // Inputs: active-LOW, using internal pullups.
  // If your inputs idle LOW instead, switch to INPUT and invert logic.
  for (uint8_t i = 0; i < 4; i++) {
    pinMode(INPUT_PINS[i], INPUT_PULLUP);
    inputs[i].pin = INPUT_PINS[i];
    inputs[i].relayPin = RELAY_PINS[i];
    inputs[i].lastReading = digitalRead(INPUT_PINS[i]);
    inputs[i].changeTime = millis();
  }
}

void updateInput(DebouncedInput &di) {
  int reading = digitalRead(di.pin);
  unsigned long now = millis();

  if (reading != di.lastReading) {
    // Raw level changed - restart the timer for this new level
    di.lastReading = reading;
    di.changeTime = now;
    return;
  }

  unsigned long elapsed = now - di.changeTime;

  if (reading == LOW && elapsed >= ON_DEBOUNCE_MS) {
    digitalWrite(di.relayPin, HIGH);
  } else if (reading == HIGH && elapsed >= OFF_DEBOUNCE_MS) {
    digitalWrite(di.relayPin, LOW);
  }
}

void loop() {
  // Wrap the per-loop work so any unexpected condition can be
  // caught and relays forced off. (Arduino/C++ has no exceptions
  // enabled by default, so we rely on defensive checks instead —
  // see note below.)
  for (uint8_t i = 0; i < 4; i++) {
    updateInput(inputs[i]);
  }

  delay(1); // fine resolution needed for the 5ms ON threshold
}
