'use strict';
const $ = id => document.getElementById(id);
const portable = Boolean(window.STRIVE_DEMO);
let token = '', callId = null, events = [], timer = null, socket = null, audioCtx = null;
let media = null, node = null, last = null, verified = false, running = false;
const pct = x => x == null ? '—' : String(Math.round(x * 100));
const reasonNames = {
  LOW_EVIDENCE: 'Insufficient evidence', LOW_AUDIO_ACTIVITY: 'Low audio activity',
  BOOTSTRAP_REJECTED: 'Initial trust gate rejected', GLOBAL_REFERENCE_ANOMALY: 'Global reference anomaly',
  SESSION_INCONSISTENCY: 'Voice differs from session profile', BOUNDARY_DISCONTINUITY: 'Boundary discontinuity',
  GLOBAL_LANGUAGE_FALLBACK: 'Language partition unavailable · global fallback',
  SURROGATE_FEATURES_NOT_A_DEEPFAKE_VERDICT: 'Demo features · no deepfake verdict',
  MODEL_OR_INDEX_ERROR: 'Model unavailable · verification required', COMPUTE_EXCEEDS_STRIDE: 'Compute exceeds 1-second budget'
};
function context() {
  return {amount_inr: Math.max(0, Number($('amount').value) || 0), urgent: $('urgent').checked,
    new_beneficiary: $('beneficiary').checked, privileged_request: false};
}
function contextScore(c) {
  return Math.min(1, (c.amount_inr >= 1000000 ? .35 : c.amount_inr >= 100000 ? .15 : 0) +
    (c.urgent ? .2 : 0) + (c.new_beneficiary ? .25 : 0) + (c.privileged_request ? .2 : 0));
}
function localPolicy(e) {
  const c = contextScore(context()), a = e.s_risk;
  const d = a == null ? null : 1 - (1 - a) * (1 - .5 * c);
  const level = d == null ? 'analyzing' : d >= .75 ? 'alert' : d >= .5 || c >= .7 ? 'warning' : 'low';
  return {...e, context_risk: c, decision_risk: d, alert_level: level,
    recommended_action: level === 'alert' || (level === 'analyzing' && c >= .5) ? 'HOLD_AND_VERIFY' :
      level === 'warning' ? 'VERIFY_CALLER' : level === 'analyzing' ? 'AWAIT_EVIDENCE' : 'CONTINUE_MONITORING'};
}
async function api(path, opts = {}) {
  const headers = {...(opts.headers || {}), ...(token ? {Authorization: 'Bearer ' + token} : {})};
  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof Blob)) {
    headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(opts.body);
  }
  const r = await fetch(path, {...opts, headers});
  if (!r.ok) { const body = await r.json().catch(() => ({})); throw new Error(typeof body.detail === 'string' ? body.detail : 'Request failed (' + r.status + ')'); }
  return r.json();
}
function message(text) { $('notice').textContent = text; }
function busy(value) {
  running = value; document.body.classList.toggle('busy', value); $('stop').disabled = !value;
  $('transfer').disabled = value || !callId; $('verify').disabled = value || !callId;
}
function reset() {
  events = []; last = null; verified = false;
  $('events').replaceChildren(); $('auth').textContent = '—'; $('decision').textContent = '—';
  $('bootstrap').textContent = 'EMPTY'; $('entries').textContent = '0'; $('similarity').textContent = '—';
  $('call-state').textContent = 'ANALYZING'; $('call-state').className = 'tag';
  $('confirmed').checked = false; $('transaction-result').textContent = 'No money moves in this demo.';
  draw();
}
function draw() {
  const canvas = $('chart'), ratio = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = 230;
  canvas.width = w * ratio; canvas.height = h * ratio;
  const c = canvas.getContext('2d'); c.scale(ratio, ratio);
  const left = 27, top = 10, bottom = 25, right = 10;
  const width = w - left - right, height = h - top - bottom;
  c.font = '10px system-ui'; c.lineWidth = 1;
  for (const value of [0, .25, .5, .75, 1]) {
    const y = top + (1 - value) * height;
    c.strokeStyle = value === .75 ? '#e9a9b3' : value === .5 ? '#e6cb93' : '#e9edf4';
    c.setLineDash(value === .75 || value === .5 ? [4, 5] : []);
    c.beginPath(); c.moveTo(left, y); c.lineTo(w - right, y); c.stroke();
    c.fillStyle = '#8b95a6'; c.fillText(String(value * 100), 0, y + 3);
  }
  c.setLineDash([]);
  const maxTime = Math.max(40, last?.session_age_s || 0);
  for (let i = 0; i <= 4; i++) { c.fillStyle = '#8b95a6'; c.fillText(Math.round(maxTime * i / 4) + 's', left + i / 4 * width - 4, h - 3); }
  c.strokeStyle = '#275df0'; c.lineWidth = 2.6; c.lineJoin = 'round'; c.beginPath(); let connected = false;
  for (const e of events) {
    if (e.s_risk == null) { connected = false; continue; }
    const x = left + e.session_age_s / maxTime * width, y = top + (1 - e.s_risk) * height;
    if (!connected) c.moveTo(x, y); else c.lineTo(x, y); connected = true;
  }
  c.stroke();
  if (last && last.s_risk != null) {
    c.beginPath(); c.fillStyle = '#275df0'; c.arc(left + last.session_age_s / maxTime * width, top + (1 - last.s_risk) * height, 4, 0, 2 * Math.PI); c.fill();
  }
}
function display(e, append = true) {
  last = e; if (append) events.push(e);
  if (e.alert_level === 'alert' || e.alert_level === 'warning') verified = false;
  $('auth').textContent = pct(e.s_risk); $('context-risk').textContent = pct(e.context_risk); $('decision').textContent = pct(e.decision_risk);
  $('clock').textContent = String(Math.floor(e.session_age_s / 60)).padStart(2, '0') + ':' + String(Math.floor(e.session_age_s % 60)).padStart(2, '0');
  $('call-state').textContent = e.alert_level.toUpperCase(); $('call-state').className = 'tag ' + e.alert_level;
  $('state-detail').textContent = e.s_risk == null ? 'Collecting enough active audio to score.' : e.demo_only ? 'Engineering score · not an authenticity verdict.' : 'Uncalibrated research score · independent verification required.';
  $('latency').textContent = e.latency_ms.end_to_end.toFixed(1) + ' ms'; $('voiced').textContent = e.voiced_seconds.toFixed(1) + ' s';
  ['global', 'session', 'coherence'].forEach((name, i) => {
    const score = e.track_scores['s_' + name]; $('' + name + '-score').textContent = pct(score);
    $(name + '-bar').value = score ?? 0; $(name + '-weight').textContent = 'w ' + e.weights[i].toFixed(2);
  });
  $('bootstrap').textContent = e.bootstrap.toUpperCase(); $('entries').textContent = e.profile_entries;
  $('similarity').textContent = e.session_similarity == null ? 'Unavailable' : pct(e.session_similarity) + '%';
  $('route').textContent = (e.retrieval.route || 'unknown') + (e.retrieval.fallback ? ' (fallback)' : '');
  $('model').textContent = e.model_version;
  const policyText = {HOLD_AND_VERIFY: 'Hold & verify', VERIFY_CALLER: 'Verify caller identity', CONTINUE_MONITORING: 'Continue monitoring', AWAIT_EVIDENCE: 'Awaiting evidence'};
  $('policy').textContent = policyText[e.recommended_action] || e.recommended_action; $('policy').className = 'policy ' + e.alert_level;
  $('reasons').replaceChildren(...(e.reasons.length ? e.reasons : ['No sustained anomaly']).map(reason => { const s = document.createElement('span'); s.textContent = reasonNames[reason] || reason; return s; }));
  if (append) {
    const row = document.createElement('tr');
    [e.session_age_s + 's', e.alert_level.toUpperCase(), pct(e.track_scores.s_global), pct(e.track_scores.s_session), pct(e.track_scores.s_coherence), policyText[e.recommended_action]].forEach(text => {const cell = document.createElement('td'); cell.textContent = text; row.append(cell);});
    $('events').prepend(row); while ($('events').children.length > 120) $('events').lastChild.remove();
  }
  $('download').disabled = false; draw();
}
async function cleanupCall() {
  if (callId && !portable) await api('/v1/calls/' + callId, {method: 'DELETE'}).catch(() => {});
  callId = null;
}
async function stop() {
  if (timer) clearInterval(timer); timer = null;
  if (node) node.disconnect(); node = null;
  if (media) media.getTracks().forEach(t => t.stop()); media = null;
  if (audioCtx) await audioCtx.close().catch(() => {}); audioCtx = null;
  if (socket) socket.close(); socket = null;
  await cleanupCall(); busy(false);
  $('transfer').disabled = true; $('verify').disabled = true;
  message('Stopped. The active session and its transient profile have been deleted. Exports contain scores and scalar diagnostics, not raw audio or embeddings.');
}
$('run').onclick = async () => {
  try {
    await cleanupCall(); reset(); busy(true);
    message('Running procedural audio through STRIVE. Playback is accelerated; timestamps reflect audio duration.');
    const name = $('scenario').value;
    const result = portable ? structuredClone(window.STRIVE_DEMO[name]) : await api('/v1/demo/' + name, {method:'POST', body:{language:$('language').value, context:context()}});
    callId = result.call_id;
    let i = 0;
    timer = setInterval(() => {
      if (i >= result.events.length) {
        clearInterval(timer); timer = null; busy(false);
        message('Scenario complete. Inspect the tracks, attempt the mock transfer, or export the measured events. Both signal families are synthetic engineering fixtures.'); return;
      }
      const event = result.events[i++]; display(portable ? localPolicy(event) : event);
    }, 120);
  } catch (e) { busy(false); message(e.message); }
};
$('stop').onclick = stop;
$('context-apply').onclick = async () => {
  verified = false; $('confirmed').checked = false;
  try {
    if (callId && !portable) await api('/v1/calls/' + callId + '/context', {method:'PATCH', body:context()});
    if (last) display(localPolicy(last), false); else $('context-risk').textContent = pct(contextScore(context()));
    message('Context updated. The acoustic score is unchanged.');
  } catch(e) {message(e.message);}
};
$('transfer').onclick = async () => {
  try {
    const result = portable ? {status: verified ? 'executed_mock' : 'held_mock'} : await api('/v1/calls/' + callId + '/transaction', {method:'POST'});
    $('transaction-result').textContent = result.status === 'executed_mock' ? 'Mock transfer approved after the required verification. No money moved.' : 'Mock transfer held. Complete an independent verification before approving.';
  } catch(e) {message(e.message);}
};
$('verify').onclick = async () => {
  if (!$('confirmed').checked) {message('Confirm the independent verification was completed first.'); return;}
  try {
    if (!portable) await api('/v1/calls/' + callId + '/verify', {method:'POST', body:{method:$('verification').value, confirmed:true}});
    verified = true; $('transaction-result').textContent = 'Mock verification recorded for the current evidence. You can retry the transfer.';
  } catch(e) {message(e.message);}
};
$('download').onclick = () => {
  const blob = new Blob([JSON.stringify({schema_version:'1.0', evidence_type:portable ? 'recorded_engineering_replay' : 'local_run', events}, null, 2)], {type:'application/json'});
  const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = 'strive-events.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
$('upload').onclick = () => $('file').click();
$('file').onchange = async () => {
  const file = $('file').files[0]; if (!file) return;
  try {
    if (file.size > 20 * 1024 * 1024) throw new Error('Use an audio file smaller than 20 MiB and shorter than two minutes.');
    await cleanupCall(); reset(); busy(true); message('Analyzing the audio in memory. No raw audio will be saved.');
    const result = await api('/v1/analyze?language=' + encodeURIComponent($('language').value), {method:'POST', body:file, headers:{'Content-Type':'application/octet-stream'}});
    result.events.forEach(e => display(e)); busy(false);
    message(result.events.length ? 'File analysis complete. Demo mode uses surrogate features; research models are needed for meaningful detection evaluation.' : 'Too little audio: at least two seconds are needed for a complete window.');
  } catch(e) {busy(false); message(e.message);} finally {$('file').value = '';}
};
$('mic').onclick = async () => {
  try {
    await cleanupCall(); reset(); busy(true);
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone access needs localhost or HTTPS in a supported browser.');
    media = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1, echoCancellation:false, noiseSuppression:false, autoGainControl:false}});
    const call = await api('/v1/calls', {method:'POST',body:{language:$('language').value,context:context()}}); callId = call.call_id;
    socket = new WebSocket(location.origin.replace(/^http/, 'ws') + call.ws_path);
    let sequence = 0, pending = false, queue = [];
    const sendNext = () => {
      if (pending || !queue.length || socket?.readyState !== WebSocket.OPEN) return;
      const raw = queue.shift(), bytes = new Uint8Array(raw); let binary = '';
      for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
      pending = true; socket.send(JSON.stringify({sequence:sequence++, pcm_s16le:btoa(binary)}));
    };
    await new Promise((resolve, reject) => {
      socket.onopen = () => socket.send(JSON.stringify({token}));
      socket.onerror = () => reject(new Error('Could not connect to the audio stream.'));
      socket.onclose = () => reject(new Error('Stream connection closed before it was ready.'));
      socket.onmessage = async msg => {
        const data = JSON.parse(msg.data);
        if (data.type === 'ready') resolve();
        else if (data.type === 'events') {pending = false; data.events.forEach(e => display(e)); sendNext();}
        else if (data.type === 'error') {await stop(); message(data.message);}
      };
    });
    socket.onclose = async () => {if (running && audioCtx) {await stop(); message('Stream disconnected. The call profile was cleared.');}};
    audioCtx = new AudioContext({sampleRate:16000}); await audioCtx.resume();
    await audioCtx.audioWorklet.addModule('/assets/pcm-worklet.js');
    const source = audioCtx.createMediaStreamSource(media);
    node = new AudioWorkletNode(audioCtx, 'strive-pcm');
    const mute = audioCtx.createGain(); mute.gain.value = 0;
    source.connect(node); node.connect(mute); mute.connect(audioCtx.destination);
    node.port.onmessage = async e => {
      queue.push(e.data);
      if (queue.length > 3) {await stop(); message('Inference fell behind the live stream. Capture stopped to avoid scoring stale audio.'); return;}
      sendNext();
    };
    $('transfer').disabled = false; $('verify').disabled = false;
    message('Microphone active · 16 kHz mono · one update per second after warm-up. In demo mode these are unvalidated surrogate scores.');
  } catch(e) {await stop(); message(e.message);}
};
$('auth-config').onclick = async () => {
  token = prompt('API bearer token (leave empty for localhost demo):', '') || '';
  try {await api('/ready'); message('API access verified. The token stays in this page’s memory.');} catch(e) {message(e.message);}
};
window.addEventListener('resize', draw);
if (portable) {
  $('connection').textContent = 'Recorded demo · offline';
  $('mic').disabled = true; $('upload').disabled = true; $('auth-config').disabled = true;
  $('language').disabled = true;
  message('Portable replay of measured backend runs. No models run in this file. Microphone and audio upload are available in the local Python app.');
} else {
  api('/v1/config').then(config => {
    $('model').textContent = config.model_version;
    if (!config.demo_only) {
      $('mode').replaceChildren(document.createTextNode('RESEARCH MODE'));
      $('run').disabled = true; $('scenario').disabled = true;
      message('Frozen local research models loaded. Scores and thresholds remain uncalibrated until evaluated on held-out speech.');
    }
  }).catch(e => message(e.message + ' Use API access if this server requires a token.'));
}
draw();
