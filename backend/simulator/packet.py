"""
AgriSetu — Packet Model
"""
import time
from dataclasses import dataclass, field
from enum import Enum


class Priority(str, Enum):
    NORMAL   = "normal"
    WARNING  = "warning"
    CRITICAL = "critical"


_pkt_counter = 0


def _next_id() -> int:
    global _pkt_counter
    _pkt_counter += 1
    return _pkt_counter


@dataclass
class Packet:
    node_id:   int
    priority:  Priority        = Priority.NORMAL
    timestamp: float           = field(default_factory=time.time)
    duration:  float           = 1.0   # transmission duration (slots)
    action:    int             = 0     # action taken (A0‑A4)
    pkt_id:    int             = field(default_factory=_next_id)

    # Outcome (filled after channel resolution)
    success:   bool            = False
    collided:  bool            = False
    energy:    float           = 0.0
    latency:   float           = 0.0

    def to_dict(self) -> dict:
        return {
            "pkt_id":    self.pkt_id,
            "node_id":   self.node_id,
            "priority":  self.priority.value,
            "timestamp": round(self.timestamp, 3),
            "action":    self.action,
            "success":   self.success,
            "collided":  self.collided,
            "energy":    round(self.energy, 4),
            "latency":   round(self.latency, 1),
        }
