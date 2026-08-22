import numpy as np
import random
import matplotlib.pyplot as plt
import os

# --- Configuration & Hyperparameters ---
NUM_NODES = 100           # High density
SIMULATION_STEPS = 10000  # Number of time steps (e.g., ms)
Q_ALPHA = 0.1             # Learning rate
Q_GAMMA = 0.9             # Discount factor
EPSILON = 0.2             # Exploration rate

# State space sizes: RSSI (3) x SF (3) x CR (3) x Entropy (4)
STATE_DIMS = (3, 3, 3, 4)

# Action space: Wait times before transmitting (in ms/slots)
ACTIONS = [0, 10, 50, 100] 
NUM_ACTIONS = len(ACTIONS)

# Weights for reward: R = alpha*Delivery - beta*Energy + gamma*Urgency
W_DELIVERY = 100
W_COLLISION = -50
W_ENERGY_IDLE = -0.1
W_ENERGY_TX = -10
W_URGENCY_BONUS = 50

class Node:
    def __init__(self, node_id, use_q_learning=False):
        self.id = node_id
        self.use_q_learning = use_q_learning
        # Initialize Q-table with zeros: (3, 3, 3, 4, 4)
        self.q_table = np.zeros(STATE_DIMS + (NUM_ACTIONS,))
        
        # State variables
        self.rssi = random.randint(0, 2)
        self.sf = random.randint(0, 2)
        self.cr = random.randint(0, 2)
        self.entropy = 0 # Updates based on recent collisions
        
        # Metrics
        self.packets_sent = 0
        self.packets_delivered = 0
        self.energy_consumed = 0
        
        # Current action state
        self.wait_timer = 0
        self.is_waiting = False
        self.has_data = False
        self.urgency = False
        self.last_state = None
        self.last_action_idx = None
        
    def generate_packet(self):
        if not self.has_data and random.random() < 0.05: # 5% chance to generate data per step
            self.has_data = True
            self.urgency = random.random() < 0.1 # 10% chance of high urgency (frost/flood)
            
            # Update state entropy based on channel conditions (simplified)
            self.entropy = random.randint(0, 3) 
            self.last_state = (self.rssi, self.sf, self.cr, self.entropy)
            
            if self.use_q_learning:
                # Epsilon-greedy action selection
                if random.random() < EPSILON:
                    self.last_action_idx = random.randint(0, NUM_ACTIONS - 1)
                else:
                    self.last_action_idx = np.argmax(self.q_table[self.last_state])
                self.wait_timer = ACTIONS[self.last_action_idx]
            else:
                # Standard ALOHA: Transmit immediately (wait = 0)
                # Or random backoff if implemented. ALOHA is immediate.
                self.wait_timer = 0 
            self.is_waiting = True

    def step(self):
        self.generate_packet()
        
        if self.is_waiting:
            if self.wait_timer > 0:
                self.wait_timer -= 1
                self.energy_consumed -= W_ENERGY_IDLE # Consume idle energy
                return False # Not transmitting yet
            else:
                # Time to transmit
                self.is_waiting = False
                self.packets_sent += 1
                self.energy_consumed -= W_ENERGY_TX
                return True # Transmitting this slot
        return False
        
    def receive_feedback(self, success):
        if not self.has_data:
            return
            
        reward = 0
        if success:
            self.packets_delivered += 1
            reward += W_DELIVERY
            if self.urgency:
                reward += W_URGENCY_BONUS
        else:
            reward += W_COLLISION
            
        # Q-Learning update
        if self.use_q_learning and self.last_state is not None:
            # POMDP assumption: Next state isn't immediately known until next packet, 
            # so we simplify the TD update (terminal state reached)
            old_q = self.q_table[self.last_state][self.last_action_idx]
            self.q_table[self.last_state][self.last_action_idx] = old_q + Q_ALPHA * (reward - old_q)
            
        self.has_data = False # Ready for next packet

class Channel:
    def __init__(self, nodes):
        self.nodes = nodes
        self.total_collisions = 0
        
    def run_step(self):
        transmitting_nodes = []
        for node in self.nodes:
            if node.step():
                transmitting_nodes.append(node)
                
        # Resolve channel access
        if len(transmitting_nodes) == 1:
            # Success
            transmitting_nodes[0].receive_feedback(success=True)
        elif len(transmitting_nodes) > 1:
            # Collision
            self.total_collisions += 1
            for node in transmitting_nodes:
                node.receive_feedback(success=False)

def run_simulation(use_q_learning):
    nodes = [Node(i, use_q_learning=use_q_learning) for i in range(NUM_NODES)]
    channel = Channel(nodes)
    
    for _ in range(SIMULATION_STEPS):
        channel.run_step()
        
    total_sent = sum(n.packets_sent for n in nodes)
    total_delivered = sum(n.packets_delivered for n in nodes)
    total_energy = -sum(n.energy_consumed for n in nodes) # Convert back to positive magnitude
    
    delivery_rate = (total_delivered / total_sent) * 100 if total_sent > 0 else 0
    return {
        'delivery_rate': delivery_rate,
        'collisions': channel.total_collisions,
        'energy': total_energy
    }

if __name__ == "__main__":
    print("Running Standard ALOHA baseline...")
    aloha_metrics = run_simulation(use_q_learning=False)
    
    print("Running AgriSetu Q-Learning...")
    agrisetu_metrics = run_simulation(use_q_learning=True)
    
    print("\n--- Results ---")
    print(f"ALOHA: Delivery Rate: {aloha_metrics['delivery_rate']:.2f}%, Collisions: {aloha_metrics['collisions']}, Energy Used: {aloha_metrics['energy']:.2f}")
    print(f"AgriSetu: Delivery Rate: {agrisetu_metrics['delivery_rate']:.2f}%, Collisions: {agrisetu_metrics['collisions']}, Energy Used: {agrisetu_metrics['energy']:.2f}")
    
    # Save plot
    labels = ['Standard ALOHA', 'AgriSetu']
    delivery_rates = [aloha_metrics['delivery_rate'], agrisetu_metrics['delivery_rate']]
    
    plt.figure(figsize=(8, 5))
    plt.bar(labels, delivery_rates, color=['grey', 'green'])
    plt.title('Packet Delivery Rate (%) Under High Node Density')
    plt.ylabel('Delivery Rate (%)')
    plt.ylim(0, 100)
    
    os.makedirs('plots', exist_ok=True)
    plt.savefig('plots/delivery_rate_comparison.png')
    print("Plot saved to plots/delivery_rate_comparison.png")
