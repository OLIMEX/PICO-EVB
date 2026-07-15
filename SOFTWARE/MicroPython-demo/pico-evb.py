"""
MicroPython firmware for Raspberry Pi Pico
- 4 digital inputs, 4 relay outputs
- UART / I2C / SPI pins reserved (initialized, not otherwise used)
- Relays are forced OFF on boot and on any unhandled error otherwise follow the inputs

Pin map (per request):
  GPIO2  - Input1
  GPIO3  - Input2
  GPIO8  - Input3
  GPIO9  - Input4
  GPIO10 - RELAY1
  GPIO11 - RELAY2
  GPIO12 - RELAY3
  GPIO13 - RELAY4
  GPIO0  - UART0 TX
  GPIO1  - UART0 RX
  GPIO16 - I2C0 SDA
  GPIO17 - I2C0 SCL
  GPIO4  - SPI0 MISO (RX)
  GPIO5  - SPI0 CS
  GPIO6  - SPI0 SCK
  GPIO7  - SPI0 MOSI (TX)
"""
from machine import Pin, UART, I2C, SPI
import utime

# ---------------------------------------------------------------
# Relay outputs (GPIO10-13) - initialize all OFF immediately
# ---------------------------------------------------------------
relay1 = Pin(10, Pin.OUT, value=0)
relay2 = Pin(11, Pin.OUT, value=0)
relay3 = Pin(12, Pin.OUT, value=0)
relay4 = Pin(13, Pin.OUT, value=0)
relays = [relay1, relay2, relay3, relay4]

def relays_off():
    for r in relays:
        r.value(0)

relays_off()  # redundant safety call at boot

# ---------------------------------------------------------------
# Input pins (GPIO2, 3, 8, 9)
# Logic here is active-LOW: input=0 -> turn relay ON
#                            input=1 -> turn relay OFF
# Adjust pull configuration to match your actual input wiring.
# ---------------------------------------------------------------
input1 = Pin(2, Pin.IN, Pin.PULL_UP)
input2 = Pin(3, Pin.IN, Pin.PULL_UP)
input3 = Pin(8, Pin.IN, Pin.PULL_UP)
input4 = Pin(9, Pin.IN, Pin.PULL_UP)
inputs = [input1, input2, input3, input4]

# ---------------------------------------------------------------
# Reserved peripheral pins (declared per your wiring, not actively
# used in this logic loop). Uncomment / configure as needed.
# ---------------------------------------------------------------
# uart = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1))
# i2c  = I2C(0, scl=Pin(17), sda=Pin(16))
# spi  = SPI(0, sck=Pin(6), mosi=Pin(7), miso=Pin(4))
# spi_cs = Pin(5, Pin.OUT, value=1)  # CS idle HIGH

# ---------------------------------------------------------------
# Asymmetric debounce logic:
#   input = 0 held continuously >= ON_DEBOUNCE_MS  -> relay ON
#   input = 1 held continuously >= OFF_DEBOUNCE_MS -> relay OFF
# Each input tracks its own raw-value change timer independently
# of the relay's current state.
# ---------------------------------------------------------------
ON_DEBOUNCE_MS = 5
OFF_DEBOUNCE_MS = 60

class DebouncedInput:
    def __init__(self, pin, relay):
        self.pin = pin
        self.relay = relay
        self.last_reading = pin.value()
        self.change_time = utime.ticks_ms()

    def update(self):
        reading = self.pin.value()
        now = utime.ticks_ms()

        if reading != self.last_reading:
            # Raw signal changed - restart the timer for this new level
            self.last_reading = reading
            self.change_time = now
            return

        elapsed = utime.ticks_diff(now, self.change_time)

        if reading == 0 and elapsed >= ON_DEBOUNCE_MS:
            self.relay.value(1)
        elif reading == 1 and elapsed >= OFF_DEBOUNCE_MS:
            self.relay.value(0)

debounced_inputs = [
    DebouncedInput(input1, relay1),
    DebouncedInput(input2, relay2),
    DebouncedInput(input3, relay3),
    DebouncedInput(input4, relay4),
]

# ---------------------------------------------------------------
# Main loop with fail-safe relay shutoff on any error.
# ---------------------------------------------------------------
def main():
    while True:
        try:
            while True:
                for di in debounced_inputs:
                    di.update()
                utime.sleep_ms(2)

        except KeyboardInterrupt:
            relays_off()
            raise

        except Exception as e:
            relays_off()
            print("Error occurred, relays forced OFF:", e)
            utime.sleep_ms(200)
            # loop continues and retries automatically

main()
