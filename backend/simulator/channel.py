"""
AgriSetu — Shared LoRa Channel Model
Detects collisions when multiple nodes transmit simultaneously.
Also maintains a sliding window for entropy calculation.
"""
import math
import random
from typing import List, Tuple

from .packet import Packet


class Channel:
    WINDOW = 30   # slots of history for entropy

    def __init__(self, noise_level: float = 0.08):
        self.noise_level = noise_level              # base packet-error rate
        self._history: List[bool] = []             # True = collision

    # ── Core: resolve a set of simultaneous transmissions ────────
    def resolve(self, packets: List[Packet]) -> List[Tuple[Packet, bool]]:
        """
        Given packets all attempting to transmit in the same slot,
        return (packet, success) pairs.
        """
        results: List[Tuple[Packet, bool]] = []

        if not packets:
            return results

        if len(packets) == 1:
            # Sole transmitter — succeeds unless background noise kills it
            ok = random.random() > self.noise_level
            packets[0].success  = ok
            packets[0].collided = not ok
            self._history.append(not ok)
            results.append((packets[0], ok))
        else:
            # Multiple simultaneous → all collide
            for pkt in packets:
                pkt.success  = False
                pkt.collided = True
                self._history.append(True)
                results.append((pkt, False))

        # Keep window bounded
        if len(self._history) > self.WINDOW:
            self._history = self._history[-self.WINDOW:]

        return results

    def record_result(self, success: bool):
        """Manually record a transmission result (used for hardware mode)."""
        self._history.append(not success)
        if len(self._history) > self.WINDOW:
            self._history = self._history[-self.WINDOW:]

    # ── Entropy ───────────────────────────────────────────────────
    def entropy(self) -> float:
        """Shannon entropy of recent collision events (0‑1)."""
        n = len(self._history)
        if n == 0:
            return 0.0
        p_c = sum(self._history) / n
        p_s = 1.0 - p_c
        if p_c in (0.0, 1.0):
            return 0.0
        return -(p_c * math.log2(p_c) + p_s * math.log2(p_s))

    def entropy_bin(self) -> int:
        """0 = Low, 1 = Medium, 2 = High, 3 = VeryHigh"""
        e = self.entropy()
        if e < 0.25:
            return 0
        elif e < 0.50:
            return 1
        elif e < 0.75:
            return 2
        return 3

    def collision_rate(self) -> float:
        if not self._history:
            return 0.0
        return sum(self._history) / len(self._history) * 100.0
