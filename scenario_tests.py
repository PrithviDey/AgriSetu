import random
import numpy as np
import math
import os
import matplotlib.pyplot as plt

# =============================================================================
# Constants & Hyperparameters
# =============================================================================
ALPHA_WEIGHT = 1.0
BETA_WEIGHT = 0.3
GAMMA_WEIGHT = 1.8

DELIVERY_SUCCESS = 10
COLLISION_PENALTY = -8
ENERGY_COST_IDLE = 0.1   # Sleep/idle during backoff (~10μA)
ENERGY_COST_TX = 50      # Transmitting is expensive (~120mA)
CRITICAL_SUCCESS = 30
DROP_PENALTY = -20

PRIORITY_LEVELS = {"NORMAL": 1, "WARNING": 5, "CRITICAL": 12}
PRIORITY_TO_IDX = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2}
IDX_TO_PRIORITY = {0: "NORMAL", 1: "WARNING", 2: "CRITICAL"}

ACTION_WINDOWS = [1, 4, 16, 64, 128]
NUM_ACTIONS = len(ACTION_WINDOWS)
MAX_RETRIES = 5

# =============================================================================
# ALOHA Node with Priority Tracking
# =============================================================================
class AlohaNode:
    def __init__(self, id):
        self.id = id
        self.total_packets = 0
        self.successful_packets = 0
        self.collisions = 0
        self.retries = 0
        self.energy_consumed = 0.0
        self.total_latency = 0
        self.dropped_packets = 0

        self.stats = {
            "NORMAL": {"gen": 0, "succ": 0, "drop": 0, "latency": 0.0},
            "WARNING": {"gen": 0, "succ": 0, "drop": 0, "latency": 0.0},
            "CRITICAL": {"gen": 0, "succ": 0, "drop": 0, "latency": 0.0}
        }

        self.has_packet = False
        self.priority = "NORMAL"
        self.wait_time = 0
        self.gen_time = 0
        self.current_retries = 0

    def step(self, t, p_tx, priority_dist=None, force_priority=None):
        if not self.has_packet:
            if random.random() < p_tx:
                self.has_packet = True
                self.total_packets += 1
                self.gen_time = t
                self.wait_time = 0
                self.current_retries = 0

                if force_priority:
                    self.priority = force_priority
                elif priority_dist:
                    p = random.random()
                    if p < priority_dist[0]:
                        self.priority = "NORMAL"
                    elif p < priority_dist[0] + priority_dist[1]:
                        self.priority = "WARNING"
                    else:
                        self.priority = "CRITICAL"
                else:
                    self.priority = "NORMAL"

                self.stats[self.priority]["gen"] += 1

        if self.has_packet:
            if self.wait_time <= 0:
                self.energy_consumed += ENERGY_COST_TX
                return True
            else:
                self.wait_time -= 1
                self.energy_consumed += ENERGY_COST_IDLE
        return False

    def feedback(self, success, t):
        if success:
            lat = t - self.gen_time
            self.successful_packets += 1
            self.total_latency += lat
            self.stats[self.priority]["succ"] += 1
            self.stats[self.priority]["latency"] += lat
            self.has_packet = False
        else:
            self.collisions += 1
            self.retries += 1
            self.current_retries += 1
            if self.current_retries >= MAX_RETRIES:
                self.has_packet = False
                self.dropped_packets += 1
                self.stats[self.priority]["drop"] += 1
            else:
                # ALOHA blind backoff regardless of urgency
                self.wait_time = random.randint(1, 20)

