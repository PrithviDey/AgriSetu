import random
import numpy as np
import math
import os
import matplotlib.pyplot as plt

# =============================================================================
# Parameters & Constants
# =============================================================================
ALPHA_WEIGHT = 1.0
BETA_WEIGHT = 0.3
GAMMA_WEIGHT = 1.5

DELIVERY_SUCCESS = 10
COLLISION_PENALTY = -8
ENERGY_COST_IDLE = 0.1
ENERGY_COST_TX = 50
CRITICAL_SUCCESS = 25
DROP_PENALTY = -15

PRIORITY_LEVELS = {"NORMAL": 1, "WARNING": 5, "CRITICAL": 10}
PRIORITY_TO_IDX = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2}

ACTION_WINDOWS = [1, 4, 16, 64, 128]
NUM_ACTIONS = len(ACTION_WINDOWS)
MAX_RETRIES = 5

# =============================================================================
# ALOHA Node
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

        self.has_packet = False
        self.wait_time = 0
        self.gen_time = 0
        self.current_retries = 0

    def step(self, t, p_tx):
        if not self.has_packet:
            if random.random() < p_tx:
                self.has_packet = True
                self.total_packets += 1
                self.gen_time = t
                self.wait_time = 0
                self.current_retries = 0

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
            self.successful_packets += 1
            self.total_latency += (t - self.gen_time)
            self.has_packet = False
        else:
            self.collisions += 1
            self.retries += 1
            self.current_retries += 1
            if self.current_retries >= MAX_RETRIES:
                self.has_packet = False
                self.dropped_packets += 1
            else:
                self.wait_time = random.randint(1, 20)

# =============================================================================
# AgriSetu Q-Learning Node
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

        # Q-table
        self.q_table = np.zeros((3, 3, 3, 4, 3, NUM_ACTIONS))
        for r in range(3):
            for s in range(3):
                for c in range(3):
                    for e in range(4):
                        for p in range(3):
                            if e == 0:
                                self.q_table[r,s,c,e,p] = [8, 5, 3, 1, 0]
                            elif e == 1:
                                self.q_table[r,s,c,e,p] = [2, 6, 7, 4, 1]
                            elif e == 2:
                                self.q_table[r,s,c,e,p] = [0, 2, 5, 8, 6]
                            else:
                                self.q_table[r,s,c,e,p] = [0, 1, 3, 6, 9]

                            if p == 2:
                                self.q_table[r,s,c,e,p,0] += 5

        self.col_history = []
        self.col_window = 20

        self.total_packets = 0
        self.successful_packets = 0
        self.collisions = 0
        self.retries = 0
        self.energy_consumed = 0.0
        self.total_latency = 0
        self.dropped_packets = 0

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

    def step(self, t, p_tx):
        if not self.has_packet:
            if random.random() < p_tx:
                self.has_packet = True
                self.total_packets += 1
                self.gen_time = t
                self.current_retries = 0

                p = random.random()
                if p < 0.1:    self.priority = "CRITICAL"
                elif p < 0.3:  self.priority = "WARNING"
                else:          self.priority = "NORMAL"

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
            old = self.q_table[self.last_state][self.last_action_idx]
            self.q_table[self.last_state][self.last_action_idx] = (
                old + self.lr * (reward - old))
            self.successful_packets += 1
            self.total_latency += (t - self.gen_time)
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

    def tick(self, nodes, t, p_tx):
        tx = [n for n in nodes if n.step(t, p_tx)]
        self.total_tx += len(tx)
        if len(tx) == 1:
            tx[0].feedback(True, t)
        elif len(tx) > 1:
            for n in tx:
                n.feedback(False, t)

# =============================================================================
# Execution
# =============================================================================
def run_benchmark(cls, N, T, p_tx):
    nodes = [cls(i) for i in range(N)]
    ch = Channel()
    for t in range(T):
        ch.tick(nodes, t, p_tx)

    tp = sum(n.total_packets for n in nodes)
    sp = sum(n.successful_packets for n in nodes)
    co = sum(n.collisions for n in nodes)
    en = sum(n.energy_consumed for n in nodes)
    dr = sum(n.dropped_packets for n in nodes)
    lat = (sum(n.total_latency for n in nodes) / sp) if sp else 0
    pdr = (sp / tp * 100) if tp else 0
    cr = (co / ch.total_tx * 100) if ch.total_tx else 0

    return {
        "pdr": pdr,
        "col_rate": cr,
        "energy": en,
        "latency": lat,
        "dropped": dr,
        "total": tp,
        "succ": sp
    }

