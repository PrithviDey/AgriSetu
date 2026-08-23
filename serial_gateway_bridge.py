#!/usr/bin/env python3
"""
AgriSetu Serial Gateway Bridge
Reads JSON telemetry from the ESP32 Gateway via USB serial,
writes it to live_telemetry.json for the Streamlit dashboard.
"""
import serial
import serial.tools.list_ports
import json
import time
import sys
import os

# ─── Configuration ───────────────────────────────────────────────────────────
BAUD_RATE = 115200
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_telemetry.json")
JSON_PREFIX = "JSON_TELEMETRY: "

def find_esp32_port():
    """Auto-detect the ESP32 serial port."""
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").lower()
        if any(k in desc for k in ["cp210", "ch340", "ftdi", "usb", "uart", "silicon labs"]):
            return p.device
    # Fallback: return first available port
    if ports:
        return ports[0].device
    return None

def run_bridge():
    # Try to auto-detect port
    port = find_esp32_port()
    if port is None:
        print("❌ No serial port detected. Is the ESP32 Gateway plugged in?")
        print("   Available ports:", [p.device for p in serial.tools.list_ports.comports()])
        sys.exit(1)

    print(f"🔌 Connecting to ESP32 Gateway on {port} @ {BAUD_RATE} baud...")

    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=2)
        time.sleep(2)  # Wait for ESP32 to reset
        print(f"✅ Connected! Listening for telemetry...")
        print(f"📁 Writing to: {OUTPUT_FILE}")
        print(f"   (Open another terminal and run: streamlit run dashboard.py)\n")

        packet_count = 0

        while True:
            if ser.in_waiting > 0:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                except Exception:
                    continue

                # Look for our JSON telemetry line
                if line.startswith(JSON_PREFIX):
                    json_str = line[len(JSON_PREFIX):]
                    try:
                        data = json.loads(json_str)
                        data["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        data["uptime_sec"] = int(time.time())

                        # Read history for time-series
                        history = []
                        if os.path.exists(OUTPUT_FILE):
                            try:
                                with open(OUTPUT_FILE, "r") as f:
                                    existing = json.load(f)
                                    history = existing.get("history", [])
                            except Exception:
                                history = []

                        # Keep last 60 entries (~5 minutes at 5s intervals)
                        history.append({
                            "ts": data["timestamp"],
                            "total": data.get("total", 0),
                            "normal": data.get("normal", 0),
                            "warning": data.get("warning", 0),
                            "critical": data.get("critical", 0),
                            "entropy": data.get("entropy", 0),
                            "nodes": data.get("nodes", [])
                        })
                        if len(history) > 60:
                            history = history[-60:]

                        data["history"] = history

                        with open(OUTPUT_FILE, "w") as f:
                            json.dump(data, f, indent=2)

                        packet_count += 1
                        node_count = len(data.get("nodes", []))
                        print(f"  📦 Update #{packet_count} | {node_count} nodes active | "
                              f"Total pkts: {data.get('total', 0)} | "
                              f"Entropy: {data.get('entropy', '?')}")

                    except json.JSONDecodeError as e:
                        print(f"  ⚠️  Bad JSON: {e}")

            time.sleep(0.1)

    except serial.SerialException as e:
        print(f"❌ Serial error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 Bridge stopped.")

if __name__ == "__main__":
    run_bridge()
