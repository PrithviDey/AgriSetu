/* ======================================================================
   AgriSetu — Dashboard Application
   WebSocket → live state → charts, topology, tables, Q-table heatmap
   ====================================================================== */

const API  = 'http://localhost:8000';
const WS_URL = 'ws://localhost:8000/ws';

// ── Global state ─────────────────────────────────────────────────────────────
let state       = null;   // latest snapshot from backend
let ws          = null;
let reconnectTimer = null;

// ── Offline detection state ───────────────────────────────────────────────────
let prevNodeStates = {};  // node_id → online boolean (previous frame)

// ── Sparkline history ─────────────────────────────────────────────────────────
const hist = {
  pdr: [], cr: [], energy: [], nodes: [],
  reward: [],
};
const MAX_HIST = 60;

function pushHist(key, val) {
  hist[key].push(val);
  if (hist[key].length > MAX_HIST) hist[key].shift();
}

// ── Chart instances ───────────────────────────────────────────────────────────
let benchmarkChart, rewardChart, actionPieChart;
let sparkPDR, sparkCR, sparkEnergy, sparkCrit, sparkNodes;
let qtableCtx;

// ── Date/time header ──────────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  document.getElementById('headerDate').textContent =
    now.toLocaleDateString('en-IN', { day:'2-digit', month:'short', year:'numeric' }) +
    ' • ' +
    now.toLocaleTimeString('en-IN', { hour:'2-digit', minute:'2-digit', hour12:true });
}
setInterval(updateClock, 1000);
updateClock();

// ═════════════════════════════════════════════════════════════════════════════
//  WEBSOCKET
// ═════════════════════════════════════════════════════════════════════════════
function connectWS() {
  setWsStatus('connecting');
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    setWsStatus('connected');
    clearTimeout(reconnectTimer);
  };

  ws.onmessage = (e) => {
    try {
      state = JSON.parse(e.data);
      updateAll(state);
    } catch (err) { console.error('updateAll error:', err); }
  };

  ws.onclose = () => {
    setWsStatus('error');
    reconnectTimer = setTimeout(connectWS, 3000);
  };

  ws.onerror = () => ws.close();
}

function setWsStatus(s) {
  const dot   = document.getElementById('wsDot');
  const label = document.getElementById('wsLabel');
  dot.className = 'ws-dot ' + (s === 'connected' ? 'connected' : s === 'error' ? 'error' : '');
  label.textContent = { connected:'Live', error:'Reconnecting…', connecting:'Connecting…' }[s] || s;
}

// ═════════════════════════════════════════════════════════════════════════════
//  MASTER UPDATE
// ═════════════════════════════════════════════════════════════════════════════
function updateAll(s) {
  const nodes = s.nodes || [];
  const alerts = s.alerts || [];
  const logs = s.logs || [];
  
  updateStats(s.metrics, nodes);
  updateGateway(s.gateway);
  updateChannel(s.channel);
  updateTopology(nodes);
  updateAlerts(alerts, s.metrics.critical_alerts);
  updateNodeGrid(nodes);
  updateBenchmark(s.benchmark);
  updateRL(s.rl, s.channel);
  updateLogs(logs);
  updateRecentPackets(logs);
}

