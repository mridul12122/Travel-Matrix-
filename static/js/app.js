/* ===================================================
   AI Travel Matrix — app.js
   All frontend logic: clock, cities, plan, rendering
   =================================================== */

'use strict';

// ── Constants ───────────────────────────────────────
const DAY_COLORS   = ['#FF5858','#58A6FF','#3FB950','#F39C12','#C678DD','#00BCD4'];
const STAR_COLOR   = '#F1C40F';

// ── State ────────────────────────────────────────────
let planData   = null;
let citySet    = new Set(); // populated from /api/cities
let leafletMap = null;
let chatCtx    = null;
let chatHist   = [];

// ════════════════════════════════════════════════════
// INIT
// ════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
  initClock();
  initDates();
  loadCities();
  detectCity();
});

// ── Analog Clock ─────────────────────────────────────
function initClock() {
  const hourHand = document.getElementById('hour-hand');
  const minHand  = document.getElementById('min-hand');
  const secHand  = document.getElementById('sec-hand');
  const dateEl   = document.getElementById('clock-date');

  function tick() {
    const now = new Date();
    const s   = now.getSeconds();
    const m   = now.getMinutes();
    const h   = now.getHours() % 12;
    secHand.style.transform  = `rotate(${(s/60)*360 + 90}deg)`;
    minHand.style.transform  = `rotate(${(m/60)*360 + (s/60)*6 + 90}deg)`;
    hourHand.style.transform = `rotate(${(h/12)*360 + (m/60)*30 + 90}deg)`;
    dateEl.textContent = now.toLocaleDateString('en-IN', { weekday:'short', day:'numeric', month:'short' });
  }
  tick();
  setInterval(tick, 1000);
}

// ── Default Dates ─────────────────────────────────────
function initDates() {
  const today   = new Date();
  const checkout = new Date(today);
  checkout.setDate(today.getDate() + 3);
  document.getElementById('checkin').value  = fmtDate(today);
  document.getElementById('checkout').value = fmtDate(checkout);
}

function fmtDate(d) {
  return d.toISOString().split('T')[0];
}

// ── City Loader ───────────────────────────────────────
async function loadCities() {
  try {
    const res    = await fetch('/api/cities');
    const cities = await res.json();
    citySet = new Set(cities.map(c => c.toLowerCase()));
    const olDL = document.getElementById('origin-list');
    const deDL = document.getElementById('dest-list');
    cities.forEach(c => {
      olDL.innerHTML += `<option value="${c}">`;
      deDL.innerHTML += `<option value="${c}">`;
    });
  } catch (e) { /* offline fallback */ }
}

// ── Auto-detect Origin ────────────────────────────────
async function detectCity() {
  try {
    const res  = await fetch('/api/detect-city');
    const data = await res.json();
    if (data.city) document.getElementById('origin').value = data.city;
  } catch (e) {}
}

// ════════════════════════════════════════════════════
// GENERATE PLAN
// ════════════════════════════════════════════════════

