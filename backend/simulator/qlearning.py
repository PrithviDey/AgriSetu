"""
AgriSetu — Q-Learning Agent
State  : S = [RSSI_bin, SF_bin, CR_bin, Entropy_bin]  → 3×3×3×4 = 108 states
Actions: A0=TX now, A1=wait 1, A2=wait 2, A3=wait 4, A4=wait 8
Reward : R = α·Delivery − β·Energy + γ·Urgency
"""
import numpy as np
import random
from typing import List


WAIT_SLOTS = [0, 1, 2, 4, 8]   # slots to wait for each action


class QLearning:
    N_STATES  = 108   # 3 × 3 × 3 × 4
    N_ACTIONS = 5

    def __init__(
        self,
        alpha:         float = 0.15,   # learning rate
        gamma:         float = 0.90,   # discount factor
        epsilon:       float = 1.00,   # initial exploration
        epsilon_min:   float = 0.05,
        epsilon_decay: float = 0.997,
        w_delivery:    float = 1.0,    # α  — delivery weight
        w_energy:      float = 0.10,   # β  — energy penalty
        w_urgency:     float = 2.0,    # γ  — urgency bonus
    ):
        self.alpha         = alpha
        self.gamma         = gamma
        self.epsilon       = epsilon
        self.epsilon_min   = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.w_delivery    = w_delivery
        self.w_energy      = w_energy
        self.w_urgency     = w_urgency

        self.q_table = np.zeros((self.N_STATES, self.N_ACTIONS), dtype=np.float32)

        # Stats
        self.update_count:  int         = 0
        self.action_counts: List[int]   = [0] * self.N_ACTIONS
        self.reward_history: List[float] = []

    # ── State ─────────────────────────────────────────────────────
    @staticmethod
    def state_index(rssi_bin: int, sf_bin: int, cr_bin: int, entropy_bin: int) -> int:
        return rssi_bin * 36 + sf_bin * 12 + cr_bin * 4 + entropy_bin

    # ── Action selection ──────────────────────────────────────────
    def select_action(self, state_idx: int) -> int:
        if random.random() < self.epsilon:
            return random.randrange(self.N_ACTIONS)
        return int(np.argmax(self.q_table[state_idx]))

    # ── Reward ────────────────────────────────────────────────────
    def compute_reward(self, success: bool, energy: float, priority: str) -> float:
        urgency_map = {"normal": 0, "warning": 1, "critical": 2}
        u = urgency_map.get(priority, 0)

        if success:
            delivery_r = 10.0 + 10.0 * u         # +20 for critical success
        else:
            delivery_r = -8.0 - 4.0 * u          # harsher penalty for critical loss

        energy_r  = -self.w_energy * energy * 10.0
        urgency_r = self.w_urgency * u if success else 0.0

        return self.w_delivery * delivery_r + energy_r + urgency_r

    # ── Q-table update ────────────────────────────────────────────
    def update(
        self,
        state: int,
        action: int,
        reward: float,
        next_state: int,
    ):
        best_next = float(np.max(self.q_table[next_state]))
        td_target = reward + self.gamma * best_next
        td_error  = td_target - float(self.q_table[state, action])
        self.q_table[state, action] += self.alpha * td_error

        self.update_count += 1
        self.action_counts[action] += 1
        self.reward_history.append(reward)

        # Decay exploration
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

        # Bound history
        if len(self.reward_history) > 2000:
            self.reward_history = self.reward_history[-1000:]

    # ── Stats helpers ─────────────────────────────────────────────
    def avg_reward(self, window: int = 100) -> float:
        if not self.reward_history:
            return 0.0
        return round(float(np.mean(self.reward_history[-window:])), 2)

    def to_dict(self) -> dict:
        return {
            "alpha":          self.alpha,
            "gamma":          self.gamma,
            "epsilon":        round(self.epsilon, 4),
            "w_delivery":     self.w_delivery,
            "w_energy":       self.w_energy,
            "w_urgency":      self.w_urgency,
            "update_count":   self.update_count,
            "avg_reward":     self.avg_reward(),
            "action_counts":  self.action_counts,
            "reward_history": [round(r, 2) for r in self.reward_history[-200:]],
            "q_table":        self.q_table.tolist(),
        }

    def update_params(self, **kwargs):
        """Hot-update hyperparameters from the settings panel."""
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, float(v))