// ═════════════════════════════════════════════════════════════════════════════
//  STATS CARDS
// ═════════════════════════════════════════════════════════════════════════════
function updateStats(m, nodes) {
  // ── Real-time offline detection ──────────────────────────────────────────
  if (nodes && nodes.length) {
    nodes.forEach(n => {
      const wasOnline = prevNodeStates[n.node_id];
      const isOnline  = !!n.online;
      if (wasOnline === true && !isOnline) {
        toast(`⚠ Node ${n.node_id} went OFFLINE!`, 'error');
        // Flash the node count card red
        const card = document.querySelector('.stat-card.green');
        if (card) {
          card.style.outline = '2.5px solid #EF4444';
          setTimeout(() => { card.style.outline = ''; }, 3000);
        }
      } else if (wasOnline === false && isOnline) {
        toast(`✓ Node ${n.node_id} is back ONLINE`, 'success');
      }
      prevNodeStates[n.node_id] = isOnline;
    });
  }

  // Use actual computed count from node list, not backend metric (which may lag)
  const realOnline = nodes ? nodes.filter(n => !!n.online).length : m.active_nodes;
  const realTotal  = nodes ? nodes.length : m.total_nodes;

  // ── Offline banner ────────────────────────────────────────────────────────
  const offlineNodes = nodes ? nodes.filter(n => !n.online) : [];
  const banner      = document.getElementById('offlineBanner');
  const bannerText  = document.getElementById('offlineBannerText');
  if (banner) {
    if (offlineNodes.length > 0) {
      banner.style.display = 'flex';
      const names = offlineNodes.map(n => `Node ${n.node_id}`).join(', ');
      if (bannerText) bannerText.textContent = `⚠ Offline: ${names} — not transmitting data`;
    } else {
      banner.style.display = 'none';
    }
  }

  setText('statActiveNodes', realOnline);
  setText('statTotalNodes',  realTotal);
  setText('statNodesPct',    `${realTotal > 0 ? Math.round(realOnline / realTotal * 100) : 0}% Online`);
  setText('statPDR',         (m.pdr != null ? m.pdr : 0).toFixed(1));
  setText('statCR',          (m.collision_rate != null ? m.collision_rate : 0).toFixed(1));
  setText('statEnergy',      (m.avg_energy != null ? m.avg_energy : 0).toFixed(1));
  setText('statCritical',    m.critical_alerts);
  setText('critCount',       m.critical_alerts);
  setText('alertBadge',      m.critical_alerts);

  // Environmental Telemetry Selection
  const select = document.getElementById('envNodeSelect');
  const selVal = select ? select.value : 'avg';

  if (nodes && nodes.length > 0) {
    const active = nodes.filter(n => n.online);
    
    // Update select options (preserve selection)
    if (select) {
      let html = '<option value="avg">Network Average</option>';
      nodes.forEach(n => {
        const lbl = n.online ? `Node ${n.node_id}` : `Node ${n.node_id} (Offline)`;
        html += `<option value="${n.node_id}" ${n.node_id == selVal ? 'selected' : ''}>${lbl}</option>`;
      });
      select.innerHTML = html;
    }

    if (selVal === 'avg') {
      const nCnt = active.length || 1;
      let s=0, t=0, h=0, r=0;
      active.forEach(n => {
        s += (n.soil || 0); t += (n.temp || 0); h += (n.hum || 0); r += (n.rain || 0);
      });
      setText('statSoil', (s/nCnt).toFixed(1));
      setText('statTemp', (t/nCnt).toFixed(1));
      setText('statHum',  (h/nCnt).toFixed(1));
      setText('statRain', (r/nCnt).toFixed(1));

      setText('lblSoil', 'Avg Soil Moisture');
      setText('lblTemp', 'Avg Temperature');
      setText('lblHum',  'Avg Humidity');
      setText('lblRain', 'Rainfall (Avg)');
      
      const foot = 'Across all nodes';
      setText('footSoil', foot); setText('footTemp', foot); setText('footHum', foot); setText('footRain', foot);
    } else {
      const n = nodes.find(n => n.node_id == selVal);
      if (n) {
        setText('statSoil', (n.soil || 0).toFixed(1));
        setText('statTemp', (n.temp || 0).toFixed(1));
        setText('statHum',  (n.hum || 0).toFixed(1));
        setText('statRain', (n.rain || 0).toFixed(1));

        setText('lblSoil', `Node ${n.node_id} Soil`);
        setText('lblTemp', `Node ${n.node_id} Temp`);
        setText('lblHum',  `Node ${n.node_id} Hum`);
        setText('lblRain', `Node ${n.node_id} Rain`);
        
        const foot = n.online ? 'Live reading' : 'Last known reading (offline)';
        setText('footSoil', foot); setText('footTemp', foot); setText('footHum', foot); setText('footRain', foot);
      }
    }
  } else {
    setText('statSoil', '—');
    setText('statTemp', '—');
    setText('statHum',  '—');
    setText('statRain', '—');
  }

  const pdrDelta = m.pdr_delta || 0;
  const crDelta  = m.cr_delta  || 0;
  setDelta('statPDRDelta', pdrDelta, true,  `+${pdrDelta.toFixed(1)}% vs ALOHA`);
  setDelta('statCRDelta',  crDelta,  true,  `↓${crDelta.toFixed(1)}% vs ALOHA`);

  pushHist('pdr',   m.pdr);
  pushHist('cr',    m.collision_rate);
  pushHist('energy',m.avg_energy);
  pushHist('nodes', m.active_nodes);

  updateSparkline(sparkPDR,    hist.pdr,    '#3B82F6');
  updateSparkline(sparkCR,     hist.cr,     '#F59E0B');
  updateSparkline(sparkEnergy, hist.energy, '#8B5CF6');
  updateSparkline(sparkNodes,  hist.nodes,  '#22C55E');
}

function setDelta(id, val, positiveIsGood, txt) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = txt;
  el.className   = 'stat-delta ' + (val >= 0 ? (positiveIsGood ? 'up' : 'down') : (positiveIsGood ? 'down' : 'up'));
}

// ═════════════════════════════════════════════════════════════════════════════
//  GATEWAY
// ═════════════════════════════════════════════════════════════════════════════
function updateGateway(gw) {
  setText('gwStatus', gw.online ? 'Online' : 'Offline');
  setText('gwUptime', 'Uptime: ' + gw.uptime_str);
}

// ═════════════════════════════════════════════════════════════════════════════
//  CHANNEL CONDITIONS
// ═════════════════════════════════════════════════════════════════════════════
const BADGE_CLASS = { Good:'badge-good', Medium:'badge-medium', High:'badge-high',
                      Poor:'badge-poor', Low:'badge-low', VeryHigh:'badge-veryhigh' };

function updateChannel(ch) {
  setText('chRSSI',    ch.rssi + ' dBm');
  setText('chSF',      ch.sf);
  setText('chCR',      ch.cr);
  setText('chEntropy', ch.entropy);

  setBadge('chRSSIBadge',    ch.rssi_label);
  setBadge('chSFBadge',      ch.sf_label);
  setBadge('chCRBadge',      ch.cr_label);
  setBadge('chEntropyBadge', ch.entropy_label);
}

function setBadge(id, label) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent  = label;
  el.className    = 'channel-badge ' + (BADGE_CLASS[label] || 'badge-medium');
}

// ═════════════════════════════════════════════════════════════════════════════
//  NETWORK TOPOLOGY CANVAS — with animated data packets
// ═════════════════════════════════════════════════════════════════════════════
const topoCanvas = document.getElementById('topoCanvas');
const topoCtx    = topoCanvas.getContext('2d');

// Animation state
let topoNodes      = [];      // latest node list
let topoAnimFrame  = null;    // requestAnimationFrame handle
let topoPackets    = [];      // [ { nodeId, t, color } ]  t ∈ [0,1]
let lastPacketTime = 0;

function spawnPacket(nodeId) {
  topoPackets.push({ nodeId, t: 0, color: '#22C55E' });
}

function topoAnimLoop(timestamp) {
  const dt = 0.016; // ~60fps tick size (fraction of path per frame)
  // Spawn a new packet every 700ms from a random online node
  if (timestamp - lastPacketTime > 700 && topoNodes.length) {
    const onlineNodes = topoNodes.filter(n => n.online !== false);
    if (onlineNodes.length) {
      const pick = onlineNodes[Math.floor(Math.random() * onlineNodes.length)];
      spawnPacket(pick.node_id);
      lastPacketTime = timestamp;
    }
  }

  // Advance packets
  topoPackets = topoPackets.map(p => ({ ...p, t: p.t + dt * 0.9 })).filter(p => p.t < 1.05);

  drawTopologyFrame();
  topoAnimFrame = requestAnimationFrame(topoAnimLoop);
}

