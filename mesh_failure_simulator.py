import numpy as np
import matplotlib.pyplot as plt

# =============================================================================
# AgriSetu - Phase 17: Failure Handling & Mesh Routing Simulator
# =============================================================================

# Common parameters
ALPHA = 0.3
GAMMA = 0.9
EPSILON_START = 0.5
EPSILON_MIN = 0.05
EPSILON_DECAY = 0.99

def run_hidden_node_test():
    """
    Test 1: Hidden Node Problem
    Node 1 and Node 3 cannot hear each other, but both transmit to Gateway.
    If they pick the same time slot, they collide.
    Actions: 4 possible time slots.
    Goal: Learn to pick different time slots to avoid collisions.
    """
    print("Running Test 1: Hidden Node Resolution...")
    episodes = 200
    
    # Q-tables for Node 1 and Node 3
    # State is just a dummy state (0) since they don't know what the other is doing
    Q1 = np.zeros(4)
    Q3 = np.zeros(4)
    
    collisions = []
    epsilon = EPSILON_START
    
    for ep in range(episodes):
        # Epsilon-greedy action selection
        if np.random.rand() < epsilon:
            a1 = np.random.randint(4)
        else:
            a1 = np.argmax(Q1)
            
        if np.random.rand() < epsilon:
            a3 = np.random.randint(4)
        else:
            a3 = np.argmax(Q3)
            
        # Environment step
        collision = (a1 == a3)
        collisions.append(1 if collision else 0)
        
        # Rewards
        r1 = -10 if collision else 10
        r3 = -10 if collision else 10
        
        # Q-learning update (simplified, no next state)
        Q1[a1] = Q1[a1] + ALPHA * (r1 - Q1[a1])
        Q3[a3] = Q3[a3] + ALPHA * (r3 - Q3[a3])
        
        if epsilon > EPSILON_MIN:
            epsilon *= EPSILON_DECAY

    # Calculate moving average of collisions
    window = 10
    moving_avg = np.convolve(collisions, np.ones(window)/window, mode='valid')
    
    return moving_avg

def run_mesh_reroute_test():
    """
    Test 2: Node Failure and Mesh Rerouting
    Node 4 must route through Node 2 or Node 3 to reach Gateway.
    Actions: 0 (Route via Node 2), 1 (Route via Node 3).
    At t = 100, Node 2 completely dies.
    Goal: Node 4 must learn to stop using Node 2 and switch to Node 3.
    """
    print("Running Test 2: Mesh Node Failure & Self-Healing...")
    episodes = 250
    
    # Q-table for Node 4 routing choices: [Route_via_2, Route_via_3]
    Q4 = np.array([5.0, 0.0]) # Initially biased towards Node 2 (maybe shorter distance)
    
    route_choices = []
    success_rate = []
    
    epsilon = 0.1 # Low exploration
    
    for ep in range(episodes):
        # Node 2 dies at episode 100
        node2_alive = (ep < 100)
        
        if np.random.rand() < epsilon:
            action = np.random.randint(2)
        else:
            action = np.argmax(Q4)
            
        route_choices.append(action)
        
        # Environment step
        success = False
        if action == 0: # Route via Node 2
            if node2_alive:
                success = True
            else:
                success = False
        else: # Route via Node 3
            success = True # Node 3 is always reliable in this test
            
        success_rate.append(1 if success else 0)
        
        # Reward
        reward = 10 if success else -20
        
        # Q-learning update
        Q4[action] = Q4[action] + ALPHA * (reward - Q4[action])

    # Moving average
    window = 10
    moving_success = np.convolve(success_rate, np.ones(window)/window, mode='valid')
    
    return route_choices, moving_success

if __name__ == "__main__":
    # Run tests
    hidden_node_cols = run_hidden_node_test()
    route_choices, mesh_success = run_mesh_reroute_test()
    
    # Plotting
    plt.style.use('dark_background')
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 12))
    
    # Test 1 Plot
    ax1.plot(hidden_node_cols, color='#ff4757', linewidth=2)
    ax1.set_title("Test 1: Hidden Node Collision Rate Over Time", fontsize=14, color='white')
    ax1.set_ylabel("Collision Rate", color='white')
    ax1.set_xlabel("Time (Episodes)", color='white')
    ax1.grid(color='#2f3542', linestyle='--')
    ax1.text(10, 0.8, "Nodes blindly transmit & collide", color='white', fontsize=10)
    ax1.text(100, 0.2, "Q-Learning finds\nseparate time slots", color='#2ed573', fontsize=10)

    # Test 2 Plot (Route Choice)
    ax2.scatter(range(len(route_choices)), route_choices, c=['#1e90ff' if r == 0 else '#ffa502' for r in route_choices], s=20)
    ax2.set_yticks([0, 1])
    ax2.set_yticklabels(['Route via Node 2', 'Route via Node 3'])
    ax2.set_title("Test 2: Edge AI Mesh Rerouting (Node 2 Dies at T=100)", fontsize=14, color='white')
    ax2.set_xlabel("Time (Episodes)", color='white')
    ax2.axvline(x=100, color='#ff4757', linestyle='--', label='Node 2 Fails')
    ax2.grid(color='#2f3542', linestyle='--', axis='x')
    ax2.legend()
    
    # Test 2 Plot (Delivery Success)
    ax3.plot(mesh_success, color='#2ed573', linewidth=2)
    ax3.set_title("Test 2: Delivery Success Rate During Failure", fontsize=14, color='white')
    ax3.set_ylabel("Success Rate", color='white')
    ax3.set_xlabel("Time (Episodes)", color='white')
    ax3.axvline(x=90, color='#ff4757', linestyle='--', label='Node 2 Fails') # 90 due to window offset
    ax3.grid(color='#2f3542', linestyle='--')
    
    plt.tight_layout()
    plt.savefig('failure_handling_mesh.png', dpi=300, facecolor='#1e272e')
    print("Simulation complete! Graph saved as 'failure_handling_mesh.png'")
