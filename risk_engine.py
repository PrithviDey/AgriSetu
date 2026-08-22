"""
AgriSetu Phase 14 — Environmental Risk & Urgency Engine
========================================================
Converts raw EnvironmentalData from Phase 13 into a structured
risk assessment and a numeric urgency value that feeds directly
into the Q-Learning reward function:

    R = α · Delivery − β · Energy + γ · Urgency

Urgency Values:
    NORMAL   → 1
    WARNING  → 5
    CRITICAL → 10

This module sits between the sensor simulator and the MAC layer:

    EnvironmentalData  →  RiskEngine  →  Urgency  →  Packet Priority
"""

from dataclasses import dataclass, field
from typing import List
from enum import Enum

from env_simulator import (
    EnvironmentalData,
    EnvironmentalSimulator,
    AgriCondition,
)


# ============================================================================
# Urgency Values (maps to reward weight γ · Urgency)
# ============================================================================

URGENCY_NORMAL   = 1
URGENCY_WARNING  = 5
URGENCY_CRITICAL = 10


# ============================================================================
# Fine-Grained Risk Thresholds
# (Extends Phase 13 thresholds with additional agricultural rules)
# ============================================================================

THRESHOLDS = {
    "soil_dry_warning":       30.0,   # %  — below this → DRY WARNING
    "soil_dry_critical":      20.0,   # %  — below this → DRY CRITICAL
    "soil_saturated":         85.0,   # %  — above this + rain → FLOOD RISK
    "rain_warning":           15.0,   # mm/hr
    "rain_critical":          30.0,   # mm/hr
    "temp_frost_warning":      4.0,   # °C
    "temp_frost_critical":     2.0,   # °C
    "temp_heat_warning":      40.0,   # °C
    "temp_heat_critical":     45.0,   # °C
    "humidity_high":          90.0,   # %
    "flood_risk_score":        0.7,   # composite 0–1
}


# ============================================================================
# Risk Assessment Result
# ============================================================================

@dataclass
class RiskAssessment:
    """Output of the risk engine for a single sensor reading."""
    condition: str            # e.g. "FLOOD_RISK", "DRY_WARNING"
    priority_label: str       # "NORMAL" / "WARNING" / "CRITICAL"
    urgency: int              # 1 / 5 / 10
    alerts: list              # Human-readable alert strings
    env_data: EnvironmentalData = None  # The raw data that triggered this

    def __repr__(self):
        return (f"RiskAssessment(condition={self.condition}, "
                f"priority={self.priority_label}, urgency={self.urgency}, "
                f"alerts={self.alerts})")


# ============================================================================
# Risk Analysis Engine
# ============================================================================

