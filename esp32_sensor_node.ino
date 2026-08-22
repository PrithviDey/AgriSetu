#include <esp_now.h>
#include <WiFi.h>

// ============================================================================
// AGRISETU EDGE AI: Q-LEARNING SENSOR NODE (v2 — Potentiometer = Noise)
// ============================================================================
// CHANGE THIS for each ESP32 board you flash:
//   Node 1 → SENSOR_ID = 1
//   Node 2 → SENSOR_ID = 2
//   Node 3 → SENSOR_ID = 3
//   Node 4 → SENSOR_ID = 4
// ============================================================================
#define SENSOR_ID 1

// ============================================================================
// Hardware Pins
// ============================================================================
#define POTENTIOMETER_PIN 34  // Shared pot → controls network noise/entropy

// ============================================================================
// Q-Learning Hyperparameters
// ============================================================================
const float ALPHA = 0.3;
const float GAMMA = 0.85;
float epsilon = 0.05;            // Low exploration — Q-table is pre-trained
const float EPSILON_DECAY = 0.9998;
const float EPSILON_MIN = 0.01;

// ============================================================================
// State Space:  3 (RSSI) × 3 (SF) × 4 (Entropy/Noise) × 3 (Priority) = 108
// Action Space: 5 Contention Windows
// ============================================================================
const int NUM_STATES  = 108;
const int NUM_ACTIONS = 5;
const int ACTION_WINDOWS[NUM_ACTIONS] = {4, 16, 64, 128, 256};

// The Edge Brain: 108 × 5 = 540 floats  (~2.1 KB RAM)
float Q_Table[NUM_STATES][NUM_ACTIONS];

// ============================================================================
// Noise → Simulated Failure Probability
// The potentiometer doesn't just label the state — it CHANGES the environment.
// ============================================================================
//                         Low    Med    High   VeryHigh
const float FAIL_PROB[4] = {0.05, 0.20, 0.40, 0.60};

// ============================================================================
// Simulated Environmental Data (Ornstein-Uhlenbeck on ESP32)
// Values drift gradually like real weather — not random noise.
// ============================================================================
float soil_moisture = 55.0;
float temperature   = 28.0;
float humidity      = 65.0;
float rainfall      =  2.0;

// OU process parameters: θ (reversion speed), μ (mean), σ (volatility)
void ou_step(float &val, float mu, float sigma, float theta, float lo, float hi) {
    float noise = ((float)random(-1000, 1000)) / 1000.0;  // Gaussian approx
    val += theta * (mu - val) + sigma * noise;
    val = constrain(val, lo, hi);
}

// ============================================================================
// Priority derived from environmental data
// ============================================================================
int current_priority = 0;      // 0=NORMAL, 1=WARNING, 2=CRITICAL
int current_urgency  = 1;      // 1, 5, or 10

void updateEnvironment() {
    // Each tick: smoothly drift all 4 sensors
    ou_step(soil_moisture, 55.0, 1.2, 0.03, 5.0, 100.0);
    ou_step(temperature,   28.0, 0.5, 0.05, -5.0, 50.0);
    ou_step(humidity,      65.0, 1.0, 0.04, 10.0, 100.0);
    ou_step(rainfall,       2.0, 1.5, 0.06, 0.0, 80.0);

    // Classify risk
    int breaches = 0;
    if (soil_moisture < 20.0) breaches++;
    if (temperature < 2.0)    breaches++;
    if (rainfall > 15.0)      breaches++;

    // Flood risk composite
    float soil_f = max(0.0f, (soil_moisture - 50.0f)) / 50.0f;
    float rain_f = min(1.0f, rainfall / 30.0f);
    float flood_risk = 0.4 * soil_f + 0.45 * rain_f + 0.15 * max(0.0f, (humidity - 70.0f) / 30.0f);
    if (flood_risk >= 0.7) breaches++;

    if (breaches >= 2)          { current_priority = 2; current_urgency = 10; }
    else if (flood_risk >= 0.7) { current_priority = 2; current_urgency = 10; }
    else if (temperature < 2.0) { current_priority = 2; current_urgency = 10; }
    else if (rainfall > 15.0)   { current_priority = 1; current_urgency = 5;  }
    else if (soil_moisture<30.0){ current_priority = 1; current_urgency = 5;  }
    else                        { current_priority = 0; current_urgency = 1;  }
}

// ============================================================================
// Noise / Entropy from Potentiometer
// ============================================================================
int current_noise_idx = 0;   // 0–3 (maps directly to entropy_idx in Q-table)

