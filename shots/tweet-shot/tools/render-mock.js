'use strict';

/**
 * Dev-only: renders a mock tweet, prints the measured CSS boxes and saves a
 * PNG to .cache/mock.png so typography can be tuned numerically against a
 * reference export. Requires the dev server on :3000 (fonts + base href).
 *
 *   npm start          # in another terminal
 *   npm run mock
 */

const path = require('path');
const puppeteer = require('puppeteer-core');
const { renderCard } = require('../lib/card');
const { findChrome } = require('../lib/shot');

const MOCK = {
  id: '1',
  url: 'https://x.com/aaronp613/status/1',
  text: 'Apple has released iOS 27.2 carrier bundles.\n\nThis means iOS 27.2 is coming today!',
  lang: 'en',
  createdAt: '2026-10-26T12:00:00.000Z',
  author: {
    name: 'Aaron',
    handle: 'aaronp613',
    avatar:
      'data:image/svg+xml;base64,' +
      Buffer.from(
        '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect width="80" height="80" fill="#8a8f98"/></svg>'
      ).toString('base64'),
    verified: true,
  },
  metrics: { replies: 12, reposts: 34, likes: 5600, bookmarks: 90, views: 123400 },
  media: [],
  quote: null,
  poll: null,
};

const OPTS = {
  theme: 'light',
  time: false,
  date: true,
  metrics: false,
  views: false,
  media: false,
  footer: true,
  scale: 1,
};

(async () => {
  const browser = await puppeteer.launch({
    executablePath: findChrome(),
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--font-render-hinting=none', '--force-color-profile=srgb'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 560, height: 700, deviceScaleFactor: 1 });

  const html = renderCard(MOCK, OPTS).replace('<head>', '<head><base href="http://localhost:3000/">');
  await page.setContent(html, { waitUntil: 'networkidle0' });
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, 120));

  const box = await page.evaluate(() => {
    const box = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {
        x: +r.x.toFixed(1),
        y: +r.y.toFixed(1),
        w: +r.width.toFixed(1),
        h: +r.height.toFixed(1),
        font: getComputedStyle(el).fontSize,
      };
    };
    return {
      card: box('.card'),
      name: box('.name'),
      handle: box('.handle'),
      text: box('.text'),
      meta: box('.meta'),
      footer: box('.footer'),
      avatar: box('.avatar'),
      brand: box('.brand svg'),
    };
  });

  const out = path.join(__dirname, '..', '.cache', 'mock.png');
  await (await page.$('#shot')).screenshot({ path: out });
  await browser.close();

  console.log(JSON.stringify(box, null, 2));
  console.log('saved', out);
})();