function startTopoAnimation() {
  if (topoAnimFrame) return;
  topoAnimFrame = requestAnimationFrame(topoAnimLoop);
}

function updateTopology(nodes) {
  // Flush packets belonging to nodes that no longer exist
  const currentIds = new Set(nodes.map(n => n.node_id));
  topoPackets = topoPackets.filter(p => currentIds.has(p.nodeId));

  topoNodes = nodes;
  if (!topoAnimFrame) startTopoAnimation();

  // Update footer stats immediately
  const realOnline = nodes.filter(n => n.online !== false).length;
  const el = document.getElementById('topoNodeCount');
  if (el) el.textContent = realOnline + '/' + nodes.length + ' Nodes Online';

  const avgRSSI = nodes.length
    ? nodes.reduce((sum, n) => sum + (n.rssi || 0), 0) / nodes.length
    : 0;
  const sigEl = document.getElementById('topoSignal');
  if (sigEl) {
    if (avgRSSI > -60) sigEl.textContent = 'Strong Signal';
    else if (avgRSSI > -80) sigEl.textContent = 'Good Signal';
    else sigEl.textContent = 'Weak Signal';
  }
}

function drawTopologyFrame() {
  const dpr = window.devicePixelRatio || 1;
  const W   = topoCanvas.clientWidth;
  const H   = topoCanvas.clientHeight;
  if (!W || !H) return;
  if (topoCanvas.width !== W * dpr || topoCanvas.height !== H * dpr) {
    topoCanvas.width  = W * dpr;
    topoCanvas.height = H * dpr;
  }
  const ctx = topoCtx;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const nodes = topoNodes;
  if (!nodes || !nodes.length) return;

  // Gateway position — left center
  const gx = W * 0.22;
  const gy = H * 0.5;

  // Display all actual nodes (not hardcoded to 4)
  const displayNodes = nodes;
  const totalNodes   = displayNodes.length || 1;

  // Node positions — right side, fanned vertically
  const nodePositions = displayNodes.map((n, i) => {
    const fraction = totalNodes === 1 ? 0.5 : i / (totalNodes - 1);
    const nx = W * 0.72;
    const ny = H * 0.12 + fraction * (H * 0.76);
    return { nx, ny, n };
  });

  // ── Helper: bezier point at t ──────────────────────────────────────────────
  function bezierPoint(t, x0, y0, cx1, cy1, cx2, cy2, x3, y3) {
    const mt = 1 - t;
    return {
      x: mt*mt*mt*x0 + 3*mt*mt*t*cx1 + 3*mt*t*t*cx2 + t*t*t*x3,
      y: mt*mt*mt*y0 + 3*mt*mt*t*cy1 + 3*mt*t*t*cy2 + t*t*t*y3,
    };
  }

  // Draw connector lines (curved bezier)
  nodePositions.forEach(({ nx, ny, n }) => {
    const online = n.online !== false;
    const cpx    = gx + (nx - gx) * 0.55;

    ctx.beginPath();
    ctx.moveTo(gx + 28, gy);
    ctx.bezierCurveTo(cpx, gy, cpx, ny, nx - 26, ny);

    if (online) {
      ctx.strokeStyle = 'rgba(22,163,74,0.45)';
      ctx.lineWidth   = 1.8;
      ctx.setLineDash([6, 4]);
    } else {
      ctx.strokeStyle = 'rgba(156,163,175,0.35)';
      ctx.lineWidth   = 1.2;
      ctx.setLineDash([4, 5]);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    // Arrowhead at node end
    ctx.save();
    ctx.translate(nx - 26, ny);
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(-8, -4.5);
    ctx.lineTo(-8, 4.5);
    ctx.closePath();
    ctx.fillStyle = online ? 'rgba(22,163,74,0.6)' : 'rgba(156,163,175,0.5)';
    ctx.fill();
    ctx.restore();
  });

  // ── Build a lookup from node_id → position ─────────────────────────────────
  const posById = {};
  nodePositions.forEach(({ nx, ny, n }) => { posById[n.node_id] = { nx, ny }; });

  // ── Draw animated data packets ─────────────────────────────────────────────
  topoPackets.forEach(pkt => {
    const target = posById[pkt.nodeId];
    if (!target) return;  // node was removed — skip this packet
    const { nx, ny } = target;
    const cpx = gx + (nx - gx) * 0.55;
    // Packet travels from node → gateway (t: 0=node, 1=gateway)
    const rt  = 1 - Math.min(pkt.t, 1);
    const pos = bezierPoint(rt, gx + 28, gy, cpx, gy, cpx, ny, nx - 26, ny);
    const alpha = pkt.t > 0.85 ? (1 - pkt.t) / 0.15 : 1;

    ctx.save();
    ctx.globalAlpha = alpha;
    // Glow
    ctx.shadowColor = '#22C55E';
    ctx.shadowBlur  = 10;
    // Packet dot
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#22C55E';
    ctx.fill();
    // Inner bright core
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, 2.5, 0, Math.PI * 2);
    ctx.fillStyle = '#FFFFFF';
    ctx.fill();
    ctx.shadowBlur  = 0;
    ctx.restore();
  });

  // Draw nodes
  nodePositions.forEach(({ nx, ny, n }) => {
    const clr    = nodeColor(n);
    const online = n.online !== false;
    const r      = 20;

    // Outer pulse ring
    ctx.beginPath();
    ctx.arc(nx, ny, r + 9, 0, Math.PI * 2);
    ctx.strokeStyle = online ? 'rgba(22,163,74,0.12)' : 'rgba(156,163,175,0.12)';
    ctx.lineWidth   = 10;
    ctx.stroke();

    // Middle ring
    ctx.beginPath();
    ctx.arc(nx, ny, r + 3, 0, Math.PI * 2);
    ctx.strokeStyle = online ? 'rgba(22,163,74,0.22)' : 'rgba(156,163,175,0.18)';
    ctx.lineWidth   = 3;
    ctx.stroke();

    // Node circle fill
    const grad = ctx.createRadialGradient(nx - 5, ny - 5, 2, nx, ny, r);
    grad.addColorStop(0, online ? '#FFFFFF' : '#F3F4F6');
    grad.addColorStop(1, online ? '#F0FDF4' : '#E5E7EB');
    ctx.beginPath();
    ctx.arc(nx, ny, r, 0, Math.PI * 2);
    ctx.fillStyle = grad;
    ctx.fill();
    ctx.strokeStyle = online ? 'rgba(22,163,74,0.45)' : 'rgba(156,163,175,0.4)';
    ctx.lineWidth   = 1.5;
    ctx.stroke();

    // LoRa wave arcs inside node
    ctx.strokeStyle = online ? '#16A34A' : '#9CA3AF';
    ctx.lineWidth   = 1.5;
    [-1, 0, 1].forEach(offset => {
      const ar = 5 + (offset + 1) * 4;
      ctx.beginPath();
      ctx.arc(nx, ny, ar, -Math.PI * 0.6, Math.PI * 0.6);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(nx, ny, ar, Math.PI + Math.PI * 0.4, 2 * Math.PI - Math.PI * 0.4);
      ctx.stroke();
    });
    ctx.beginPath();
    ctx.arc(nx, ny, 2.5, 0, Math.PI * 2);
    ctx.fillStyle = online ? '#16A34A' : '#9CA3AF';
    ctx.fill();

    // Status indicator dot (top-right of node)
    ctx.beginPath();
    ctx.arc(nx + r - 2, ny - r + 2, 5, 0, Math.PI * 2);
    ctx.fillStyle = clr;
    ctx.fill();
    ctx.strokeStyle = '#FFFFFF';
    ctx.lineWidth   = 2;
    ctx.stroke();

    // ── Offline overlay ────────────────────────────────────────────────────
    if (!online) {
      ctx.save();
      ctx.globalAlpha = 0.45;
      ctx.fillStyle   = '#F3F4F6';
      ctx.beginPath();
      ctx.arc(nx, ny, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
      // ✕ mark
      ctx.strokeStyle = '#EF4444';
      ctx.lineWidth   = 2;
      ctx.beginPath();
      ctx.moveTo(nx - 7, ny - 7); ctx.lineTo(nx + 7, ny + 7);
      ctx.moveTo(nx + 7, ny - 7); ctx.lineTo(nx - 7, ny + 7);
      ctx.stroke();
    }

    // Label to the right of node
    const lx = nx + r + 10;
    ctx.font         = 'bold 11.5px Inter, sans-serif';
    ctx.textAlign    = 'left';
    ctx.textBaseline = 'middle';

    // Node name
    ctx.fillStyle = '#111827';
    ctx.fillText('N' + n.node_id, lx, ny - 9);

    // Status
    ctx.font      = '10px Inter, sans-serif';
    ctx.fillStyle = online ? '#16A34A' : '#EF4444';
    ctx.fillText(online ? '● Online' : '✕ Offline', lx, ny + 4);

    // RSSI
    ctx.fillStyle = '#6B7280';
    ctx.fillText('RSSI: ' + n.rssi + ' dBm', lx, ny + 17);

    // Noise level (potentiometer)
    const noiseLbls = ['Low', 'Med', 'High', 'V.High'];
    const noiseClrs = ['#22C55E', '#F59E0B', '#F97316', '#EF4444'];
    const nl = n.noise_level || 0;
    ctx.fillStyle = noiseClrs[nl];
    ctx.fillText('Noise: ' + noiseLbls[nl], lx, ny + 29);
  });

  // Draw Gateway
  const gwR = 30;

  // Outer glow rings
  ctx.beginPath();
  ctx.arc(gx, gy, gwR + 18, 0, Math.PI * 2);
  ctx.strokeStyle = 'rgba(22,163,74,0.1)';
  ctx.lineWidth   = 12;
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(gx, gy, gwR + 7, 0, Math.PI * 2);
  ctx.strokeStyle = 'rgba(22,163,74,0.2)';
  ctx.lineWidth   = 5;
  ctx.stroke();

  // GW fill
  const gwGrad = ctx.createRadialGradient(gx - 7, gy - 7, 4, gx, gy, gwR);
  gwGrad.addColorStop(0, '#2D6A4F');
  gwGrad.addColorStop(1, '#1B4332');
  ctx.beginPath();
  ctx.arc(gx, gy, gwR, 0, Math.PI * 2);
  ctx.fillStyle   = gwGrad;
  ctx.shadowColor = 'rgba(22,163,74,0.45)';
  ctx.shadowBlur  = 18;
  ctx.fill();
  ctx.shadowBlur  = 0;
  ctx.strokeStyle = 'rgba(255,255,255,0.25)';
  ctx.lineWidth   = 2;
  ctx.stroke();

  // GW text
  ctx.fillStyle    = '#FFFFFF';
  ctx.font         = 'bold 12px Inter, sans-serif';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('GW', gx, gy);
}

function nodeColor(n) {
  if (!n.online)        return '#9CA3AF';
  if (n.pdr < 50)       return '#EF4444';
  if (n.battery < 20)   return '#F59E0B';
  return '#22C55E';
}
function lerp(a, b, t) { return Math.round(a + (b - a) * t); }

// ═════════════════════════════════════════════════════════════════════════════
//  ALERTS TABLE
// ═════════════════════════════════════════════════════════════════════════════
const ACTION_NAMES = ['TX Now', 'Wait 1', 'Wait 2', 'Wait 4', 'Wait 8'];
const SEV_CLASS    = { critical:'sev-critical', high:'sev-high', medium:'sev-medium', low:'sev-low' };

function updateAlerts(alerts, critCount) {
  const tbody = document.getElementById('alertsTableBody');
  setText('alertCountBadge', `${alerts.length} alerts`);
  if (!alerts.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px">No alerts — system normal</td></tr>';
    return;
  }
  tbody.innerHTML = alerts.slice(0, 20).map(a => `
    <tr>
      <td>${a.time}</td>
      <td><strong>Node ${a.node_id}</strong></td>
      <td><span class="severity-badge ${SEV_CLASS[a.severity] || 'sev-low'}">${a.severity}</span></td>
      <td>${a.message}</td>
    </tr>
  `).join('');
}

function updateRecentPackets(logs) {
  const tbody = document.getElementById('packetsTableBody');
  if (!tbody) return;
  if (!logs.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);padding:24px">Waiting for data...</td></tr>';
    return;
  }
  
  tbody.innerHTML = logs.slice(0, 10).map(l => {
    const status = l.success
      ? '<span style="color:var(--success);font-weight:600">✓ OK</span>'
      : '<span style="color:var(--danger);font-weight:600">✗ Drop</span>';
    const priBg  = { normal:'#DCFCE7', warning:'#FEF3C7', critical:'#FEE2E2' }[l.priority] || '#F3F4F6';
    const priClr = { normal:'#16A34A', warning:'#D97706', critical:'#DC2626' }[l.priority] || '#6B7280';
    return `
    <tr>
      <td><strong>N${l.node_id}</strong></td>
      <td>${status}</td>
      <td><span style="background:${priBg};color:${priClr};padding:2px 8px;border-radius:99px;font-size:10px;font-weight:600">${l.priority}</span></td>
      <td>${l.latency.toFixed(1)}ms</td>
    </tr>`;
  }).join('');
}

