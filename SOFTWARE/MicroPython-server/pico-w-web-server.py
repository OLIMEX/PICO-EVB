"""
MicroPython firmware for Raspberry Pi Pico W
- 4 digital inputs (debounced: 0 for >=5ms => ON, 1 for >=60ms => OFF), 4 relay outputs
- UART / I2C / SPI pins reserved (initialized, not otherwise used)
- Simple web server: shows input state as ON/OFF icons, buttons toggle relays
- Relays are forced OFF on boot and on any unhandled error

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

import network
import socket
import time
import machine
from machine import Pin, UART, I2C, SPI

# ---------------------------------------------------------------------------
# Wi-Fi credentials - EDIT THESE
# ---------------------------------------------------------------------------
WIFI_SSID = "yourSSID"
WIFI_PASSWORD = "yourPASSWORD"

# ---------------------------------------------------------------------------
# I/O setup
# ---------------------------------------------------------------------------

# Inputs. Change PULL_UP/PULL_DOWN to match your wiring (e.g. switch to GND
# needs PULL_UP, switch to 3V3 needs PULL_DOWN).
inputs = [
    Pin(2, Pin.IN, Pin.PULL_UP),
    Pin(3, Pin.IN, Pin.PULL_UP),
    Pin(8, Pin.IN, Pin.PULL_UP),
    Pin(9, Pin.IN, Pin.PULL_UP),
]

# ---------------------------------------------------------------------------
# Input debounce
#   raw = 0 held for >= DEBOUNCE_ON_MS  -> considered ON
#   raw = 1 held for >= DEBOUNCE_OFF_MS -> considered OFF
# Sampled from a periodic timer so it works independently of HTTP requests.
# ---------------------------------------------------------------------------
DEBOUNCE_ON_MS = 5
DEBOUNCE_OFF_MS = 60

_num_inputs = len(inputs)
_last_raw = [p.value() for p in inputs]
_last_change_ms = [time.ticks_ms()] * _num_inputs
debounced_state = [0 if v else 1 for v in _last_raw]  # raw 1 (idle) -> OFF(0)


def _debounce_tick(timer):
    now = time.ticks_ms()
    for i in range(_num_inputs):
        raw = inputs[i].value()
        if raw != _last_raw[i]:
            _last_raw[i] = raw
            _last_change_ms[i] = now
        else:
            elapsed = time.ticks_diff(now, _last_change_ms[i])
            if raw == 0 and elapsed >= DEBOUNCE_ON_MS:
                debounced_state[i] = 1
            elif raw == 1 and elapsed >= DEBOUNCE_OFF_MS:
                debounced_state[i] = 0


debounce_timer = machine.Timer(-1)
debounce_timer.init(period=1, mode=machine.Timer.PERIODIC, callback=_debounce_tick)

# Relays - active HIGH (change if your relay board is active LOW)
relays = [
    Pin(10, Pin.OUT),
    Pin(11, Pin.OUT),
    Pin(12, Pin.OUT),
    Pin(13, Pin.OUT),
]


def relays_off():
    """Force all relays to the OFF state."""
    for r in relays:
        r.value(0)


# Make sure relays start OFF
relays_off()

# Reserved peripherals (initialized so pins are claimed / configured, not
# otherwise used by the web server logic below)
uart = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1))
i2c = I2C(0, sda=Pin(16), scl=Pin(17), freq=400000)
spi = SPI(0, baudrate=1_000_000, sck=Pin(6), mosi=Pin(7), miso=Pin(4))
spi_cs = Pin(5, Pin.OUT, value=1)  # CS idle HIGH


# ---------------------------------------------------------------------------
# Wi-Fi connect
# ---------------------------------------------------------------------------
def wifi_connect(timeout_s=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    t0 = time.time()
    while not wlan.isconnected():
        if time.time() - t0 > timeout_s:
            raise RuntimeError("Wi-Fi connection timed out")
        time.sleep(0.5)

    print("Connected, IP:", wlan.ifconfig()[0])
    return wlan


# ---------------------------------------------------------------------------
# Web page
# ---------------------------------------------------------------------------
PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pico W I/O Panel</title>
<style>
  body { font-family: Arial, sans-serif; background:#1e1e1e; color:#eee;
         text-align:center; margin:0; padding:20px; }
  h1 { font-size:1.4em; }
  .grid { display:flex; justify-content:center; gap:24px; flex-wrap:wrap; margin:20px 0; }
  .card { background:#2b2b2b; border-radius:12px; padding:16px; width:140px; }
  .label { font-size:0.9em; color:#bbb; margin-top:10px; }

  /* Toggle switch, styled after the red/OFF - green/ON pill icon */
  .toggle {
    display:inline-flex;
    align-items:center;
    justify-content:space-between;
    width:110px;
    height:44px;
    border-radius:22px;
    background:#292c33;
    padding:0 10px;
    box-sizing:border-box;
    border:none;
    font-family:inherit;
  }
  .toggle.clickable { cursor:pointer; }
  .toggle .txt {
    color:#fff;
    font-weight:bold;
    font-size:0.85em;
    letter-spacing:0.5px;
  }
  .toggle .knob {
    width:28px;
    height:28px;
    border-radius:50%;
    flex-shrink:0;
  }
  .toggle .knob.red   { background:#e8483a; }
  .toggle .knob.green { background:#22a75d; }
</style>
</head>
<body>
<h1>Pico W Input / Relay Panel</h1>

<h2>Inputs</h2>
<div class="grid" id="inputs"></div>

<h2>Relays</h2>
<div class="grid" id="relays"></div>

<script>
async function refresh() {
  try {
    const r = await fetch('/status.json');
    const data = await r.json();

    const inDiv = document.getElementById('inputs');
    inDiv.innerHTML = '';
    data.inputs.forEach((v, i) => {
      const active = v === 1;   // debounced_state: 1 = ON, 0 = OFF
      const switchHtml = active
        ? `<div class="toggle"><span class="txt">ON</span><span class="knob green"></span></div>`
        : `<div class="toggle"><span class="knob red"></span><span class="txt">OFF</span></div>`;
      inDiv.innerHTML += `
        <div class="card">
          ${switchHtml}
          <div class="label">Input ${i+1}</div>
        </div>`;
    });

    const relDiv = document.getElementById('relays');
    relDiv.innerHTML = '';
    data.relays.forEach((v, i) => {
      const switchHtml = v
        ? `<div class="toggle clickable" onclick="toggle(${i})"><span class="txt">ON</span><span class="knob green"></span></div>`
        : `<div class="toggle clickable" onclick="toggle(${i})"><span class="knob red"></span><span class="txt">OFF</span></div>`;
      relDiv.innerHTML += `
        <div class="card">
          ${switchHtml}
          <div class="label">Relay ${i+1}</div>
        </div>`;
    });
  } catch (e) {
    console.log('status refresh failed', e);
  }
}

async function toggle(i) {
  await fetch('/relay/' + i + '/toggle');
  refresh();
}

refresh();
setInterval(refresh, 1500);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def read_inputs():
    return list(debounced_state)


def read_relays():
    return [r.value() for r in relays]


def json_status():
    ins = read_inputs()
    rel = read_relays()
    body = '{"inputs":[%d,%d,%d,%d],"relays":[%d,%d,%d,%d]}' % (
        ins[0], ins[1], ins[2], ins[3],
        rel[0], rel[1], rel[2], rel[3],
    )
    return body


def send_response(conn, body, content_type="text/html"):
    header = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: {}\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n\r\n"
    ).format(content_type, len(body))
    conn.send(header.encode())
    conn.send(body.encode() if isinstance(body, str) else body)


def send_404(conn):
    body = "Not found"
    header = (
        "HTTP/1.1 404 Not Found\r\n"
        "Content-Type: text/plain\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n\r\n"
    ).format(len(body))
    conn.send(header.encode())
    conn.send(body.encode())


def handle_request(conn, request):
    # First line looks like: GET /path HTTP/1.1
    try:
        first_line = request.split("\r\n", 1)[0]
        method, path, _ = first_line.split(" ")
    except Exception:
        send_404(conn)
        return

    if path == "/" or path == "/index.html":
        send_response(conn, PAGE)
        return

    if path == "/status.json":
        send_response(conn, json_status(), "application/json")
        return

    if path.startswith("/relay/") and path.endswith("/toggle"):
        try:
            idx = int(path.split("/")[2])
            if 0 <= idx < len(relays):
                relays[idx].value(0 if relays[idx].value() else 1)
                send_response(conn, json_status(), "application/json")
                return
        except Exception:
            pass
        send_404(conn)
        return

    send_404(conn)


# ---------------------------------------------------------------------------
# Server loop
# ---------------------------------------------------------------------------
def run_server():
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(4)
    print("Web server listening on", addr)

    while True:
        conn, client_addr = s.accept()
        try:
            conn.settimeout(3.0)
            request = conn.recv(1024).decode("utf-8", "ignore")
            if request:
                handle_request(conn, request)
        except Exception as e:
            print("Request error:", e)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    try:
        wifi_connect()
        run_server()
    except Exception as e:
        # Any unhandled error -> make sure relays are safely OFF
        print("Fatal error, forcing relays OFF:", e)
        relays_off()
        # Optional: brief pause then reset so the device can retry
        time.sleep(5)
        machine.reset()


if __name__ == "__main__":
    main()
