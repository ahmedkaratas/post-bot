'use strict';

const express = require('express');
const path = require('path');
const { parseTweetInput, fetchTweet } = require('./lib/tweet');
const { renderCard, DEFAULTS } = require('./lib/card');
const { screenshot } = require('./lib/shot');

const PORT = Number(process.env.PORT || 3000);
const BASE = process.env.BASE_URL || `http://127.0.0.1:${PORT}`;
const PUBLIC_DIR = path.join(__dirname, 'public');

const app = express();
app.disable('x-powered-by');
app.use(express.json({ limit: '32kb' }));
app.use(
  express.static(PUBLIC_DIR, {
    maxAge: '7d',
    setHeaders(res, filePath) {
      if (filePath.endsWith('.html')) res.setHeader('Cache-Control', 'no-cache');
    },
  })
);

/* --------------------------- tweet data cache -------------------------- */

const TTL = Number(process.env.TWEET_CACHE_TTL || 3 * 60 * 1000);
const tweetCache = new Map(); // id -> { at, tweet }
const inflight = new Map();

async function getTweet(id) {
  const hit = tweetCache.get(id);
  if (hit && Date.now() - hit.at < TTL) return hit.tweet;
  if (inflight.has(id)) return inflight.get(id);

  const p = fetchTweet(id)
    .then((tweet) => {
      tweetCache.set(id, { at: Date.now(), tweet });
      return tweet;
    })
    .finally(() => inflight.delete(id));

  inflight.set(id, p);
  return p;
}

/* ------------------------------ options ------------------------------- */

const toBool = (v, def = false) => {
  if (v === undefined || v === null || v === '') return def;
  return v === '1' || v === 'true' || v === 'on' || v === 'yes';
};
const clampInt = (v, def, min, max) => {
  const n = Number.parseInt(v, 10);
  if (!Number.isFinite(n)) return def;
  return Math.max(min, Math.min(max, n));
};

function parseOptions(q = {}) {
  return {
    theme: q.theme === 'oled' ? 'oled' : q.theme === 'dark' ? 'dark' : 'light',
    time: toBool(q.time),
    date: toBool(q.date),
    metrics: toBool(q.metrics),
    views: toBool(q.views),
    media: toBool(q.media),
    footer: q.footer === undefined ? DEFAULTS.footer : toBool(q.footer),
    scale: clampInt(q.scale, DEFAULTS.scale, 1, 3),
  };
}

function optionsToQuery(opts) {
  const q = new URLSearchParams();
  q.set('theme', opts.theme);
  for (const k of ['time', 'date', 'metrics', 'views', 'media', 'footer']) {
    q.set(k, opts[k] ? '1' : '0');
  }
  q.set('scale', String(opts.scale));
  return q.toString();
}

const validId = (id) => /^\d{6,25}$/.test(String(id || ''));

function normalizeId(input) {
  if (validId(input)) return String(input);
  const parsed = parseTweetInput(input);
  return parsed ? parsed.id : null;
}

/* ------------------------------- routes ------------------------------- */

app.get('/health', (_req, res) => res.json({ ok: true, uptime: process.uptime() }));

// Tweet JSON (used by the editor to validate a link before rendering).
app.get('/api/tweet', async (req, res) => {
  const id = normalizeId(req.query.url || req.query.id);
  if (!id) return res.status(400).json({ error: 'Paste a valid X/Twitter status URL.' });
  try {
    const tweet = await getTweet(id);
    res.set('Cache-Control', 'public, max-age=60');
    res.json({ tweet, options: DEFAULTS });
  } catch (e) {
    res.status(404).json({ error: 'Tweet not found or unavailable.', details: e.details || e.message });
  }
});

app.get('/api/tweet/:id', async (req, res) => {
  const id = normalizeId(req.params.id);
  if (!id) return res.status(400).json({ error: 'Invalid tweet id.' });
  try {
    const tweet = await getTweet(id);
    res.json({ tweet });
  } catch (e) {
    res.status(404).json({ error: 'Tweet not found or unavailable.', details: e.details || e.message });
  }
});

// HTML card used by the capture pipeline (and handy for debugging).
app.get('/render/:id', async (req, res) => {
  const id = normalizeId(req.params.id);
  if (!id) return res.status(400).type('html').send('<h1>Invalid tweet id</h1>');
  try {
    const tweet = await getTweet(id);
    const opts = parseOptions(req.query);
    res.set('Cache-Control', 'no-store');
    res.type('html').send(renderCard(tweet, opts));
  } catch (e) {
    res.status(404).type('html').send('<h1>Tweet unavailable</h1>');
  }
});

// PNG capture. Mirrors the public shape of the original service:
//   /api/v1/screenshot/:id?format=png&theme=light&time=1&date=1...
async function screenshotHandler(req, res) {
  const raw = req.params.id || req.query.url || req.query.id;
  const id = normalizeId(raw);
  if (!id) return res.status(400).json({ error: 'Paste a valid X/Twitter status URL or id.' });

  const format = (req.query.format || 'png').toLowerCase();
  if (format !== 'png') {
    return res.status(400).json({ error: `Unsupported format "${format}". This build renders PNG only.` });
  }

  const opts = parseOptions(req.query);

  try {
    const tweet = await getTweet(id);
    const renderUrl = `${BASE}/render/${id}?${optionsToQuery(opts)}`;

    // Short cache bucket so metrics do not stay stale forever.
    const bucket = Math.floor(Date.now() / (10 * 60 * 1000));
    const buf = await screenshot({
      id: `${id}-${bucket}`,
      renderUrl,
      options: opts,
    });

    const filename = `tweet-${id}${opts.theme === 'dark' ? '-dark' : ''}.png`;
    res.set({
      'Content-Type': 'image/png',
      'Content-Length': String(buf.length),
      'Cache-Control': 'public, max-age=600',
      'Content-Disposition': `${req.query.download ? 'attachment' : 'inline'}; filename="${filename}"`,
    });
    res.end(buf);
  } catch (e) {
    const status = e && e.status === 404 ? 404 : 502;
    res.status(status).json({ error: 'Screenshot failed.', details: e.details || e.message });
  }
}

app.get('/api/v1/screenshot/:id', screenshotHandler);
app.get('/api/v1/screenshot', screenshotHandler);
app.get('/api/screenshot/:id', screenshotHandler);

app.use((req, res) => {
  if (req.path.startsWith('/api/')) return res.status(404).json({ error: 'Not found' });
  res.status(404).sendFile(path.join(PUBLIC_DIR, 'index.html'));
});

/* ------------------------------- boot -------------------------------- */

let server;
if (require.main === module) {
  server = app.listen(PORT, '127.0.0.1', () => {
    console.log(`\n  TweetShot running → http://localhost:${PORT}\n`);
  });
}

process.on('SIGINT', async () => {
  const { closeBrowser } = require('./lib/shot');
  await closeBrowser();
  if (server) server.close(() => process.exit(0));
  else process.exit(0);
});

module.exports = app;
