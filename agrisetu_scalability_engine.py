import random
import numpy as np
import math
import os
import matplotlib.pyplot as plt

# =============================================================================
# AGRISETU 500-1000 NODE HIGH-DENSITY SCALABILITY ENGINE
# Leverages:
# 1. Extended Multi-Window Contention (W up to 512 slots)
# 2. LoRa Spreading Factor (SF7-SF10) Quasi-Orthogonal Demodulation
# 3. Multi-Channel Frequency Allocation (3 standard LoRa channels)
# 4. Q-Learning Channel + Timing + SF Coordination
# =============================================================================

ALPHA_WEIGHT = 1.0
BETA_WEIGHT = 0.3
GAMMA_WEIGHT = 1.5

DELIVERY_SUCCESS = 10
COLLISION_PENALTY = -8
ENERGY_COST_IDLE = 0.05   # Deep sleep during backoff
ENERGY_COST_TX = 50       # LoRa TX pulse
CRITICAL_SUCCESS = 30
DROP_PENALTY = -20

PRIORITY_LEVELS = {"NORMAL": 1, "WARNING": 5, "CRITICAL": 10}
PRIORITY_TO_IDX = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2}

# Actions: (Contention Window Size, SF selection, Channel ID)
# 5 window options x 3 channels = 15 coordinated actions
ACTION_WINDOWS = [4, 16, 64, 256, 512]
NUM_CHANNELS = 3
NUM_SFS = 3 # SF7, SF8, SF9 (orthogonal in LoRa PHY)

# Discrete Action Map: (Window, Channel)
ACTIONS = []
for w in ACTION_WINDOWS:
    for ch in range(NUM_CHANNELS):
        ACTIONS.append((w, ch))
NUM_ACTIONS = len(ACTIONS)

MAX_RETRIES = 6

# =============================================================================
# Standard ALOHA (No SF/Channel intelligence, fixed blind single-channel)
# =============================================================================
class StandardAlohaNode:
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
        self.channel_id = 0
        self.sf = 7

    def step(self, t, p_tx):
        if not self.has_packet:
            if random.random() < p_tx:
                self.has_packet = True
                self.total_packets += 1
                self.gen_time = t
                self.wait_time = 0
                self.current_retries = 0
                # Standard ALOHA transmits randomly or fixed on channel 0, SF7
                self.channel_id = random.randint(0, NUM_CHANNELS - 1)
                self.sf = 7

        if self.has_packet:
            if self.wait_time <= 0:
                self.energy_consumed += ENERGY_COST_TX
                return True, self.channel_id, self.sf
            else:
                self.wait_time -= 1
                self.energy_consumed += ENERGY_COST_IDLE
        return False, None, None

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
                self.wait_time = random.randint(1, 30)

# =============================================================================
# AgriSetu High-Density Q-Learning Node
# =============================================================================
class AgriSetuQNode:
    def __init__(self, id):
        self.id = id

        self.rssi_idx = random.randint(0, 2)
        self.sf_idx = random.randint(0, NUM_SFS - 1)
        self.cr_idx = random.randint(0, 2)
        self.entropy_idx = 0
        self.priority = "NORMAL"

        self.lr = 0.35
        self.gamma = 0.9
        self.epsilon = 0.15
        self.epsilon_decay = 0.9998
        self.epsilon_min = 0.01

        # Q-table: [rssi][sf][cr][entropy][priority][action]
        self.q_table = np.zeros((3, NUM_SFS, 3, 4, 3, NUM_ACTIONS))

        # Warm start Q-table with channel diversity & entropy rules
        for r in range(3):
            for s in range(NUM_SFS):
                for c in range(3):
                    for e in range(4):
                        for p in range(3):
                            for a_idx, (w, ch) in enumerate(ACTIONS):
                                base_score = 5.0
                                # High entropy -> favor larger windows
                                if e >= 2 and w >= 64:
                                    base_score += 8.0
                                elif e < 2 and w <= 64:
                                    base_score += 6.0

                                # Spread across channels
                                if ch == (self.id % NUM_CHANNELS):
                                    base_score += 3.0

                                # Critical alerts get smaller window
                                if p == 2 and w <= 16:
                                    base_score += 15.0

                                self.q_table[r,s,c,e,p,a_idx] = base_score

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
        self.channel_id = 0
        self.sf = 7

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

        if p_c <= 0.4:
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

        w, ch = ACTIONS[self.last_action_idx]
        self.wait_time = random.randint(0, w - 1)
        self.channel_id = ch
        self.sf = 7 + self.sf_idx

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
                return True, self.channel_id, self.sf
            else:
                self.wait_time -= 1
                self.energy_consumed += ENERGY_COST_IDLE
        return False, None, None

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
                # Dynamic SF switching upon persistent collisions
                if self.current_retries >= 2:
                    self.sf_idx = (self.sf_idx + 1) % NUM_SFS

                ns = self.get_state()
                old = self.q_table[self.last_state][self.last_action_idx]
                mf = np.max(self.q_table[ns])
                self.q_table[self.last_state][self.last_action_idx] = (
                    old + self.lr * (reward + self.gamma * mf - old))
                self.last_state = ns
                self._pick_action()

        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

