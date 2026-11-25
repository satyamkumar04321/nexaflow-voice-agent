const state = {
  callId: null,
  ws: null,
  recognition: null,
  micActive: false,
  speaking: false,
  sentiments: [],
};

const els = {
  healthBadge: document.getElementById("healthBadge"),
  startCallBtn: document.getElementById("startCallBtn"),
  endCallBtn: document.getElementById("endCallBtn"),
  micBtn: document.getElementById("micBtn"),
  stopSpeakBtn: document.getElementById("stopSpeakBtn"),
  ttsToggle: document.getElementById("ttsToggle"),
  voiceStatus: document.getElementById("voiceStatus"),
  sttSupportHint: document.getElementById("sttSupportHint"),
  callMeta: document.getElementById("callMeta"),
  transcriptList: document.getElementById("transcriptList"),
  interimBar: document.getElementById("interimBar"),
  textTurnForm: document.getElementById("textTurnForm"),
  textInput: document.getElementById("textInput"),
  sendTurnBtn: document.getElementById("sendTurnBtn"),
  tierBadge: document.getElementById("tierBadge"),
  scoreFill: document.getElementById("scoreFill"),
  bantList: document.getElementById("bantList"),
  objectionTags: document.getElementById("objectionTags"),
  sentimentReadout: document.getElementById("sentimentReadout"),
  ragList: document.getElementById("ragList"),
  appointmentBox: document.getElementById("appointmentBox"),
  summaryBox: document.getElementById("summaryBox"),
  waveCanvas: document.getElementById("waveCanvas"),
  sentimentCanvas: document.getElementById("sentimentCanvas"),
};

// Tab navigation
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "crm") loadCrmTab();
    if (btn.dataset.tab === "insights") loadInsightsTab();
  });
});

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    els.healthBadge.textContent = `${data.llm_provider} · ${data.kb_chunks} KB chunks`;
  } catch {
    els.healthBadge.textContent = "Offline";
  }
}

function setStatus(label, cssClass = "") {
  els.voiceStatus.textContent = label;
  els.voiceStatus.className = `status-pill ${cssClass}`.trim();
}

function appendMessage(speaker, text, meta = "") {
  const empty = els.transcriptList.querySelector(".empty-state");
  if (empty) empty.remove();

  const div = document.createElement("div");
  div.className = `msg ${speaker}`;
  div.textContent = text;

  if (meta) {
    const m = document.createElement("div");
    m.className = "msg-meta";
    m.textContent = meta;
    div.appendChild(m);
  }
  els.transcriptList.appendChild(div);
  els.transcriptList.scrollTop = els.transcriptList.scrollHeight;
}

