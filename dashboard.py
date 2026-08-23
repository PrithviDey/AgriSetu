#!/usr/bin/env python3
"""
AgriSetu — Real-Time Edge AI Dashboard (Professional Edition)
=============================================================
Reads live_telemetry.json (written by serial_gateway_bridge.py)
and displays a hackathon-grade real-time visualization.

Usage:
  Terminal 1: python serial_gateway_bridge.py
  Terminal 2: streamlit run dashboard.py
"""
import streamlit as st
import json
import os
import time
import random
import math

# ─── Page Config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AgriSetu — Edge AI Dashboard",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

/* Reset & Global */
*, *::before, *::after { box-sizing: border-box; }
.stApp {
    background: #060b18;
    font-family: 'Inter', -apple-system, sans-serif;
    color: #e2e8f0;
}
#MainMenu, footer, header, .stDeployButton { display: none !important; }
div[data-testid="stToolbar"] { display: none !important; }

/* Remove default streamlit padding */
.block-container { padding-top: 1rem !important; padding-bottom: 0 !important; max-width: 1400px; }

/* ─── Header ───────────────────────────────────────────────── */
.dash-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0.8rem 1.5rem; margin-bottom: 1.2rem;
    background: linear-gradient(135deg, rgba(10,17,40,0.95), rgba(15,25,50,0.9));
    border: 1px solid rgba(0,180,216,0.12);
    border-radius: 14px;
    backdrop-filter: blur(12px);
}
.dash-logo {
    display: flex; align-items: center; gap: 0.8rem;
}
.dash-logo-icon {
    width: 42px; height: 42px;
    background: linear-gradient(135deg, #00d4aa, #00b4d8);
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.3rem;
}
.dash-title {
    font-size: 1.5rem; font-weight: 800;
    background: linear-gradient(90deg, #00d4aa, #00b4d8);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    letter-spacing: -0.3px;
}
.dash-subtitle { font-size: 0.7rem; color: #64748b; letter-spacing: 2px; text-transform: uppercase; }
.dash-status {
    display: flex; align-items: center; gap: 0.5rem;
    padding: 0.4rem 1rem; border-radius: 20px;
    font-size: 0.75rem; font-weight: 600;
}
.status-live {
    background: rgba(34,197,94,0.12); border: 1px solid rgba(34,197,94,0.3); color: #22c55e;
}
.status-demo {
    background: rgba(251,191,36,0.12); border: 1px solid rgba(251,191,36,0.3); color: #fbbf24;
}
.status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    animation: blink 1.5s ease-in-out infinite;
}
.status-dot-live { background: #22c55e; }
.status-dot-demo { background: #fbbf24; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

/* ─── Alert Banner ─────────────────────────────────────────── */
.alert-banner {
    background: linear-gradient(90deg, rgba(239,68,68,0.08), rgba(239,68,68,0.03));
    border: 1px solid rgba(239,68,68,0.3); border-left: 4px solid #ef4444;
    border-radius: 10px; padding: 0.8rem 1.2rem;
    margin-bottom: 1rem; display: flex; align-items: center; gap: 0.8rem;
    animation: alert-pulse 2s infinite;
}
@keyframes alert-pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); }
    50% { box-shadow: 0 0 20px 0 rgba(239,68,68,0.15); }
}
.alert-icon { font-size: 1.4rem; }
.alert-text { color: #fca5a5; font-weight: 600; font-size: 0.9rem; }
.alert-sub { color: #64748b; font-size: 0.75rem; }

/* ─── KPI Cards ────────────────────────────────────────────── */
.kpi-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 0.8rem; margin-bottom: 1.2rem; }
.kpi {
    background: linear-gradient(145deg, rgba(12,20,45,0.95), rgba(20,30,55,0.85));
    border: 1px solid rgba(100,200,255,0.06);
    border-radius: 12px; padding: 1rem 1.2rem;
    position: relative; overflow: hidden;
    transition: all 0.3s ease;
}
.kpi:hover { border-color: rgba(0,212,170,0.25); transform: translateY(-1px); }
.kpi::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    border-radius: 12px 12px 0 0;
}
.kpi-packets::before { background: linear-gradient(90deg, #00d4aa, #00b4d8); }
.kpi-pdr::before { background: linear-gradient(90deg, #22c55e, #4ade80); }
.kpi-collision::before { background: linear-gradient(90deg, #f97316, #fbbf24); }
.kpi-entropy::before { background: linear-gradient(90deg, #a78bfa, #818cf8); }
.kpi-nodes::before { background: linear-gradient(90deg, #38bdf8, #0ea5e9); }
.kpi-critical::before { background: linear-gradient(90deg, #ef4444, #f87171); }

.kpi-label {
    font-size: 0.65rem; color: #64748b;
    text-transform: uppercase; letter-spacing: 1.5px; font-weight: 600;
    margin-bottom: 0.4rem;
}
.kpi-value {
    font-size: 1.8rem; font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    line-height: 1.1;
}
.kpi-detail { font-size: 0.7rem; color: #475569; margin-top: 0.3rem; font-family: 'JetBrains Mono'; }

/* ─── Section Headers ──────────────────────────────────────── */
.section-header {
    display: flex; align-items: center; gap: 0.6rem;
    margin: 1rem 0 0.8rem 0;
}
.section-icon {
    width: 28px; height: 28px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.85rem;
}
.section-icon-env { background: rgba(34,197,94,0.15); }
.section-icon-net { background: rgba(0,180,216,0.15); }
.section-icon-ai { background: rgba(167,139,250,0.15); }
.section-title {
    font-size: 0.78rem; font-weight: 700; color: #94a3b8;
    text-transform: uppercase; letter-spacing: 2px;
}

/* ─── Node Cards ───────────────────────────────────────────── */
.node-card {
    background: linear-gradient(145deg, rgba(12,20,45,0.95), rgba(20,30,55,0.85));
    border: 1px solid rgba(100,200,255,0.06);
    border-radius: 14px; padding: 1.2rem; height: 100%;
    transition: all 0.3s ease;
}
.node-card:hover { border-color: rgba(0,212,170,0.2); }
.node-top {
    display: flex; justify-content: space-between; align-items: center;
    padding-bottom: 0.7rem; margin-bottom: 0.7rem;
    border-bottom: 1px solid rgba(100,200,255,0.06);
}
.node-name { font-size: 0.95rem; font-weight: 700; color: #e2e8f0; }
.badge {
    padding: 0.2rem 0.6rem; border-radius: 6px;
    font-size: 0.6rem; font-weight: 700; letter-spacing: 1px;
}
.b-normal { background: rgba(34,197,94,0.12); color: #4ade80; border: 1px solid rgba(34,197,94,0.2); }
.b-warning { background: rgba(251,191,36,0.12); color: #fbbf24; border: 1px solid rgba(251,191,36,0.2); }
.b-critical {
    background: rgba(239,68,68,0.12); color: #f87171; border: 1px solid rgba(239,68,68,0.2);
    animation: badge-pulse 1.5s infinite;
}
@keyframes badge-pulse { 0%,100% { box-shadow: none; } 50% { box-shadow: 0 0 12px rgba(239,68,68,0.3); } }

.b-offline { background: rgba(100,116,139,0.1); color: #475569; border: 1px solid rgba(100,116,139,0.15); }

.metrics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.metric-box {
    background: rgba(0,0,0,0.25); border-radius: 8px; padding: 0.6rem 0.5rem;
    text-align: center;
}
.metric-val {
    font-size: 1.25rem; font-weight: 700;
    font-family: 'JetBrains Mono', monospace; line-height: 1.2;
}
.metric-lbl {
    font-size: 0.58rem; color: #64748b; text-transform: uppercase;
    letter-spacing: 1px; margin-top: 0.15rem;
}
.node-footer {
    display: flex; justify-content: space-between; align-items: center;
    margin-top: 0.6rem; padding-top: 0.5rem;
    border-top: 1px solid rgba(100,200,255,0.04);
    font-size: 0.65rem; color: #475569;
}
.noise-tag {
    padding: 0.15rem 0.45rem; border-radius: 4px;
    font-size: 0.6rem; font-weight: 600;
}
.n-low { background: rgba(34,197,94,0.1); color: #4ade80; }
.n-med { background: rgba(251,191,36,0.1); color: #fbbf24; }
.n-high { background: rgba(249,115,22,0.1); color: #f97316; }
.n-vhigh { background: rgba(239,68,68,0.1); color: #f87171; }

/* ─── Offline Card ─────────────────────────────────────────── */
.node-card-offline {
    background: linear-gradient(145deg, rgba(12,20,45,0.5), rgba(20,30,55,0.4));
    border: 1px dashed rgba(100,200,255,0.06);
    border-radius: 14px; padding: 1.2rem; height: 100%;
    display: flex; flex-direction: column; justify-content: center; align-items: center;
    gap: 0.5rem;
}
.offline-icon { font-size: 1.5rem; opacity: 0.3; }
.offline-text { font-size: 0.75rem; color: #334155; font-weight: 500; }

/* ─── Q-Learning Stats Card ───────────────────────────────── */
.ai-card {
    background: linear-gradient(145deg, rgba(12,20,45,0.95), rgba(20,30,55,0.85));
    border: 1px solid rgba(167,139,250,0.1);
    border-radius: 14px; padding: 1.2rem;
}
.ai-stat-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.5rem 0;
    border-bottom: 1px solid rgba(100,200,255,0.04);
}
.ai-stat-row:last-child { border: none; }
.ai-stat-label { font-size: 0.75rem; color: #94a3b8; }
.ai-stat-value { font-size: 0.85rem; font-weight: 600; font-family: 'JetBrains Mono'; }

/* ─── Entropy Bar ──────────────────────────────────────────── */
.entropy-container { margin-top: 0.5rem; }
.entropy-bar-bg {
    height: 6px; background: rgba(255,255,255,0.04); border-radius: 3px;
    overflow: hidden; margin-top: 0.3rem;
}
.entropy-bar-fill {
    height: 100%; border-radius: 3px;
    transition: width 0.8s cubic-bezier(0.4,0,0.2,1);
}

/* ─── Chart containers ─────────────────────────────────────── */
.chart-card {
    background: linear-gradient(145deg, rgba(12,20,45,0.95), rgba(20,30,55,0.85));
    border: 1px solid rgba(100,200,255,0.06);
    border-radius: 14px; padding: 1rem 1.2rem;
}
.chart-title {
    font-size: 0.72rem; font-weight: 700; color: #94a3b8;
    text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 0.6rem;
}

/* ─── Footer ───────────────────────────────────────────────── */
.dash-footer {
    text-align: center; padding: 0.8rem;
    font-size: 0.65rem; color: #1e293b;
    font-family: 'JetBrains Mono'; letter-spacing: 1px;
}
</style>
""", unsafe_allow_html=True)

TELEMETRY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_telemetry.json")
PRIO_MAP = {0: ("NORMAL", "b-normal"), 1: ("WARNING", "b-warning"), 2: ("CRITICAL", "b-critical")}
NOISE_MAP = {0: ("LOW", "n-low"), 1: ("MED", "n-med"), 2: ("HIGH", "n-high"), 3: ("V.HIGH", "n-vhigh")}
ENTROPY_INFO = {
    0: ("#22c55e", "Stable", 15),
    1: ("#fbbf24", "Mild Congestion", 40),
    2: ("#f97316", "Elevated", 70),
    3: ("#ef4444", "Critical", 95),
}


def load_telemetry():
    if not os.path.exists(TELEMETRY_FILE):
        return None
    try:
        with open(TELEMETRY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def generate_demo_data():
    """Generates realistic demo data with history for testing without hardware."""
    # Use session state to persist history across refreshes
    if "demo_history" not in st.session_state:
        st.session_state.demo_history = []
        st.session_state.demo_tick = 0
        st.session_state.demo_soil = [55.0, 48.0, 62.0, 70.0]
        st.session_state.demo_temp = [28.0, 31.0, 25.0, 27.0]
        st.session_state.demo_hum = [65.0, 58.0, 72.0, 80.0]
        st.session_state.demo_rain = [2.0, 0.5, 5.0, 12.0]

    t = st.session_state.demo_tick
    st.session_state.demo_tick += 1

    # Ornstein-Uhlenbeck drift for each node
    nodes = []
    for i in range(4):
        # OU step
        st.session_state.demo_soil[i] += 0.03 * (55 - st.session_state.demo_soil[i]) + random.gauss(0, 1.2)
        st.session_state.demo_temp[i] += 0.05 * (28 - st.session_state.demo_temp[i]) + random.gauss(0, 0.5)
        st.session_state.demo_hum[i] += 0.04 * (65 - st.session_state.demo_hum[i]) + random.gauss(0, 1.0)
        st.session_state.demo_rain[i] += 0.06 * (2 - st.session_state.demo_rain[i]) + random.gauss(0, 1.5)
        st.session_state.demo_rain[i] = max(0, st.session_state.demo_rain[i])

        soil = round(max(5, min(100, st.session_state.demo_soil[i])), 1)
        temp = round(max(-5, min(50, st.session_state.demo_temp[i])), 1)
        hum = round(max(10, min(100, st.session_state.demo_hum[i])), 1)
        rain = round(max(0, min(80, st.session_state.demo_rain[i])), 1)

        prio = 0
        if soil < 20 or rain > 25 or temp < 2: prio = 2
        elif soil < 30 or rain > 15 or temp < 5: prio = 1

        nodes.append({"id": i+1, "soil": soil, "temp": temp, "hum": hum, "rain": rain, "prio": prio, "noise": random.randint(0, 2)})

    total = 50 + t * random.randint(3, 7)
    crit = max(0, int(total * 0.04 + random.gauss(0, 2)))
    warn = max(0, int(total * 0.15 + random.gauss(0, 3)))
    norm = total - crit - warn

    entry = {
        "ts": time.strftime("%H:%M:%S"),
        "total": total, "normal": norm, "warning": warn, "critical": crit,
        "entropy": random.choices([0, 1, 2, 3], weights=[50, 30, 15, 5])[0],
        "nodes": nodes,
    }
    st.session_state.demo_history.append(entry)
    if len(st.session_state.demo_history) > 60:
        st.session_state.demo_history = st.session_state.demo_history[-60:]

    return {
        **entry,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "history": st.session_state.demo_history,
    }


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    data = load_telemetry()
    demo_mode = data is None
    if demo_mode:
        data = generate_demo_data()

    total = data.get("total", 0)
    normal = data.get("normal", 0)
    warning = data.get("warning", 0)
    critical = data.get("critical", 0)
    entropy_idx = data.get("entropy", 0)
    nodes = data.get("nodes", [])
    history = data.get("history", [])
    active = len(nodes)
    pdr = round((total / max(1, total + critical * 0.5)) * 100, 1) if total > 0 else 100.0
    col_rate = round(100 - pdr, 1)

    ent_color, ent_label, ent_pct = ENTROPY_INFO.get(entropy_idx, ("#22c55e", "Stable", 15))
    status_class = "status-demo" if demo_mode else "status-live"
    status_dot = "status-dot-demo" if demo_mode else "status-dot-live"
    status_text = "DEMO MODE" if demo_mode else "LIVE"

    # ── Header ──
    st.markdown(f'''
    <div class="dash-header">
        <div class="dash-logo">
            <div class="dash-logo-icon">🌾</div>
            <div>
                <div class="dash-title">AgriSetu</div>
                <div class="dash-subtitle">Edge AI · Q-Learning · ESP-NOW Mesh</div>
            </div>
        </div>
        <div class="dash-status {status_class}">
            <div class="status-dot {status_dot}"></div>
            {status_text}
        </div>
    </div>
    ''', unsafe_allow_html=True)

    # ── Critical Alert Banner ──
    crit_nodes = [n for n in nodes if n.get("prio") == 2]
    if crit_nodes:
        ids = ", ".join([f"Node {n['id']}" for n in crit_nodes])
        st.markdown(f'''
        <div class="alert-banner">
            <div class="alert-icon">🚨</div>
            <div>
                <div class="alert-text">CRITICAL ALERT — {ids}</div>
                <div class="alert-sub">Flood/Frost risk detected · Packets prioritized with Urgency=10</div>
            </div>
        </div>
        ''', unsafe_allow_html=True)

    # ── KPI Row ──
    st.markdown(f'''
    <div class="kpi-grid">
        <div class="kpi kpi-nodes">
            <div class="kpi-label">Active Nodes</div>
            <div class="kpi-value" style="color:#38bdf8;">{active}<span style="font-size:1rem;color:#475569;">/4</span></div>
            <div class="kpi-detail">ESP-NOW Connected</div>
        </div>
        <div class="kpi kpi-packets">
            <div class="kpi-label">Packets Received</div>
            <div class="kpi-value" style="color:#00d4aa;">{total}</div>
            <div class="kpi-detail">Total Gateway RX</div>
        </div>
        <div class="kpi kpi-pdr">
            <div class="kpi-label">Delivery Rate</div>
            <div class="kpi-value" style="color:#4ade80;">{pdr}%</div>
            <div class="kpi-detail">PDR (higher is better)</div>
        </div>
        <div class="kpi kpi-collision">
            <div class="kpi-label">N / W / C</div>
            <div class="kpi-value"><span style="color:#4ade80;font-size:1.3rem;">{normal}</span> <span style="color:#334155;">·</span> <span style="color:#fbbf24;font-size:1.3rem;">{warning}</span> <span style="color:#334155;">·</span> <span style="color:#f87171;font-size:1.3rem;">{critical}</span></div>
            <div class="kpi-detail">Priority Breakdown</div>
        </div>
        <div class="kpi kpi-entropy">
            <div class="kpi-label">Shannon Entropy</div>
            <div class="kpi-value" style="color:{ent_color};">{ent_label}</div>
            <div class="entropy-container">
                <div class="entropy-bar-bg"><div class="entropy-bar-fill" style="width:{ent_pct}%;background:{ent_color};"></div></div>
            </div>
        </div>
        <div class="kpi kpi-critical">
            <div class="kpi-label">Q-Learning</div>
            <div class="kpi-value" style="color:#a78bfa;">Active</div>
            <div class="kpi-detail">ε = 0.05 · α = 0.3</div>
        </div>
    </div>
    ''', unsafe_allow_html=True)

    # ── Live Charts ──
    if len(history) > 2:
        import pandas as pd

        st.markdown('''<div class="section-header">
            <div class="section-icon section-icon-net">📈</div>
            <div class="section-title">Network Performance — Live</div>
        </div>''', unsafe_allow_html=True)

        c1, c2, c3 = st.columns(3)
        df = pd.DataFrame(history)

        with c1:
            st.markdown('<div class="chart-card"><div class="chart-title">📦 Cumulative Packets</div></div>', unsafe_allow_html=True)
            chart_data = df[["total"]].rename(columns={"total": "Packets"})
            st.area_chart(chart_data, color="#00d4aa", height=180)

        with c2:
            st.markdown('<div class="chart-card"><div class="chart-title">⚠️ Warnings & Criticals</div></div>', unsafe_allow_html=True)
            alert_data = df[["warning", "critical"]].rename(columns={"warning": "Warning", "critical": "Critical"})
            st.area_chart(alert_data, color=["#fbbf24", "#ef4444"], height=180)

        with c3:
            st.markdown('<div class="chart-card"><div class="chart-title">🧠 Entropy Over Time</div></div>', unsafe_allow_html=True)
            ent_data = df[["entropy"]].rename(columns={"entropy": "Entropy"})
            st.line_chart(ent_data, color="#a78bfa", height=180)

    # ── Environmental Data (Node Cards) ──
    st.markdown('''<div class="section-header">
        <div class="section-icon section-icon-env">🌱</div>
        <div class="section-title">Environmental Sensors — Per Node</div>
    </div>''', unsafe_allow_html=True)

    node_map = {n["id"]: n for n in nodes}
    cols = st.columns(4)

    for idx in range(4):
        nid = idx + 1
        with cols[idx]:
            if nid in node_map:
                n = node_map[nid]
                prio_label, prio_class = PRIO_MAP.get(n.get("prio", 0), ("NORMAL", "b-normal"))
                noise_label, noise_class = NOISE_MAP.get(n.get("noise", 0), ("LOW", "n-low"))
                soil, temp, hum, rain = n.get("soil", 0), n.get("temp", 0), n.get("hum", 0), n.get("rain", 0)

                sc = "#ef4444" if soil < 20 else "#fbbf24" if soil < 35 else "#4ade80"
                tc = "#ef4444" if (temp > 40 or temp < 2) else "#fbbf24" if (temp > 35 or temp < 5) else "#38bdf8"
                hc = "#ef4444" if hum > 90 else "#a78bfa"
                rc = "#ef4444" if rain > 15 else "#fbbf24" if rain > 8 else "#38bdf8"

                st.markdown(f'''
                <div class="node-card">
                    <div class="node-top">
                        <div class="node-name">🌱 Node {nid}</div>
                        <div class="badge {prio_class}">{prio_label}</div>
                    </div>
                    <div class="metrics-grid">
                        <div class="metric-box">
                            <div class="metric-val" style="color:{sc};">{soil}%</div>
                            <div class="metric-lbl">💧 Soil Moisture</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-val" style="color:{tc};">{temp}°C</div>
                            <div class="metric-lbl">🌡️ Temperature</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-val" style="color:{hc};">{hum}%</div>
                            <div class="metric-lbl">💨 Humidity</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-val" style="color:{rc};">{rain}</div>
                            <div class="metric-lbl">🌧️ Rain mm/h</div>
                        </div>
                    </div>
                    <div class="node-footer">
                        <span>Noise: <span class="noise-tag {noise_class}">{noise_label}</span></span>
                        <span>U={10 if n.get("prio")==2 else 5 if n.get("prio")==1 else 1}</span>
                    </div>
                </div>
                ''', unsafe_allow_html=True)
            else:
                st.markdown(f'''
                <div class="node-card-offline">
                    <div class="offline-icon">📴</div>
                    <div class="offline-text">Node {nid} — Offline</div>
                    <div class="badge b-offline">NO DATA</div>
                </div>
                ''', unsafe_allow_html=True)

    # ── Soil Moisture Trends ──
    if len(history) > 3:
        st.markdown('''<div class="section-header">
            <div class="section-icon section-icon-env">📊</div>
            <div class="section-title">Soil Moisture Trends — All Nodes</div>
        </div>''', unsafe_allow_html=True)

        import pandas as pd
        soil_rows = []
        for entry in history:
            row = {}
            for node in entry.get("nodes", []):
                row[f"Node {node['id']}"] = node.get("soil", 0)
            if row:
                soil_rows.append(row)
        if soil_rows:
            soil_df = pd.DataFrame(soil_rows)
            colors = ["#4ade80", "#38bdf8", "#a78bfa", "#fbbf24"][:len(soil_df.columns)]
            st.line_chart(soil_df, color=colors, height=220)

    # ── Q-Learning Intelligence Panel ──
    st.markdown('''<div class="section-header">
        <div class="section-icon section-icon-ai">🧠</div>
        <div class="section-title">Q-Learning Intelligence</div>
    </div>''', unsafe_allow_html=True)

    q1, q2, q3 = st.columns(3)
    with q1:
        st.markdown(f'''
        <div class="ai-card">
            <div class="ai-stat-row"><span class="ai-stat-label">Algorithm</span><span class="ai-stat-value" style="color:#a78bfa;">Q-Learning (Tabular)</span></div>
            <div class="ai-stat-row"><span class="ai-stat-label">State Space</span><span class="ai-stat-value" style="color:#e2e8f0;">3×3×4×3 = 108 states</span></div>
            <div class="ai-stat-row"><span class="ai-stat-label">Action Space</span><span class="ai-stat-value" style="color:#e2e8f0;">5 contention windows</span></div>
            <div class="ai-stat-row"><span class="ai-stat-label">Q-Table Size</span><span class="ai-stat-value" style="color:#00d4aa;">540 floats (2.1 KB)</span></div>
        </div>
        ''', unsafe_allow_html=True)

    with q2:
        st.markdown(f'''
        <div class="ai-card">
            <div class="ai-stat-row"><span class="ai-stat-label">Learning Rate (α)</span><span class="ai-stat-value" style="color:#38bdf8;">0.30</span></div>
            <div class="ai-stat-row"><span class="ai-stat-label">Discount (γ)</span><span class="ai-stat-value" style="color:#38bdf8;">0.85</span></div>
            <div class="ai-stat-row"><span class="ai-stat-label">Exploration (ε)</span><span class="ai-stat-value" style="color:#fbbf24;">0.05 → 0.01</span></div>
            <div class="ai-stat-row"><span class="ai-stat-label">Reward Function</span><span class="ai-stat-value" style="color:#e2e8f0;">R = αD − βE + γU</span></div>
        </div>
        ''', unsafe_allow_html=True)

    with q3:
        st.markdown(f'''
        <div class="ai-card">
            <div class="ai-stat-row"><span class="ai-stat-label">Shannon Entropy</span><span class="ai-stat-value" style="color:{ent_color};">{ent_label}</span></div>
            <div class="ai-stat-row"><span class="ai-stat-label">Entropy Index</span><span class="ai-stat-value" style="color:#e2e8f0;">{entropy_idx}/3</span></div>
            <div class="ai-stat-row"><span class="ai-stat-label">Active Nodes</span><span class="ai-stat-value" style="color:#38bdf8;">{active}/4</span></div>
            <div class="ai-stat-row"><span class="ai-stat-label">Protocol</span><span class="ai-stat-value" style="color:#00d4aa;">ESP-NOW</span></div>
        </div>
        ''', unsafe_allow_html=True)

    # ── Footer ──
    ts = data.get("timestamp", time.strftime("%H:%M:%S"))
    st.markdown(f'<div class="dash-footer">LAST UPDATE: {ts} · AUTO-REFRESH: 5s · AGRISETU v2.0</div>', unsafe_allow_html=True)

    time.sleep(5)
    st.rerun()


if __name__ == "__main__":
    main()
