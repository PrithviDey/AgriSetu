"""
AgriSetu — Full-Stack Benchmark with Environmental Data
=========================================================
Integrates: Phase 13 (Environmental Simulator) + Phase 14 (Risk Engine)
          + Phase 10 (Realistic LoRa PHY with Capture Effect)

Benchmarks Standard ALOHA vs AgriSetu at:
    10, 25, 50, 100, 250, 500, 1000 nodes

Metrics: PDR, Collision Rate, Energy, Latency, Critical Alert Latency
Also: Per-node soil moisture & weather snapshot
"""

import random
import numpy as np
import math
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import defaultdict

from env_simulator import EnvironmentalSimulator
from risk_engine import RiskEngine, compute_reward

# =============================================================================
# LoRa Physical Layer Constants
# =============================================================================
ENERGY_IDLE = 0.02
ENERGY_TX_SF7 = 40
ENERGY_TX_SF8 = 70
ENERGY_TX_SF9 = 120
SF_ENERGY_MAP = {7: ENERGY_TX_SF7, 8: ENERGY_TX_SF8, 9: ENERGY_TX_SF9}

CHANNELS = [868.1, 868.3, 868.5]
SPREADING_FACTORS = [7, 8, 9]
MAX_RETRIES = 3
PACKET_TTL = 300

# =============================================================================
# Base Node with Environment + Risk Engine
# =============================================================================
class EnvLoRaNode:
    def __init__(self, id):
        self.id = id
        self.x = random.uniform(-1000, 1000)
        self.y = random.uniform(-1000, 1000)
        self.distance = math.sqrt(self.x**2 + self.y**2)
        d = max(10, self.distance)
        self.rssi = -40 - 10 * 3.2 * math.log10(d / 1.0) + random.gauss(0, 3)

        # Environmental simulator per node
        self.env_sim = EnvironmentalSimulator(node_id=id, seed=id * 7 + 42)
        self.risk_engine = RiskEngine()
        self.last_env_data = None
        self.last_risk = None

        # Counters
        self.total_packets = 0
        self.successful_packets = 0
        self.collisions = 0
        self.retries = 0
        self.energy_consumed = 0.0
        self.total_latency = 0
        self.dropped_packets = 0

        # Critical alert tracking
        self.critical_packets = 0
        self.critical_delivered = 0
        self.critical_total_latency = 0

        self.has_packet = False
        self.wait_time = 0
        self.gen_time = 0
        self.current_retries = 0
        self.channel = 868.1
        self.sf = 7
        self.priority = "NORMAL"
        self.urgency = 1

    def _tick_environment(self):
        """Advance the environment simulation and determine priority."""
        self.last_env_data = self.env_sim.step()
        self.last_risk = self.risk_engine.assess(self.last_env_data)
        self.priority = self.last_risk.priority_label
        self.urgency = self.last_risk.urgency

    def generate_packet(self, t, p_tx):
        if not self.has_packet:
            if random.random() < p_tx:
                self._tick_environment()
                self.has_packet = True
                self.total_packets += 1
                self.gen_time = t
                self.current_retries = 0
                if self.priority == "CRITICAL":
                    self.critical_packets += 1
                return True
        return False


# =============================================================================
# Standard ALOHA Node (with Environmental Data)
# =============================================================================
class StandardAlohaEnvNode(EnvLoRaNode):
    def step(self, t, p_tx):
        self.generate_packet(t, p_tx)
        if self.has_packet:
            if (t - self.gen_time) > PACKET_TTL:
                self.has_packet = False
                self.dropped_packets += 1
                return False, None, None, None
            if self.wait_time <= 0:
                self.channel = random.choice(CHANNELS)
                self.sf = 7
                self.energy_consumed += SF_ENERGY_MAP[self.sf]
                return True, self.channel, self.sf, self.rssi
            else:
                self.wait_time -= 1
                self.energy_consumed += ENERGY_IDLE
        return False, None, None, None

    def feedback(self, success, t):
        if success:
            self.successful_packets += 1
            lat = t - self.gen_time
            self.total_latency += lat
            if self.priority == "CRITICAL":
                self.critical_delivered += 1
                self.critical_total_latency += lat
            self.has_packet = False
        else:
            self.collisions += 1
            self.retries += 1
            self.current_retries += 1
            if self.current_retries >= MAX_RETRIES:
                self.has_packet = False
                self.dropped_packets += 1
            else:
                self.wait_time = random.randint(10, 40)


