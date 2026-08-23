"""
AgriSetu — Simulation Environment
Orchestrates nodes, channel, ALOHA baseline and AgriSetu Q-Learning side by side.
Produces a complete JSON state snapshot every tick.
"""
import random
import time
from collections import deque
from typing import Any, Dict, List

from .node    import Node
from .packet  import Packet, Priority
from .channel import Channel
from .qlearning import QLearning, WAIT_SLOTS


# ─── Alert store ──────────────────────────────────────────────────────────────
_ALERT_ID = 0

def _alert(node_id: int, kind: str, severity: str, msg: str) -> dict:
    global _ALERT_ID
    _ALERT_ID += 1
    return {
        "id":       _ALERT_ID,
        "time":     time.strftime("%H:%M:%S"),
        "node_id":  node_id,
        "type":     kind,
        "severity": severity,
        "message":  msg,
    }


# ─── Benchmark data (pre-computed theoretical curve) ──────────────────────────
_BENCHMARK_DENSITIES = [10, 25, 50, 100, 250, 500, 1000]

def _aloha_pdr(n: int) -> float:
    """Approximate Slotted-ALOHA PDR for n nodes, p=1/n."""
    p = 1.0 / max(1, n)
    return round(n * p * (1 - p) ** (n - 1) * 100, 1)

def _agrisetu_pdr(n: int) -> float:
    """Simulated AgriSetu improvement (learned backoff)."""
    base = _aloha_pdr(n)
    gain = 15 * (1 - base / 100)   # bigger gain at high density
    return round(min(99.0, base + gain), 1)