function speakText(text, lang) {
  if (!els.ttsToggle.checked || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();

  const utter = new SpeechSynthesisUtterance(text);
  const langMap = { hi: "hi-IN", es: "es-ES", en: "en-IN" };
  utter.lang = langMap[lang] || "en-US";
  utter.rate = 1.02;

  utter.onstart = () => {
    state.speaking = true;
    els.stopSpeakBtn.disabled = false;
    setStatus("Speaking", "speaking");
  };
  utter.onend = () => {
    state.speaking = false;
    els.stopSpeakBtn.disabled = true;
    setStatus(state.micActive ? "Listening" : "Ready", state.micActive ? "listening" : "");
  };
  window.speechSynthesis.speak(utter);
}

els.stopSpeakBtn.addEventListener("click", () => {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  state.speaking = false;
  els.stopSpeakBtn.disabled = true;
  setStatus(state.micActive ? "Listening" : "Ready", state.micActive ? "listening" : "");
});

function renderTelemetry(data) {
  const score = data.qualification_score || 0;
  const tier = data.qualification_tier || "Cold";
  els.scoreFill.style.width = `${score}%`;
  els.tierBadge.textContent = `${tier} · ${score}`;
  els.tierBadge.className = `tier-badge ${tier.toLowerCase().includes("hot") ? "hot" : tier.toLowerCase().includes("warm") ? "warm" : "cold"}`;

  const bant = data.bant || {};
  const entries = [
    ["Need", bant.need],
    ["Team Size", bant.team_size],
    ["Budget", bant.budget],
    ["Authority", bant.authority],
    ["Timeline", bant.timeline],
    ["Email", bant.contact_email],
  ];
  els.bantList.innerHTML = entries
    .map(([k, v]) => `<div><dt>${k}</dt><dd>${v || "—"}</dd></div>`)
    .join("");

  els.objectionTags.innerHTML = (data.objections || [])
    .map((o) => `<span class="tag">${o}</span>`)
    .join("");

  if (typeof data.sentiment_score === "number") {
    state.sentiments.push(data.sentiment_score);
    els.sentimentReadout.textContent = `${data.sentiment_label} (${data.sentiment_score})`;
    drawSentimentChart();
  }

  const chunks = data.rag_chunks || [];
  if (chunks.length) {
    els.ragList.innerHTML = chunks
      .map(
        (c) => `
        <div class="rag-item">
          <div><strong>${c.title}</strong> · ${c.section} (${Math.round(c.score * 100)}%)</div>
          <div>${c.content.slice(0, 180)}${c.content.length > 180 ? "..." : ""}</div>
        </div>`
      )
      .join("");
  }

  if (data.appointment) {
    const a = data.appointment;
    els.appointmentBox.innerHTML = `
      <div class="list-card">
        <strong>Demo Confirmed</strong><br/>
        ${a.slot_date} at ${a.slot_time}<br/>
        ${a.prospect_email}<br/>
        <span class="meta-text">${a.meeting_link}</span>
      </div>`;
  }
}

function drawSentimentChart() {
  const ctx = els.sentimentCanvas.getContext("2d");
  const w = els.sentimentCanvas.width;
  const h = els.sentimentCanvas.height;
  ctx.clearRect(0, 0, w, h);

  // Midline (0.0)
  ctx.strokeStyle = "#334155";
  ctx.beginPath();
  ctx.moveTo(0, h / 2);
  ctx.lineTo(w, h / 2);
  ctx.stroke();

  if (state.sentiments.length === 0) return;
  ctx.strokeStyle = "#10b981";
  ctx.lineWidth = 2;
  ctx.beginPath();
  state.sentiments.forEach((val, idx) => {
    const x = state.sentiments.length === 1 ? w / 2 : (idx / (state.sentiments.length - 1)) * (w - 20) + 10;
    const y = h / 2 - val * (h / 2 - 8);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

// Simple ambient waveform loop when mic or TTS is active
function startWaveformLoop() {
  const ctx = els.waveCanvas.getContext("2d");
  let phase = 0;
  function frame() {
    const w = els.waveCanvas.width;
    const h = els.waveCanvas.height;
    ctx.clearRect(0, 0, w, h);
    const active = state.micActive || state.speaking;
    ctx.strokeStyle = state.speaking ? "#f59e0b" : state.micActive ? "#10b981" : "#334155";
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let x = 0; x < w; x += 4) {
      const amp = active ? 14 * Math.sin(phase + x * 0.06) * Math.sin(x / w * Math.PI) : 1.5;
      const y = h / 2 + amp;
      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    phase += active ? 0.18 : 0.03;
    requestAnimationFrame(frame);
  }
  frame();
}
startWaveformLoop();

function connectWebSocket(callId) {
  if (state.ws) state.ws.close();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/call/${callId}`);
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "status" && msg.state === "thinking") {
      setStatus("Thinking...", "");
    } else if (msg.type === "response") {
      const d = msg.data;
      appendMessage("agent", d.reply, `${d.language.toUpperCase()} · ${d.intent} · ${d.latency_ms}ms (${d.llm_mode})`);
      renderTelemetry(d);
      speakText(d.reply, d.language);
    } else if (msg.type === "error") {
      setStatus("Error", "");
      appendMessage("agent", `Error: ${msg.message}`);
    }
  };
  state.ws = ws;
}

async function sendUserTurn(text) {
  const cleaned = text.trim();
  if (!cleaned || !state.callId) return;

  // Barge-in: stop ongoing TTS when user speaks or sends a turn.
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();

  const lang = document.getElementById("languageSelect").value;
  appendMessage("user", cleaned);

  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: "transcript", text: cleaned, language: lang }));
  } else {
    setStatus("Thinking...", "");
    const res = await fetch(`/api/calls/${state.callId}/turn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: cleaned, language: lang }),
    });
    const d = await res.json();
    appendMessage("agent", d.reply, `${d.language.toUpperCase()} · ${d.intent} · ${d.latency_ms}ms`);
    renderTelemetry(d);
    speakText(d.reply, d.language);
  }
}