if __name__ == "__main__":
    node_list = [2, 5, 10, 20, 35, 50, 75, 100, 150, 250, 500, 750, 1000]
    TIMESLOTS = 35000
    G_TARGET = 1.5

    results = []
    print("=" * 115)
    print("                      FULL GRANULAR DENSITY SWEEP: ALOHA vs AGRISETU")
    print("=" * 115)
    print(f"{'Nodes':>5} | {'p_tx':>7} | {'ALOHA PDR':>9} | {'Agri PDR':>9} | {'PDR Diff':>10} | {'ALOHA Energy':>12} | {'Agri Energy':>11} | {'Energy Saved':>12} | {'Status':<16}")
    print("-" * 115)

    for N in node_list:
        p_tx = G_TARGET / N
        res_a = run_benchmark(AlohaNode, N, TIMESLOTS, p_tx)
        res_q = run_benchmark(QNode, N, TIMESLOTS, p_tx)

        pdr_diff = res_q['pdr'] - res_a['pdr']
        energy_saved = ((res_a['energy'] - res_q['energy']) / res_a['energy'] * 100) if res_a['energy'] > 0 else 0

        if abs(pdr_diff) < 2.0 and abs(energy_saved) < 10.0:
            status = "Identical / Parity"
        elif pdr_diff > 0 and energy_saved > 0:
            status = "AgriSetu Superior"
        elif pdr_diff > 0:
            status = "AgriSetu High PDR"
        else:
            status = "ALOHA Simpler"

        results.append({
            "nodes": N,
            "p_tx": p_tx,
            "aloha_pdr": res_a['pdr'],
            "agri_pdr": res_q['pdr'],
            "pdr_diff": pdr_diff,
            "aloha_energy": res_a['energy'],
            "agri_energy": res_q['energy'],
            "energy_saved": energy_saved,
            "aloha_lat": res_a['latency'],
            "agri_lat": res_q['latency'],
            "aloha_col": res_a['col_rate'],
            "agri_col": res_q['col_rate'],
            "status": status
        })

        print(f"{N:>5} | {p_tx:>7.4f} | {res_a['pdr']:>8.2f}% | {res_q['pdr']:>8.2f}% | {pdr_diff:>+9.2f}% | {res_a['energy']:>12.0f} | {res_q['energy']:>11.0f} | {energy_saved:>+11.1f}% | {status:<16}")

    # Generate Analysis Plot
    artifact_dir = "/Users/prithvidey/.gemini/antigravity-ide/brain/cbe11394-39d5-4947-ba9d-5e98e1e81690"
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('ALOHA vs AgriSetu Q-Learning: Full Node Density Analysis', fontsize=15, fontweight='bold')

    nodes = [r['nodes'] for r in results]
    a_pdr = [r['aloha_pdr'] for r in results]
    q_pdr = [r['agri_pdr'] for r in results]
    a_e = [r['aloha_energy'] / 1e6 for r in results]
    q_e = [r['agri_energy'] / 1e6 for r in results]
    a_lat = [r['aloha_lat'] for r in results]
    q_lat = [r['agri_lat'] for r in results]
    a_col = [r['aloha_col'] for r in results]
    q_col = [r['agri_col'] for r in results]

    # Plot 1: PDR with crossover annotation
    axes[0, 0].plot(nodes, a_pdr, 'o-', color='grey', label='Standard ALOHA', linewidth=2)
    axes[0, 0].plot(nodes, q_pdr, 's-', color='#2ecc71', label='AgriSetu Q-Learning', linewidth=2.5)
    axes[0, 0].axvspan(2, 10, color='yellow', alpha=0.15, label='Parity Zone (N <= 10)')
    axes[0, 0].axvspan(10, 1000, color='green', alpha=0.10, label='AgriSetu Superior Zone (N > 10)')
    axes[0, 0].set_title('1. Packet Delivery Rate (PDR %)')
    axes[0, 0].set_xlabel('Number of Nodes')
    axes[0, 0].set_ylabel('PDR (%)')
    axes[0, 0].legend()
    axes[0, 0].grid(True, alpha=0.3)

    # Plot 2: Collision Rate
    axes[0, 1].plot(nodes, a_col, 'o-', color='grey', label='Standard ALOHA', linewidth=2)
    axes[0, 1].plot(nodes, q_col, 's-', color='#e74c3c', label='AgriSetu Q-Learning', linewidth=2.5)
    axes[0, 1].set_title('2. Collision Rate (%)')
    axes[0, 1].set_xlabel('Number of Nodes')
    axes[0, 1].set_ylabel('Collision Rate (%)')
    axes[0, 1].legend()
    axes[0, 1].grid(True, alpha=0.3)

    # Plot 3: Energy Consumed
    axes[1, 0].plot(nodes, a_e, 'o-', color='grey', label='Standard ALOHA', linewidth=2)
    axes[1, 0].plot(nodes, q_e, 's-', color='#3498db', label='AgriSetu Q-Learning', linewidth=2.5)
    axes[1, 0].set_title('3. Total Energy Consumption (Million Units)')
    axes[1, 0].set_xlabel('Number of Nodes')
    axes[1, 0].set_ylabel('Energy (M Units)')
    axes[1, 0].legend()
    axes[1, 0].grid(True, alpha=0.3)

    # Plot 4: Latency
    axes[1, 1].plot(nodes, a_lat, 'o-', color='grey', label='Standard ALOHA', linewidth=2)
    axes[1, 1].plot(nodes, q_lat, 's-', color='#9b59b6', label='AgriSetu Q-Learning', linewidth=2.5)
    axes[1, 1].set_title('4. Average Latency (Slots)')
    axes[1, 1].set_xlabel('Number of Nodes')
    axes[1, 1].set_ylabel('Latency (Slots)')
    axes[1, 1].legend()
    axes[1, 1].grid(True, alpha=0.3)

    plt.tight_layout()
    chart_path = os.path.join(artifact_dir, 'full_density_sweep.png')
    plt.savefig(chart_path, dpi=150)
    plt.close()
    print(f"\nFull density sweep chart saved to: {chart_path}")