# =============================================================================
# AgriSetu Q-Learning Node with Shannon Entropy & Urgency Awareness
# =============================================================================
class QNode:
    def __init__(self, id):
        self.id = id

        self.rssi_idx = random.randint(0, 2)
        self.sf_idx = random.randint(0, 2)
        self.cr_idx = random.randint(0, 2)
        self.entropy_idx = 0
        self.priority = "NORMAL"

        self.lr = 0.3
        self.gamma = 0.9
        self.epsilon = 0.15
        self.epsilon_decay = 0.9998
        self.epsilon_min = 0.01

        # Q-table: [rssi][sf][cr][entropy][priority][action]
        self.q_table = np.zeros((3, 3, 3, 4, 3, NUM_ACTIONS))

        # Warm start Q-table with domain rules
        for r in range(3):
            for s in range(3):
                for c in range(3):
                    for e in range(4):
                        for p in range(3):
                            # Routine traffic: adapt contention window based on entropy
                            if e == 0:
                                self.q_table[r,s,c,e,p] = [8, 5, 3, 1, 0]
                            elif e == 1:
                                self.q_table[r,s,c,e,p] = [2, 6, 7, 4, 1]
                            elif e == 2:
                                self.q_table[r,s,c,e,p] = [0, 2, 5, 8, 6]
                            else:
                                self.q_table[r,s,c,e,p] = [0, 1, 3, 6, 9]

                            # Urgency awareness
                            if p == 2: # CRITICAL (Frost/Flood Alert)
                                self.q_table[r,s,c,e,p] = [20, 14, 6, 0, -10]
                            elif p == 1: # WARNING
                                self.q_table[r,s,c,e,p] += [6, 4, 2, 0, 0]

        self.col_history = []
        self.col_window = 20

        self.total_packets = 0
        self.successful_packets = 0
        self.collisions = 0
        self.retries = 0
        self.energy_consumed = 0.0
        self.total_latency = 0
        self.dropped_packets = 0

        self.stats = {
            "NORMAL": {"gen": 0, "succ": 0, "drop": 0, "latency": 0.0},
            "WARNING": {"gen": 0, "succ": 0, "drop": 0, "latency": 0.0},
            "CRITICAL": {"gen": 0, "succ": 0, "drop": 0, "latency": 0.0}
        }

        self.has_packet = False
        self.wait_time = 0
        self.gen_time = 0
        self.current_retries = 0
        self.last_state = None
        self.last_action_idx = None

    def _update_entropy(self, was_col):
        self.col_history.append(1 if was_col else 0)
        if len(self.col_history) > self.col_window:
            self.col_history.pop(0)
        if len(self.col_history) < 3:
            return

        N = len(self.col_history)
        collisions = sum(self.col_history)
        successes = N - collisions

        p_c = collisions / N
        p_s = successes / N

        # Shannon Entropy: H = -p_s*log2(p_s) - p_c*log2(p_c)
        h_c = -p_c * math.log2(p_c) if p_c > 0 else 0
        h_s = -p_s * math.log2(p_s) if p_s > 0 else 0
        H = h_c + h_s

        if p_c <= 0.5:
            self.entropy_idx = 0 if H < 0.8 else 1
        else:
            self.entropy_idx = 2 if H >= 0.8 else 3

    def get_state(self):
        return (self.rssi_idx, self.sf_idx, self.cr_idx,
                self.entropy_idx, PRIORITY_TO_IDX[self.priority])

    def _pick_action(self):
        if random.random() < self.epsilon:
            self.last_action_idx = random.randint(0, NUM_ACTIONS - 1)
        else:
            self.last_action_idx = np.argmax(self.q_table[self.last_state])
        w = ACTION_WINDOWS[self.last_action_idx]
        self.wait_time = random.randint(0, w - 1)

    def step(self, t, p_tx, priority_dist=None, force_priority=None):
        if not self.has_packet:
            if random.random() < p_tx:
                self.has_packet = True
                self.total_packets += 1
                self.gen_time = t
                self.current_retries = 0

                if force_priority:
                    self.priority = force_priority
                elif priority_dist:
                    p = random.random()
                    if p < priority_dist[0]:
                        self.priority = "NORMAL"
                    elif p < priority_dist[0] + priority_dist[1]:
                        self.priority = "WARNING"
                    else:
                        self.priority = "CRITICAL"
                else:
                    self.priority = "NORMAL"

                self.stats[self.priority]["gen"] += 1
                self.last_state = self.get_state()
                self._pick_action()

        if self.has_packet:
            if self.wait_time <= 0:
                self.energy_consumed += ENERGY_COST_TX
                return True
            else:
                self.wait_time -= 1
                self.energy_consumed += ENERGY_COST_IDLE
        return False

    def feedback(self, success, t):
        self._update_entropy(not success)

        if success:
            d_r = CRITICAL_SUCCESS if self.priority == "CRITICAL" else DELIVERY_SUCCESS
            u_r = PRIORITY_LEVELS[self.priority]
        else:
            d_r = COLLISION_PENALTY
            u_r = -PRIORITY_LEVELS[self.priority]

        e_c = ENERGY_COST_TX + self.wait_time * ENERGY_COST_IDLE
        reward = ALPHA_WEIGHT * d_r - BETA_WEIGHT * e_c + GAMMA_WEIGHT * u_r

        if success:
            lat = t - self.gen_time
            old = self.q_table[self.last_state][self.last_action_idx]
            self.q_table[self.last_state][self.last_action_idx] = (
                old + self.lr * (reward - old))
            self.successful_packets += 1
            self.total_latency += lat
            self.stats[self.priority]["succ"] += 1
            self.stats[self.priority]["latency"] += lat
            self.has_packet = False
        else:
            self.collisions += 1
            self.retries += 1
            self.current_retries += 1

            if self.current_retries >= MAX_RETRIES:
                old = self.q_table[self.last_state][self.last_action_idx]
                self.q_table[self.last_state][self.last_action_idx] = (
                    old + self.lr * (DROP_PENALTY - old))
                self.has_packet = False
                self.dropped_packets += 1
                self.stats[self.priority]["drop"] += 1
            else:
                ns = self.get_state()
                old = self.q_table[self.last_state][self.last_action_idx]
                mf = np.max(self.q_table[ns])
                self.q_table[self.last_state][self.last_action_idx] = (
                    old + self.lr * (reward + self.gamma * mf - old))
                self.last_state = ns
                self._pick_action()

        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