// ═════════════════════════════════════════════════════════════════════════════
//  NODE GRID
// ═════════════════════════════════════════════════════════════════════════════
function updateNodeGrid(nodes) {
  const grid = document.getElementById('nodeGrid');
  grid.innerHTML = nodes.map(n => {
    const bat  = n.battery != null ? n.battery : 0;
    const batC = bat > 60 ? '#22C55E' : bat > 30 ? '#F59E0B' : '#EF4444';
    const cls  = n.online ? '' : 'offline';
    return `
    <div class="node-card ${cls}" title="Node ${n.node_id}">
      <div class="node-card-header">
        <div class="node-id">Node ${n.node_id < 10 ? '0' : ''}${n.node_id}</div>
        <div class="node-status-dot ${n.online ? 'dot-online' : 'dot-offline'}"></div>
      </div>
      <div class="node-battery-bar">
        <div class="node-battery-fill" style="width:${bat}%;background:${batC}"></div>
      </div>
      <div class="node-stat-row">
        <span class="node-stat-label">Battery</span>
        <span class="node-stat-val" style="color:${batC}">${bat.toFixed(0)}%</span>
      </div>
      <div class="node-stat-row">
        <span class="node-stat-label">RSSI</span>
        <span class="node-stat-val">${n.rssi} dBm</span>
      </div>
      <div class="node-stat-row">
        <span class="node-stat-label">PDR</span>
        <span class="node-stat-val" style="color:${n.pdr>80?'var(--success)':n.pdr>50?'var(--warning)':'var(--danger)'}">${n.pdr}%</span>
      </div>
      <div class="node-stat-row">
        <span class="node-stat-label">SF / CR</span>
        <span class="node-stat-val">SF${n.sf} / ${n.cr}</span>
      </div>
      <div class="node-stat-row">
        <span class="node-stat-label">Soil / Temp</span>
        <span class="node-stat-val">${(n.soil||0).toFixed(1)}% / ${(n.temp||0).toFixed(1)}°C</span>
      </div>
      <div class="node-stat-row">
        <span class="node-stat-label">Hum / Rain</span>
        <span class="node-stat-val">${(n.hum||0).toFixed(1)}% / ${(n.rain||0).toFixed(1)}mm</span>
      </div>
      <div class="node-stat-row">
        <span class="node-stat-label">Noise Level</span>
        <span class="node-stat-val" style="color:${['#22C55E','#F59E0B','#F97316','#EF4444'][n.noise_level||0]}">${['Low','Medium','High','V.High'][n.noise_level||0]}</span>
      </div>
      <div class="node-stat-row">
        <span class="node-stat-label">Sent / OK</span>
        <span class="node-stat-val">${n.packets_sent} / ${n.packets_success}</span>
      </div>
    </div>`;
  }).join('');
}



