import random
import numpy as np
import os
import matplotlib.pyplot as plt

# =============================================================================
# Constants
# =============================================================================
ALPHA_WEIGHT = 1.0
BETA_WEIGHT = 0.3
GAMMA_WEIGHT = 1.5

DELIVERY_SUCCESS = 10
COLLISION_PENALTY = -8
ENERGY_COST_IDLE = 0.1   # Sleep/idle during backoff (~10μA, negligible)
ENERGY_COST_TX = 50      # Transmitting is expensive (~120mA for ~100ms)
CRITICAL_SUCCESS = 20
DROP_PENALTY = -15

PRIORITY_LEVELS = {"NORMAL": 1, "WARNING": 5, "CRITICAL": 10}
PRIORITY_TO_IDX = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2}

# Actions = contention window sizes. Node picks random slot within window.
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
        self.epsilon = 0.2
        self.epsilon_decay = 0.9997
        self.epsilon_min = 0.01

        # Q-table: [rssi][sf][cr][entropy][priority][action]
        self.q_table = np.zeros((3, 3, 3, 4, 3, NUM_ACTIONS))

        # Warm-start: bias Q-values based on entropy level
        for r in range(3):
            for s in range(3):
                for c in range(3):
                    for e in range(4):
                        for p in range(3):
                            # Higher entropy → prefer larger windows
                            if e == 0:
                                self.q_table[r,s,c,e,p] = [8, 5, 3, 1, 0]
                            elif e == 1:
                                self.q_table[r,s,c,e,p] = [2, 6, 7, 4, 1]
                            elif e == 2:
                                self.q_table[r,s,c,e,p] = [0, 2, 5, 8, 6]
                            else:
                                self.q_table[r,s,c,e,p] = [0, 1, 3, 6, 9]
                            # CRITICAL: boost immediate tx
                            if p == 2:
                                self.q_table[r,s,c,e,p,0] += 5

        self.col_history = []
        self.col_window = 15

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
            
        import math
        N = len(self.col_history)
        collisions = sum(self.col_history)
        successes = N - collisions
        
        p_c = collisions / N
        p_s = successes / N
        
        # Calculate Shannon Entropy: H = -p_s*log2(p_s) - p_c*log2(p_c)
        h_c = -p_c * math.log2(p_c) if p_c > 0 else 0
        h_s = -p_s * math.log2(p_s) if p_s > 0 else 0
        H = h_c + h_s
        
        # Discretize into 4 states keeping collision directionality
        # H is 0..1. High entropy (H>=0.8) means channel is chaotic.
        # Low entropy means channel is stable (either mostly succeeding or mostly colliding).
        if p_c <= 0.5:
            # Mostly succeeding
            self.entropy_idx = 0 if H < 0.8 else 1
        else:
            # Mostly colliding
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
# Channel
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
# Runner
# =============================================================================
def run(cls, N, T, p_tx):
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
    return {"pdr": pdr, "col": cr, "energy": en, "lat": lat,
            "drop": dr, "total": tp, "succ": sp}

# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    densities = [10, 25, 50, 100, 250, 500, 1000]
    T = 50000  # More time for convergence

    # Offered load G = N * p_tx ≈ 1.5 (congested but solvable)
    # This is realistic: 1000 sensors each transmitting 0.15% of the time
    G_TARGET = 1.5

    ra, rq = {}, {}

    hdr = (f"{'N':>5} | {'p_tx':>8} | {'ALOHA':>9} | {'AgriSetu':>9} | "
           f"{'A Col%':>7} | {'Q Col%':>7} | "
           f"{'A Energy':>10} | {'Q Energy':>10} | "
           f"{'A Lat':>7} | {'Q Lat':>7}")
    print(hdr)
    print("-" * len(hdr))

    for N in densities:
        p_tx = G_TARGET / N
        a = run(AlohaNode, N, T, p_tx)
        q = run(QNode, N, T, p_tx)
        ra[N] = a
        rq[N] = q
        print(f"{N:>5} | {p_tx:>8.5f} | {a['pdr']:>8.2f}% | {q['pdr']:>8.2f}% | "
              f"{a['col']:>6.1f}% | {q['col']:>6.1f}% | "
              f"{a['energy']:>10.0f} | {q['energy']:>10.0f} | "
              f"{a['lat']:>7.1f} | {q['lat']:>7.1f}")

    # ---- Graphs ----
    art = "/Users/prithvidey/.gemini/antigravity-ide/brain/cbe11394-39d5-4947-ba9d-5e98e1e81690"

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('ALOHA vs AgriSetu Q-Learning  (G=1.5 offered load)',
                 fontsize=15, fontweight='bold')

    metrics = [
        ('pdr',    'Packet Delivery Rate (%)', 'PDR (%)'),
        ('col',    'Collision Rate (%)',        'Collision Rate (%)'),
        ('energy', 'Energy Consumption',        'Energy'),
        ('lat',    'Average Latency',           'Latency (slots)')
    ]

    for ax, (key, title, ylabel) in zip(axes.flat, metrics):
        ya = [ra[n][key] for n in densities]
        yq = [rq[n][key] for n in densities]
        ax.plot(densities, ya, 'o-', color='grey', label='ALOHA', lw=2)
        ax.plot(densities, yq, 's-', color='green', label='AgriSetu', lw=2)
        ax.set_title(title)
        ax.set_xlabel('Nodes')
        ax.set_ylabel(ylabel)
        ax.legend()
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(art, 'benchmark_comparison.png'), dpi=150)
    plt.close()
    print("\nGraph saved.")