void readNoiseLevel() {
    static float smoothed_adc = -1;
    int raw_adc = analogRead(POTENTIOMETER_PIN);
    
    // Initialize on first run
    if (smoothed_adc < 0) smoothed_adc = raw_adc;
    
    // Exponential smoothing (smooths out noisy spikes)
    smoothed_adc = (smoothed_adc * 0.9) + (raw_adc * 0.1);
    
    int adc = (int)smoothed_adc;
    
    if      (adc < 1024) current_noise_idx = 0;  // Low
    else if (adc < 2048) current_noise_idx = 1;  // Medium
    else if (adc < 3072) current_noise_idx = 2;  // High
    else                 current_noise_idx = 3;  // Very High
}

// ============================================================================
// State & Q-Learning Core
// ============================================================================
int current_rssi_idx = 1;   // Assume mid-range (updated from WiFi.RSSI if needed)
int current_sf_idx   = 0;   // SF7 default

int last_state     = 0;
int last_action_idx= 0;
unsigned long gen_time = 0;
bool waiting_for_ack = false;

int getStateIndex(int rssi, int sf, int entropy, int priority) {
    return (rssi * 36) + (sf * 12) + (entropy * 3) + priority;
}

void initQTable() {
    // Pre-trained domain knowledge (matches Python benchmark warm-start)
    for (int r = 0; r < 3; r++) {
        for (int s = 0; s < 3; s++) {
            for (int e = 0; e < 4; e++) {
                for (int p = 0; p < 3; p++) {
                    int state = getStateIndex(r, s, e, p);
                    for (int a = 0; a < NUM_ACTIONS; a++) {
                        float score = 5.0;
                        // High congestion → prefer larger backoff
                        if (e >= 2 && ACTION_WINDOWS[a] >= 64)  score += 8.0;
                        else if (e < 2 && ACTION_WINDOWS[a] <= 64) score += 6.0;
                        // CRITICAL alerts → fast delivery (small window)
                        if (p == 2 && ACTION_WINDOWS[a] <= 16)  score += 14.0;
                        Q_Table[state][a] = score;
                    }
                }
            }
        }
    }
}

int chooseAction(int state) {
    if (random(0, 1000) / 1000.0 < epsilon) {
        return random(0, NUM_ACTIONS);
    }
    int best = 0;
    float maxQ = -9999.0;
    for (int a = 0; a < NUM_ACTIONS; a++) {
        if (Q_Table[state][a] > maxQ) {
            maxQ = Q_Table[state][a];
            best = a;
        }
    }
    return best;
}

float getMaxQ(int state) {
    float maxQ = -9999.0;
    for (int a = 0; a < NUM_ACTIONS; a++) {
        if (Q_Table[state][a] > maxQ) maxQ = Q_Table[state][a];
    }
    return maxQ;
}

// ============================================================================
// ESP-NOW Communication
// ============================================================================
uint8_t gatewayAddress[] = {0x14, 0x08, 0x08, 0x9F, 0x79, 0x64}; // Gateway MAC
esp_now_peer_info_t peerInfo;

typedef struct struct_message {
    int   sensor_id;
    int   priority;
    int   urgency;
    float soil_moisture;
    float temperature;
    float humidity;
    float rainfall;
    int   noise_level;
} struct_message;
struct_message myData;

typedef struct struct_ack {
    bool success;
    int  entropy_broadcast;
} struct_ack;
struct_ack ackData;

// ============================================================================
// Callbacks
// ============================================================================

void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
    // Real ESP-NOW delivery status
    bool espnow_ok = (status == ESP_NOW_SEND_SUCCESS);

    // Layer the potentiometer-controlled noise ON TOP:
    // Even if ESP-NOW says "sent", simulate environment failure at this noise level
    bool simulated_fail = (random(0, 100) < (int)(FAIL_PROB[current_noise_idx] * 100));
    bool success = espnow_ok && !simulated_fail;

    // ---- Reward Function: R = α·Delivery − β·Energy + γ·Urgency ----
    float reward = 0;
    float e_cost = ACTION_WINDOWS[last_action_idx] * 0.05 * 0.3;

    if (success) {
        float del_r = 10.0 + current_urgency * 1.5;
        reward = 1.0 * del_r - e_cost + 1.5 * current_urgency;
        Serial.println("✅ DELIVERED | Reward: " + String(reward, 2));
    } else {
        reward = 1.0 * (-8.0) - e_cost + 1.5 * (-current_urgency);
        if (espnow_ok) {
            Serial.println("📡 ESP-NOW OK but SIMULATED COLLISION (noise=" + 
                           String(current_noise_idx) + ") | Reward: " + String(reward, 2));
        } else {
            Serial.println("❌ ESP-NOW FAIL | Reward: " + String(reward, 2));
        }
    }

    // ---- Bellman Update ----
    int next_state = getStateIndex(current_rssi_idx, current_sf_idx,
                                    current_noise_idx, current_priority);
    float old_q = Q_Table[last_state][last_action_idx];
    float maxNQ = getMaxQ(next_state);
    Q_Table[last_state][last_action_idx] = old_q + ALPHA * (reward + GAMMA * maxNQ - old_q);

    if (epsilon > EPSILON_MIN) epsilon *= EPSILON_DECAY;
    waiting_for_ack = false;
}