// ═════════════════════════════════════════════════════════════════════════════
//  BENCHMARK CHART
// ═════════════════════════════════════════════════════════════════════════════
function updateBenchmark(bm) {
  if (benchmarkChart) return;  // only draw once (static data)
  benchmarkChart = new Chart(document.getElementById('benchmarkChart'), {
    type: 'line',
    data: {
      labels: bm.densities,
      datasets: [
        lineDS('AgriSetu (Q-Learning)', bm.agrisetu_pdr, '#40916C', false),
        lineDS('Standard ALOHA',        bm.aloha_pdr,    '#94A3B8', true),
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { labels: { font: { family:'Inter', size:12 }, color:'#3D6350' } },
        tooltip: { mode:'index', intersect:false },
      },
      scales: {
        x: {
          title: { display:true, text:'Node Density (Nodes)', color:'#7A9E8A', font:{size:11} },
          grid:  { color:'#EAF4EC' },
          ticks: { color:'#7A9E8A', font:{size:11} },
          type: 'logarithmic',
        },
        y: {
          min: 0, max: 100,
          title: { display:true, text:'PDR (%)', color:'#7A9E8A', font:{size:11} },
          grid:  { color:'#EAF4EC' },
          ticks: { color:'#7A9E8A', font:{size:11}, callback: v => v+'%' },
        }
      },
      elements: { point: { radius:4, hoverRadius:6 } },
      interaction: { mode:'nearest', axis:'x', intersect:false },
    },
  });
}

