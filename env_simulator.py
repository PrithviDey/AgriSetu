"""
AgriSetu Phase 13 — Environmental Data Simulation Engine
=========================================================
Generates realistic agricultural sensor data using Ornstein-Uhlenbeck
mean-reverting random walks. Values drift gradually (like real weather)
instead of jumping randomly each tick.

Each virtual node owns an instance of EnvironmentalSimulator, producing:
  - Soil Moisture (%)
  - Temperature (°C)
  - Humidity (%)
  - Rainfall (mm/hr)
  - Flood Risk Score (0.0 – 1.0, computed from the above)

Agricultural Conditions:
  NORMAL            — all parameters within safe range
  DRY_WARNING       — soil moisture < 30%
  HEAVY_RAIN        — rainfall > 15 mm/hr
  FLOOD_RISK        — high rainfall + high soil moisture
  FROST_ALERT       — temperature < 2°C
  EXTREME_CONDITION — multiple thresholds breached simultaneously
"""

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple


# ============================================================================
# Task 13.1 — Environmental Data Structure
# ============================================================================

@dataclass
class EnvironmentalData:
    soil_moisture: float    # % (0–100)
    temperature: float      # °C
    humidity: float          # % (0–100)
    rainfall: float          # mm/hr (0–60+)
    flood_risk: float        # composite score 0.0–1.0
    condition: str = "NORMAL"
    timestamp: int = 0


# ============================================================================
# Task 13.3 — Agricultural Condition Definitions
# ============================================================================

class AgriCondition(Enum):
    NORMAL            = 0
    DRY_WARNING       = 1
    HEAVY_RAIN        = 2
    FLOOD_RISK        = 3
    FROST_ALERT       = 4
    EXTREME_CONDITION = 5


# Thresholds
SOIL_DRY_THRESHOLD      = 30.0   # % — below this → DRY_WARNING
SOIL_SATURATED_THRESHOLD = 80.0   # % — above this + rain → FLOOD_RISK
RAIN_HEAVY_THRESHOLD     = 15.0   # mm/hr — above this → HEAVY_RAIN
FROST_THRESHOLD          = 2.0    # °C — below this → FROST_ALERT
FLOOD_RISK_THRESHOLD     = 0.7    # composite score — above this → FLOOD_RISK


def classify_condition(data: EnvironmentalData) -> Tuple[AgriCondition, int]:
    """
    Classify the environmental state and return (condition, priority).
    Priority: 0 = NORMAL, 1 = WARNING, 2 = CRITICAL
    """
    breaches = 0

    is_dry   = data.soil_moisture < SOIL_DRY_THRESHOLD
    is_frost = data.temperature < FROST_THRESHOLD
    is_heavy_rain = data.rainfall > RAIN_HEAVY_THRESHOLD
    is_flood = data.flood_risk >= FLOOD_RISK_THRESHOLD

    if is_dry:   breaches += 1
    if is_frost: breaches += 1
    if is_heavy_rain: breaches += 1
    if is_flood: breaches += 1

    # Multiple thresholds breached → EXTREME
    if breaches >= 2:
        return AgriCondition.EXTREME_CONDITION, 2

    # Single-condition classification (priority order: most dangerous first)
    if is_flood:
        return AgriCondition.FLOOD_RISK, 2
    if is_frost:
        return AgriCondition.FROST_ALERT, 2
    if is_heavy_rain:
        return AgriCondition.HEAVY_RAIN, 1
    if is_dry:
        return AgriCondition.DRY_WARNING, 1

    return AgriCondition.NORMAL, 0


# ============================================================================
# Task 13.2 — Ornstein-Uhlenbeck Mean-Reverting Random Walk
# Values change gradually, creating meaningful agricultural trends.
# ============================================================================

class OUProcess:
    """
    Ornstein-Uhlenbeck process: dx = θ(μ - x)dt + σ dW
    θ (theta) = mean reversion speed
    μ (mu)    = long-term mean
    σ (sigma) = volatility (how noisy the drift is)
    """
    def __init__(self, mu: float, sigma: float, theta: float,
                 x0: float = None, lo: float = None, hi: float = None):
        self.mu = mu
        self.sigma = sigma
        self.theta = theta
        self.x = x0 if x0 is not None else mu
        self.lo = lo
        self.hi = hi

    def step(self, dt: float = 1.0) -> float:
        dx = self.theta * (self.mu - self.x) * dt + \
             self.sigma * math.sqrt(dt) * random.gauss(0, 1)
        self.x += dx
        if self.lo is not None:
            self.x = max(self.lo, self.x)
        if self.hi is not None:
            self.x = min(self.hi, self.x)
        return self.x


