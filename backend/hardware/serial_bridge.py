"""
AgriSetu — ESP32 Serial Bridge
===============================
Reads newline-delimited JSON frames from ESP32 nodes over UART (USB-Serial).
Decodes them and pushes parsed frames into a thread-safe queue so the main
FastAPI/asyncio loop can drain and inject them into the Q-Learning environment.

──────────────────────────────────────────────────────────────────
WIRE PROTOCOL (ESP32 → Python, 115200 baud, newline-terminated JSON)
──────────────────────────────────────────────────────────────────

Frame 1 — Node telemetry   (send every ~500 ms)
  {"t":"nd","id":<int>,"rssi":<float>,"sf":<int>,"cr":<float>,"bat":<float>}

  Example:
  {"t":"nd","id":1,"rssi":-74.2,"sf":9,"cr":0.5,"bat":87.3}

Frame 2 — Transmission result   (send after every TX attempt)
  {"t":"tx","id":<int>,"ok":<0|1>,"pri":<"normal"|"warning"|"critical">,
   "e":<float_mWh>,"lat":<float_ms>,"act":<0-4>}

  ok  : 1 = ACK received (success), 0 = collision/timeout
  pri : packet priority
  e   : energy used in mWh
  lat : round-trip latency in ms
  act : action chosen by on-device Q-table (0=TX now, 1=wait1, …)

  Example:
  {"t":"tx","id":1,"ok":1,"pri":"normal","e":0.082,"lat":245.0,"act":2}

Frame 3 — Heartbeat / ping  (send every 2 s)
  {"t":"ping","id":<int>}

──────────────────────────────────────────────────────────────────
MINIMAL ARDUINO / ESP32 SKETCH (paste into your firmware)
──────────────────────────────────────────────────────────────────

  // In loop() — send node telemetry
  void sendTelemetry(int nodeId, float rssi, int sf, float cr, float battery) {
    Serial.print("{\"t\":\"nd\",\"id\":");
    Serial.print(nodeId);
    Serial.print(",\"rssi\":"); Serial.print(rssi, 1);
    Serial.print(",\"sf\":");   Serial.print(sf);
    Serial.print(",\"cr\":");   Serial.print(cr, 2);
    Serial.print(",\"bat\":");  Serial.print(battery, 1);
    Serial.println("}");
  }

  // After a TX attempt
  void sendTxResult(int nodeId, bool ok, const char* pri,
                    float energy, float latency, int action) {
    Serial.print("{\"t\":\"tx\",\"id\":");
    Serial.print(nodeId);
    Serial.print(",\"ok\":");   Serial.print(ok ? 1 : 0);
    Serial.print(",\"pri\":\""); Serial.print(pri); Serial.print("\"");
    Serial.print(",\"e\":");    Serial.print(energy, 4);
    Serial.print(",\"lat\":");  Serial.print(latency, 1);
    Serial.print(",\"act\":");  Serial.print(action);
    Serial.println("}");
  }

──────────────────────────────────────────────────────────────────
"""

import json
import queue
import threading
import time
from typing import Optional

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


class SerialBridge:
    """
    Thread-based serial reader.
    Call connect() to open the port; the reader thread pushes parsed
    JSON frames into self.queue for the async environment loop to drain.
    """

    def __init__(self):
        self._ser:    Optional["serial.Serial"] = None
        self._thread: Optional[threading.Thread] = None
        self._stop    = threading.Event()
        self.queue:   queue.Queue = queue.Queue(maxsize=500)

        # Status
        self.connected:   bool  = False
        self.port:        str   = ""
        self.baud:        int   = 115200
        self.rx_count:    int   = 0
        self.err_count:   int   = 0
        self.last_rx_ts:  float = 0.0
        self.error_msg:   str   = ""

    # ── Connection management ─────────────────────────────────────
    def connect(self, port: str, baud: int = 115200) -> bool:
        """Open the serial port and start the reader thread."""
        if not SERIAL_AVAILABLE:
            self.error_msg = "pyserial not installed — run: pip install pyserial"
            return False
        if self.connected:
            self.disconnect()

        self.port = port
        self.baud = baud
        self._stop.clear()

        try:
            self._ser = serial.Serial(
                port=port,
                baudrate=baud,
                timeout=1.0,
                write_timeout=1.0,
            )
            self.connected = True
            self.error_msg = ""
            self._thread = threading.Thread(
                target=self._read_loop, daemon=True, name="AgriSetu-SerialBridge"
            )
            self._thread.start()
            return True
        except Exception as e:
            self.error_msg = str(e)
            self.connected = False
            return False

    def disconnect(self):
        """Stop the reader thread and close the port."""
        self._stop.set()
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        self.connected = False

    # ── Reader thread ─────────────────────────────────────────────
    def _read_loop(self):
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = self._ser.read(512)
                if chunk:
                    buf += chunk
                    # Process all complete newline-delimited frames
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        self._parse_frame(line.strip())
            except serial.SerialException as e:
                self.error_msg  = f"Serial error: {e}"
                self.connected  = False
                break
            except Exception as e:
                self.err_count += 1
                self.error_msg  = str(e)

    def _parse_frame(self, raw: bytes):
        if not raw:
            return
        try:
            frame = json.loads(raw.decode("utf-8", errors="replace"))
            self.rx_count  += 1
            self.last_rx_ts = time.time()
            # Drop oldest if queue full (never block the reader thread)
            if self.queue.full():
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    pass
            self.queue.put_nowait(frame)
        except json.JSONDecodeError:
            self.err_count += 1

    # ── Queue drain (called by async sim loop) ────────────────────
    def drain(self) -> list:
        """Return all pending frames without blocking."""
        frames = []
        while True:
            try:
                frames.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return frames

    # ── Helpers ───────────────────────────────────────────────────
    @staticmethod
    def list_ports() -> list:
        """List available serial ports on this machine."""
        if not SERIAL_AVAILABLE:
            return []
        return [
            {"port": p.device, "description": p.description}
            for p in serial.tools.list_ports.comports()
        ]

    def status(self) -> dict:
        since_rx = round(time.time() - self.last_rx_ts, 1) if self.last_rx_ts else None
        return {
            "connected":   self.connected,
            "port":        self.port,
            "baud":        self.baud,
            "rx_count":    self.rx_count,
            "err_count":   self.err_count,
            "last_rx_sec": since_rx,
            "error":       self.error_msg,
            "pyserial":    SERIAL_AVAILABLE,
            "queue_depth": self.queue.qsize(),
        }

    def send(self, data: dict):
        """Send a JSON command back to the ESP32 (e.g. Q-table export)."""
        if self._ser and self.connected:
            try:
                self._ser.write((json.dumps(data) + "\n").encode())
            except Exception as e:
                self.error_msg = str(e)