// ═════════════════════════════════════════════════════════════════════════════
//  Q-LEARNING PANEL
// ═════════════════════════════════════════════════════════════════════════════
function updateRL(rl, ch) {
  setText('rlAvgReward', rl.avg_reward > 0 ? '+' + rl.avg_reward : rl.avg_reward);
  setText('rlUpdates',   rl.update_count.toLocaleString());
  setText('rlEpsilon2',  rl.epsilon.toFixed(3));
  setText('rlAlpha',     rl.alpha);

  // Live state vector display
  setText('qlStateVec',   `${ch.rssi_label[0]},${ch.sf_label[0]},${ch.cr_label[0]},${ch.entropy_label[0]}`);
  const bestAction = (rl.action_counts.indexOf(Math.max(...rl.action_counts)));
  setText('qlActionName', ACTION_NAMES[bestAction] || '—');
  setText('qlEpsilon',    rl.epsilon.toFixed(3));

  // Reward chart
  pushHist('reward', rl.avg_reward);
  const rLabels = hist.reward.map((_, i) => i);
  if (!rewardChart) {
    rewardChart = new Chart(document.getElementById('rewardChart'), {
      type: 'line',
      data: {
        labels: rLabels,
        datasets: [lineDS('Avg Reward', hist.reward, '#40916C', false)],
      },
      options: chartOpts('Avg Reward'),
    });
  } else {
    rewardChart.data.labels   = rLabels;
    rewardChart.data.datasets[0].data = [...hist.reward];
    rewardChart.update('none');
  }

  // Action distribution pie
  const totalActions = rl.action_counts.reduce((a, b) => a + b, 0) || 1;
  const pieData      = rl.action_counts.map(c => Math.round(c / totalActions * 100));
  if (!actionPieChart) {
    actionPieChart = new Chart(document.getElementById('actionPieChart'), {
      type: 'doughnut',
      data: {
        labels: ACTION_NAMES,
        datasets: [{
          data: pieData,
          backgroundColor: ['#40916C','#52B788','#74C69D','#95D5B2','#B7E4C7'],
          borderWidth: 2, borderColor: '#fff',
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position:'bottom', labels:{ font:{family:'Inter',size:10}, color:'#3D6350', boxWidth:10 } },
        },
        cutout: '65%',
      },
    });
  } else {
    actionPieChart.data.datasets[0].data = pieData;
    actionPieChart.update('none');
  }

  // Action bars
  const bars = document.getElementById('actionBars');
  bars.innerHTML = ACTION_NAMES.map((name, i) => {
    const pct = Math.round(rl.action_counts[i] / totalActions * 100);
    return `
    <div class="action-bar-row">
      <span class="action-bar-label">A${i}</span>
      <div class="action-bar-track">
        <div class="action-bar-fill" style="width:${pct}%"></div>
      </div>
      <span class="action-bar-pct">${pct}%</span>
    </div>`;
  }).join('');

  // Q-table heatmap
  drawQTable(rl.q_table);
}

function drawQTable(qtable) {
  const canvas = document.getElementById('qtableCanvas');
  const dpr    = window.devicePixelRatio || 1;
  const W      = canvas.clientWidth;
  const H      = canvas.clientHeight || 200;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  if (!qtable || !qtable.length) return;

  const rows    = qtable.length;    // 108
  const cols    = qtable[0].length; // 5
  const cW      = W / cols;
  const cH      = H / rows;

  // Find global min/max for colour scale
  let mn = Infinity, mx = -Infinity;
  qtable.forEach(row => row.forEach(v => { if (v < mn) mn = v; if (v > mx) mx = v; }));
  const range = mx - mn || 1;

  qtable.forEach((row, r) => {
    row.forEach((val, c) => {
      const t   = (val - mn) / range;
      const red = Math.round(255 * (1 - t));
      const grn = Math.round(180 + 75 * t);
      const blu = Math.round(100 * (1 - t));
      ctx.fillStyle = `rgb(${red},${grn},${blu})`;
      ctx.fillRect(c * cW, r * cH, cW, cH);
    });
  });

  // Column labels
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.font      = 'bold 10px Inter';
  ctx.textAlign = 'center';
  ACTION_NAMES.forEach((name, c) => {
    ctx.fillText(name, c * cW + cW / 2, 14);
  });

  // Hover tooltip
  canvas.onmousemove = (e) => {
    const rect = canvas.getBoundingClientRect();
    const mx   = e.clientX - rect.left;
    const my   = e.clientY - rect.top;
    const col  = Math.floor(mx / (W / cols));
    const row  = Math.floor(my / (H / rows));
    if (row >= 0 && row < rows && col >= 0 && col < cols) {
      const v = qtable[row][col];
      setText('qtableHover', `State #${row} | Action: ${ACTION_NAMES[col]} | Q-value: ${v.toFixed(4)}`);
    }
  };
}

// ═════════════════════════════════════════════════════════════════════════════
//  LOGS TABLE
// ═════════════════════════════════════════════════════════════════════════════
let logsCache = [];

function updateLogs(logs) {
  logsCache = logs;
  const tbody = document.getElementById('logsTableBody');
  if (!logs.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:24px">No packets yet</td></tr>';
    return;
  }
  tbody.innerHTML = logs.slice(0, 50).map(l => {
    const cls    = l.success ? 'log-row-success' : 'log-row-collision';
    const result = l.success
      ? '<span style="color:var(--success);font-weight:600">✓ Success</span>'
      : '<span style="color:var(--danger);font-weight:600">✗ Collision</span>';
    const priBg  = { normal:'#DCFCE7', warning:'#FEF3C7', critical:'#FEE2E2' }[l.priority] || '#F3F4F6';
    const priClr = { normal:'#16A34A', warning:'#D97706', critical:'#DC2626' }[l.priority] || '#6B7280';
    const ts     = new Date(l.timestamp * 1000).toLocaleTimeString('en-IN', { hour12:true });
    return `
    <tr class="${cls}">
      <td>#${l.pkt_id}</td>
      <td>Node ${l.node_id}</td>
      <td><span style="background:${priBg};color:${priClr};padding:2px 8px;border-radius:99px;font-size:10px;font-weight:600">${l.priority}</span></td>
      <td>${ACTION_NAMES[l.action] || l.action}</td>
      <td>${result}</td>
      <td>${(l.energy * 1000).toFixed(2)}</td>
      <td>${l.latency.toFixed(1)}</td>
      <td>${ts}</td>
    </tr>`;
  }).join('');
}