# =============================================================================
# AgriSetu Q-Learning Node (with Environmental Data + Risk Engine)
# =============================================================================
class AgriSetuEnvQNode(EnvLoRaNode):
    def __init__(self, id):
        super().__init__(id)
        self.rssi_idx = 0 if self.rssi < -100 else (1 if self.rssi < -85 else 2)
        self.sf_idx = 0
        self.entropy_idx = 0

        self.action_windows = [4, 16, 64, 128, 256]
        self.actions = []
        for w in self.action_windows:
            for ch in CHANNELS:
                self.actions.append((w, ch))
        self.num_actions = len(self.actions)

        self.lr = 0.3
        self.gamma = 0.85
        self.epsilon = 0.15
        self.epsilon_decay = 0.9998
        self.epsilon_min = 0.01

        # Q-table: (RSSI, SF, Entropy, Priority, Actions)
        self.q_table = np.zeros((3, 3, 4, 3, self.num_actions))

        # Domain knowledge warm start
        for r in range(3):
            for s in range(3):
                for e in range(4):
                    for p in range(3):
                        for a_idx, (w, ch) in enumerate(self.actions):
                            score = 5.0
                            if e >= 2 and w >= 64:
                                score += 8.0
                            elif e < 2 and w <= 64:
                                score += 6.0
                            if p == 2 and w <= 16:
                                score += 14.0
                            self.q_table[r, s, e, p, a_idx] = score

        self.col_history = []
        self.col_window = 20
        self.last_state = None
        self.last_action_idx = None

    def _update_entropy(self, was_col):
        self.col_history.append(1 if was_col else 0)
        if len(self.col_history) > self.col_window:
            self.col_history.pop(0)
        if len(self.col_history) < 3:
            return
        N = len(self.col_history)
        c = sum(self.col_history)
        p_c = c / N
        p_s = (N - c) / N
        h_c = -p_c * math.log2(p_c) if p_c > 0 else 0
        h_s = -p_s * math.log2(p_s) if p_s > 0 else 0
        H = h_c + h_s
        if p_c <= 0.4:
            self.entropy_idx = 0 if H < 0.8 else 1
        else:
            self.entropy_idx = 2 if H >= 0.8 else 3

    def get_state(self):
        p_idx = 0 if self.priority == "NORMAL" else (1 if self.priority == "WARNING" else 2)
        return (self.rssi_idx, self.sf_idx, self.entropy_idx, p_idx)

    def _pick_action(self):
        if random.random() < self.epsilon:
            self.last_action_idx = random.randint(0, self.num_actions - 1)
        else:
            self.last_action_idx = np.argmax(self.q_table[self.last_state])
        w, ch = self.actions[self.last_action_idx]
        self.wait_time = random.randint(0, w - 1)
        self.channel = ch
        self.sf = SPREADING_FACTORS[self.sf_idx]

    def step(self, t, p_tx):
        new_pkt = self.generate_packet(t, p_tx)
        if new_pkt:
            self.last_state = self.get_state()
            self._pick_action()

        if self.has_packet:
            if (t - self.gen_time) > PACKET_TTL:
                self.has_packet = False
                self.dropped_packets += 1
                return False, None, None, None
            if self.wait_time <= 0:
                self.energy_consumed += SF_ENERGY_MAP[self.sf]
                return True, self.channel, self.sf, self.rssi
            else:
                self.wait_time -= 1
                self.energy_consumed += ENERGY_IDLE
        return False, None, None, None

    def feedback(self, success, t):
        self._update_entropy(not success)

        # Reward using Phase 14 urgency values
        e_cost = (SF_ENERGY_MAP[self.sf] / 10.0) + (self.wait_time * ENERGY_IDLE)
        reward = compute_reward(delivered=success, urgency=self.urgency, energy_cost=e_cost)

        if success:
            old = self.q_table[self.last_state][self.last_action_idx]
            self.q_table[self.last_state][self.last_action_idx] = old + self.lr * (reward - old)
            self.successful_packets += 1
            lat = t - self.gen_time
            self.total_latency += lat
            if self.priority == "CRITICAL":
                self.critical_delivered += 1
                self.critical_total_latency += lat
            self.has_packet = False
        else:
            self.collisions += 1
            self.retries += 1
            self.current_retries += 1
            if self.current_retries >= MAX_RETRIES:
                old = self.q_table[self.last_state][self.last_action_idx]
                self.q_table[self.last_state][self.last_action_idx] = old + self.lr * (-15 - old)
                self.has_packet = False
                self.dropped_packets += 1
            else:
                self.sf_idx = (self.sf_idx + 1) % len(SPREADING_FACTORS)
                ns = self.get_state()
                old = self.q_table[self.last_state][self.last_action_idx]
                mf = np.max(self.q_table[ns])
                self.q_table[self.last_state][self.last_action_idx] = old + self.lr * (reward + self.gamma * mf - old)
                self.last_state = ns
                self._pick_action()

        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)


