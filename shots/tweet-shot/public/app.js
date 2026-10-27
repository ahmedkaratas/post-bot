'use strict';

const DEFAULTS = {
  theme: 'light',
  time: false,
  date: false,
  metrics: false,
  views: false,
  media: false,
  footer: true,
  scale: 2,
};

const LS_KEY = 'tweetshot.settings.v1';

const state = { ...DEFAULTS, id: null, url: '', loading: false };

const $ = (id) => document.getElementById(id);

const els = {
  form: $('form'),
  url: $('url'),
  hint: $('hint'),
  reset: $('reset'),
  toggles: $('toggles'),
  theme: $('theme'),
  scale: $('scale'),
  footer: $('footer'),
  status: $('status'),
  author: $('author'),
  frame: $('frame'),
  preview: $('preview'),
  placeholder: $('placeholder'),
  spinner: $('spinner'),
  copy: $('copy'),
  download: $('download'),
  dimensions: $('dimensions'),
  source: $('source'),
  example: $('example'),
  toast: $('toast'),
};

/* ----------------------------- persistence ---------------------------- */

function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
    for (const k of ['theme', 'time', 'date', 'metrics', 'views', 'media', 'footer', 'scale']) {
      if (saved[k] !== undefined) state[k] = saved[k];
    }
  } catch (_) {
    /* ignore */
  }
}

function saveSettings() {
  try {
    const { theme, time, date, metrics, views, media, footer, scale } = state;
    localStorage.setItem(
      LS_KEY,
      JSON.stringify({ theme, time, date, metrics, views, media, footer, scale })
    );
  } catch (_) {
    /* ignore */
  }
}

/* -------------------------------- UI sync ----------------------------- */

function syncControls() {
  document.querySelectorAll('.switch[data-key]').forEach((btn) => {
    btn.setAttribute('aria-checked', String(!!state[btn.dataset.key]));
  });

  document.querySelectorAll('#theme button').forEach((b) => {
    b.classList.toggle('active', b.dataset.value === state.theme);
  });
  document.querySelectorAll('#scale button').forEach((b) => {
    b.classList.toggle('active', Number(b.dataset.value) === Number(state.scale));
  });
  document.querySelectorAll('#footer button').forEach((b) => {
    b.classList.toggle('active', (b.dataset.value === '1') === !!state.footer);
  });
}

/* ------------------------------- rendering ---------------------------- */

function previewQuery() {
  const q = new URLSearchParams();
  q.set('theme', state.theme);
  q.set('time', state.time ? '1' : '0');
  q.set('date', state.date ? '1' : '0');
  q.set('metrics', state.metrics ? '1' : '0');
  q.set('views', state.views ? '1' : '0');
  q.set('media', state.media ? '1' : '0');
  q.set('footer', state.footer ? '1' : '0');
  q.set('scale', String(state.scale));
  return q.toString();
}

function previewUrl() {
  return `/api/v1/screenshot/${state.id}?${previewQuery()}`;
}

function setBusy(busy, label) {
  state.loading = busy;
  els.spinner.hidden = !busy;
  els.frame.setAttribute('aria-busy', String(busy));
  if (busy) {
    els.status.className = 'status busy';
    els.status.textContent = label || 'Rendering…';
  }
}

function setReady() {
  els.status.className = 'status';
  els.status.textContent = 'Ready';
}

function setError(message) {
  els.status.className = 'status error';
  els.status.textContent = message || 'Could not render';
}

let renderTimer = null;
let requestSeq = 0;

function scheduleRender() {
  clearTimeout(renderTimer);
  renderTimer = setTimeout(render, 180);
}

function render() {
  if (!state.id) return;

  const seq = ++requestSeq;
  const url = previewUrl();

  setBusy(true);

  const probe = new Image();
  probe.onload = () => {
    if (seq !== requestSeq) return;
    els.preview.src = url;
    els.preview.hidden = false;
    els.placeholder.hidden = true;
    els.spinner.hidden = true;
    els.download.href = url + '&download=1';
    els.download.download = `tweet-${state.id}.png`;
    els.download.classList.remove('disabled');
    els.download.removeAttribute('aria-disabled');
    els.copy.disabled = false;
    els.dimensions.textContent = `${probe.naturalWidth} × ${probe.naturalHeight} px`;
    setReady();
  };
  probe.onerror = () => {
    if (seq !== requestSeq) return;
    els.spinner.hidden = true;
    setError('Could not render this post');
    els.hint.textContent =
      'The post could not be captured. It may be private, deleted, or the upstream source is rate-limited.';
    els.hint.className = 'hint error';
    if (els.preview.hidden) els.placeholder.hidden = false;
  };
  probe.src = url;
}