void OnDataRecv(const esp_now_recv_info_t *info, const uint8_t *incomingData, int len) {
    memcpy(&ackData, incomingData, sizeof(ackData));
    // Gateway can override entropy if it has a better estimate
}

// ============================================================================
// Setup
// ============================================================================
void setup() {
    Serial.begin(115200);
    randomSeed(analogRead(0) + SENSOR_ID * 1337);
    initQTable();

    WiFi.mode(WIFI_STA);

    Serial.print("Node ");
    Serial.print(SENSOR_ID);
    Serial.print(" MAC: ");
    Serial.println(WiFi.macAddress());

    if (esp_now_init() != ESP_OK) {
        Serial.println("ESP-NOW init failed!");
        return;
    }

    esp_now_register_send_cb((esp_now_send_cb_t)OnDataSent);
    esp_now_register_recv_cb(OnDataRecv);

    memset(&peerInfo, 0, sizeof(peerInfo)); // <--- THIS IS CRITICAL FOR CORE V3
    memcpy(peerInfo.peer_addr, gatewayAddress, 6);
    peerInfo.channel = 0;
    peerInfo.encrypt = false;
    
    if (esp_now_add_peer(&peerInfo) != ESP_OK) {
        Serial.println("Failed to add peer!");
        return;
    }

    Serial.println("AgriSetu Node " + String(SENSOR_ID) + " ready.");
}

// ============================================================================
// Main Loop
// ============================================================================
void loop() {
    if (!waiting_for_ack) {
        // 1. Read potentiometer → noise level → entropy state
        readNoiseLevel();

        // 2. Advance simulated environment → determine priority
        updateEnvironment();

        // 3. Observe full state
        last_state = getStateIndex(current_rssi_idx, current_sf_idx,
                                    current_noise_idx, current_priority);

        // 4. Q-Learning chooses backoff action
        last_action_idx = chooseAction(last_state);
        int backoff_ms = ACTION_WINDOWS[last_action_idx] * 10;

        // 5. Serial monitor output
        const char* noise_labels[] = {"LOW", "MED", "HIGH", "V.HIGH"};
        const char* prio_labels[]  = {"NORMAL", "WARNING", "CRITICAL"};

        Serial.println("─────────────────────────────────────");
        Serial.println("Node " + String(SENSOR_ID) +
                       " | Noise: " + String(noise_labels[current_noise_idx]) +
                       " (fail=" + String((int)(FAIL_PROB[current_noise_idx]*100)) + "%)" +
                       " | Prio: " + String(prio_labels[current_priority]) +
                       " (U=" + String(current_urgency) + ")");
        Serial.println("  Soil:" + String(soil_moisture, 1) + "%" +
                       " Temp:" + String(temperature, 1) + "°C" +
                       " Hum:" + String(humidity, 1) + "%" +
                       " Rain:" + String(rainfall, 1) + "mm/hr");
        Serial.println("  Action: wait " + String(ACTION_WINDOWS[last_action_idx]) +
                       " slots (" + String(backoff_ms) + " ms)");

        // 6. Execute backoff
        delay(backoff_ms);

        // 7. Transmit packet with full environmental payload
        myData.sensor_id     = SENSOR_ID;
        myData.priority      = current_priority;
        myData.urgency       = current_urgency;
        myData.soil_moisture = soil_moisture;
        myData.temperature   = temperature;
        myData.humidity      = humidity;
        myData.rainfall      = rainfall;
        myData.noise_level   = current_noise_idx;

        esp_now_send(gatewayAddress, (uint8_t *)&myData, sizeof(myData));
        waiting_for_ack = true;
        gen_time = millis();
    }

    delay(100);
}