function exportLogs() {
  const headers = ['pkt_id','node_id','priority','action','success','energy','latency','timestamp'];
  const rows    = logsCache.map(l => headers.map(h => l[h]).join(','));
  const csv     = [headers.join(','), ...rows].join('\n');
  const blob    = new Blob([csv], { type:'text/csv' });
  const url     = URL.createObjectURL(blob);
  const a       = Object.assign(document.createElement('a'), { href:url, download:'agrisetu_logs.csv' });
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
  toast('Logs exported as CSV', 'success');
}

// ═════════════════════════════════════════════════════════════════════════════
//  SPARKLINES (mini inline charts)
// ═════════════════════════════════════════════════════════════════════════════
function makeSparkline(id, color) {
  return new Chart(document.getElementById(id), {
    type: 'line',
    data: { labels: [], datasets: [{ data: [], borderColor: color, borderWidth: 1.5,
      fill: true, backgroundColor: color + '22', tension: 0.4,
      pointRadius: 0, pointHoverRadius: 0 }] },
    options: {
      responsive: false, maintainAspectRatio: false,
      animation: false,
      plugins: { legend:{ display:false }, tooltip:{ enabled:false } },
      scales: { x:{ display:false }, y:{ display:false } },
    }
  });
}

function updateSparkline(chart, data, color) {
  if (!chart) return;
  chart.data.labels   = data.map((_, i) => i);
  chart.data.datasets[0].data          = [...data];
  chart.data.datasets[0].borderColor   = color;
  chart.data.datasets[0].backgroundColor = color + '22';
  chart.update('none');
}

// ═════════════════════════════════════════════════════════════════════════════
//  CHART HELPERS
// ═════════════════════════════════════════════════════════════════════════════
function lineDS(label, data, color, dashed) {
  return {
    label, data: [...data], borderColor: color, borderWidth: 2,
    backgroundColor: color + '18',
    fill: true, tension: 0.4,
    pointRadius: 0, pointHoverRadius: 4,
    borderDash: dashed ? [5,5] : [],
  };
}

function chartOpts(yLabel, yMin = undefined, yMax = undefined) {
  const yScale = {
    grid:  { color:'#EAF4EC' },
    ticks: { color:'#7A9E8A', font:{ family:'Inter', size:11 } },
    title: { display:!!yLabel, text:yLabel, color:'#7A9E8A', font:{size:11} },
  };
  if (yMin !== undefined) yScale.min = yMin;
  if (yMax !== undefined) yScale.max = yMax;
  return {
    responsive: true, maintainAspectRatio: false,
    animation: { duration: 200 },
    plugins: {
      legend: { labels:{ font:{ family:'Inter', size:11 }, color:'#3D6350', boxWidth:12 } },
      tooltip: { mode:'index', intersect:false, bodyFont:{ family:'Inter', size:11 } },
    },
    scales: {
      x: { grid:{ color:'#EAF4EC' }, ticks:{ color:'#7A9E8A', font:{ family:'Inter', size:10 }, maxTicksLimit:8 } },
      y: yScale,
    },
    interaction: { mode:'nearest', axis:'x', intersect:false },
  };
}

// ═════════════════════════════════════════════════════════════════════════════
//  HARDWARE / ESP32 SERIAL BRIDGE
// ═════════════════════════════════════════════════════════════════════════════

// Update HW status badge from every snapshot
function updateHardwareStatus(hw) {
  if (!hw) return;
  const badge = document.getElementById('hwStatusBadge');
  const info  = document.getElementById('hwStatusInfo');
  const btnC  = document.getElementById('btnHwConnect');
  const btnD  = document.getElementById('btnHwDisconnect');

  if (badge) {
    badge.textContent = hw.connected ? 'Connected' : 'Disconnected';
    badge.style.background = hw.connected ? '#DCFCE7' : '#FEE2E2';
    badge.style.color      = hw.connected ? '#16A34A' : '#DC2626';
  }
  if (info) {
    info.style.display = hw.connected ? 'block' : 'none';
    setText('hwInfoPort', hw.port || '—');
    setText('hwInfoBaud', hw.baud || '—');
    setText('hwInfoRx',   hw.rx_count ?? 0);
    setText('hwInfoLast', hw.last_rx_sec != null ? `${hw.last_rx_sec}s ago` : '—');
    setText('hwInfoErr',  hw.err_count ?? 0);
    setText('hwInfoQ',    hw.queue_depth ?? 0);
    const errEl = document.getElementById('hwInfoError');
    if (errEl) {
      errEl.style.display = hw.error ? 'block' : 'none';
      errEl.textContent   = hw.error || '';
    }
  }
  if (btnC) btnC.style.display = hw.connected ? 'none'  : '';
  if (btnD) btnD.style.display = hw.connected ? ''      : 'none';
}

async function scanPorts() {
  const sel = document.getElementById('sComPort');
  if (!sel) return;
  toast('Scanning serial ports…');
  try {
    const r    = await fetch(API + '/api/hardware/ports');
    const data = await r.json();
    const ports = data.ports || [];
    sel.innerHTML = '<option value="">-- Select Port --</option>' +
      ports.map(p => `<option value="${p.port}">${p.port} — ${p.description}</option>`).join('');
    toast(ports.length ? `${ports.length} port(s) found` : 'No serial ports found', ports.length ? 'success' : 'warning');
  } catch (_) {
    toast('Cannot reach backend', 'error');
  }
}

