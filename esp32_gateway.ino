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

// Collision rate values for wire protocol (maps noise_level to CR)
const float FAIL_PROB_WIRE[4] = {0.05, 0.20, 0.40, 0.60};

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

    // Priority labels for wire protocol
    const char* prio_wire[] = {"normal", "warning", "critical"};
    int prio_idx = constrain(msg.priority, 0, 2);

    // ── WIRE PROTOCOL: Node telemetry frame ──
    // {"t":"nd","id":<int>,"rssi":<float>,"sf":<int>,"cr":<float>,"bat":<float>}
    Serial.print("{\"t\":\"nd\",\"id\":");
    Serial.print(msg.sensor_id);
    Serial.print(",\"rssi\":");
    Serial.print(WiFi.RSSI());
    Serial.print(",\"sf\":7,\"cr\":");
    Serial.print(FAIL_PROB_WIRE[msg.noise_level]);
    Serial.print(",\"bat\":95.0");
    // Include environmental data as extra fields
    Serial.print(",\"soil\":");
    Serial.print(msg.soil_moisture);
    Serial.print(",\"temp\":");
    Serial.print(msg.temperature);
    Serial.print(",\"hum\":");
    Serial.print(msg.humidity);
    Serial.print(",\"rain\":");
    Serial.print(msg.rainfall);
    Serial.print(",\"noise\":");
    Serial.print(msg.noise_level);
    Serial.println("}");

    // ── WIRE PROTOCOL: Transmission result frame ──
    // {"t":"tx","id":<int>,"ok":<0|1>,"pri":<str>,"e":<float>,"lat":<float>,"act":<0-4>}
    bool sim_fail = (random(0, 100) < (int)(FAIL_PROB_WIRE[msg.noise_level] * 100));
    Serial.print("{\"t\":\"tx\",\"id\":");
    Serial.print(msg.sensor_id);
    Serial.print(",\"ok\":");
    Serial.print(sim_fail ? 0 : 1);
    Serial.print(",\"pri\":\"");
    Serial.print(prio_wire[prio_idx]);
    Serial.print("\",\"e\":0.082,\"lat\":");
    Serial.print(millis() % 500);
    Serial.print(",\"act\":2}");
    Serial.println();

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
void loop() {
    // The Gateway no longer prints the dashboard locally. 
    // It emits JSON frames inside OnDataRecv directly for the Python bridge.
    
    // We can emit a heartbeat/ping here to keep the connection active
    static unsigned long last_ping = 0;
    if (millis() - last_ping > 2000) {
        last_ping = millis();
        Serial.println("{\"t\":\"ping\",\"id\":0}");
    }
    
    delay(10);
}
