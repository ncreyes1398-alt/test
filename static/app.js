'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  a: { fileId: null, bpm: null, filename: null },
  b: { fileId: null, bpm: null, filename: null },
  mode: 'ab',   // 'ab' = A vocals + B instrumental, 'ba' = B vocals + A instrumental
  pollTimer: null,
};

// ── Tab switching (File / YouTube) ─────────────────────────────────────────

function setTab(deck, tab) {
  const tabs = el(`tabs-${deck}`).querySelectorAll('.tab-btn');
  tabs.forEach((btn, i) => btn.classList.toggle('active', i === (tab === 'file' ? 0 : 1)));
  show(`tab-file-${deck}`, tab === 'file');
  show(`tab-yt-${deck}`,   tab === 'yt');
}

async function loadYt(deck) {
  const input = el(`yt-url-${deck}`);
  const url = input.value.trim();
  if (!url) return;

  if (!url.includes('youtube.com') && !url.includes('youtu.be')) {
    alert('Please enter a valid YouTube URL');
    return;
  }

  show(`tab-yt-${deck}`, false);
  show(`loading-${deck}`, true);
  el(`loading-label-${deck}`).textContent = 'Downloading from YouTube…';

  const form = new FormData();
  form.append('url', url);

  try {
    const res = await fetch('/api/yt-upload', { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'YouTube download failed' }));
      throw new Error(err.detail || 'YouTube download failed');
    }
    const data = await res.json();
    applyTrackInfo(deck, data);
  } catch (err) {
    show(`loading-${deck}`, false);
    show(`tab-yt-${deck}`, true);
    alert(`Error: ${err.message}`);
  }
}

// ── Upload & analysis ──────────────────────────────────────────────────────

function handleDragOver(e) {
  e.preventDefault();
  e.currentTarget.classList.add('drag-over');
}

function handleDragLeave(e) {
  e.currentTarget.classList.remove('drag-over');
}

function handleDrop(e, deck) {
  e.preventDefault();
  e.currentTarget.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file, deck);
}

function handleFileSelect(e, deck) {
  const file = e.target.files[0];
  if (file) uploadFile(file, deck);
}

function applyTrackInfo(deck, data) {
  state[deck].fileId   = data.file_id;
  state[deck].bpm      = data.bpm;
  state[deck].filename = data.filename;

  el(`name-${deck}`).textContent = data.filename;
  el(`name-${deck}`).title       = data.filename;
  el(`bpm-${deck}`).textContent  = data.bpm;
  el(`key-${deck}`).textContent  = data.key;
  el(`dur-${deck}`).textContent  = fmtDuration(data.duration);

  show(`loading-${deck}`, false);
  show(`info-${deck}`, true);
  updateGenerateBtn();
}