/* -------------------------------- actions ----------------------------- */

function showToast(text, bad = false) {
  els.toast.textContent = text;
  els.toast.classList.toggle('bad', bad);
  els.toast.hidden = false;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => (els.toast.hidden = true), 2200);
}

async function generate(raw) {
  const value = String(raw || '').trim();
  if (!value) {
    els.hint.textContent = 'Paste an X / Twitter status link first.';
    els.hint.className = 'hint error';
    els.url.focus();
    return;
  }

  els.hint.textContent = 'Looking up the post…';
  els.hint.className = 'hint';
  setBusy(true, 'Looking up post…');

  try {
    const res = await fetch('/api/tweet?url=' + encodeURIComponent(value), {
      headers: { accept: 'application/json' },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Post not found');

    const tweet = data.tweet;
    state.id = tweet.id;
    state.url = tweet.url || value;

    els.author.textContent = `${tweet.author.name} · @${tweet.author.handle}`;
    els.source.innerHTML = '';
    const link = document.createElement('a');
    link.href = state.url;
    link.target = '_blank';
    link.rel = 'noreferrer noopener';
    link.textContent = `${tweet.author.handle} ↗`;
    els.source.append('Source: ', link);

    els.hint.textContent = 'Post loaded. Adjust the display settings below.';
    els.hint.className = 'hint ok';

    const next = new URL(location.href);
    next.searchParams.set('url', state.url);
    history.replaceState(null, '', next);

    render();
  } catch (err) {
    setBusy(false);
    setError('Lookup failed');
    els.hint.textContent =
      err.message === 'Failed to fetch'
        ? 'Network error. Is the server running?'
        : `${err.message}. Check that the post is public and the link is complete.`;
    els.hint.className = 'hint error';
  }
}

async function copyImage() {
  if (!state.id) return;
  const url = previewUrl();
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('fetch failed');
    const blob = await res.blob();
    if (!navigator.clipboard || !window.ClipboardItem) throw new Error('unsupported');
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
    showToast('Image copied to clipboard');
  } catch (_) {
    window.open(url, '_blank', 'noopener');
    showToast('Opened image in a new tab', true);
  }
}

function resetSettings() {
  Object.assign(state, {
    theme: DEFAULTS.theme,
    time: DEFAULTS.time,
    date: DEFAULTS.date,
    metrics: DEFAULTS.metrics,
    views: DEFAULTS.views,
    media: DEFAULTS.media,
    footer: DEFAULTS.footer,
    scale: DEFAULTS.scale,
  });
  syncControls();
  saveSettings();
  if (state.id) render();
}

/* -------------------------------- events ------------------------------ */

els.form.addEventListener('submit', (e) => {
  e.preventDefault();
  generate(els.url.value);
});

els.toggles.addEventListener('click', (e) => {
  const btn = e.target.closest('.switch[data-key]');
  if (!btn) return;
  const key = btn.dataset.key;
  state[key] = !state[key];
  btn.setAttribute('aria-checked', String(state[key]));
  saveSettings();
  scheduleRender();
});

els.theme.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-value]');
  if (!btn) return;
  state.theme = btn.dataset.value;
  syncControls();
  saveSettings();
  scheduleRender();
});

els.scale.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-value]');
  if (!btn) return;
  state.scale = Number(btn.dataset.value);
  syncControls();
  saveSettings();
  scheduleRender();
});

els.footer.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-value]');
  if (!btn) return;
  state.footer = btn.dataset.value === '1';
  syncControls();
  saveSettings();
  scheduleRender();
});

els.reset.addEventListener('click', resetSettings);
els.copy.addEventListener('click', copyImage);

els.example.addEventListener('click', () => {
  els.url.value = 'https://x.com/karpathy/status/1617979122625712128';
  generate(els.url.value);
});

/* --------------------------------- boot ------------------------------- */

loadSettings();
syncControls();

const initialUrl = new URL(location.href).searchParams.get('url');
if (initialUrl) {
  els.url.value = initialUrl;
  generate(initialUrl);
}

// Auto-generate when a full status URL is pasted / typed.
els.url.addEventListener('paste', () => {
  setTimeout(() => {
    if (/status\/\d{6,25}/.test(els.url.value)) generate(els.url.value);
  }, 0);
});
