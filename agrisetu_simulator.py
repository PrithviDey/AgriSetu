import random
import numpy as np

# Reward Weights
ALPHA_WEIGHT = 1.0 
BETA_WEIGHT = 1.0
GAMMA_WEIGHT = 1.0

# Base constants
DELIVERY_SUCCESS = 10
COLLISION = -8
ENERGY_COST_IDLE = 1
ENERGY_COST_TX = 5
CRITICAL_SUCCESS = 20

PRIORITY_LEVELS = {
    "NORMAL": 1,
    "WARNING": 5,
    "CRITICAL": 10
}
PRIORITY_TO_IDX = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2}

# Action Space: wait times in slots
ACTIONS = [0, 1, 2, 4, 8]
NUM_ACTIONS = len(ACTIONS)

class QNode:
    def __init__(self, id, battery=100.0, rssi=-70, sf=7, cr=1):
        self.id = id
        self.battery = battery
        
        # State vector variables
        self.rssi_idx = random.randint(0, 2)
        self.sf_idx = random.randint(0, 2)
        self.cr_idx = random.randint(0, 2)
        self.entropy_idx = 0 
        self.priority = "NORMAL"
        
        # Hyperparameters
        self.alpha = 0.1
        self.gamma = 0.9
        self.epsilon = 1.0
        self.epsilon_decay = 0.999 
        self.epsilon_min = 0.05
        
        # Q-table: Q[rssi][sf][cr][entropy][priority][action]
        # Adding priority to state so the agent learns to not wait for CRITICAL packets
        self.q_table = np.zeros((3, 3, 3, 4, 3, NUM_ACTIONS))
        
        self.total_packets_generated = 0
        self.successful_packets = 0
        self.collisions = 0
        self.retries = 0
        self.energy_consumed = 0.0
        self.total_latency = 0 
        
        self.has_packet = False
        self.wait_time = 0 
        self.packet_generation_time = 0
        
        self.last_state = None
        self.last_action_idx = None

    def get_state(self):
        return (self.rssi_idx, self.sf_idx, self.cr_idx, self.entropy_idx, PRIORITY_TO_IDX[self.priority])

    def step(self, current_time, probability=0.01):
        if not self.has_packet:
            if random.random() < probability:
                self.has_packet = True
                self.total_packets_generated += 1
                self.packet_generation_time = current_time
                
                # Assign random priority to incoming packet
                p_rand = random.random()
                if p_rand < 0.1:
                    self.priority = "CRITICAL" # 10% chance frost/flood
                elif p_rand < 0.3:
                    self.priority = "WARNING"  # 20% chance warning
                else:
                    self.priority = "NORMAL"   # 70% normal telemetry
                
                self.last_state = self.get_state()
                
                if random.random() < self.epsilon:
                    self.last_action_idx = random.randint(0, NUM_ACTIONS - 1)
                else:
                    self.last_action_idx = np.argmax(self.q_table[self.last_state])
                    
                self.wait_time = ACTIONS[self.last_action_idx]
                
        if self.has_packet:
            if self.wait_time == 0:
                self.energy_consumed += ENERGY_COST_TX 
                return True
            else:
                self.wait_time -= 1
                self.energy_consumed += ENERGY_COST_IDLE 
        return False
        
    def feedback(self, success, current_time):
        # Calculate Phase 7 Reward
        if success:
            self.successful_packets += 1
            self.total_latency += (current_time - self.packet_generation_time)
            self.has_packet = False
            self.entropy_idx = max(0, self.entropy_idx - 1)
            
            delivery_reward = CRITICAL_SUCCESS if self.priority == "CRITICAL" else DELIVERY_SUCCESS
            # Urgency reward is positive on success
            urgency_reward = PRIORITY_LEVELS[self.priority]
        else:
            self.collisions += 1
            self.retries += 1
            self.entropy_idx = min(3, self.entropy_idx + 1)
            
            delivery_reward = COLLISION
            # Penalty for critical packet collision is steep
            urgency_reward = -PRIORITY_LEVELS[self.priority]
            
        # Energy cost based on action taken (wait time + tx)
        energy_cost = ENERGY_COST_TX + (ACTIONS[self.last_action_idx] * ENERGY_COST_IDLE)
        
        # Exact mathematical model from proposal
        reward = (ALPHA_WEIGHT * delivery_reward) - (BETA_WEIGHT * energy_cost) + (GAMMA_WEIGHT * urgency_reward)

        if success:
             old_q = self.q_table[self.last_state][self.last_action_idx]
             new_q = old_q + self.alpha * (reward - old_q)
             self.q_table[self.last_state][self.last_action_idx] = new_q
        else:
            new_state = self.get_state()
            if random.random() < self.epsilon:
                new_action_idx = random.randint(0, NUM_ACTIONS - 1)
            else:
                new_action_idx = np.argmax(self.q_table[new_state])
            
            old_q = self.q_table[self.last_state][self.last_action_idx]
            max_future_q = np.max(self.q_table[new_state])
            
            new_q = old_q + self.alpha * (reward + self.gamma * max_future_q - old_q)
            self.q_table[self.last_state][self.last_action_idx] = new_q
            
            self.last_state = new_state
            self.last_action_idx = new_action_idx
            self.wait_time = ACTIONS[self.last_action_idx]
            
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

