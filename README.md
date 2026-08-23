# AgriSetu

AgriSetu is a framework for managing and simulating agricultural sensor networks. It combines physical ESP32-based hardware nodes with a Python-backed web dashboard, allowing you to monitor real-time environmental data and experiment with Q-Learning based medium access control (MAC) protocols.

The system is designed to solve the problem of packet collisions in dense sensor networks. By using reinforcement learning, nodes learn when to transmit their data to avoid overlapping with others, vastly improving packet delivery rates over standard ALOHA protocols.

## Key Features

* Hybrid Network Support: Run the system entirely in software simulation, exclusively with physical ESP32 hardware, or a mix of both.
* Q-Learning MAC Protocol: The backend features an implementation of a reinforcement learning agent that optimizes transmission windows to reduce collisions.
* Real-time Dashboard: A web interface built with HTML, CSS, and Vanilla JavaScript that visualizes network topology, active alerts, packet delivery rates, and raw telemetry data.
* Hardware Integration: C++ code for ESP32 microcontrollers utilizing the ESP-NOW protocol for fast, low-latency communication between sensor nodes and the central gateway.

## Hardware Setup

To run the hardware side of AgriSetu, you will need at least two ESP32 development boards: one to act as the gateway and one or more to act as sensor nodes.

1. Gateway Setup: Flash the `esp32_gateway.ino` sketch to an ESP32. This board will act as the receiver and bridge, passing data from the sensor network to your computer via Serial over USB.
2. Sensor Node Setup: Flash the `esp32_sensor_node.ino` sketch to your other ESP32 boards. The nodes simulate environmental data (soil moisture, temperature, humidity, rainfall) and use a physical potentiometer connected to pin 34 to determine local noise and priority levels.

Ensure that the MAC address of your gateway is correctly configured in the sensor node code so they can communicate via ESP-NOW.

## Software Setup

The backend and dashboard are powered by Python and FastAPI.

1. Ensure you have Python 3.9 or newer installed.
2. Create and activate a virtual environment.
3. Install the required dependencies (FastAPI, Uvicorn, PySerial).
4. Start the backend server by running `uvicorn main:app --reload --port 8000` inside the `backend` directory.

## Usage

Once the backend is running, open your browser and navigate to `http://localhost:8000/ui/` to access the dashboard. 

From the dashboard, you can:
* Use the Simulation Control panel to spawn virtual nodes and adjust the simulation speed.
* Connect to your physical gateway by entering the appropriate COM port in the Hardware Connection panel.
* Monitor incoming packets, channel entropy, and system alerts in real time.
* Adjust the Q-Learning hyperparameters to see how the network adapts to different reward structures.