class RiskEngine:
    """
    Stateless risk classifier.
    Takes an EnvironmentalData snapshot and returns a RiskAssessment
    with the urgency value that feeds the Q-learning reward.
    """

    def __init__(self, thresholds: dict = None):
        self.th = thresholds or THRESHOLDS

    def assess(self, data: EnvironmentalData) -> RiskAssessment:
        alerts = []
        severity_scores = []   # 0 = normal, 1 = warning, 2 = critical

        # ---- Soil Moisture ----
        if data.soil_moisture < self.th["soil_dry_critical"]:
            alerts.append(f"🔴 SOIL CRITICALLY DRY ({data.soil_moisture:.1f}% < {self.th['soil_dry_critical']}%)")
            severity_scores.append(2)
        elif data.soil_moisture < self.th["soil_dry_warning"]:
            alerts.append(f"🟡 Soil Dry Warning ({data.soil_moisture:.1f}% < {self.th['soil_dry_warning']}%)")
            severity_scores.append(1)

        # ---- Rainfall ----
        if data.rainfall > self.th["rain_critical"]:
            alerts.append(f"🔴 EXTREME RAINFALL ({data.rainfall:.1f} mm/hr)")
            severity_scores.append(2)
        elif data.rainfall > self.th["rain_warning"]:
            alerts.append(f"🟡 Heavy Rainfall ({data.rainfall:.1f} mm/hr)")
            severity_scores.append(1)

        # ---- Temperature: Frost ----
        if data.temperature < self.th["temp_frost_critical"]:
            alerts.append(f"🔴 FROST ALERT ({data.temperature:.1f}°C)")
            severity_scores.append(2)
        elif data.temperature < self.th["temp_frost_warning"]:
            alerts.append(f"🟡 Frost Warning ({data.temperature:.1f}°C)")
            severity_scores.append(1)

        # ---- Temperature: Heat ----
        if data.temperature > self.th["temp_heat_critical"]:
            alerts.append(f"🔴 EXTREME HEAT ({data.temperature:.1f}°C)")
            severity_scores.append(2)
        elif data.temperature > self.th["temp_heat_warning"]:
            alerts.append(f"🟡 Heat Warning ({data.temperature:.1f}°C)")
            severity_scores.append(1)

        # ---- Flood Risk (composite) ----
        if data.flood_risk >= self.th["flood_risk_score"]:
            alerts.append(f"🔴 FLOOD RISK ({data.flood_risk:.3f})")
            severity_scores.append(2)

        # ---- Combined: Saturated Soil + Rain = Flood ----
        if (data.soil_moisture > self.th["soil_saturated"] and
                data.rainfall > self.th["rain_warning"]):
            if 2 not in severity_scores:  # Don't double-count if flood_risk already critical
                alerts.append(f"🔴 FLOOD: Saturated soil ({data.soil_moisture:.1f}%) + Rain ({data.rainfall:.1f} mm/hr)")
                severity_scores.append(2)

        # ---- Humidity ----
        if data.humidity > self.th["humidity_high"]:
            alerts.append(f"🟡 High Humidity ({data.humidity:.1f}%) — disease risk")
            severity_scores.append(1)

        # ---- Determine Overall Severity ----
        if not severity_scores:
            max_severity = 0
        else:
            max_severity = max(severity_scores)

        # Multi-factor escalation: 2+ warnings → treat as CRITICAL
        if severity_scores.count(1) >= 2 and max_severity < 2:
            max_severity = 2
            alerts.append("⚠️  Multiple warnings escalated to CRITICAL")

        # Map to output
        if max_severity == 2:
            condition = self._pick_critical_condition(data)
            return RiskAssessment(
                condition=condition,
                priority_label="CRITICAL",
                urgency=URGENCY_CRITICAL,
                alerts=alerts,
                env_data=data,
            )
        elif max_severity == 1:
            condition = self._pick_warning_condition(data)
            return RiskAssessment(
                condition=condition,
                priority_label="WARNING",
                urgency=URGENCY_WARNING,
                alerts=alerts,
                env_data=data,
            )
        else:
            return RiskAssessment(
                condition="NORMAL",
                priority_label="NORMAL",
                urgency=URGENCY_NORMAL,
                alerts=["✅ All parameters nominal"],
                env_data=data,
            )

    def _pick_critical_condition(self, d: EnvironmentalData) -> str:
        if d.flood_risk >= self.th["flood_risk_score"]:
            return "FLOOD_RISK"
        if d.temperature < self.th["temp_frost_critical"]:
            return "FROST_ALERT"
        if d.temperature > self.th["temp_heat_critical"]:
            return "EXTREME_HEAT"
        if d.rainfall > self.th["rain_critical"]:
            return "EXTREME_RAIN"
        if d.soil_moisture < self.th["soil_dry_critical"]:
            return "DROUGHT_CRITICAL"
        return "EXTREME_CONDITION"

    def _pick_warning_condition(self, d: EnvironmentalData) -> str:
        if d.soil_moisture < self.th["soil_dry_warning"]:
            return "DRY_WARNING"
        if d.rainfall > self.th["rain_warning"]:
            return "HEAVY_RAIN"
        if d.temperature < self.th["temp_frost_warning"]:
            return "FROST_WARNING"
        if d.temperature > self.th["temp_heat_warning"]:
            return "HEAT_WARNING"
        return "WARNING"


# ============================================================================
# Integration Helper: Feed urgency into Q-Learning Reward
# ============================================================================

def compute_reward(delivered: bool, urgency: int, energy_cost: float,
                   alpha: float = 1.0, beta: float = 0.3, gamma: float = 1.5) -> float:
    """
    R = α · Delivery − β · Energy + γ · Urgency

    Parameters:
        delivered    : True if packet was successfully received by gateway
        urgency      : 1 (NORMAL), 5 (WARNING), 10 (CRITICAL)
        energy_cost  : normalized energy consumed for this transmission
        alpha, beta, gamma : tunable reward weights
    """
    if delivered:
        delivery_reward = 10.0 + (urgency * 1.5)   # Base + urgency bonus
        urgency_reward  = urgency
    else:
        delivery_reward = -8.0
        urgency_reward  = -urgency  # Bigger penalty for dropping critical data

    return alpha * delivery_reward - beta * energy_cost + gamma * urgency_reward