class Channel:
    def __init__(self):
        self.total_transmissions = 0
        
    def process_timeslot(self, nodes, current_time, p_tx=0.01):
        transmitting_nodes = []
        for node in nodes:
            if node.step(current_time, probability=p_tx):
                transmitting_nodes.append(node)
                
        self.total_transmissions += len(transmitting_nodes)

        if len(transmitting_nodes) == 1:
            transmitting_nodes[0].feedback(success=True, current_time=current_time)
        elif len(transmitting_nodes) > 1:
            for node in transmitting_nodes:
                node.feedback(success=False, current_time=current_time)

def run_agrisetu_simulation(num_nodes, timeslots=50000, p_tx=0.01):
    nodes = [QNode(id=i) for i in range(num_nodes)]
    channel = Channel()
    
    for t in range(timeslots):
        channel.process_timeslot(nodes, current_time=t, p_tx=p_tx)
        
    total_packets = sum(n.total_packets_generated for n in nodes)
    successful_packets = sum(n.successful_packets for n in nodes)
    collisions = sum(n.collisions for n in nodes)
    retries = sum(n.retries for n in nodes)
    energy_consumed = sum(n.energy_consumed for n in nodes)
    
    avg_latency = (sum(n.total_latency for n in nodes) / successful_packets) if successful_packets > 0 else 0
    pdr = (successful_packets / total_packets) if total_packets > 0 else 0
    collision_rate = (collisions / channel.total_transmissions) if channel.total_transmissions > 0 else 0
    
    return {
        "pdr": pdr * 100,
        "collision_rate": collision_rate * 100,
        "total_packets": total_packets,
        "successful_packets": successful_packets,
        "collisions": collisions,
        "retries": retries,
        "energy_consumed": energy_consumed,
        "latency": avg_latency
    }

if __name__ == "__main__":
    node_densities = [10, 25, 50, 100, 250]
    
    print(f"{'Nodes':<6} | {'PDR (%)':<8} | {'Col Rate (%)':<12} | {'Pkts':<6} | {'Succ':<6} | {'Col':<6} | {'Retry':<6} | {'Energy':<8} | {'Lat (slots)'}")
    print("-" * 95)
    
    for N in node_densities:
        duty_cycle_tx = 0.05 / (N / 50) if N > 50 else 0.05
        # Give more time to converge for Q-learning
        metrics = run_agrisetu_simulation(num_nodes=N, timeslots=50000, p_tx=duty_cycle_tx)
        print(f"{N:<6} | {metrics['pdr']:<8.2f} | {metrics['collision_rate']:<12.2f} | {metrics['total_packets']:<6} | {metrics['successful_packets']:<6} | {metrics['collisions']:<6} | {metrics['retries']:<6} | {metrics['energy_consumed']:<8.2f} | {metrics['latency']:.2f}")
