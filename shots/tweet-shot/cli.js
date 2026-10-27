#!/usr/bin/env node
'use strict';

const path = require('path');
const fs = require('fs');
const puppeteer = require('puppeteer-core');
const { parseTweetInput, fetchTweet } = require('./lib/tweet');
const { renderCard } = require('./lib/card');
const { findChrome } = require('./lib/shot');

async function main() {
  const input = process.argv[2];
  const outputPath = process.argv[3];

  if (!input) {
    console.error(JSON.stringify({ success: false, error: 'Tweet URL veya ID gerekli' }));
    process.exit(1);
  }

  const parsed = parseTweetInput(input);
  if (!parsed || !parsed.id) {
    console.error(JSON.stringify({ success: false, error: 'Geçersiz Twitter / X linki veya ID' }));
    process.exit(1);
  }

  // 1. Tweet verilerini çek
  const tweet = await fetchTweet(parsed.id);

  // 2. Kullanıcının belirttiği default ayarlar:
  // time: false, date: false, views: false, metrics: false, media: true, footer: false, theme: 'oled'
  const opts = {
    theme: 'oled',
    time: false,
    date: false,
    metrics: false,
    views: false,
    media: true,
    footer: false,
    scale: 2,
  };

  const publicPath = path.resolve(__dirname, 'public');
  const html = renderCard(tweet, opts).replace('<head>', `<head><base href="file://${publicPath}/">`);

  // 3. Headless Chrome ile render
  const browser = await puppeteer.launch({
    executablePath: findChrome(),
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--allow-file-access-from-files',
      '--font-render-hinting=none',
      '--force-color-profile=srgb',
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 560, height: 700, deviceScaleFactor: opts.scale });
    await page.setContent(html, { waitUntil: 'networkidle0' });
    await page.waitForFunction("document.documentElement.dataset.ready === '1'", { timeout: 15000 });

    const el = await page.$('#shot');
    if (!el) throw new Error('Shot elementi bulunamadı');

    const buf = await el.screenshot({ type: 'png' });

    if (outputPath) {
      fs.writeFileSync(outputPath, buf);
    } else {
      process.stdout.write(buf);
    }

    console.log(
      JSON.stringify({
        success: true,
        id: tweet.id,
        author: tweet.author.handle,
        name: tweet.author.name,
        text: tweet.text ? tweet.text.slice(0, 100) : '',
        mediaCount: tweet.media ? tweet.media.length : 0,
      })
    );
  } finally {
    await browser.close().catch(() => {});
  }
}

main().catch((err) => {
  console.error(JSON.stringify({ success: false, error: err.message || String(err) }));
  process.exit(1);
});