# =============================================================================
# LoRa Multi-Channel Gateway Channel Model
# (Packets only collide if they share BOTH the same Channel ID AND the same SF!)
# =============================================================================
class LoRaGatewayChannel:
    def __init__(self):
        self.total_tx = 0

    def tick(self, nodes, t, p_tx):
        transmissions = {}
        for n in nodes:
            active, ch, sf = n.step(t, p_tx)
            if active:
                key = (ch, sf)
                if key not in transmissions:
                    transmissions[key] = []
                transmissions[key].append(n)
                self.total_tx += 1

        for (ch, sf), tx_nodes in transmissions.items():
            if len(tx_nodes) == 1:
                tx_nodes[0].feedback(True, t)
            else:
                for n in tx_nodes:
                    n.feedback(False, t)

# =============================================================================
# Simulation Runner
# =============================================================================
def run_sim(node_cls, N, T, p_tx):
    nodes = [node_cls(i) for i in range(N)]
    gateway = LoRaGatewayChannel()

    for t in range(T):
        gateway.tick(nodes, t, p_tx)

    tp = sum(n.total_packets for n in nodes)
    sp = sum(n.successful_packets for n in nodes)
    co = sum(n.collisions for n in nodes)
    en = sum(n.energy_consumed for n in nodes)
    dr = sum(n.dropped_packets for n in nodes)
    lat = (sum(n.total_latency for n in nodes) / sp) if sp else 0
    pdr = (sp / tp * 100) if tp else 0
    cr = (co / gateway.total_tx * 100) if gateway.total_tx else 0

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
    densities = [50, 100, 250, 500, 750, 1000]
    TIMESLOTS = 40000

    print("=" * 110)
    print("       AGRISETU HIGH-DENSITY SCALABILITY BENCHMARK (500 - 1000 NODES)")
    print("=" * 110)
    print(f"{'Nodes':>5} | {'ALOHA PDR':>10} | {'AgriSetu PDR':>13} | {'ALOHA Energy':>13} | {'Agri Energy':>12} | {'Energy Saved':>13} | {'ALOHA Lat':>10} | {'Agri Lat':>9}")
    print("-" * 110)

    res_aloha, res_agri = [], []

    for N in densities:
        # Realistic agricultural sensor telemetry interval (~0.002 - 0.005 duty cycle)
        p_tx = 0.003
        ma = run_sim(StandardAlohaNode, N, TIMESLOTS, p_tx)
        mq = run_sim(AgriSetuQNode, N, TIMESLOTS, p_tx)

        res_aloha.append(ma)
        res_agri.append(mq)

        saved = (ma['energy'] - mq['energy']) / ma['energy'] * 100

        print(f"{N:>5} | {ma['pdr']:>9.2f}% | {mq['pdr']:>12.2f}% | {ma['energy']:>13.0f} | {mq['energy']:>12.0f} | {saved:>+12.1f}% | {ma['latency']:>9.1f} | {mq['latency']:>8.1f}")

    # Plot 500-1000 High Density Benchmark
    artifact_dir = "/Users/prithvidey/.gemini/antigravity-ide/brain/cbe11394-39d5-4947-ba9d-5e98e1e81690"
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle('AgriSetu High-Density Scalability: 500 to 1000 Nodes Benchmark', fontsize=14, fontweight='bold')

    # Plot 1: PDR
    axes[0].plot(densities, [r['pdr'] for r in res_aloha], 'o-', color='grey', label='Standard ALOHA', linewidth=2)
    axes[0].plot(densities, [r['pdr'] for r in res_agri], 's-', color='#2ecc71', label='AgriSetu Q-Learning (LoRa-PHY Aware)', linewidth=2.5)
    axes[0].set_title('Packet Delivery Rate (500 - 1000 Nodes)')
    axes[0].set_xlabel('Number of Sensor Nodes')
    axes[0].set_ylabel('PDR (%)')
    axes[0].set_ylim(0, 105)
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # Plot 2: Energy
    axes[1].plot(densities, [r['energy']/1e6 for r in res_aloha], 'o-', color='grey', label='Standard ALOHA', linewidth=2)
    axes[1].plot(densities, [r['energy']/1e6 for r in res_agri], 's-', color='#3498db', label='AgriSetu Q-Learning (LoRa-PHY Aware)', linewidth=2.5)
    axes[1].set_title('Energy Consumption (Million Units)')
    axes[1].set_xlabel('Number of Sensor Nodes')
    axes[1].set_ylabel('Energy (Lower is Better)')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    chart_path = os.path.join(artifact_dir, 'scalability_500_1000_nodes.png')
    plt.savefig(chart_path, dpi=150)
    plt.close()
    print(f"\nScalability chart saved to: {chart_path}")
