import time
import threading
import random
import sys
import serial
import json

# Import the existing Python Q-Learning node from Phase 10
from realistic_lora_benchmark import AgriSetuRealQNode, RealLoRaGateway

# =============================================================================
# HYBRID PROTOTYPE BRIDGE (HARDWARE IN THE LOOP)
# Connects 4 Physical ESP32 Nodes (via ESP-NOW Serial) + 96 Simulated Python Nodes
# =============================================================================

# Configuration
NUM_VIRTUAL_NODES = 96
SERIAL_PORT = '/dev/ttyUSB0'  # Adjust to COM3 for Windows, or /dev/tty.SLAB_USBtoUART for Mac
BAUD_RATE = 115200

# Shared state
hardware_packets_received = 0
hardware_alerts_received = 0
hardware_nodes = set()

# =============================================================================
# 1. Hardware Serial Listener Thread
# Reads packets from the physical ESP32 Gateway via USB
# =============================================================================
def hardware_listener(port, baud):
    global hardware_packets_received, hardware_alerts_received, hardware_nodes
    try:
        ser = serial.Serial(port, baud, timeout=1)
        print(f"[HARDWARE] Connected to physical ESP32 Gateway on {port}")
        
        while True:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8').strip()
                
                # Expected format from esp32_gateway.ino:
                # "Received from Node: 1 | Priority: 2 | Payload: 3546"
                if "Received from Node" in line:
                    hardware_packets_received += 1
                    
                    try:
                        # Simple parsing
                        parts = line.split("|")
                        node_id_str = parts[0].split(":")[1].strip()
                        priority_str = parts[1].split(":")[1].strip()
                        
                        node_id = int(node_id_str)
                        priority = int(priority_str)
                        
                        hardware_nodes.add(node_id)
                        
                        if priority == 2:
                            hardware_alerts_received += 1
                            print(f"🚨 [HARDWARE ALERT] Physical Node {node_id} reported CRITICAL FLOOD/FROST!")
                        else:
                            print(f"✅ [HARDWARE DATA] Routine packet from physical Node {node_id}")
                            
                    except Exception as e:
                        print(f"[HARDWARE] Failed to parse: {line}")
    except serial.SerialException as e:
        print(f"[HARDWARE ERROR] Could not connect to {port}. (Is the ESP32 plugged in?)")
        print("Continuing with virtual simulation only...\n")

# =============================================================================
# 2. Hybrid Simulation Runner
# Runs the 96 virtual nodes while running the hardware listener in parallel
# =============================================================================
def run_hybrid_network():
    print("=" * 80)
    print(f"  AGRISETU HYBRID NETWORK PROTOTYPE (4 Physical + {NUM_VIRTUAL_NODES} Virtual Nodes)")
    print("=" * 80)
    
    # 1. Start Hardware Listener Thread
    hw_thread = threading.Thread(target=hardware_listener, args=(SERIAL_PORT, BAUD_RATE))
    hw_thread.daemon = True
    hw_thread.start()
    
    # 2. Initialize Virtual Nodes
    print(f"[VIRTUAL] Spawning {NUM_VIRTUAL_NODES} virtual Q-learning nodes in background...")
    virtual_nodes = [AgriSetuRealQNode(i+10) for i in range(NUM_VIRTUAL_NODES)]
    gateway = RealLoRaGateway()
    
    TIMESLOTS = 5000  # Run for ~10 seconds
    P_TX = 0.005
    
    print("\n[HYBRID] Network active. Turning analog potentiometers on physical ESP32s...")
    print("[HYBRID] Simulation running for 10 seconds. Press Ctrl+C to stop.\n")
    
    start_time = time.time()
    
    try:
        # We step the virtual simulation 500 times per second to mimic fast time
        for t in range(TIMESLOTS):
            gateway.tick(virtual_nodes, t, P_TX)
            time.sleep(0.002) # Yield time for real-world hardware packets to arrive
            
    except KeyboardInterrupt:
        print("\n[HYBRID] Interrupted by user.")
        
    end_time = time.time()
    
    # 3. Aggregate Virtual Metrics
    v_total = sum(n.total_packets for n in virtual_nodes)
    v_succ = sum(n.successful_packets for n in virtual_nodes)
    v_pdr = (v_succ / v_total * 100) if v_total > 0 else 0
    
    print("=" * 80)
    print("                     HYBRID PROTOTYPE RESULTS SUMMARY")
    print("=" * 80)
    print(f"Execution Time     : {end_time - start_time:.2f} seconds")
    print(f"Total Network Nodes: {len(hardware_nodes)} Physical + {NUM_VIRTUAL_NODES} Virtual")
    print("-" * 80)
    print("[PHYSICAL HARDWARE STATS (ESP-NOW)]")
    print(f"  Physical Packets Received : {hardware_packets_received}")
    print(f"  Critical Alerts Handled   : {hardware_alerts_received}")
    print(f"  Unique ESP32 MACs active  : {len(hardware_nodes)}")
    print("-" * 80)
    print("[VIRTUAL BACKGROUND STATS (Python)]")
    print(f"  Virtual Packets Generated : {v_total}")
    print(f"  Virtual Packets Delivered : {v_succ}")
    print(f"  Virtual PDR               : {v_pdr:.2f}%")
    print("=" * 80)

if __name__ == "__main__":
    run_hybrid_network()