# =============================================================================
# Channel Simulator
# =============================================================================
class Channel:
    def __init__(self):
        self.total_tx = 0

    def tick(self, nodes, t, p_tx, priority_dist=None, force_priority=None):
        tx = [n for n in nodes if n.step(t, p_tx, priority_dist=priority_dist, force_priority=force_priority)]
        self.total_tx += len(tx)
        if len(tx) == 1:
            tx[0].feedback(True, t)
        elif len(tx) > 1:
            for n in tx:
                n.feedback(False, t)

# =============================================================================
# Scenario Evaluator
# =============================================================================
def evaluate_scenario(scenario_name, node_cls, N, T, p_tx, priority_dist=None, force_priority=None):
    nodes = [node_cls(i) for i in range(N)]
    ch = Channel()

    for t in range(T):
        ch.tick(nodes, t, p_tx, priority_dist=priority_dist, force_priority=force_priority)

    tp = sum(n.total_packets for n in nodes)
    sp = sum(n.successful_packets for n in nodes)
    co = sum(n.collisions for n in nodes)
    en = sum(n.energy_consumed for n in nodes)
    dr = sum(n.dropped_packets for n in nodes)
    lat = (sum(n.total_latency for n in nodes) / sp) if sp else 0
    pdr = (sp / tp * 100) if tp else 0
    cr = (co / ch.total_tx * 100) if ch.total_tx else 0

    # Aggregate priority stats
    priority_results = {}
    for prio in ["NORMAL", "WARNING", "CRITICAL"]:
        gen = sum(n.stats[prio]["gen"] for n in nodes)
        succ = sum(n.stats[prio]["succ"] for n in nodes)
        drop = sum(n.stats[prio]["drop"] for n in nodes)
        p_lat = (sum(n.stats[prio]["latency"] for n in nodes) / succ) if succ > 0 else 0
        p_pdr = (succ / gen * 100) if gen > 0 else 0
        priority_results[prio] = {
            "gen": gen,
            "succ": succ,
            "drop": drop,
            "pdr": p_pdr,
            "latency": p_lat
        }

    return {
        "scenario": scenario_name,
        "nodes": N,
        "pdr": pdr,
        "col_rate": cr,
        "energy": en,
        "latency": lat,
        "total_packets": tp,
        "successful_packets": sp,
        "collisions": co,
        "dropped": dr,
        "priority_stats": priority_results
    }