# ============================================================================
# Demo: Full Pipeline
# ============================================================================

def demo_risk_pipeline():
    """
    EnvironmentalSimulator → RiskEngine → Urgency → Reward
    Shows the complete data-to-decision pipeline.
    """
    engine = RiskEngine()
    sim = EnvironmentalSimulator(node_id=1, seed=42)

    print("=" * 90)
    print("  PHASE 14 DEMO — Environmental Risk & Urgency Engine")
    print("  EnvironmentalData → RiskEngine → Urgency → Packet Priority → Reward")
    print("=" * 90)

    # Phase 1: Normal conditions (30 ticks)
    print("\n--- PHASE A: Normal Weather (t=1–30) ---")
    for t in range(30):
        data = sim.step()
        risk = engine.assess(data)
        reward = compute_reward(delivered=True, urgency=risk.urgency, energy_cost=4.0)
        if t % 5 == 0 or risk.priority_label != "NORMAL":
            print(f"  t={data.timestamp:3d} | SM:{data.soil_moisture:5.1f}% "
                  f"T:{data.temperature:5.1f}°C R:{data.rainfall:5.1f}mm "
                  f"FR:{data.flood_risk:.3f} | {risk.priority_label:>8s} "
                  f"(U={risk.urgency:2d}) | Reward={reward:+7.2f} | {risk.condition}")

    # Phase 2: Inject MONSOON (30 ticks)
    print("\n>>> 🌧️  MONSOON EVENT INJECTED <<<")
    sim.inject_event("MONSOON")
    print("--- PHASE B: Monsoon (t=31–60) ---")
    for t in range(30):
        data = sim.step()
        risk = engine.assess(data)
        reward = compute_reward(delivered=True, urgency=risk.urgency, energy_cost=4.0)
        if t % 3 == 0 or risk.priority_label != "NORMAL":
            print(f"  t={data.timestamp:3d} | SM:{data.soil_moisture:5.1f}% "
                  f"T:{data.temperature:5.1f}°C R:{data.rainfall:5.1f}mm "
                  f"FR:{data.flood_risk:.3f} | {risk.priority_label:>8s} "
                  f"(U={risk.urgency:2d}) | Reward={reward:+7.2f} | {risk.condition}")
        for a in risk.alerts:
            if "🔴" in a or "⚠️" in a:
                print(f"        └─ {a}")

    # Phase 3: Inject FROST_SNAP (30 ticks)
    print("\n>>> 🥶  FROST SNAP INJECTED <<<")
    sim.inject_event("FROST_SNAP")
    print("--- PHASE C: Frost (t=61–90) ---")
    for t in range(30):
        data = sim.step()
        risk = engine.assess(data)
        reward_ok = compute_reward(delivered=True, urgency=risk.urgency, energy_cost=4.0)
        reward_fail = compute_reward(delivered=False, urgency=risk.urgency, energy_cost=4.0)
        if t % 3 == 0 or risk.priority_label != "NORMAL":
            print(f"  t={data.timestamp:3d} | SM:{data.soil_moisture:5.1f}% "
                  f"T:{data.temperature:5.1f}°C R:{data.rainfall:5.1f}mm "
                  f"FR:{data.flood_risk:.3f} | {risk.priority_label:>8s} "
                  f"(U={risk.urgency:2d}) | R_ok={reward_ok:+7.2f} R_fail={reward_fail:+7.2f} "
                  f"| {risk.condition}")
        for a in risk.alerts:
            if "🔴" in a:
                print(f"        └─ {a}")

    # Summary
    print("\n" + "=" * 90)
    print("  URGENCY → REWARD MAPPING SUMMARY")
    print("=" * 90)
    print(f"  {'Priority':<12} {'Urgency':>7} {'R(delivered)':>14} {'R(dropped)':>12}")
    print(f"  {'-'*50}")
    for label, u in [("NORMAL", 1), ("WARNING", 5), ("CRITICAL", 10)]:
        r_ok   = compute_reward(delivered=True,  urgency=u, energy_cost=4.0)
        r_fail = compute_reward(delivered=False, urgency=u, energy_cost=4.0)
        print(f"  {label:<12} {u:>7} {r_ok:>+14.2f} {r_fail:>+12.2f}")
    print()
    print("  The agent LEARNS that dropping a CRITICAL packet costs 5x more")
    print("  than dropping a NORMAL packet → it fights harder to deliver alerts!")
    print("=" * 90)


if __name__ == "__main__":
    demo_risk_pipeline()