els.startCallBtn.addEventListener("click", async () => {
  const payload = {
    prospect_name: document.getElementById("prospectName").value.trim() || null,
    prospect_email: document.getElementById("prospectEmail").value.trim() || null,
    company: document.getElementById("prospectCompany").value.trim() || null,
    language: document.getElementById("languageSelect").value,
  };

  const res = await fetch("/api/calls", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();

  state.callId = data.call_id;
  state.sentiments = [];
  els.transcriptList.innerHTML = "";
  els.summaryBox.classList.add("hidden");
  els.appointmentBox.textContent = "No demo booked in this call yet.";
  els.callMeta.textContent = `Active: ${data.call_id}${data.returning_lead ? " (Returning Lead)" : ""}`;

  els.endCallBtn.disabled = false;
  els.textInput.disabled = false;
  els.sendTurnBtn.disabled = false;
  els.micBtn.disabled = !("SpeechRecognition" in window || "webkitSpeechRecognition" in window);

  connectWebSocket(data.call_id);
  renderTelemetry(data);
  appendMessage("agent", data.greeting, `${data.language.toUpperCase()} · greeting`);
  speakText(data.greeting, data.language);
  setStatus("Ready");
});

els.endCallBtn.addEventListener("click", async () => {
  if (!state.callId) return;
  stopMic();
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();

  const res = await fetch(`/api/calls/${state.callId}/end`, { method: "POST" });
  const summary = await res.json();

  els.summaryBox.classList.remove("hidden");
  els.summaryBox.textContent =
    `Summary: ${summary.summary}\n\nNext Action: ${summary.next_action}\n\n${summary.followup_email}`;

  els.callMeta.textContent = `Completed: ${state.callId}`;
  els.endCallBtn.disabled = true;
  els.micBtn.disabled = true;
  els.textInput.disabled = true;
  els.sendTurnBtn.disabled = true;
  setStatus("Call Ended");
});

els.textTurnForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const val = els.textInput.value;
  els.textInput.value = "";
  sendUserTurn(val);
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    if (!state.callId) {
      alert("Start a call first.");
      return;
    }
    sendUserTurn(chip.dataset.text);
  });
});

// Browser Web Speech API STT
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!SpeechRec) {
  els.sttSupportHint.textContent = "Browser STT unavailable here — use text or demo scenarios.";
}

function startMic() {
  if (!SpeechRec || !state.callId) return;
  const rec = new SpeechRec();
  const selectedLang = document.getElementById("languageSelect").value;
  rec.lang = selectedLang === "auto" ? "en-IN" : selectedLang;
  rec.interimResults = true;
  rec.continuous = true;

  rec.onstart = () => {
    state.micActive = true;
    els.micBtn.textContent = "Stop Mic";
    setStatus("Listening", "listening");
  };

  rec.onresult = (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const t = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        els.interimBar.textContent = "";
        sendUserTurn(t);
      } else {
        interim += t;
      }
    }
    if (interim) els.interimBar.textContent = `Hearing: "${interim}"`;
  };

  rec.onerror = () => stopMic();
  rec.onend = () => {
    if (state.micActive) {
      try { rec.start(); } catch { stopMic(); }
    }
  };

  state.recognition = rec;
  rec.start();
}

function stopMic() {
  state.micActive = false;
  if (state.recognition) {
    try { state.recognition.stop(); } catch {}
    state.recognition = null;
  }
  els.micBtn.textContent = "Start Mic";
  els.interimBar.textContent = "";
  setStatus("Ready");
}

els.micBtn.addEventListener("click", () => {
  if (state.micActive) stopMic();
  else startMic();
});