async function generatePlan() {
  const origin      = document.getElementById('origin').value.trim();
  const destination = document.getElementById('destination').value.trim();
  const budget      = parseInt(document.getElementById('budget').value) || 15000;
  const checkin     = document.getElementById('checkin').value;
  const checkout    = document.getElementById('checkout').value;
  const travelers   = parseInt(document.getElementById('travelers').value) || 1;
  const errEl       = document.getElementById('form-error');

  // Validate
  errEl.classList.add('hidden');
  if (!origin || !destination) { showError('Please enter both Origin and Destination cities.'); return; }
  if (citySet.size > 0 && !citySet.has(origin.toLowerCase())) {
    showError(`"${origin}" is not a valid Indian city. Please select from the suggestions.`);
    return;
  }
  if (citySet.size > 0 && !citySet.has(destination.toLowerCase())) {
    showError(`"${destination}" is not a valid Indian city. Please select from the suggestions.`);
    return;
  }
  if (origin.toLowerCase() === destination.toLowerCase()) { showError('Origin and Destination cannot be the same city!'); return; }
  if (!checkin || !checkout || checkin >= checkout) { showError('Please select valid Check-in and Check-out dates.'); return; }

  // Show loading
  document.getElementById('input-section').classList.add('hidden');
  document.getElementById('results-section').classList.add('hidden');
  document.getElementById('loading-screen').classList.remove('hidden');
  document.getElementById('generate-btn').disabled = true;

  // Animate loading steps
  const steps = ['ls1','ls2','ls3','ls4','ls5'];
  let si = 0;
  const stepInterval = setInterval(() => {
    if (si > 0) document.getElementById(steps[si-1]).classList.remove('active');
    if (si < steps.length) { document.getElementById(steps[si]).classList.add('active'); si++; }
    else clearInterval(stepInterval);
  }, 900);

  try {
    const res  = await fetch('/api/plan', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ origin, destination, budget, checkin, checkout, travelers }),
    });
    if (!res.ok) throw new Error(`Server error: ${res.status}`);
    planData = await res.json();
  } catch (e) {
    clearInterval(stepInterval);
    document.getElementById('loading-screen').classList.add('hidden');
    document.getElementById('input-section').classList.remove('hidden');
    showError(`Failed to generate plan: ${e.message}`);
    document.getElementById('generate-btn').disabled = false;
    return;
  }

  clearInterval(stepInterval);
  steps.forEach(id => document.getElementById(id).classList.remove('active'));

  document.getElementById('loading-screen').classList.add('hidden');
  document.getElementById('results-section').classList.remove('hidden');
  document.getElementById('generate-btn').disabled = false;

  // Reset chat state
  chatHist = [];
  chatCtx  = planData;

  renderAll(planData);
  switchTab('itinerary');
}

function showError(msg) {
  const el = document.getElementById('form-error');
  el.textContent = msg;
  el.classList.remove('hidden');
}