async function uploadFile(file, deck) {
  const allowed = ['.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a'];
  const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
  if (!allowed.includes(ext)) {
    alert(`Unsupported format: ${ext}`);
    return;
  }

  show(`tab-file-${deck}`, false);
  show(`loading-${deck}`, true);
  el(`loading-label-${deck}`).textContent = 'Analyzing…';

  const form = new FormData();
  form.append('file', file);

  try {
    const res = await fetch('/api/upload', { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
      throw new Error(err.detail || 'Upload failed');
    }
    applyTrackInfo(deck, await res.json());
  } catch (err) {
    show(`loading-${deck}`, false);
    show(`tab-file-${deck}`, true);
    alert(`Error: ${err.message}`);
  }
}

function resetDeck(deck) {
  state[deck] = { fileId: null, bpm: null, filename: null };
  show(`info-${deck}`, false);
  show(`tab-file-${deck}`, true);
  show(`tab-yt-${deck}`, false);
  el(`file-${deck}`).value = '';
  el(`yt-url-${deck}`).value = '';
  // Reset tabs to File
  const tabs = el(`tabs-${deck}`).querySelectorAll('.tab-btn');
  tabs[0].classList.add('active');
  tabs[1].classList.remove('active');
  updateGenerateBtn();
}

// ── Mixer controls ─────────────────────────────────────────────────────────

function setMode(mode) {
  state.mode = mode;
  el('mode-ab').classList.toggle('active', mode === 'ab');
  el('mode-ba').classList.toggle('active', mode === 'ba');
}

function snapBpm(deck) {
  if (!state[deck].bpm) return;
  const bpm = state[deck].bpm;
  el('target-bpm').value  = bpm;
  el('bpm-slider').value  = bpm;
}

function onBpmInput() {
  el('bpm-slider').value = el('target-bpm').value;
}

function onBpmSlider() {
  el('target-bpm').value = el('bpm-slider').value;
}

function faderLabel(rangeId, labelId, signed = false) {
  const val = parseFloat(el(rangeId).value);
  el(labelId).textContent = signed
    ? (val > 0 ? `+${val}` : String(val))
    : `${val}%`;
}

function updateGenerateBtn() {
  const ready = state.a.fileId && state.b.fileId;
  el('generate-btn').disabled = !ready;
}

// ── Mix generation ─────────────────────────────────────────────────────────

async function createMix() {
  if (!state.a.fileId || !state.b.fileId) return;

  resetOutput();
  show('output-idle', false);
  show('output-processing', true);
  setProgress(0, 'Starting…');

  const vocalsFrom = state.mode === 'ab' ? 'a' : 'b';
  const form = new FormData();
  form.append('song_a_id',            state.a.fileId);
  form.append('song_b_id',            state.b.fileId);
  form.append('vocals_from',          vocalsFrom);
  form.append('target_bpm',           el('target-bpm').value);
  form.append('vocals_volume',        parseFloat(el('vol-vocals').value) / 100);
  form.append('instrumental_volume',  parseFloat(el('vol-instr').value) / 100);
  form.append('pitch_shift',          el('pitch-shift').value);

  try {
    const res = await fetch('/api/process', { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Process failed' }));
      throw new Error(err.detail || 'Process failed');
    }
    const { job_id } = await res.json();
    pollJob(job_id);
  } catch (err) {
    showJobError(err.message);
  }
}

function pollJob(jobId) {
  clearPoll();
  state.pollTimer = setInterval(async () => {
    try {
      const res  = await fetch(`/api/status/${jobId}`);
      const data = await res.json();

      if (data.status === 'processing') {
        const pct = data.progress || 0;
        setProgress(pct, `Processing… ${pct}%`);
        el('proc-pct').textContent = `${pct}%`;

      } else if (data.status === 'complete') {
        clearPoll();
        setProgress(100, 'Done!');
        setTimeout(() => showPlayer(jobId), 400);

      } else if (data.status === 'error') {
        clearPoll();
        showJobError(data.error || 'Unknown error');
      }
    } catch (e) {
      // network hiccup — keep polling
    }
  }, 1200);
}

function clearPoll() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

function setProgress(pct, label) {
  el('progress-fill').style.width = `${pct}%`;
  el('proc-label').textContent = label;
  el('proc-pct').textContent   = `${pct}%`;
}

function showPlayer(jobId) {
  const downloadUrl = `/api/download/${jobId}`;
  const player = el('audio-player');
  player.src   = downloadUrl;
  el('dl-btn').href = downloadUrl;

  show('output-processing', false);
  show('output-ready', true);
}

function showJobError(msg) {
  show('output-processing', false);
  el('err-msg').textContent = msg;
  show('output-error', true);
}

function resetOutput() {
  clearPoll();
  show('output-processing', false);
  show('output-ready',      false);
  show('output-error',      false);
  show('output-idle',       true);
  el('audio-player').src = '';
}

// ── Utility ────────────────────────────────────────────────────────────────

function el(id) { return document.getElementById(id); }

function show(id, visible) {
  const node = el(id);
  if (!node) return;
  node.classList.toggle('hidden', !visible);
}

function fmtDuration(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function showError(msg) {
  alert(msg);
}
