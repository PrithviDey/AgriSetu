import random
import numpy as np
import math

# =============================================================================
# VERIFICATION SUITE: Why ALOHA PDR Changes with Physical Channel Parameters
# =============================================================================

def simulate_aloha_theory(num_nodes, num_channels, p_tx, enable_capture=False, timeslots=20000):
    """
    Runs an isolated, mathematically transparent ALOHA simulation.
    """
    total_generated = 0
    successful = 0
    collisions = 0
    
    # Track node state
    node_packets = [False] * num_nodes
    node_wait = [0] * num_nodes
    node_retries = [0] * num_nodes
    node_rssi = [-40 - 32 * math.log10(max(10, random.uniform(50, 1000))) for _ in range(num_nodes)]
    
    for t in range(timeslots):
        # 1. Packet Generation
        for i in range(num_nodes):
            if not node_packets[i]:
                if random.random() < p_tx:
                    node_packets[i] = True
                    node_wait[i] = 0
                    node_retries[i] = 0
                    total_generated += 1
                    
        # 2. Transmission Step
        channel_transmissions = {ch: [] for ch in range(num_channels)}
        for i in range(num_nodes):
            if node_packets[i]:
                if node_wait[i] <= 0:
                    chosen_ch = random.randint(0, num_channels - 1)
                    channel_transmissions[chosen_ch].append(i)
                else:
                    node_wait[i] -= 1
                    
        # 3. Channel Resolution
        for ch, tx_nodes in channel_transmissions.items():
            if len(tx_nodes) == 1:
                # Clean single transmission -> SUCCESS
                node_id = tx_nodes[0]
                successful += 1
                node_packets[node_id] = False
            elif len(tx_nodes) > 1:
                collisions += len(tx_nodes)
                
                # Check Capture Effect
                if enable_capture:
                    tx_nodes.sort(key=lambda idx: node_rssi[idx], reverse=True)
                    strongest = tx_nodes[0]
                    runner_up = tx_nodes[1]
                    if (node_rssi[strongest] - node_rssi[runner_up]) >= 6.0:
                        # Strongest survives!
                        successful += 1
                        node_packets[strongest] = False
                        tx_nodes = tx_nodes[1:]
                
                # Failed nodes backoff
                for node_id in tx_nodes:
                    node_retries[node_id] += 1
                    if node_retries[node_id] >= 3:
                        node_packets[node_id] = False # Dropped
                    else:
                        node_wait[node_id] = random.randint(10, 40)
                        
    pdr = (successful / total_generated * 100) if total_generated > 0 else 0
    return {
        "generated": total_generated,
        "successful": successful,
        "collisions": collisions,
        "pdr": pdr
    }

if __name__ == "__main__":
    print("=" * 95)
    print("      MATHEMATICAL & EMPIRICAL VERIFICATION: WHY ALOHA PDR VARIED AT 100 NODES")
    print("=" * 95)

    # Test Case 1: Early Benchmark (Single Channel, Higher Traffic, No Capture)
    # Offered Load per channel G = 100 * 0.015 / 1 = 1.5 packets/slot (Severely Overloaded)
    g1 = 100 * 0.015 / 1
    p_theory_1 = math.exp(-g1) * 100
    res1 = simulate_aloha_theory(num_nodes=100, num_channels=1, p_tx=0.015, enable_capture=False)

    print("\n[CONFIGURATION 1: Early Benchmark - Single Channel, High Traffic]")
    print(f"  • Channels: 1 Channel (868.1 MHz)")
    print(f"  • Traffic Rate (p_tx): 0.015 (High duty cycle)")
    print(f"  • Capture Effect: Disabled (All overlapping packets collide & die)")
    print(f"  • Offered Load (G): {g1:.2f} packets/slot (Capacity limit is 1.0)")
    print(f"  • Theoretical First-Attempt Success e^(-G): {p_theory_1:.2f}%")
    print(f"  • Empirical Simulation Result -> Generated: {res1['generated']} | Delivered: {res1['successful']} | PDR: {res1['pdr']:.2f}%\n")

    # Test Case 2: Realistic LoRa Benchmark (3 Channels, 1% Duty Cycle, Capture Effect)
    # Offered Load per channel G = (100/3) * 0.005 = 0.167 packets/slot (Sparse Channel)
    g2 = (100 / 3) * 0.005
    p_theory_2 = math.exp(-g2) * 100
    res2 = simulate_aloha_theory(num_nodes=100, num_channels=3, p_tx=0.005, enable_capture=True)

    print("[CONFIGURATION 2: Realistic LoRa Benchmark - 3 Channels, 1% Duty Cycle, Capture Effect]")
    print(f"  • Channels: 3 Sub-Band Channels (868.1, 868.3, 868.5 MHz)")
    print(f"  • Traffic Rate (p_tx): 0.005 (~1% realistic LoRa sensor duty cycle)")
    print(f"  • Capture Effect: Enabled (6 dB SIR threshold allows stronger signal to survive)")
    print(f"  • Offered Load per Channel (G): {g2:.3f} packets/slot (Light load per sub-band)")
    print(f"  • Theoretical First-Attempt Success e^(-G): {p_theory_2:.2f}% (Boosted to >99% via Retries + Capture)")
    print(f"  • Empirical Simulation Result -> Generated: {res2['generated']} | Delivered: {res2['successful']} | PDR: {res2['pdr']:.2f}%\n")

    # Test Case 3: Realistic LoRa Benchmark at 1000 Nodes (Where Config 2 Collapses)
    g3 = (1000 / 3) * 0.005
    res3 = simulate_aloha_theory(num_nodes=1000, num_channels=3, p_tx=0.005, enable_capture=True)
    print("[CONFIGURATION 2 AT 1000 NODES: Heavy Load Across 3 Channels]")
    print(f"  • Nodes: 1,000 Nodes across 3 Channels")
    print(f"  • Offered Load per Channel (G): {g3:.3f} packets/slot (Channel collapse occurs!)")
    print(f"  • Empirical Simulation Result -> Generated: {res3['generated']} | Delivered: {res3['successful']} | PDR: {res3['pdr']:.2f}%")
    print("=" * 95)
