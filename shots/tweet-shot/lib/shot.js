'use strict';

/**
 * PNG capture pipeline.
 *
 * The card is rendered as a real HTML page (same markup as /render/:id) and
 * captured with headless Chrome at `scale`x, so the downloaded image is a
 * pixel-for-pixel match of the preview and supports any CSS the browser does
 * (webfonts, media, emoji, shadows). Results are cached by option hash.
 */

const fs = require('fs');
const fsp = require('fs/promises');
const path = require('path');
const crypto = require('crypto');
const puppeteer = require('puppeteer-core');

const CACHE_DIR = path.join(__dirname, '..', '.cache');
fs.mkdirSync(CACHE_DIR, { recursive: true });

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  process.env.PUPPETEER_EXECUTABLE_PATH,
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/snap/bin/chromium',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean);

function findChrome() {
  for (const p of CHROME_CANDIDATES) {
    try {
      if (fs.existsSync(p)) return p;
    } catch (_) {
      /* ignore */
    }
  }
  throw new Error(
    'Chrome not found. Install Chrome/Chromium or set CHROME_PATH=/path/to/chrome'
  );
}

let browserPromise = null;

async function getBrowser() {
  if (browserPromise) {
    const b = await browserPromise.catch(() => null);
    if (b && b.connected !== false && b.isConnected()) return b;
    browserPromise = null;
  }
  browserPromise = puppeteer.launch({
    executablePath: findChrome(),
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--hide-scrollbars',
      '--force-color-profile=srgb',
      '--font-render-hinting=none',
      '--disable-lcd-text',
      '--disable-background-timer-throttling',
      '--disable-renderer-backgrounding',
    ],
  });
  return browserPromise;
}

async function closeBrowser() {
  if (!browserPromise) return;
  const b = await browserPromise.catch(() => null);
  browserPromise = null;
  if (b) await b.close().catch(() => {});
}

/* ------------------------------- cache ------------------------------- */

const memory = new Map(); // key -> Buffer
const MEMORY_LIMIT = 60;

function cacheKey(id, opts) {
  return crypto
    .createHash('sha1')
    .update(id + '|' + JSON.stringify(opts))
    .digest('hex');
}

function cachePath(key) {
  return path.join(CACHE_DIR, key + '.png');
}

async function readCache(key) {
  if (memory.has(key)) return memory.get(key);
  try {
    const buf = await fsp.readFile(cachePath(key));
    remember(key, buf);
    return buf;
  } catch (_) {
    return null;
  }
}

function remember(key, buf) {
  memory.set(key, buf);
  if (memory.size > MEMORY_LIMIT) {
    const first = memory.keys().next().value;
    memory.delete(first);
  }
}

/* ---------------------------- concurrency ---------------------------- */

function semaphore(max) {
  let active = 0;
  const queue = [];
  const next = () => {
    if (active >= max || !queue.length) return;
    active++;
    const { fn, resolve, reject } = queue.shift();
    fn()
      .then(resolve, reject)
      .finally(() => {
        active--;
        next();
      });
  };
  return (fn) =>
    new Promise((resolve, reject) => {
      queue.push({ fn, resolve, reject });
      next();
    });
}

const limit = semaphore(Number(process.env.RENDER_CONCURRENCY || 3));

/* ------------------------------ capture ------------------------------ */

async function capture(url, scale) {
  const browser = await getBrowser();
  const page = await browser.newPage();
  try {
    await page.setViewport({
      width: 560,
      height: 700,
      deviceScaleFactor: scale,
    });
    page.setDefaultTimeout(20000);
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForFunction(
      "document.documentElement.dataset.ready === '1'",
      { timeout: 20000 }
    );
    const el = await page.$('#shot');
    if (!el) throw new Error('render root missing');
    return await el.screenshot({ type: 'png', captureBeyondViewport: true });
  } finally {
    await page.close().catch(() => {});
  }
}

/**
 * @param {{ id: string, renderUrl: string, options: object }} args
 * @returns {Promise<Buffer>}
 */
async function screenshot({ id, renderUrl, options }) {
  const key = cacheKey(id, options);
  const hit = await readCache(key);
  if (hit) return hit;

  const buf = await limit(() => capture(renderUrl, options.scale || 2));
  remember(key, buf);
  fsp.writeFile(cachePath(key), buf).catch(() => {});
  return buf;
}

module.exports = { screenshot, cacheKey, getBrowser, closeBrowser, findChrome };
