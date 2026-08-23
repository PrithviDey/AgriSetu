"""
AgriSetu — LoRa Node Model
Represents a virtual ESP32 + LoRa sensor node.
"""
import random
import time
import math


class Node:
    """Virtual LoRa sensor node with Q-Learning MAC."""

    def __init__(self, node_id: int, total_nodes: int):
        self.node_id = node_id

        # --- Radio parameters (randomised per node) ---
        self.rssi_raw: float = random.uniform(-115.0, -60.0)   # dBm
        self.sf: int = random.choice([7, 8, 9, 10, 11, 12])    # Spreading Factor
        self.cr: float = random.uniform(0.2, 0.9)              # Coding Rate

        # --- Battery (mWh) ---
        self.battery: float = random.uniform(75.0, 100.0)
        self.battery_drain_per_tx: float = random.uniform(0.04, 0.12)

        # --- Environmental Data ---
        self.soil: float = random.uniform(30.0, 70.0)
        self.temp: float = random.uniform(20.0, 35.0)
        self.hum: float = random.uniform(40.0, 80.0)
        self.rain: float = max(0.0, random.uniform(-5.0, 5.0))
        self.noise_level: int = 0  # 0=Low, 1=Medium, 2=High, 3=VeryHigh (potentiometer)

        # --- Position (circle around gateway) ---
        angle = (2 * math.pi * node_id) / total_nodes
        radius = 0.35 + random.uniform(-0.05, 0.05)
        self.x: float = 0.5 + radius * math.cos(angle)
        self.y: float = 0.5 + radius * math.sin(angle)

        # --- Status ---
        self.online: bool = True
        self.last_tx_time: float = time.time()

        # --- Cumulative stats ---
        self.packets_sent: int = 0
        self.packets_success: int = 0
        self.packets_collision: int = 0
        self.total_energy: float = 0.0
        self.latency_sum: float = 0.0

    # ── State discretisation ─────────────────────────────────────
    def rssi_bin(self) -> int:
        """0 = Good, 1 = Medium, 2 = Poor"""
        if self.rssi_raw > -85:
            return 0
        elif self.rssi_raw > -100:
            return 1
        return 2

    def sf_bin(self) -> int:
        """0 = Low, 1 = Medium, 2 = High"""
        if self.sf <= 8:
            return 0
        elif self.sf <= 10:
            return 1
        return 2

    def cr_bin(self) -> int:
        """0 = Low, 1 = Medium, 2 = High"""
        if self.cr < 0.4:
            return 0
        elif self.cr < 0.7:
            return 1
        return 2

    # ── Helpers ──────────────────────────────────────────────────
    def drain_battery(self, amount: float):
        self.battery = max(0.0, self.battery - amount)
        if self.battery < 5.0:
            if random.random() < 0.02:
                self.online = False

    def fluctuate(self):
        """Slightly vary radio parameters each tick to simulate real conditions."""
        self.rssi_raw += random.gauss(0, 2.0)
        self.rssi_raw = max(-130.0, min(-40.0, self.rssi_raw))
        self.cr += random.gauss(0, 0.02)
        self.cr = max(0.1, min(1.0, self.cr))

    @property
    def pdr(self) -> float:
        return (self.packets_success / max(1, self.packets_sent)) * 100.0

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "battery": round(self.battery, 1),
            "rssi": round(self.rssi_raw, 1),
            "sf": self.sf,
            "cr": round(self.cr, 2),
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "online": self.online,
            "packets_sent": self.packets_sent,
            "packets_success": self.packets_success,
            "packets_collision": self.packets_collision,
            "pdr": round(self.pdr, 1),
            "total_energy": round(self.total_energy, 3),
            "avg_latency": round(
                self.latency_sum / max(1, self.packets_success), 1
            ),
            "soil": round(self.soil, 1),
            "temp": round(self.temp, 1),
            "hum": round(self.hum, 1),
            "rain": round(self.rain, 1),
            "noise_level": self.noise_level,
        }