// CRM Tab
async function loadCrmTab() {
  const [leadsRes, apptsRes, slotsRes] = await Promise.all([
    fetch("/api/crm/leads"),
    fetch("/api/crm/appointments"),
    fetch("/api/calendar/slots?days=3"),
  ]);
  const leads = (await leadsRes.json()).leads || [];
  const appts = (await apptsRes.json()).appointments || [];
  const slots = (await slotsRes.json()).slots || [];

  const tbody = document.getElementById("leadsTableBody");
  tbody.innerHTML = leads
    .map(
      (l) => `
      <tr>
        <td><strong>${l.name || "Unknown"}</strong><br/><span class="meta-text">${l.email || ""}</span></td>
        <td>${l.company || "—"}</td>
        <td>${l.qualification_score}</td>
        <td>
          <select class="stage-select" data-id="${l.id}">
            ${["New", "Discovery", "Qualified", "Demo Booked", "Closed Won"]
              .map((s) => `<option value="${s}" ${l.stage === s ? "selected" : ""}>${s}</option>`)
              .join("")}
          </select>
        </td>
        <td>${(l.language || "en").toUpperCase()}</td>
        <td>${(l.need || "—").slice(0, 60)}</td>
      </tr>`
    )
    .join("") || `<tr><td colspan="6" class="meta-text">No leads captured yet.</td></tr>`;

  document.querySelectorAll(".stage-select").forEach((sel) => {
    sel.addEventListener("change", async () => {
      await fetch(`/api/crm/leads/${sel.dataset.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: sel.value }),
      });
    });
  });

  document.getElementById("appointmentsList").innerHTML = appts
    .map(
      (a) => `
      <div class="list-card">
        <strong>${a.prospect_name}</strong> (${a.company || "Prospect"})<br/>
        ${a.slot_date} · ${a.slot_time} · ${a.prospect_email}<br/>
        <span class="meta-text">${a.meeting_link}</span>
      </div>`
    )
    .join("") || `<p class="meta-text">No demos booked yet.</p>`;

  document.getElementById("openSlotsChips").innerHTML = slots
    .slice(0, 12)
    .map((s) => `<span class="slot-pill">${s.label}</span>`)
    .join("");
}

document.getElementById("refreshCrmBtn").addEventListener("click", loadCrmTab);

// Insights & KB Tab
async function loadInsightsTab() {
  const [insRes, kbRes] = await Promise.all([fetch("/api/insights"), fetch("/api/kb")]);
  const ins = await insRes.json();
  const kb = (await kbRes.json()).chunks || [];

  const kpis = [
    ["Total Calls", ins.total_calls],
    ["Leads Captured", ins.total_leads],
    ["SQLs (Score 70+)", ins.sql_count],
    ["Demos Booked", `${ins.demos_booked} (${ins.conversion_rate_pct}%)`],
    ["Avg Qualification", `${ins.avg_qualification_score}/100`],
    ["Est. Pipeline", `$${ins.estimated_pipeline_usd.toLocaleString()}`],
  ];
  document.getElementById("kpiGrid").innerHTML = kpis
    .map(([label, val]) => `<div class="kpi-card"><div class="meta-text">${label}</div><div class="kpi-val">${val}</div></div>`)
    .join("");

  document.getElementById("breakdownBox").innerHTML = `
    <div class="list-card"><strong>Languages:</strong> ${JSON.stringify(ins.languages)}</div>
    <div class="list-card"><strong>Top Objections:</strong> ${JSON.stringify(ins.top_objections)}</div>
    <div class="list-card"><strong>Pipeline Stages:</strong> ${JSON.stringify(ins.pipeline_stages)}</div>
  `;

  document.getElementById("kbCountMeta").textContent = `${kb.length} indexed chunks`;
  document.getElementById("kbList").innerHTML = kb
    .map((c) => `<div class="list-card"><strong>${c.title}</strong> · ${c.section}<br/><span class="meta-text">${c.doc_id}</span></div>`)
    .join("");
}

document.getElementById("addKbForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const filename = document.getElementById("kbFilename").value.trim();
  const content = document.getElementById("kbContent").value.trim();
  await fetch("/api/kb", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename, content }),
  });
  document.getElementById("kbFilename").value = "";
  document.getElementById("kbContent").value = "";
  loadInsightsTab();
  checkHealth();
});

checkHealth();