# =============================================================================
# Gateway with Capture Effect
# =============================================================================
class CaptureGateway:
    def __init__(self):
        self.total_tx = 0

    def tick(self, nodes, t, p_tx):
        transmissions = {}
        for n in nodes:
            active, ch, sf, rssi = n.step(t, p_tx)
            if active:
                key = (ch, sf)
                if key not in transmissions:
                    transmissions[key] = []
                transmissions[key].append((n, rssi))
                self.total_tx += 1

        for (ch, sf), tx_list in transmissions.items():
            if len(tx_list) == 1:
                tx_list[0][0].feedback(True, t)
            else:
                tx_list.sort(key=lambda x: x[1], reverse=True)
                strongest_node, strongest_rssi = tx_list[0]
                runner_up_rssi = tx_list[1][1]
                if (strongest_rssi - runner_up_rssi) >= 6.0:
                    strongest_node.feedback(True, t)
                    for n, _ in tx_list[1:]:
                        n.feedback(False, t)
                else:
                    for n, _ in tx_list:
                        n.feedback(False, t)


# =============================================================================
# Benchmark Runner
# =============================================================================
def run_benchmark(node_cls, N, T=40000, p_tx=0.005):
    random.seed(42 + N)
    np.random.seed(42 + N)
    nodes = [node_cls(i) for i in range(N)]
    gateway = CaptureGateway()

    # Inject weather events at specific times for realism
    event_schedule = {
        int(T * 0.3): "MONSOON",
        int(T * 0.5): "NORMAL",
        int(T * 0.7): "FROST_SNAP",
        int(T * 0.85): "NORMAL",
    }

    for t in range(T):
        if t in event_schedule:
            event = event_schedule[t]
            for n in nodes:
                n.env_sim.inject_event(event)
        gateway.tick(nodes, t, p_tx)

    tp = sum(n.total_packets for n in nodes)
    sp = sum(n.successful_packets for n in nodes)
    co = sum(n.collisions for n in nodes)
    en = sum(n.energy_consumed for n in nodes)
    dr = sum(n.dropped_packets for n in nodes)
    lat = (sum(n.total_latency for n in nodes) / sp) if sp else 0
    pdr = (sp / tp * 100) if tp else 0
    cr = (co / gateway.total_tx * 100) if gateway.total_tx else 0

    # Critical alert metrics
    cp = sum(n.critical_packets for n in nodes)
    cd = sum(n.critical_delivered for n in nodes)
    cpdr = (cd / cp * 100) if cp else 0
    clat = (sum(n.critical_total_latency for n in nodes) / cd) if cd else 0

    return {
        "pdr": pdr,
        "col_rate": cr,
        "energy": en,
        "latency": lat,
        "dropped": dr,
        "total": tp,
        "succ": sp,
        "critical_pdr": cpdr,
        "critical_latency": clat,
        "critical_total": cp,
        "critical_delivered": cd,
        "nodes": nodes,
    }


# =============================================================================
# Environmental Snapshot Printer
# =============================================================================
def print_env_snapshot(nodes, label, max_show=8):
    print(f"\n  📡 {label} — Environmental Snapshot (showing {min(max_show, len(nodes))} of {len(nodes)} nodes)")
    print(f"  {'Node':>6} | {'Soil%':>6} | {'Temp°C':>7} | {'Hum%':>5} | {'Rain':>6} | {'Flood':>6} | {'Priority':>9} | {'Urgency':>7}")
    print(f"  {'-'*72}")
    for n in nodes[:max_show]:
        if n.last_env_data:
            d = n.last_env_data
            r = n.last_risk
            print(f"  {n.id:6d} | {d.soil_moisture:6.1f} | {d.temperature:7.1f} | {d.humidity:5.1f} | "
                  f"{d.rainfall:6.1f} | {d.flood_risk:6.3f} | {r.priority_label:>9s} | {r.urgency:>7d}")