class EnvironmentalSimulator:
    """
    Per-node environmental simulator.  Generates smooth, realistic
    agricultural data that drifts over time.

    Optional: inject weather events (drought, monsoon, frost snap)
    that shift the long-term mean temporarily.
    """

    def __init__(self, node_id: int, seed: int = None):
        self.node_id = node_id
        if seed is not None:
            random.seed(seed)

        # Each node starts at slightly different conditions
        # (fields across a farm are not identical)
        jitter = random.uniform(-5, 5)

        # Soil Moisture: mean 55%, slow drift, bounded [5, 100]
        self.soil = OUProcess(mu=55 + jitter, sigma=1.2, theta=0.03,
                              x0=55 + jitter, lo=5, hi=100)

        # Temperature: mean 28°C (tropical India), bounded [-5, 50]
        self.temp = OUProcess(mu=28 + jitter * 0.3, sigma=0.5, theta=0.05,
                              x0=28, lo=-5, hi=50)

        # Humidity: mean 65%, correlated loosely with rainfall
        self.hum = OUProcess(mu=65 + jitter * 0.4, sigma=1.0, theta=0.04,
                             x0=65, lo=10, hi=100)

        # Rainfall: mean 2 mm/hr (light drizzle baseline), can spike
        self.rain = OUProcess(mu=2.0, sigma=1.5, theta=0.06,
                              x0=0.0, lo=0.0, hi=80)

        self.tick = 0

    def inject_event(self, event: str):
        """
        Shift the OU means to simulate a weather event.
        The mean-reversion will pull values toward the new target gradually.
        """
        if event == "DROUGHT":
            self.soil.mu = 18.0     # soil dries out
            self.rain.mu = 0.0      # no rain
            self.temp.mu = 40.0     # heatwave
            self.hum.mu = 25.0      # dry air
        elif event == "MONSOON":
            self.rain.mu = 35.0     # heavy sustained rain
            self.soil.mu = 90.0     # waterlogged
            self.hum.mu = 95.0      # saturated air
        elif event == "FROST_SNAP":
            self.temp.mu = -1.0     # sub-zero snap
            self.hum.mu = 40.0
        elif event == "NORMAL":
            self.soil.mu = 55.0
            self.temp.mu = 28.0
            self.hum.mu = 65.0
            self.rain.mu = 2.0

    def compute_flood_risk(self, soil: float, rain: float, hum: float) -> float:
        """
        Composite flood-risk score (0–1).
        Weighted combination of soil saturation, rainfall intensity,
        and humidity.
        """
        soil_factor = max(0, (soil - 50)) / 50.0          # 0 when ≤50%, 1 at 100%
        rain_factor = min(1.0, rain / 30.0)                # saturates at 30 mm/hr
        hum_factor  = max(0, (hum - 70)) / 30.0            # kicks in above 70%
        return min(1.0, 0.4 * soil_factor + 0.45 * rain_factor + 0.15 * hum_factor)

    def step(self) -> EnvironmentalData:
        """Advance one timestep and return the current reading."""
        self.tick += 1

        sm   = self.soil.step()
        temp = self.temp.step()
        hum  = self.hum.step()
        rain = self.rain.step()
        fr   = self.compute_flood_risk(sm, rain, hum)

        data = EnvironmentalData(
            soil_moisture=round(sm, 2),
            temperature=round(temp, 2),
            humidity=round(hum, 2),
            rainfall=round(rain, 2),
            flood_risk=round(fr, 4),
            timestamp=self.tick
        )

        cond, priority = classify_condition(data)
        data.condition = cond.name
        return data


# ============================================================================
# Demo / Self-Test
# ============================================================================

def demo_single_node(steps: int = 60):
    """Print 60 timesteps for one node to show smooth drift."""
    sim = EnvironmentalSimulator(node_id=1, seed=42)

    print(f"{'t':>4} | {'Soil%':>7} | {'Temp°C':>7} | {'Hum%':>6} | "
          f"{'Rain':>6} | {'Flood':>6} | Condition")
    print("-" * 75)

    for _ in range(steps):
        d = sim.step()
        print(f"{d.timestamp:4d} | {d.soil_moisture:7.2f} | {d.temperature:7.2f} | "
              f"{d.humidity:6.2f} | {d.rainfall:6.2f} | {d.flood_risk:6.4f} | {d.condition}")


def demo_event_injection():
    """Show a node going through NORMAL → MONSOON → NORMAL."""
    sim = EnvironmentalSimulator(node_id=1, seed=7)

    print("\n" + "=" * 75)
    print("EVENT INJECTION DEMO: Normal → Monsoon (t=20) → Recovery (t=50)")
    print("=" * 75)
    print(f"{'t':>4} | {'Soil%':>7} | {'Temp°C':>7} | {'Hum%':>6} | "
          f"{'Rain':>6} | {'Flood':>6} | Condition")
    print("-" * 75)

    for t in range(80):
        if t == 20:
            print(">>>  🌧️  MONSOON EVENT INJECTED  🌧️")
            sim.inject_event("MONSOON")
        if t == 50:
            print(">>>  ☀️  WEATHER NORMALISING  ☀️")
            sim.inject_event("NORMAL")

        d = sim.step()
        print(f"{d.timestamp:4d} | {d.soil_moisture:7.2f} | {d.temperature:7.2f} | "
              f"{d.humidity:6.2f} | {d.rainfall:6.2f} | {d.flood_risk:6.4f} | {d.condition}")


def demo_multi_node(num_nodes: int = 5, steps: int = 10):
    """Show multiple nodes with slightly different readings (field variation)."""
    sims = [EnvironmentalSimulator(node_id=i, seed=i * 13) for i in range(num_nodes)]

    print("\n" + "=" * 85)
    print(f"MULTI-NODE DEMO: {num_nodes} nodes, {steps} timesteps each")
    print("=" * 85)

    for t in range(steps):
        print(f"\n--- Timestep {t+1} ---")
        for sim in sims:
            d = sim.step()
            print(f"  Node {sim.node_id:2d} | SM: {d.soil_moisture:5.1f}% | "
                  f"T: {d.temperature:5.1f}°C | H: {d.humidity:5.1f}% | "
                  f"R: {d.rainfall:5.2f} mm/hr | FR: {d.flood_risk:.3f} | {d.condition}")


if __name__ == "__main__":
    demo_single_node(60)
    demo_event_injection()
    demo_multi_node(5, 10)
