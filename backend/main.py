"""
AgriSetu — FastAPI Backend
Serves the Q-Learning simulation over REST + WebSocket.
Run: uvicorn main:app --reload --port 8000
"""
import asyncio
import json
import time
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from simulator.environment import Environment
from hardware.serial_bridge  import SerialBridge

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="AgriSetu API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the dashboard folder as static files at /ui
DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")
if os.path.isdir(DASHBOARD_DIR):
    app.mount("/ui", StaticFiles(directory=DASHBOARD_DIR, html=True), name="ui")

# ── Simulation state ──────────────────────────────────────────────────────────
env = Environment(n_nodes=20)
_running     = True
_clients: Set[WebSocket] = set()
_sim_speed   = 1.0      # seconds per tick (default 1 Hz)
_hw_mode     = False    # True = use real ESP32 data instead of (or alongside) sim
bridge       = SerialBridge()   # singleton serial bridge

# ── Background simulation loop ────────────────────────────────────────────────
async def simulation_loop():
    global _clients, _running, _hw_mode
    while True:
        if _running:
            # ── Drain hardware frames first ───────────────────────
            if bridge.connected:
                for frame in bridge.drain():
                    ftype = frame.get("t", "")
                    if ftype == "nd":
                        env.inject_node_data(frame)
                    elif ftype == "tx":
                        env.inject_tx_result(frame)
                    # "ping" frames are silently consumed

            # ── Run software simulation (unless pure hw mode) ──────
            if not _hw_mode:
                env.tick()

            # ── Broadcast to all WebSocket clients ────────────────
            snapshot = env.snapshot()
            snapshot["hardware"] = bridge.status()   # always include HW status
            dead = set()
            for ws in list(_clients):
                try:
                    await ws.send_text(json.dumps(snapshot))
                except Exception:
                    dead.add(ws)
            _clients -= dead
        await asyncio.sleep(_sim_speed)


@app.on_event("startup")
async def startup():
    asyncio.create_task(simulation_loop())


# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    # Send initial snapshot immediately
    await ws.send_text(json.dumps(env.snapshot()))
    try:
        while True:
            await ws.receive_text()   # keep alive / accept client messages
    except WebSocketDisconnect:
        _clients.discard(ws)


# ── REST API ──────────────────────────────────────────────────────────────────
@app.get("/api/status")
def get_status():
    return {"running": _running, "speed": _sim_speed, "tick": env.tick_count}


@app.get("/api/snapshot")
def get_snapshot():
    return env.snapshot()


@app.get("/api/nodes")
def get_nodes():
    return {"nodes": [n.to_dict() for n in env.nodes]}


@app.get("/api/alerts")
def get_alerts():
    return {"alerts": list(env.alerts)}


@app.get("/api/logs")
def get_logs():
    return {"logs": list(env.logs)}


@app.get("/api/rl")
def get_rl():
    return env.agent.to_dict()


@app.get("/api/benchmark")
def get_benchmark():
    return env.benchmark


@app.post("/api/control")
async def control(body: dict):
    global _running, _sim_speed, _hw_mode
    action = body.get("action")
    if action == "start":
        _running = True
    elif action == "stop":
        _running = False
    elif action == "reset":
        env.reset()
        _running = True
    elif action == "set_nodes":
        env.update_node_count(int(body.get("count", 20)))
    elif action == "set_speed":
        _sim_speed = float(body.get("speed", 1.0))
    elif action == "set_hw_mode":
        _hw_mode = bool(body.get("hw_mode", False))
    return {"ok": True, "running": _running}


@app.post("/api/settings/rl")
async def update_rl_settings(body: dict):
    """Hot-update Q-Learning hyperparameters from the Settings panel."""
    env.agent.update_params(
        alpha=body.get("alpha", env.agent.alpha),
        gamma=body.get("gamma", env.agent.gamma),
        epsilon_min=body.get("epsilon_min", env.agent.epsilon_min),
        epsilon_decay=body.get("epsilon_decay", env.agent.epsilon_decay),
        w_delivery=body.get("w_delivery", env.agent.w_delivery),
        w_energy=body.get("w_energy", env.agent.w_energy),
        w_urgency=body.get("w_urgency", env.agent.w_urgency),
    )
    return {"ok": True, "params": env.agent.to_dict()}


@app.post("/api/trigger/critical")
async def trigger_critical():
    """Manually inject a critical alert (demo / potentiometer simulation)."""
    from simulator.environment import _alert
    env.critical_alert_count += 1
    env.alerts.appendleft(
        _alert(
            node_id=1,
            kind="Manual Critical",
            severity="critical",
            msg="Manual critical alert triggered (potentiometer / demo)",
        )
    )
    return {"ok": True}


# ── Hardware / Serial API ─────────────────────────────────────────────────────
@app.get("/api/hardware/ports")
def list_ports():
    """List available serial ports on this machine."""
    return {"ports": SerialBridge.list_ports()}


@app.get("/api/hardware/status")
def hw_status():
    return bridge.status()


@app.post("/api/hardware/connect")
async def hw_connect(body: dict):
    """Connect to an ESP32 via serial port."""
    global _hw_mode
    port = body.get("port", "")
    baud = int(body.get("baud", 115200))
    hw   = body.get("hw_mode", False)   # True = disable software sim
    if not port:
        return {"ok": False, "error": "No port specified"}
    ok = bridge.connect(port, baud)
    if ok:
        _hw_mode = hw
        if hw:
            # Clear fake software nodes so ONLY real hardware nodes appear
            env.nodes = []
            env.n_nodes = 0
            env.alerts.clear()
            from simulator.environment import _alert
            env.alerts.appendleft(_alert(0, "Hardware Mode", "low", "Switched to pure hardware mode. Waiting for ESP32 nodes..."))
    return {"ok": ok, "status": bridge.status(), "hw_mode": _hw_mode}


@app.post("/api/hardware/disconnect")
async def hw_disconnect():
    global _hw_mode
    bridge.disconnect()
    _hw_mode = False
    return {"ok": True, "status": bridge.status()}


@app.post("/api/hardware/send")
async def hw_send(body: dict):
    """Send a raw JSON command to the ESP32 (e.g. export Q-table)."""
    bridge.send(body)
    return {"ok": True}


@app.get("/")
def root():
    return {"message": "AgriSetu API running. Dashboard at /ui"}