async function hwConnect() {
  const port    = document.getElementById('sComPort')?.value;
  const baud    = parseInt(document.getElementById('sBaud')?.value) || 115200;
  const hwMode  = document.getElementById('sHwMode')?.checked || false;
  if (!port) { toast('Select a COM port first', 'warning'); return; }

  const r = await apiPost('/api/hardware/connect', { port, baud, hw_mode: hwMode });
  if (r?.ok) {
    toast(`Connected to ${port} at ${baud} baud`, 'success');
    updateHardwareStatus(r.status);
  } else {
    toast(`Connection failed: ${r?.status?.error || 'Unknown error'}`, 'error');
  }
}

async function hwDisconnect() {
  const r = await apiPost('/api/hardware/disconnect', {});
  if (r?.ok) {
    toast('ESP32 disconnected', 'warning');
    updateHardwareStatus(r.status);
  }
}

// Patch updateAll to also handle hardware field
const _origUpdateAll = updateAll;
window.updateAll = function(s) {
  _origUpdateAll(s);
  if (s.hardware) updateHardwareStatus(s.hardware);
};


async function apiPost(path, body) {
  try {
    const r = await fetch(API + path, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    return await r.json();
  } catch (e) {
    toast('Backend not reachable', 'error');
  }
}

function ctrlStart()  { apiPost('/api/control', {action:'start'}).then(() => toast('Simulation started','success')); }
function ctrlStop()   { apiPost('/api/control', {action:'stop'}).then(() => toast('Simulation paused','warning')); }
function ctrlReset()  { apiPost('/api/control', {action:'reset'}).then(() => toast('Simulation reset','warning')); }

function triggerCritical() {
  apiPost('/api/trigger/critical', {}).then(() => toast('Critical alert injected!','error'));
}

function saveSettings() {
  const nodeCount = parseInt(document.getElementById('sNodeCount').value) || 20;
  const speed     = parseFloat(document.getElementById('sSimSpeed').value) || 1.0;
  const hwMode    = document.getElementById('sHwMode').checked;

  apiPost('/api/control', {action:'set_nodes', count: nodeCount});
  apiPost('/api/control', {action:'set_speed', speed});
  apiPost('/api/control', {action:'set_hw_mode', hw_mode: hwMode});
  apiPost('/api/settings/rl', {
    alpha:         parseFloat(document.getElementById('sAlpha').value),
    gamma:         parseFloat(document.getElementById('sGamma').value),
    epsilon_decay: parseFloat(document.getElementById('sEpsDecay').value),
    w_delivery:    parseFloat(document.getElementById('sWDelivery').value),
    w_energy:      parseFloat(document.getElementById('sWEnergy').value),
    w_urgency:     parseFloat(document.getElementById('sWUrgency').value),
  }).then(() => toast('Settings saved!','success'));
}

// ═════════════════════════════════════════════════════════════════════════════
//  SIDEBAR NAVIGATION — active state on scroll
// ═════════════════════════════════════════════════════════════════════════════
const SECTIONS = ['overview','network','alerts','nodes','analytics','benchmark','qlearning','logs','settings'];

function scrollTo(id) {
  document.getElementById(id)?.scrollIntoView({ behavior:'smooth', block:'start' });
  setActiveNav(id);
  return false;
}

function setActiveNav(id) {
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.getAttribute('href') === '#' + id);
  });
}

// Intersection Observer for active nav
const observer = new IntersectionObserver((entries) => {
  entries.forEach(e => {
    if (e.isIntersecting) setActiveNav(e.target.id);
  });
}, { rootMargin: '-50% 0px -50% 0px' });

SECTIONS.forEach(id => {
  const el = document.getElementById(id);
  if (el) observer.observe(el);
});

// ═════════════════════════════════════════════════════════════════════════════
//  TOAST
// ═════════════════════════════════════════════════════════════════════════════
function toast(msg, type = '') {
  const c = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className   = `toast ${type}`;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => { t.style.opacity='0'; t.style.transition='opacity .3s'; setTimeout(()=>t.remove(), 300); }, 3000);
}

// ═════════════════════════════════════════════════════════════════════════════
//  HELPERS
// ═════════════════════════════════════════════════════════════════════════════
function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ═════════════════════════════════════════════════════════════════════════════
//  INIT
// ═════════════════════════════════════════════════════════════════════════════
window.addEventListener('DOMContentLoaded', () => {
  // Init sparklines
  sparkPDR    = makeSparkline('sparkPDR',    '#3B82F6');
  sparkCR     = makeSparkline('sparkCR',     '#F59E0B');
  sparkEnergy = makeSparkline('sparkEnergy', '#8B5CF6');
  sparkNodes  = makeSparkline('sparkNodes',  '#22C55E');

  // Connect WebSocket
  connectWS();

  // Sidebar toggle
  const sidebarToggle = document.getElementById('sidebarToggle');
  const sidebar = document.getElementById('sidebar');
  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', () => {
      sidebar.classList.toggle('collapsed');
      document.body.classList.toggle('sidebar-collapsed');
    });
  }

  // Fallback polling if WS fails after 5s
  setTimeout(() => {
    if (!state) {
      fetch(API + '/api/snapshot')
        .then(r => r.json())
        .then(d => { state = d; updateAll(d); })
        .catch(() => {});
    }
  }, 5000);

  toast('Dashboard loaded — connecting to backend…');
});

// Expose globals for inline onclick
window.scrollTo    = scrollTo;
window.ctrlStart   = ctrlStart;
window.ctrlStop    = ctrlStop;
window.ctrlReset   = ctrlReset;
window.saveSettings    = saveSettings;
window.exportLogs      = exportLogs;
window.triggerCritical = triggerCritical;
window.toast           = toast;
window.scanPorts       = scanPorts;
window.hwConnect       = hwConnect;
window.hwDisconnect    = hwDisconnect;
