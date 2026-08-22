import random
import os
import matplotlib.pyplot as plt

class Node:
    def __init__(self, id, battery=100.0, rssi=-70, sf=7, cr=1, priority="NORMAL"):
        self.id = id
        self.battery = battery
        self.rssi = rssi
        self.sf = sf
        self.cr = cr
        self.priority = priority
        
        self.total_packets_generated = 0
        self.successful_packets = 0
        self.collisions = 0
        self.retries = 0
        self.energy_consumed = 0.0
        self.total_latency = 0 
        
        self.has_packet = False
        self.wait_time = 0 
        self.packet_generation_time = 0

    def step(self, current_time, probability=0.01):
        if not self.has_packet:
            if random.random() < probability:
                self.has_packet = True
                self.total_packets_generated += 1
                self.packet_generation_time = current_time
                self.wait_time = 0
                
        if self.has_packet:
            if self.wait_time == 0:
                self.energy_consumed += 0.1 
                return True
            else:
                self.wait_time -= 1
                self.energy_consumed += 0.01 
        return False
        
    def feedback(self, success, current_time):
        if success:
            self.successful_packets += 1
            self.total_latency += (current_time - self.packet_generation_time)
            self.has_packet = False
        else:
            self.collisions += 1
            self.retries += 1
            self.wait_time = random.randint(1, 20) 

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

def run_aloha_simulation(num_nodes, timeslots=10000, p_tx=0.01):
    nodes = [Node(id=i) for i in range(num_nodes)]
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
        "energy_consumed": energy_consumed,
        "latency": avg_latency
    }

if __name__ == "__main__":
    node_densities = [10, 25, 50, 100, 250, 500, 1000]
    
    pdr_list = []
    col_rate_list = []
    energy_list = []
    latency_list = []
    
    print("Running simulations to generate graphs...")
    for N in node_densities:
        duty_cycle_tx = 0.05 / (N / 50) if N > 50 else 0.05
        metrics = run_aloha_simulation(num_nodes=N, timeslots=10000, p_tx=duty_cycle_tx)
        
        pdr_list.append(metrics['pdr'])
        col_rate_list.append(metrics['collision_rate'])
        energy_list.append(metrics['energy_consumed'])
        latency_list.append(metrics['latency'])
        
    artifact_dir = "/Users/prithvidey/.gemini/antigravity-ide/brain/cbe11394-39d5-4947-ba9d-5e98e1e81690"
    
    # 1. PDR
    plt.figure(figsize=(8,5))
    plt.plot(node_densities, pdr_list, marker='o', color='green', linewidth=2)
    plt.title('Nodes vs Packet Delivery Rate')
    plt.xlabel('Number of Nodes')
    plt.ylabel('PDR (%)')
    plt.grid(True)
    plt.savefig(os.path.join(artifact_dir, 'pdr_graph.png'))
    plt.close()
    
    # 2. Collision Rate
    plt.figure(figsize=(8,5))
    plt.plot(node_densities, col_rate_list, marker='o', color='red', linewidth=2)
    plt.title('Nodes vs Collision Rate')
    plt.xlabel('Number of Nodes')
    plt.ylabel('Collision Rate (%)')
    plt.grid(True)
    plt.savefig(os.path.join(artifact_dir, 'col_rate_graph.png'))
    plt.close()
    
    # 3. Energy
    plt.figure(figsize=(8,5))
    plt.plot(node_densities, energy_list, marker='o', color='orange', linewidth=2)
    plt.title('Nodes vs Energy Consumption')
    plt.xlabel('Number of Nodes')
    plt.ylabel('Total Energy Consumed')
    plt.grid(True)
    plt.savefig(os.path.join(artifact_dir, 'energy_graph.png'))
    plt.close()
    
    # 4. Latency
    plt.figure(figsize=(8,5))
    plt.plot(node_densities, latency_list, marker='o', color='purple', linewidth=2)
    plt.title('Nodes vs Average Latency')
    plt.xlabel('Number of Nodes')
    plt.ylabel('Latency (timeslots)')
    plt.grid(True)
    plt.savefig(os.path.join(artifact_dir, 'latency_graph.png'))
    plt.close()
    
    print("Graphs successfully generated and saved.")