// ── New Search ───────────────────────────────────────
function newSearch() {
  document.getElementById('results-section').classList.add('hidden');
  document.getElementById('input-section').classList.remove('hidden');
  if (leafletMap) { leafletMap.remove(); leafletMap = null; }
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function exportToPDF() {
  if (!planData) return;
  const btn = document.getElementById('export-pdf-btn');
  const originalText = btn.textContent;
  
  try {
    btn.disabled = true;
    btn.textContent = '⏳ Generating...';
    
    const res = await fetch('/api/export-pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(planData)
    });
    
    if (!res.ok) throw new Error('PDF generation failed');
    
    const blob = await res.blob();
    const url  = window.URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.download = `AI_Travel_Plan_${planData.destination}.pdf`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
  } catch (e) {
    console.error(e);
    alert('Failed to download PDF: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

// ════════════════════════════════════════════════════
// RENDER ALL TABS
// ════════════════════════════════════════════════════

function renderAll(d) {
  renderTripBar(d);
  renderItinerary(d);
  renderTransport(d);
  renderHotel(d);
  renderFood(d);
  renderBudget(d);
  renderChat(d);

  if (!d.online) document.getElementById('offline-banner').classList.remove('hidden');
  else document.getElementById('offline-banner').classList.add('hidden');
}

// ── Trip Summary Bar ──────────────────────────────────
function renderTripBar(d) {
  document.getElementById('trip-bar').innerHTML = `
    <div class="trip-stat"><div class="trip-stat-label">Route</div><div class="trip-stat-value">${d.origin} → ${d.destination}</div></div>
    <div class="trip-stat"><div class="trip-stat-label">Duration</div><div class="trip-stat-value blue">${d.days} Day${d.days>1?'s':''}</div></div>
    <div class="trip-stat"><div class="trip-stat-label">Distance</div><div class="trip-stat-value">${d.distance_text}</div></div>
    <div class="trip-stat"><div class="trip-stat-label">Transport</div><div class="trip-stat-value">${d.transport_mode}</div></div>
    <div class="trip-stat"><div class="trip-stat-label">Est. Cost</div><div class="trip-stat-value ${d.total_cost<=d.budget?'green':''}">₹${d.total_cost.toLocaleString('en-IN')}</div></div>
    <div class="trip-stat"><div class="trip-stat-label">Budget</div><div class="trip-stat-value">₹${d.budget.toLocaleString('en-IN')}</div></div>
  `;
}

// ════════════════════════════════════════════════════
// TAB 1 — ITINERARY
// ════════════════════════════════════════════════════

function renderItinerary(d) {
  const el = document.getElementById('panel-itinerary');

  // Weather
  const w        = d.weather || {};
  const packHtml = (w.packing_list || []).map(p => `<div class="packing-item">${p}</div>`).join('');
  const weatherHtml = `
    <div class="glass-card weather-card">
      <div class="section-title">🌤️ Live Weather & AI Packing Guide</div>
      <div class="metrics-row" style="grid-template-columns:1fr 1fr;max-width:360px;margin-bottom:14px">
        <div class="metric-card"><div class="metric-label">🌡️ Est. Max Temp</div><div class="metric-value" style="font-size:18px">${w.temp_max||'N/A'}</div></div>
        <div class="metric-card"><div class="metric-label">🌧️ Rain Probability</div><div class="metric-value" style="font-size:18px">${w.rain_chance||'N/A'}</div></div>
      </div>
      <div class="sub-title">🧳 Recommended Packing List</div>
      <div class="packing-grid">${packHtml}</div>
    </div>`;

  // Group by day
  const byDay = {};
  d.itinerary.forEach(p => { if (!byDay[p.day]) byDay[p.day] = []; byDay[p.day].push(p); });

  let timelineHtml = '';
  for (let day = 1; day <= d.days; day++) {
    const places = byDay[day] || [];
    const color  = DAY_COLORS[(day-1) % DAY_COLORS.length];
    const items  = places.map(p => {
      const photosHtml = (p.photos && p.photos.length && d.online)
        ? `<div class="photos-row">${p.photos.slice(0,3).map(u=>`<img src="${u}" class="place-photo" alt="${esc(p.name)}" onerror="this.style.display='none'">`).join('')}</div>`
        : (p.photos && p.photos.length && !d.online) ? `<p class="offline-note">📵 Images unavailable in offline mode</p>` : '';
      return `
        <div class="timeline-item">
          <div class="timeline-dot" style="background:${color}"></div>
          <div class="timeline-content glass-card" style="padding:14px">
            <div class="timeline-time">${p.start_time} — ${p.end_time}</div>
            <div class="place-name">${esc(p.name)}</div>
            <div class="place-rating">⭐ ${Number(p.rating).toFixed(1)}</div>
            ${photosHtml}
          </div>
        </div>`;
    }).join('');

    timelineHtml += `
      <div class="day-section">
        <div class="day-header">
          <div class="day-badge" style="background:linear-gradient(135deg,${color},${color}99)">Day ${day}</div>
          <div class="day-count">${places.length} location${places.length!==1?'s':''}</div>
        </div>
        <div class="timeline">${items || '<p style="color:var(--text-2);font-size:13px">No locations for this day.</p>'}</div>
      </div>`;
  }

  const mapHtml = d.dest_coords
    ? `<div class="map-sticky"><div class="map-title">🗺️ Live Map Tracker</div><div class="map-container" id="itin-map"></div></div>`
    : '';

  el.innerHTML = `
    ${weatherHtml}
    <div class="itinerary-layout">
      <div class="itinerary-timeline">${timelineHtml}</div>
      <div class="itinerary-map">${mapHtml}</div>
    </div>`;

  if (d.dest_coords) {
    setTimeout(() => initMap(d.itinerary, d.dest_coords), 500);
  }
}

// Leaflet Map
function initMap(itinerary, coords) {
  if (leafletMap) { leafletMap.remove(); leafletMap = null; }
  const el = document.getElementById('itin-map');
  if (!el) return;

  leafletMap = L.map('itin-map', { zoomControl: true, scrollWheelZoom: true });
  leafletMap.setView(coords, 13);

  const tileLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
    attribution: '© <a href="https://carto.com/">CartoDB</a>',
    maxZoom: 19,
    subdomains: 'abcd',
    updateWhenZooming: false,
    keepBuffer: 4,
  }).addTo(leafletMap);

  // Auto-retry failed tiles once
  tileLayer.on('tileerror', (e) => {
    if (!e.tile.dataset.retried) {
      e.tile.dataset.retried = '1';
      setTimeout(() => { e.tile.src = e.url; }, 800);
    }
  });

  // Triple invalidateSize — fixes partial grey tile bug in tab containers
  setTimeout(() => { if (leafletMap) leafletMap.invalidateSize(true); }, 100);
  setTimeout(() => {
    if (!leafletMap) return;
    leafletMap.invalidateSize(true);
    // Also force-redraw all layers to reload any stuck tiles
    leafletMap.eachLayer(l => { if (l.redraw) l.redraw(); });
  }, 600);
  setTimeout(() => { if (leafletMap) leafletMap.invalidateSize(true); }, 1500);

  // Add markers
  itinerary.forEach(p => {
    const color = DAY_COLORS[(p.day - 1) % DAY_COLORS.length];
    const icon  = L.divIcon({
      className: '',
      html: `<div style="background:${color};width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 8px ${color}cc"></div>`,
      iconSize:   [14, 14],
      iconAnchor: [7, 7],
    });
    L.marker([p.lat, p.lng], { icon })
      .addTo(leafletMap)
      .bindPopup(`<b>${p.name}</b><br>⭐ ${Number(p.rating).toFixed(1)}<br>Day ${p.day}`);
  });
}

// ════════════════════════════════════════════════════
// TAB 2 — TRANSPORT
// ════════════════════════════════════════════════════

function renderTransport(d) {
  const tc = d.transport_cost;
  const flightVal = tc.flight > 0 ? `₹${tc.flight.toLocaleString('en-IN')}` : 'N/A';
  document.getElementById('panel-transport').innerHTML = `
    <div class="section-title">🚆 Transport AI Prediction</div>
    <div class="metrics-row">
      <div class="metric-card"><div class="metric-label">📏 Distance</div><div class="metric-value">${d.distance_text}</div></div>
      <div class="metric-card"><div class="metric-label">⏱️ Est. Travel Time</div><div class="metric-value">${d.duration}</div></div>
      <div class="metric-card"><div class="metric-label">🎯 Selected Mode</div><div class="metric-value" style="font-size:16px">${d.transport_mode}</div></div>
    </div>
    <div class="info-box">🤖 AI Recommended Cost: <strong>₹${tc.selected.toLocaleString('en-IN')}</strong></div>
    <hr class="divider">
    <div class="sub-title">🚦 Alternative Modes Comparison</div>
    <div class="alt-grid">
      <div class="alt-card"><div class="alt-icon">🚌</div><div class="alt-label">Bus Alternate</div><div class="alt-price">₹${tc.bus.toLocaleString('en-IN')}</div></div>
      <div class="alt-card"><div class="alt-icon">🚆</div><div class="alt-label">Train Alternate</div><div class="alt-price">₹${tc.train.toLocaleString('en-IN')}</div></div>
      <div class="alt-card ${tc.flight===0?'na':''}"><div class="alt-icon">✈️</div><div class="alt-label">Flight Alternate</div><div class="alt-price">${flightVal}</div></div>
    </div>`;
}

// ════════════════════════════════════════════════════
// TAB 3 — HOTEL
// ════════════════════════════════════════════════════

function renderHotel(d) {
  const h = d.hotel;
  document.getElementById('panel-hotel').innerHTML = `
    <div class="section-title">🏨 Hotel AI Inference</div>
    <div class="glass-card hotel-card">
      <div class="hotel-name">🏨 ${esc(h.name)}</div>
      <div class="hotel-row"><span class="hotel-row-label">💵 Price Per Night</span><span class="hotel-row-value">₹${h.price_per_night.toLocaleString('en-IN')}</span></div>
      <div class="hotel-row"><span class="hotel-row-label">📅 Total Stay (${d.days} night${d.days>1?'s':''})</span><span class="hotel-row-value">₹${h.total_cost.toLocaleString('en-IN')}</span></div>
      <a href="${h.link}" target="_blank" rel="noopener" class="book-btn">👉 Reserve at Booking.com</a>
    </div>`;
}

// ════════════════════════════════════════════════════
// TAB 4 — FOOD
// ════════════════════════════════════════════════════

function renderFood(d) {
  const cards = d.food_items.map(item => {
    const photos = (item.photos && item.photos.length && d.online)
      ? `<div class="food-photos">${item.photos.slice(0,3).map(u=>`<img src="${u}" class="food-photo" alt="${esc(item.name)}" onerror="this.style.display='none'">`).join('')}</div>`
      : '';
    return `
      <div class="glass-card food-card">
        <div class="food-header">
          <div class="food-name">${esc(item.name)}</div>
          <div class="food-badge">₹${item.price}</div>
        </div>
        <div class="food-meta"><span>⭐ ${Number(item.rating).toFixed(1)}</span><span>Est. meal: ₹${item.price}</span></div>
        ${photos}
      </div>`;
  }).join('');

  document.getElementById('panel-food').innerHTML = `
    <div class="section-title">🍽️ Dynamic Food Engine</div>
    <div class="info-box">Estimated Total Food Cost: <strong>₹${d.food_cost.toLocaleString('en-IN')}</strong> for ${d.days} day${d.days>1?'s':''}</div>
    <div class="food-grid">${cards}</div>`;
}

// ════════════════════════════════════════════════════
// TAB 5 — BUDGET
// ════════════════════════════════════════════════════

function renderBudget(d) {
  const tc    = d.transport_cost.selected;
  const hc    = d.hotel.total_cost;
  const fc    = d.food_cost;
  const total = d.total_cost;
  const safe  = total <= d.budget;

  const statusHtml = `
    <div class="budget-status ${safe?'safe':'over'}">
      ${safe ? `✅ Plan is within your ₹${d.budget.toLocaleString('en-IN')} budget! (Est: ₹${total.toLocaleString('en-IN')})` :
               `❌ Caution: Plan exceeds budget! Est: ₹${total.toLocaleString('en-IN')} vs Allocated: ₹${d.budget.toLocaleString('en-IN')}`}
    </div>`;

  const breakdownHtml = `
    <div class="cost-breakdown">
      <div class="cost-row"><span class="cost-row-label">🚆 Transport</span><span class="cost-row-value">₹${tc.toLocaleString('en-IN')}</span></div>
      <div class="cost-row"><span class="cost-row-label">🏨 Hotel</span><span class="cost-row-value">₹${hc.toLocaleString('en-IN')}</span></div>
      <div class="cost-row"><span class="cost-row-label">🍽️ Food</span><span class="cost-row-value">₹${fc.toLocaleString('en-IN')}</span></div>
      <div class="cost-row total"><span class="cost-row-label">💰 Total Estimated</span><span class="cost-row-value">₹${total.toLocaleString('en-IN')}</span></div>
    </div>`;

  document.getElementById('panel-budget').innerHTML = `
    <div class="section-title">💰 AI Financial Analyst</div>
    ${statusHtml}
    <div class="budget-layout">
      ${breakdownHtml}
      <div id="budget-chart"></div>
    </div>`;

  Plotly.newPlot('budget-chart', [{
    type:   'pie',
    hole:   0.5,
    labels: ['Transport','Hotel','Food'],
    values: [tc, hc, fc],
    marker: { colors: ['#58A6FF','#3FB950','#FF5858'] },
    textinfo: 'label+percent',
    textfont: { color:'#E6EDF3', size:12 },
    hovertemplate: '%{label}<br>₹%{value:,}<extra></extra>',
  }], {
    paper_bgcolor: 'transparent',
    plot_bgcolor:  'transparent',
    font:   { family: 'Inter', color: '#E6EDF3' },
    legend: { font: { color: '#8B949E' } },
    margin: { t:20, b:20, l:20, r:20 },
    showlegend: true,
  }, { responsive: true, displayModeBar: false });
}

// ════════════════════════════════════════════════════
// TAB 6 — CHAT
// ════════════════════════════════════════════════════

function renderChat(d) {
  document.getElementById('panel-chat').innerHTML = `
    <div class="chat-layout">
      <div class="chat-header">
        <div class="chat-header-avatar">🤖</div>
        <div class="chat-header-info">
          <h4>AI Travel Assistant</h4>
          <p>Powered by Llama 3 · ${esc(d.origin)} → ${esc(d.destination)}</p>
        </div>
        <div class="online-dot" title="Online"></div>
      </div>
      <div class="chat-messages" id="chat-messages">
        <div class="chat-msg assistant">
          👋 Hello! I'm your AI Travel Guide for your trip from <strong>${esc(d.origin)}</strong> to <strong>${esc(d.destination)}</strong>!<br><br>
          You have a ${d.days}-day trip planned with a budget of ₹${d.budget.toLocaleString('en-IN')}. Total estimated cost is ₹${d.total_cost.toLocaleString('en-IN')}.<br><br>
          Ask me anything — best things to do, safety tips, local food, weather advice, and more! ✈️
        </div>
      </div>
      <button class="chat-clear-btn" onclick="clearChat()">🗑️ Clear Chat History</button>
      <div class="chat-footer">
        <textarea class="chat-input" id="chat-input" rows="1" placeholder="Ask me about your trip... ✈️" onkeydown="chatKeydown(event)"></textarea>
        <button class="chat-send-btn" onclick="sendChat()" title="Send">➤</button>
      </div>
    </div>`;
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const text  = input.value.trim();
  if (!text || !planData) return;

  input.value = '';
  appendMsg('user', text);

  // Build system prompt from trip context
  const ctx = planData;
  const sysPrompt = `You are an expert AI Travel Guide and personal travel assistant.
The user is planning a trip from ${ctx.origin} to ${ctx.destination} for ${ctx.days} days with a budget of ₹${ctx.budget}.
Their estimated transport mode is ${ctx.transport_mode} costing ₹${ctx.transport_cost.selected}.
Hotel budget per night is approximately ₹${ctx.hotel.price_per_night}.
Total estimated trip cost is ₹${ctx.total_cost}.
Answer all travel questions in a helpful, friendly and expert manner.
Provide specific tips about ${ctx.destination} — local culture, must-see spots, food, safety, best time to visit, etc.
Keep responses concise but informative. Use emojis to make responses engaging.`;

  chatHist.push({ role:'user', content: text });
  const msgs = [{ role:'system', content: sysPrompt }, ...chatHist];

  // Thinking indicator
  const thinkId = 'think-' + Date.now();
  appendMsg('assistant thinking', '⏳ Thinking...', thinkId);

  try {
    const res  = await fetch('/api/chat', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ messages: msgs }),
    });
    const data = await res.json();
    const reply = data.reply || '⚠️ No response received.';

    // Remove thinking indicator
    const thinkEl = document.getElementById(thinkId);
    if (thinkEl) thinkEl.remove();

    chatHist.push({ role:'assistant', content: reply });
    appendMsg('assistant', reply);
  } catch (e) {
    const thinkEl = document.getElementById(thinkId);
    if (thinkEl) thinkEl.remove();
    appendMsg('assistant', `⚠️ Connection error: ${e.message}`);
  }
}

function chatKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
}

function appendMsg(role, text, id) {
  const container = document.getElementById('chat-messages');
  if (!container) return;
  const div       = document.createElement('div');
  div.className   = `chat-msg ${role}`;
  div.innerHTML   = text.replace(/\n/g, '<br>');
  if (id) div.id  = id;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function clearChat() {
  chatHist = [];
  const c  = document.getElementById('chat-messages');
  if (!c || !planData) return;
  const d  = planData;
  c.innerHTML = `<div class="chat-msg assistant">
    👋 Chat cleared! I'm still here to help with your trip from <strong>${esc(d.origin)}</strong> to <strong>${esc(d.destination)}</strong>. What would you like to know? ✈️
  </div>`;
}

// ════════════════════════════════════════════════════
// TAB SWITCHING
// ════════════════════════════════════════════════════

function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById(`tb-${name}`).classList.add('active');
  document.getElementById(`panel-${name}`).classList.add('active');

  // Re-flow Leaflet map when itinerary tab becomes visible
  if (name === 'itinerary' && leafletMap) {
    setTimeout(() => { leafletMap.invalidateSize(true); }, 200);
  }
  // Re-flow Plotly chart when budget tab becomes visible
  if (name === 'budget') {
    const chartEl = document.getElementById('budget-chart');
    if (chartEl && chartEl.data) Plotly.Plots.resize(chartEl);
  }
}

// ════════════════════════════════════════════════════
// UTILS
// ════════════════════════════════════════════════════

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}
