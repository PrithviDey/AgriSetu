#include <esp_now.h>
#include <WiFi.h>
#include <math.h>

// ============================================================================
// AGRISETU EDGE AI: ESP32 GATEWAY (v2)
// Receives environmental packets from 4 sensor nodes via ESP-NOW
// Logs everything to Serial for the laptop bridge to capture
// ============================================================================

// ============================================================================
// Packet Structures (must match sensor node exactly)
// ============================================================================
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

typedef struct struct_ack {
    bool success;
    int  entropy_broadcast;
} struct_ack;
struct_ack ackData;

// ============================================================================
// Statistics
// ============================================================================
unsigned long total_packets   = 0;
unsigned long critical_packets = 0;
unsigned long warning_packets  = 0;
unsigned long normal_packets   = 0;

// Per-node last readings (up to 4 nodes)
struct_message node_readings[5]; // index 1–4
bool node_seen[5] = {false};

// Shannon Entropy tracking (collision ring buffer)
const int COL_WINDOW = 20;
int col_history[COL_WINDOW];
int history_index = 0;
int history_count = 0;
int current_entropy_idx = 0;

void updateEntropy(bool was_collision) {
    col_history[history_index] = was_collision ? 1 : 0;
    history_index = (history_index + 1) % COL_WINDOW;
    if (history_count < COL_WINDOW) history_count++;
    if (history_count < 3) return;

    int collisions = 0;
    for (int i = 0; i < history_count; i++) {
        collisions += col_history[i];
    }

    float p_c = (float)collisions / history_count;
    float p_s = 1.0 - p_c;
    float h_c = (p_c > 0) ? -p_c * log2(p_c) : 0;
    float h_s = (p_s > 0) ? -p_s * log2(p_s) : 0;
    float H = h_c + h_s;

    if (p_c <= 0.4) {
        current_entropy_idx = (H < 0.8) ? 0 : 1;
    } else {
        current_entropy_idx = (H >= 0.8) ? 2 : 3;
    }
}

// ============================================================================
// ESP-NOW Receive Callback
// ============================================================================
void OnDataRecv(const esp_now_recv_info_t *info, const uint8_t *incomingData, int len) {
    struct_message msg;
    memcpy(&msg, incomingData, sizeof(msg));

    total_packets++;

    // Track per-node
    if (msg.sensor_id >= 1 && msg.sensor_id <= 4) {
        node_readings[msg.sensor_id] = msg;
        node_seen[msg.sensor_id] = true;
    }

    // Count by priority
    if (msg.priority == 2) critical_packets++;
    else if (msg.priority == 1) warning_packets++;
    else normal_packets++;

    // Update entropy (success = received without collision)
    updateEntropy(false);

    // Priority labels
    const char* prio_labels[] = {"NORMAL", "WARNING", "CRITICAL"};
    const char* noise_labels[] = {"LOW", "MED", "HIGH", "V.HIGH"};

    // We are no longer printing per-packet logs here to keep the Serial Monitor clean.
    // The Gateway will only print the 5-second dashboard in the main loop.

    // Send ACK back to the sender node using its MAC from info->src_addr
    ackData.success = true;
    ackData.entropy_broadcast = current_entropy_idx;
    esp_now_send(info->src_addr, (uint8_t *)&ackData, sizeof(ackData));
}

// ============================================================================
// Setup
// ============================================================================
void setup() {
    Serial.begin(115200);
    for (int i = 0; i < COL_WINDOW; i++) col_history[i] = 0;

    WiFi.mode(WIFI_STA);

    Serial.println("════════════════════════════════════════════");
    Serial.println("  AGRISETU GATEWAY v2");
    Serial.print("  Gateway MAC: ");
    Serial.println(WiFi.macAddress());
    Serial.println("  Waiting for sensor nodes...");
    Serial.println("════════════════════════════════════════════");

    if (esp_now_init() != ESP_OK) {
        Serial.println("ESP-NOW init failed!");
        return;
    }
    esp_now_register_recv_cb(OnDataRecv);
}

// ============================================================================
// Main Loop — Print Dashboard every 10 seconds
// ============================================================================
unsigned long last_dashboard = 0;

void loop() {
    if (millis() - last_dashboard > 5000) {
        last_dashboard = millis();

        Serial.println();
        Serial.println("╔══════════════════════════════════════════════════════════════╗");
        Serial.println("║              AGRISETU GATEWAY — LIVE DASHBOARD              ║");
        Serial.println("╠══════════════════════════════════════════════════════════════╣");
        Serial.print("║  Total Packets : ");
        Serial.print(total_packets);
        Serial.print("  (Normal: ");
        Serial.print(normal_packets);
        Serial.print(" | Warn: ");
        Serial.print(warning_packets);
        Serial.print(" | Crit: ");
        Serial.print(critical_packets);
        Serial.println(")");

        Serial.println("║");
        Serial.println("║  Node |  Soil%  |  Temp°C |  Hum%  | Rain  | Prio     | Noise");
        Serial.println("║  ─────┼─────────┼─────────┼────────┼───────┼──────────┼──────");

        const char* prio_labels[] = {"NORMAL ", "WARNING", "CRITCAL"};
        const char* noise_labels[] = {"LOW ", "MED ", "HIGH", "VHIG"};

        for (int i = 1; i <= 4; i++) {
            if (node_seen[i]) {
                struct_message &m = node_readings[i];
                Serial.print("║    ");
                Serial.print(i);
                Serial.print("  |  ");
                Serial.print(m.soil_moisture, 1);
                Serial.print("%  |  ");
                Serial.print(m.temperature, 1);
                Serial.print("°C  |  ");
                Serial.print(m.humidity, 1);
                Serial.print("% | ");
                Serial.print(m.rainfall, 1);
                Serial.print("  | ");
                Serial.print(prio_labels[m.priority]);
                Serial.print("  | ");
                Serial.println(noise_labels[m.noise_level]);
            } else {
                Serial.print("║    ");
                Serial.print(i);
                Serial.println("  |  -- offline --");
            }
        }

        Serial.print("║  Shannon Entropy State: ");
        Serial.println(current_entropy_idx);
        Serial.println("╚══════════════════════════════════════════════════════════════╝");
    }

    delay(100);
}