# =============================================================================
# Main Runner for Phase 10 Scenarios
# =============================================================================
if __name__ == "__main__":
    print("=" * 80)
    print("           AGRISETU PHASE 10: URGENCY-AWARE SCENARIO EVALUATION")
    print("=" * 80)

    TIMESLOTS = 40000
    artifact_dir = "/Users/prithvidey/.gemini/antigravity-ide/brain/cbe11394-39d5-4947-ba9d-5e98e1e81690"

    # -------------------------------------------------------------------------
    # Scenario A: Normal Traffic (100 Nodes, Routine Telemetry)
    # -------------------------------------------------------------------------
    print("\n[Scenario A] Normal Traffic (100 Nodes - Routine Moisture/Temperature Data)")
    print("Aim: Optimize Energy + Delivery under standard operating load.")
    res_a_aloha = evaluate_scenario("Scenario A", AlohaNode, N=100, T=TIMESLOTS, p_tx=0.015, force_priority="NORMAL")
    res_a_agri = evaluate_scenario("Scenario A", QNode, N=100, T=TIMESLOTS, p_tx=0.015, force_priority="NORMAL")

    print(f"  ALOHA    -> PDR: {res_a_aloha['pdr']:5.2f}% | Col%: {res_a_aloha['col_rate']:5.2f}% | Energy: {res_a_aloha['energy']:10.0f} | Lat: {res_a_aloha['latency']:5.1f}")
    print(f"  AgriSetu -> PDR: {res_a_agri['pdr']:5.2f}% | Col%: {res_a_agri['col_rate']:5.2f}% | Energy: {res_a_agri['energy']:10.0f} | Lat: {res_a_agri['latency']:5.1f}")

    # -------------------------------------------------------------------------
    # Scenario B: Heavy Congestion (500 Nodes - High Collision Storm)
    # -------------------------------------------------------------------------
    print("\n[Scenario B] Congestion Storm (500 Nodes - High Channel Entropy/Collisions)")
    print("Aim: Agent dynamically shifts to wider contention windows to avoid channel collapse.")
    res_b_aloha = evaluate_scenario("Scenario B", AlohaNode, N=500, T=TIMESLOTS, p_tx=0.003, force_priority="NORMAL")
    res_b_agri = evaluate_scenario("Scenario B", QNode, N=500, T=TIMESLOTS, p_tx=0.003, force_priority="NORMAL")

    print(f"  ALOHA    -> PDR: {res_b_aloha['pdr']:5.2f}% | Col%: {res_b_aloha['col_rate']:5.2f}% | Energy: {res_b_aloha['energy']:10.0f} | Lat: {res_b_aloha['latency']:5.1f}")
    print(f"  AgriSetu -> PDR: {res_b_agri['pdr']:5.2f}% | Col%: {res_b_agri['col_rate']:5.2f}% | Energy: {res_b_agri['energy']:10.0f} | Lat: {res_b_agri['latency']:5.1f}")

    # -------------------------------------------------------------------------
    # Scenario C: Critical Alert Injection (Frost/Flood Alert in Congested Network)
    # -------------------------------------------------------------------------
    print("\n[Scenario C] Critical Alert Injection (FROST ALERT & FLOOD ALERT in Congested Network)")
    print("Distribution: 80% Routine Telemetry (NORMAL), 15% WARNING, 5% CRITICAL Alerts")
    print("Aim: Verify that urgent alerts are not drowned in network noise.")
    res_c_aloha = evaluate_scenario("Scenario C", AlohaNode, N=100, T=TIMESLOTS, p_tx=0.015, priority_dist=[0.80, 0.15, 0.05])
    res_c_agri = evaluate_scenario("Scenario C", QNode, N=100, T=TIMESLOTS, p_tx=0.015, priority_dist=[0.80, 0.15, 0.05])

    print("\n  Scenario C Breakdown by Traffic Urgency:")
    print("  " + "-" * 75)
    print(f"  {'Protocol':<10} | {'Priority':<10} | {'Generated':<10} | {'Delivered':<10} | {'PDR (%)':<10} | {'Avg Latency':<10}")
    print("  " + "-" * 75)
    for p in ["NORMAL", "WARNING", "CRITICAL"]:
        sa = res_c_aloha['priority_stats'][p]
        sq = res_c_agri['priority_stats'][p]
        print(f"  {'ALOHA':<10} | {p:<10} | {sa['gen']:<10} | {sa['succ']:<10} | {sa['pdr']:<10.2f} | {sa['latency']:<10.1f}")
        print(f"  {'AgriSetu':<10} | {p:<10} | {sq['gen']:<10} | {sq['succ']:<10} | {sq['pdr']:<10.2f} | {sq['latency']:<10.1f}")
        print("  " + "-" * 75)

    # -------------------------------------------------------------------------
    # Generate Visualizations for Phase 10
    # -------------------------------------------------------------------------
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    fig.suptitle('Phase 10: Urgency-Aware Behavior & Scenario Benchmarks', fontsize=15, fontweight='bold')

    # Plot 1: Scenario A & B Overall PDR
    scenarios = ['Scenario A\n(100 Nodes Normal)', 'Scenario B\n(500 Nodes Congested)']
    aloha_pdrs = [res_a_aloha['pdr'], res_b_aloha['pdr']]
    agri_pdrs = [res_a_agri['pdr'], res_b_agri['pdr']]

    x = np.arange(len(scenarios))
    width = 0.35
    axes[0].bar(x - width/2, aloha_pdrs, width, label='Standard ALOHA', color='grey', alpha=0.8)
    axes[0].bar(x + width/2, agri_pdrs, width, label='AgriSetu Q-Learning', color='#2ecc71', alpha=0.9)
    axes[0].set_ylabel('Packet Delivery Rate (%)')
    axes[0].set_title('Scenario A & B: Delivery Rate (PDR)')
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(scenarios)
    axes[0].legend()
    axes[0].grid(axis='y', linestyle='--', alpha=0.4)

    # Plot 2: Scenario A & B Energy Comparison
    aloha_energy = [res_a_aloha['energy'] / 1e6, res_b_aloha['energy'] / 1e6]
    agri_energy = [res_a_agri['energy'] / 1e6, res_b_agri['energy'] / 1e6]

    axes[1].bar(x - width/2, aloha_energy, width, label='Standard ALOHA', color='grey', alpha=0.8)
    axes[1].bar(x + width/2, agri_energy, width, label='AgriSetu Q-Learning', color='#3498db', alpha=0.9)
    axes[1].set_ylabel('Energy Consumed (Million Units)')
    axes[1].set_title('Energy Efficiency (Lower is Better)')
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(scenarios)
    axes[1].legend()
    axes[1].grid(axis='y', linestyle='--', alpha=0.4)

    # Plot 3: Scenario C Critical Packet PDR by Priority
    priorities = ['NORMAL\n(Moisture)', 'WARNING\n(Alert)', 'CRITICAL\n(Frost/Flood)']
    aloha_c_pdr = [res_c_aloha['priority_stats'][p]['pdr'] for p in ["NORMAL", "WARNING", "CRITICAL"]]
    agri_c_pdr = [res_c_agri['priority_stats'][p]['pdr'] for p in ["NORMAL", "WARNING", "CRITICAL"]]

    xp = np.arange(len(priorities))
    axes[2].bar(xp - width/2, aloha_c_pdr, width, label='Standard ALOHA', color='grey', alpha=0.8)
    axes[2].bar(xp + width/2, agri_c_pdr, width, label='AgriSetu Q-Learning', color='#e74c3c', alpha=0.9)
    axes[2].set_ylabel('Delivery Rate (%)')
    axes[2].set_title('Scenario C: PDR by Alert Urgency')
    axes[2].set_xticks(xp)
    axes[2].set_xticklabels(priorities)
    axes[2].legend()
    axes[2].grid(axis='y', linestyle='--', alpha=0.4)

    plt.tight_layout()
    chart_path = os.path.join(artifact_dir, 'scenario_benchmarks.png')
    plt.savefig(chart_path, dpi=150)
    plt.close()
    print(f"\nScenario benchmark chart saved to: {chart_path}")