# =============================================================================
# Main Benchmark
# =============================================================================
if __name__ == "__main__":
    DENSITIES = [10, 25, 50, 100, 250, 500, 1000]
    TIMESLOTS = 40000
    P_TX = 0.005

    artifact_dir = "/Users/prithvidey/.gemini/antigravity-ide/brain/cbe11394-39d5-4947-ba9d-5e98e1e81690"

    aloha_results = []
    agri_results = []

    print("=" * 130)
    print("  AGRISETU FULL-STACK BENCHMARK — Realistic LoRa PHY + Environmental Data + Risk Engine")
    print("  Weather Events: MONSOON injected at t=12000 | FROST_SNAP at t=28000")
    print("=" * 130)

    header = (f"{'Nodes':>5} | {'ALOHA PDR':>9} | {'Agri PDR':>9} | {'Δ PDR':>7} | "
              f"{'ALOHA Col%':>10} | {'Agri Col%':>9} | "
              f"{'ALOHA E':>10} | {'Agri E':>10} | {'E Saved':>8} | "
              f"{'ALOHA Lat':>9} | {'Agri Lat':>8} | "
              f"{'Crit ALOHA':>10} | {'Crit Agri':>9} | {'Crit Lat A':>10} | {'Crit Lat Q':>10}")
    print(header)
    print("-" * 130)

    for N in DENSITIES:
        print(f"\n▶ Running {N} nodes...", end="", flush=True)
        ra = run_benchmark(StandardAlohaEnvNode, N, TIMESLOTS, P_TX)
        rq = run_benchmark(AgriSetuEnvQNode, N, TIMESLOTS, P_TX)
        aloha_results.append(ra)
        agri_results.append(rq)

        gain = rq['pdr'] - ra['pdr']
        saved = ((ra['energy'] - rq['energy']) / ra['energy'] * 100) if ra['energy'] else 0

        print(f"\r{N:>5} | {ra['pdr']:>8.2f}% | {rq['pdr']:>8.2f}% | {gain:>+6.2f}% | "
              f"{ra['col_rate']:>9.2f}% | {rq['col_rate']:>8.2f}% | "
              f"{ra['energy']:>10.0f} | {rq['energy']:>10.0f} | {saved:>+7.1f}% | "
              f"{ra['latency']:>9.1f} | {rq['latency']:>8.1f} | "
              f"{ra['critical_pdr']:>9.1f}% | {rq['critical_pdr']:>8.1f}% | "
              f"{ra['critical_latency']:>10.1f} | {rq['critical_latency']:>10.1f}")

        # Show environmental data for this density
        print_env_snapshot(rq['nodes'], f"AgriSetu @ {N} nodes")

    # =========================================================================
    # Plotting
    # =========================================================================
    plt.style.use('seaborn-v0_8-darkgrid')
    fig, axes = plt.subplots(3, 2, figsize=(16, 18))
    fig.suptitle('AgriSetu Full-Stack Benchmark\n(LoRa PHY + Environmental Simulation + Risk Engine)',
                 fontsize=15, fontweight='bold', y=0.98)

    colors_aloha = '#e74c3c'
    colors_agri = '#2ecc71'

    # 1. PDR vs Node Count
    ax = axes[0, 0]
    ax.plot(DENSITIES, [r['pdr'] for r in aloha_results], 'o-', color=colors_aloha, label='Standard ALOHA', linewidth=2, markersize=6)
    ax.plot(DENSITIES, [r['pdr'] for r in agri_results], 's-', color=colors_agri, label='AgriSetu Q-Learning', linewidth=2.5, markersize=7)
    ax.fill_between(DENSITIES, [r['pdr'] for r in agri_results], [r['pdr'] for r in aloha_results], alpha=0.15, color=colors_agri)
    ax.set_title('Packet Delivery Rate (PDR %)', fontweight='bold')
    ax.set_xlabel('Number of Sensor Nodes')
    ax.set_ylabel('PDR (%)')
    ax.set_ylim(0, 105)
    ax.legend(loc='lower left')
    ax.grid(True, alpha=0.3)

    # 2. Collision Rate vs Node Count
    ax = axes[0, 1]
    ax.plot(DENSITIES, [r['col_rate'] for r in aloha_results], 'o-', color=colors_aloha, label='Standard ALOHA', linewidth=2, markersize=6)
    ax.plot(DENSITIES, [r['col_rate'] for r in agri_results], 's-', color=colors_agri, label='AgriSetu Q-Learning', linewidth=2.5, markersize=7)
    ax.fill_between(DENSITIES, [r['col_rate'] for r in aloha_results], [r['col_rate'] for r in agri_results], alpha=0.15, color=colors_aloha)
    ax.set_title('Collision Rate (%)', fontweight='bold')
    ax.set_xlabel('Number of Sensor Nodes')
    ax.set_ylabel('Collision Rate (%) — Lower is Better')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)

    # 3. Energy vs Node Count
    ax = axes[1, 0]
    ax.plot(DENSITIES, [r['energy']/1e6 for r in aloha_results], 'o-', color=colors_aloha, label='Standard ALOHA', linewidth=2, markersize=6)
    ax.plot(DENSITIES, [r['energy']/1e6 for r in agri_results], 's-', color='#3498db', label='AgriSetu Q-Learning', linewidth=2.5, markersize=7)
    ax.set_title('Total Energy Consumption', fontweight='bold')
    ax.set_xlabel('Number of Sensor Nodes')
    ax.set_ylabel('Energy (Million Units) — Lower is Better')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 4. Latency vs Node Count
    ax = axes[1, 1]
    ax.plot(DENSITIES, [r['latency'] for r in aloha_results], 'o-', color=colors_aloha, label='Standard ALOHA', linewidth=2, markersize=6)
    ax.plot(DENSITIES, [r['latency'] for r in agri_results], 's-', color='#9b59b6', label='AgriSetu Q-Learning', linewidth=2.5, markersize=7)
    ax.set_title('Average Latency (timeslots)', fontweight='bold')
    ax.set_xlabel('Number of Sensor Nodes')
    ax.set_ylabel('Latency — Lower is Better')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 5. Critical Alert PDR
    ax = axes[2, 0]
    ax.plot(DENSITIES, [r['critical_pdr'] for r in aloha_results], 'o-', color=colors_aloha, label='Standard ALOHA', linewidth=2, markersize=6)
    ax.plot(DENSITIES, [r['critical_pdr'] for r in agri_results], 's-', color='#e67e22', label='AgriSetu Q-Learning', linewidth=2.5, markersize=7)
    ax.fill_between(DENSITIES, [r['critical_pdr'] for r in agri_results], [r['critical_pdr'] for r in aloha_results], alpha=0.15, color='#e67e22')
    ax.set_title('🚨 Critical Alert Delivery Rate (%)', fontweight='bold')
    ax.set_xlabel('Number of Sensor Nodes')
    ax.set_ylabel('Critical PDR (%)')
    ax.set_ylim(0, 105)
    ax.legend(loc='lower left')
    ax.grid(True, alpha=0.3)

    # 6. Critical Alert Latency
    ax = axes[2, 1]
    ax.plot(DENSITIES, [r['critical_latency'] for r in aloha_results], 'o-', color=colors_aloha, label='Standard ALOHA', linewidth=2, markersize=6)
    ax.plot(DENSITIES, [r['critical_latency'] for r in agri_results], 's-', color='#e67e22', label='AgriSetu Q-Learning', linewidth=2.5, markersize=7)
    ax.set_title('🚨 Critical Alert Latency (timeslots)', fontweight='bold')
    ax.set_xlabel('Number of Sensor Nodes')
    ax.set_ylabel('Latency — Lower is Better')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    chart_path = os.path.join(artifact_dir, 'fullstack_benchmark.png')
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\n📊 Full-stack benchmark chart saved to: {chart_path}")

    # =========================================================================
    # Environmental Conditions Summary Plot
    # =========================================================================
    fig2, axes2 = plt.subplots(2, 2, figsize=(14, 10))
    fig2.suptitle('Environmental Conditions Across Network\n(Snapshot of Last Reading per Node — 1000 Node Run)',
                  fontsize=13, fontweight='bold')

    # Use the 1000-node AgriSetu run
    big_nodes = agri_results[-1]['nodes']
    node_ids = list(range(len(big_nodes)))

    soil_vals = [n.last_env_data.soil_moisture if n.last_env_data else 50 for n in big_nodes]
    temp_vals = [n.last_env_data.temperature if n.last_env_data else 28 for n in big_nodes]
    hum_vals = [n.last_env_data.humidity if n.last_env_data else 65 for n in big_nodes]
    rain_vals = [n.last_env_data.rainfall if n.last_env_data else 0 for n in big_nodes]

    # Soil Moisture
    ax = axes2[0, 0]
    scatter = ax.scatter(node_ids, soil_vals, c=soil_vals, cmap='RdYlGn_r', s=3, alpha=0.7)
    ax.axhline(y=30, color='orange', linestyle='--', alpha=0.7, label='Dry Warning (30%)')
    ax.axhline(y=20, color='red', linestyle='--', alpha=0.7, label='Critical Dry (20%)')
    ax.axhline(y=85, color='blue', linestyle='--', alpha=0.7, label='Saturated (85%)')
    ax.set_title('Soil Moisture per Node', fontweight='bold')
    ax.set_xlabel('Node ID')
    ax.set_ylabel('Soil Moisture (%)')
    ax.legend(fontsize=7, loc='upper right')
    ax.set_ylim(0, 100)
    plt.colorbar(scatter, ax=ax, label='%')

    # Temperature
    ax = axes2[0, 1]
    scatter = ax.scatter(node_ids, temp_vals, c=temp_vals, cmap='coolwarm', s=3, alpha=0.7)
    ax.axhline(y=2, color='blue', linestyle='--', alpha=0.7, label='Frost Alert (2°C)')
    ax.axhline(y=40, color='red', linestyle='--', alpha=0.7, label='Heat Warning (40°C)')
    ax.set_title('Temperature per Node', fontweight='bold')
    ax.set_xlabel('Node ID')
    ax.set_ylabel('Temperature (°C)')
    ax.legend(fontsize=7, loc='upper right')
    plt.colorbar(scatter, ax=ax, label='°C')

    # Humidity
    ax = axes2[1, 0]
    scatter = ax.scatter(node_ids, hum_vals, c=hum_vals, cmap='Blues', s=3, alpha=0.7)
    ax.axhline(y=90, color='red', linestyle='--', alpha=0.7, label='Disease Risk (90%)')
    ax.set_title('Humidity per Node', fontweight='bold')
    ax.set_xlabel('Node ID')
    ax.set_ylabel('Humidity (%)')
    ax.legend(fontsize=7)
    plt.colorbar(scatter, ax=ax, label='%')

    # Rainfall
    ax = axes2[1, 1]
    scatter = ax.scatter(node_ids, rain_vals, c=rain_vals, cmap='YlOrRd', s=3, alpha=0.7)
    ax.axhline(y=15, color='orange', linestyle='--', alpha=0.7, label='Heavy Rain (15 mm/hr)')
    ax.axhline(y=30, color='red', linestyle='--', alpha=0.7, label='Extreme Rain (30 mm/hr)')
    ax.set_title('Rainfall per Node', fontweight='bold')
    ax.set_xlabel('Node ID')
    ax.set_ylabel('Rainfall (mm/hr)')
    ax.legend(fontsize=7)
    plt.colorbar(scatter, ax=ax, label='mm/hr')

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    env_chart_path = os.path.join(artifact_dir, 'environmental_snapshot.png')
    plt.savefig(env_chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"🌿 Environmental snapshot chart saved to: {env_chart_path}")

    # =========================================================================
    # Summary Table
    # =========================================================================
    print("\n" + "=" * 130)
    print("  FINAL SUMMARY TABLE")
    print("=" * 130)
    print(f"{'Nodes':>5} | {'ALOHA PDR':>9} | {'Agri PDR':>9} | {'Gain':>6} | "
          f"{'ALOHA Col':>9} | {'Agri Col':>8} | "
          f"{'Energy Saved':>12} | "
          f"{'Crit PDR(A)':>11} | {'Crit PDR(Q)':>11} | {'Crit Lat(A)':>11} | {'Crit Lat(Q)':>11}")
    print("-" * 130)
    for i, N in enumerate(DENSITIES):
        ra = aloha_results[i]
        rq = agri_results[i]
        gain = rq['pdr'] - ra['pdr']
        saved = ((ra['energy'] - rq['energy']) / ra['energy'] * 100) if ra['energy'] else 0
        print(f"{N:>5} | {ra['pdr']:>8.2f}% | {rq['pdr']:>8.2f}% | {gain:>+5.1f}% | "
              f"{ra['col_rate']:>8.2f}% | {rq['col_rate']:>7.2f}% | "
              f"{saved:>+11.1f}% | "
              f"{ra['critical_pdr']:>10.1f}% | {rq['critical_pdr']:>10.1f}% | "
              f"{ra['critical_latency']:>11.1f} | {rq['critical_latency']:>11.1f}")
    print("=" * 130)