# ─── Environment ──────────────────────────────────────────────────────────────
class Environment:
    MAX_ALERTS = 50
    MAX_LOGS   = 200

    def __init__(self, n_nodes: int = 20):
        self.n_nodes = n_nodes
        self.nodes: List[Node] = [Node(i + 1, n_nodes) for i in range(n_nodes)]

        # Two channels: one for ALOHA, one for AgriSetu
        self.ch_aloha   = Channel(noise_level=0.05)
        self.ch_rl      = Channel(noise_level=0.05)

        self.agent = QLearning()

        # Sliding metrics (last 50 ticks)
        self._pdr_window: deque  = deque(maxlen=50)
        self._cr_window:  deque  = deque(maxlen=50)
        self._energy_window: deque = deque(maxlen=50)
        self._latency_window: deque = deque(maxlen=50)
        self._aloha_pdr_window: deque = deque(maxlen=50)

        self.alerts: deque  = deque(maxlen=self.MAX_ALERTS)
        self.logs:   deque  = deque(maxlen=self.MAX_LOGS)

        self.tick_count = 0
        self.start_time = time.time()
        self.critical_alert_count = 0

        # Pre-computed benchmark
        self.benchmark = {
            "densities":    _BENCHMARK_DENSITIES,
            "aloha_pdr":    [_aloha_pdr(n)     for n in _BENCHMARK_DENSITIES],
            "agrisetu_pdr": [_agrisetu_pdr(n)  for n in _BENCHMARK_DENSITIES],
        }

    # ── Single simulation tick ────────────────────────────────────
    def tick(self):
        self.tick_count += 1

        online_nodes = [n for n in self.nodes if n.online]
        if not online_nodes:
            return

        # Decide which nodes generate a packet this tick (70% probability)
        generating = [n for n in online_nodes if random.random() < 0.70]

        aloha_pkts: List[Packet] = []
        rl_pkts:    List[Packet] = []
        wait_map:   Dict[int, int] = {}   # node_id → slots to wait

        for node in generating:
            # Assign priority (mostly normal, occasional warning/critical)
            r = random.random()
            if r < 0.03:
                priority = Priority.CRITICAL
            elif r < 0.12:
                priority = Priority.WARNING
            else:
                priority = Priority.NORMAL

            energy = node.battery_drain_per_tx * (1 + 0.2 * (node.sf - 7) / 5)

            # ── ALOHA packet ────────────────────────────────────
            ap = Packet(node_id=node.node_id, priority=priority, energy=energy)
            ap.action  = 0   # always TX immediately
            aloha_pkts.append(ap)

            # ── AgriSetu packet (Q-Learning) ────────────────────
            state_idx = QLearning.state_index(
                node.rssi_bin(),
                node.sf_bin(),
                node.cr_bin(),
                self.ch_rl.entropy_bin(),
            )
            action = self.agent.select_action(state_idx)
            wait   = WAIT_SLOTS[action]
            wait_map[node.node_id] = wait

            rp = Packet(node_id=node.node_id, priority=priority, energy=energy)
            rp.action = action
            rl_pkts.append(rp)

        # ── Resolve channels ─────────────────────────────────────
        # ALOHA: everyone transmits immediately → many collisions at high density
        aloha_results = self.ch_aloha.resolve(aloha_pkts)

        # AgriSetu: group by wait slot, resolve each group separately
        groups: Dict[int, List[Packet]] = {}
        for pkt in rl_pkts:
            w = wait_map[pkt.node_id]
            groups.setdefault(w, []).append(pkt)

        rl_results = []
        for slot_pkts in groups.values():
            rl_results.extend(self.ch_rl.resolve(slot_pkts))

        # ── Update stats & Q-table ────────────────────────────────
        tick_aloha_success = 0
        tick_aloha_total   = 0
        for pkt, ok in aloha_results:
            pkt.latency = (wait_map.get(pkt.node_id, 0) * 0.1 +
                           random.uniform(0.05, 0.3))
            tick_aloha_total   += 1
            tick_aloha_success += int(ok)

        tick_rl_success = 0
        tick_rl_total   = 0
        for pkt, ok in rl_results:
            node = next((n for n in self.nodes if n.node_id == pkt.node_id), None)
            if not node:
                continue

            pkt.latency = wait_map.get(pkt.node_id, 0) * 100 + random.uniform(10, 80)

            node.packets_sent      += 1
            node.packets_success   += int(ok)
            node.packets_collision += int(pkt.collided)
            node.drain_battery(pkt.energy)
            node.total_energy      += pkt.energy
            node.last_tx_time       = time.time()
            if ok:
                node.latency_sum += pkt.latency

            tick_rl_total   += 1
            tick_rl_success += int(ok)

            # Q-table update
            state_idx = QLearning.state_index(
                node.rssi_bin(), node.sf_bin(), node.cr_bin(),
                self.ch_rl.entropy_bin(),
            )
            reward = self.agent.compute_reward(ok, pkt.energy, pkt.priority.value)
            next_state = QLearning.state_index(
                node.rssi_bin(), node.sf_bin(), node.cr_bin(),
                self.ch_rl.entropy_bin(),
            )
            self.agent.update(state_idx, pkt.action, reward, next_state)

            # Alerts
            if not ok and pkt.priority == Priority.CRITICAL:
                self.critical_alert_count += 1
                self.alerts.appendleft(
                    _alert(pkt.node_id, "Critical Packet", "critical",
                           f"Critical packet lost — collision")
                )
            elif not ok and pkt.priority == Priority.WARNING:
                self.alerts.appendleft(
                    _alert(pkt.node_id, "Congestion", "high",
                           "Channel congestion detected")
                )
            if node.battery < 20 and ok:
                self.alerts.appendleft(
                    _alert(pkt.node_id, "Battery Low", "medium",
                           f"Battery level {node.battery:.0f}%")
                )

            # Log
            self.logs.appendleft(pkt.to_dict())

        # Fluctuate node radio params
        for node in self.nodes:
            node.fluctuate()

        # Update sliding windows
        if tick_rl_total:
            pdr  = tick_rl_success / tick_rl_total * 100
            cr   = self.ch_rl.collision_rate()
            self._pdr_window.append(pdr)
            self._cr_window.append(cr)
            avg_e = sum(n.battery_drain_per_tx for n in online_nodes) / len(online_nodes) * 10
            self._energy_window.append(avg_e)
        if tick_aloha_total:
            self._aloha_pdr_window.append(tick_aloha_success / tick_aloha_total * 100)

    # ── State snapshot for WebSocket ─────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        # ── Hardware heartbeat timeout: mark nodes offline if no data for 5s ──
        now = time.time()
        for node in self.nodes:
            if node.online and node.last_tx_time and (now - node.last_tx_time) > 5.0:
                node.online = False
                self.alerts.appendleft(
                    _alert(node.node_id, "Node Timeout", "high",
                           f"Node {node.node_id} went offline (no data for 5s)")
                )
                # Update n_nodes to reflect the real count
                self.n_nodes = len([n for n in self.nodes if n.online])

        online = [n for n in self.nodes if n.online]
        uptime_s = int(time.time() - self.start_time)

        def _avg(q) -> float:
            return round(sum(q) / max(1, len(q)), 1) if q else 0.0

        pdr             = _avg(self._pdr_window)
        aloha_pdr       = _avg(self._aloha_pdr_window)
        collision_rate  = _avg(self._cr_window)
        avg_energy      = _avg(self._energy_window)
        aloha_cr        = round(100 - aloha_pdr, 1)
        channel_entropy = self.ch_rl.entropy()
        entropy_bin     = self.ch_rl.entropy_bin()
        entropy_labels  = ["Low", "Medium", "High", "VeryHigh"]

        # Sample node for channel display (fallback if no nodes)
        if self.nodes:
            sample = self.nodes[0]
            rssi = sample.rssi_raw
            rssi_lbl = ["Good", "Medium", "Poor"][sample.rssi_bin()]
            sf = sample.sf
            sf_lbl = ["Low", "Medium", "High"][sample.sf_bin()]
            cr = sample.cr
            cr_lbl = ["Low", "Medium", "High"][sample.cr_bin()]
        else:
            rssi, rssi_lbl = -100.0, "Poor"
            sf, sf_lbl = 12, "High"
            cr, cr_lbl = 0.0, "Low"

        return {
            "tick": self.tick_count,
            "gateway": {
                "online": True,
                "uptime": uptime_s,
                "uptime_str": f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m {uptime_s % 60}s",
            },
            "metrics": {
                "active_nodes":    len(online),
                "total_nodes":     self.n_nodes,
                "pdr":             pdr,
                "pdr_aloha":       aloha_pdr,
                "collision_rate":  collision_rate,
                "collision_aloha": aloha_cr,
                "avg_energy":      avg_energy,
                "critical_alerts": self.critical_alert_count,
                "pdr_delta":       round(pdr - aloha_pdr, 1),
                "cr_delta":        round(aloha_cr - collision_rate, 1),
            },
            "channel": {
                "rssi":         round(rssi, 1),
                "rssi_label":   rssi_lbl,
                "sf":           sf,
                "sf_label":     sf_lbl,
                "cr":           round(cr, 2),
                "cr_label":     cr_lbl,
                "entropy":      round(channel_entropy, 3),
                "entropy_label":entropy_labels[entropy_bin],
            },
            "nodes":     [n.to_dict() for n in self.nodes],
            "alerts":    list(self.alerts)[:20],
            "logs":      list(self.logs)[:50],
            "rl":        self.agent.to_dict(),
            "benchmark": self.benchmark,
        }

    def update_node_count(self, n: int):
        """Hot-resize the node pool."""
        self.n_nodes = n
        if n > len(self.nodes):
            for i in range(len(self.nodes), n):
                self.nodes.append(Node(i + 1, n))
        else:
            self.nodes = self.nodes[:n]

    # ── Hardware injection methods ────────────────────────────────
    def inject_node_data(self, frame: dict):
        """
        Update a node's radio state from a real ESP32 telemetry frame.
        Frame: {"t":"nd","id":<int>,"rssi":<float>,"sf":<int>,"cr":<float>,"bat":<float>}
        If node_id doesn't exist yet, it is auto-created.
        """
        nid = frame.get("id")
        if nid is None:
            return

        node = next((n for n in self.nodes if n.node_id == nid), None)
        if node is None:
            # Auto-register a new hardware node
            node = Node(nid, max(nid, self.n_nodes))
            self.nodes.append(node)
            self.n_nodes = len(self.nodes)
            self.alerts.appendleft(
                _alert(nid, "Hardware Node", "low",
                       f"ESP32 Node {nid} connected via serial")
            )

        node.rssi_raw = float(frame.get("rssi", node.rssi_raw))
        node.sf       = int(frame.get("sf",    node.sf))
        node.cr       = float(frame.get("cr",   node.cr))
        node.battery  = float(frame.get("bat",  node.battery))
        
        # Parse environmental data if present
        node.soil     = float(frame.get("soil", node.soil))
        node.temp     = float(frame.get("temp", node.temp))
        node.hum      = float(frame.get("hum",  node.hum))
        node.rain     = float(frame.get("rain", node.rain))
        node.noise_level = int(frame.get("noise", node.noise_level))
        
        node.online   = True
        node.last_tx_time = time.time()

    def inject_tx_result(self, frame: dict):
        """
        Record a real transmission result from ESP32 and update the Q-table.
        Frame: {"t":"tx","id":<int>,"ok":<0|1>,"pri":<str>,
                "e":<float>,"lat":<float>,"act":<0-4>}
        """
        nid     = int(frame.get("id",  0))
        success = bool(frame.get("ok", 0))
        pri     = frame.get("pri", "normal")
        energy  = float(frame.get("e",   0.05))
        latency = float(frame.get("lat", 100.0))
        action  = int(frame.get("act",  0))

        node = next((n for n in self.nodes if n.node_id == nid), None)
        if node is None:
            return

        # Update node stats
        node.packets_sent      += 1
        node.packets_success   += int(success)
        node.packets_collision += int(not success)
        node.total_energy      += energy
        if success:
            node.latency_sum += latency
        node.drain_battery(energy)

        # Feed real result into Q-Learning (same pipeline as simulation)
        self.ch_rl.record_result(success)
        state_idx = QLearning.state_index(
            node.rssi_bin(), node.sf_bin(), node.cr_bin(),
            self.ch_rl.entropy_bin(),
        )
        reward = self.agent.compute_reward(success, energy, pri)
        self.agent.update(state_idx, action, reward, state_idx)

        # Update sliding metric windows
        self._pdr_window.append(100.0 if success else 0.0)
        self._cr_window.append(0.0 if success else 100.0)
        self._energy_window.append(energy * 10)
        if success:
            self._latency_window.append(latency)

        # Alerts for critical failures
        if not success and pri == "critical":
            self.critical_alert_count += 1
            self.alerts.appendleft(
                _alert(nid, "Critical Packet", "critical",
                       f"Critical packet lost on real hardware (Node {nid})")
            )

        # Log the hardware packet
        from .packet import Packet, Priority
        hw_pkt = Packet(
            node_id=nid,
            priority=Priority(pri) if pri in ("normal", "warning", "critical") else Priority.NORMAL,
            energy=energy,
            action=action,
        )
        hw_pkt.success  = success
        hw_pkt.collided = not success
        hw_pkt.latency  = latency
        self.logs.appendleft(hw_pkt.to_dict())

    def reset(self):
        """Full reset — new nodes, new Q-table."""
        self.__init__(self.n_nodes)
