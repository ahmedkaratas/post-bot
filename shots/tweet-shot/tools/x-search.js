#!/usr/bin/env node
'use strict';

/**
 * X/Twitter Search Scraper via Puppeteer
 * 
 * Verilen arama sorgusunu (örn: min_faves:5000 lang:tr since:2026-10-25) 
 * Puppeteer ve kullanıcının oturum çerezleri (auth_token, ct0) ile çalıştırır.
 */

const puppeteer = require('puppeteer-core');
const { findChrome } = require('../lib/shot');

async function searchTwitter(query, authToken, ct0, maxWait = 45000) {
  if (!authToken || !ct0) {
    return {
      success: false,
      error: 'TWITTER_AUTH_TOKEN ve TWITTER_CT0 çerezleri gerekli.',
      tweets: []
    };
  }

  authToken = String(authToken).trim();
  ct0 = String(ct0).trim();

  const browser = await puppeteer.launch({
    executablePath: findChrome(),
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--no-first-run',
      '--disable-extensions',
      '--disable-component-update',
      '--disable-background-networking',
      '--disable-sync',
      '--disable-default-apps',
      '--mute-audio',
      '--no-default-browser-check',
      '--disable-blink-features=AutomationControlled',
      '--window-size=1280,900',
      '--js-flags=--max-old-space-size=256',
    ],
  });

  const tweetsFound = [];
  const seenIds = new Set();

  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(maxWait);
    await page.setViewport({ width: 1280, height: 900 });

    // Ağ trafiğini ve RAM kullanımını %70 azaltmak için resim, video ve font indirmelerini iptal et
    await page.setRequestInterception(true);
    page.on('request', (req) => {
      const type = req.resourceType();
      if (['image', 'media', 'font'].includes(type)) {
        req.abort();
      } else {
        req.continue();
      }
    });

    // Doğal Chrome User-Agent ve webdriver gizleme
    await page.setUserAgent(
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
    );
    await page.evaluateOnNewDocument(() => {
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    });

    // Oturum çerezlerini doğrudan çerez deposuna ekle (CORS hatası yaratmaz)
    const cookiesToSet = [
      { name: 'auth_token', value: authToken, domain: '.x.com', path: '/', secure: true, httpOnly: true },
      { name: 'ct0', value: ct0, domain: '.x.com', path: '/', secure: true },
      { name: 'auth_token', value: authToken, domain: '.twitter.com', path: '/', secure: true, httpOnly: true },
      { name: 'ct0', value: ct0, domain: '.twitter.com', path: '/', secure: true },
    ];
    await page.setCookie(...cookiesToSet);

    // SearchTimeline GraphQL yanıtını sayfa açılmadan ÖNCE dinlemeye başla (en hızlı ve garantili yöntem)
    const responsePromise = page.waitForResponse(
      (res) => res.url().includes('SearchTimeline') && res.status() === 200,
      { timeout: 35000 }
    ).catch(() => null);

    // Kullanıcının belirttiği f=top arama URL'sine git
    const searchUrl = `https://x.com/search?q=${encodeURIComponent(query)}&f=top`;
    await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: 35000 }).catch(() => {});

    // SearchTimeline yanıtını bekle
    const searchRes = await responsePromise;
    if (searchRes) {
      try {
        const json = await searchRes.json();
        extractTweetsRecursively(json, tweetsFound, seenIds);
      } catch (_) {}
    }

    const currentUrl = page.url();
    const pageTitle = await page.title().catch(() => '');

    // Eğer oturum düşmüşse ve login sayfasına yönlendirildiyse net hata dön
    if (currentUrl.includes('/login') || currentUrl.includes('/i/flow/login')) {
      return {
        success: false,
        error: 'Twitter oturumu geçersiz (Login sayfasına yönlendirildi). Lütfen güncel TWITTER_AUTH_TOKEN ve TWITTER_CT0 çerezlerini girin.',
        currentUrl,
        title: pageTitle,
        tweets: []
      };
    }

    // GraphQL yakalanamadıysa DOM makale elemanlarını yedek olarak tara
    if (tweetsFound.length === 0) {
      await page.waitForSelector('article[data-testid="tweet"]', { timeout: 3000 }).catch(() => {});
      const domTweets = await page.$$eval('article[data-testid="tweet"]', (articles) => {
        return articles.map((art) => {
          const links = Array.from(art.querySelectorAll('a[href*="/status/"]'));
          let targetHref = '';
          for (const l of links) {
            const h = l.getAttribute('href') || '';
            if (h.includes('/status/') && !h.includes('/photo/') && !h.includes('/video/')) {
              targetHref = h;
              break;
            }
          }
          if (!targetHref && links.length > 0) {
            targetHref = links[0].getAttribute('href') || '';
          }

          const match = targetHref.match(/\/([a-zA-Z0-9_]+)\/status\/(\d+)/);
          const textEl = art.querySelector('div[data-testid="tweetText"]');

          let likeCount = 0;
          let hasMetrics = false;
          const likeBtn = art.querySelector('button[data-testid="like"]');
          if (likeBtn) {
            const label = likeBtn.getAttribute('aria-label') || '';
            const numMatch = label.match(/(\d[\d,\.]*)/);
            if (numMatch) {
              likeCount = parseInt(numMatch[1].replace(/[,\.]/g, ''), 10) || 0;
              hasMetrics = true;
            }
          }

          return {
            id: match ? match[2] : null,
            author: match ? match[1] : '',
            url: match ? `https://x.com/${match[1]}/status/${match[2]}` : '',
            text: textEl ? textEl.innerText.trim() : '',
            likes: likeCount,
            has_metrics: hasMetrics,
          };
        }).filter((t) => t.id && t.author);
      }).catch(() => []);

      for (const dt of domTweets) {
        if (!seenIds.has(dt.id)) {
          seenIds.add(dt.id);
          // Sayısal verisi olmayan adayı varsayılan 5000 basmak yerine metriksiz olarak kaydet
          tweetsFound.push({
            id: dt.id,
            author: dt.author,
            name: dt.author,
            text: dt.text,
            likes: dt.likes || 0,
            retweets: 0,
            replies: 0,
            quotes: 0,
            bookmarks: 0,
            views: 0,
            lang: '',
            url: dt.url,
            createdAt: '',
            is_promoted: false,
            has_video: false,
            video_url: '',
            has_metrics: Boolean(dt.has_metrics),
            is_metric_missing: !dt.has_metrics
          });
        }
      }
    }

    // Beğeniye göre sırala (en popüler en üstte)
    tweetsFound.sort((a, b) => (b.likes || 0) - (a.likes || 0));

    return {
      success: true,
      query,
      count: tweetsFound.length,
      currentUrl,
      title: pageTitle,
      tweets: tweetsFound,
    };
  } catch (err) {
    return {
      success: false,
      error: err.message,
      tweets: tweetsFound,
    };
  } finally {
    try {
      await Promise.race([
        browser.close(),
        new Promise((r) => setTimeout(r, 2000))
      ]);
    } catch (_) {}
  }
}

function parseMetricCount(val) {
  if (val === undefined || val === null || val === '') return 0;
  if (typeof val === 'number') return val;
  const cleaned = String(val).replace(/,/g, '').trim();
  const num = parseInt(cleaned, 10);
  return isNaN(num) ? 0 : num;
}

function extractVideoMedia(legacy, tweetObj) {
  const extended = legacy?.extended_entities || tweetObj?.extended_entities;
  const mediaList = extended?.media || [];
  for (const m of mediaList) {
    if ((m.type === 'video' || m.type === 'animated_gif') && m.video_info) {
      const variants = m.video_info.variants || [];
      const mp4s = variants
        .filter((v) => v.content_type === 'video/mp4' && v.url)
        .sort((a, b) => (b.bitrate || 0) - (a.bitrate || 0));
      return {
        has_video: true,
        video_url: mp4s[0]?.url || '',
        aspect_ratio: m.video_info.aspect_ratio || [],
        width: m.original_info?.width || 0,
        height: m.original_info?.height || 0,
        thumbnail_url: m.media_url_https || ''
      };
    }
  }
  return { has_video: false, video_url: '', aspect_ratio: [], width: 0, height: 0, thumbnail_url: '' };
}

/**
 * Twitter'ın karmaşık GraphQL JSON çıktısını derinlemesine tarayarak tweet objelerini bulur.
 */
function extractTweetsRecursively(obj, tweetsList, seenIds) {
  if (!obj || typeof obj !== 'object') return;

  // Tweet objesi tespiti
  if (obj.tweet_results?.result || (obj.legacy && obj.rest_id)) {
    const tweetObj = obj.tweet_results?.result?.tweet || obj.tweet_results?.result || obj;
    const legacy = tweetObj.legacy;
    if (legacy && legacy.full_text) {
      const tweetId = tweetObj.rest_id || legacy.id_str;
      if (tweetId && !seenIds.has(tweetId)) {
        const userRes = tweetObj.core?.user_results?.result || {};
        const userCore = userRes.core || userRes.legacy || userRes;
        const authorHandle = userCore.screen_name || userRes.screen_name || '';
        const authorName = userCore.name || userRes.name || authorHandle;
        const cleanUrl = authorHandle
          ? `https://x.com/${authorHandle}/status/${tweetId}`
          : `https://x.com/i/status/${tweetId}`;

        // Promoted / Sponsorlu reklam tespiti
        const isPromoted = Boolean(
          tweetObj.promotedMetadata ||
          tweetObj.promoted_metadata ||
          obj.promotedMetadata ||
          obj.itemContent?.promotedMetadata ||
          (typeof tweetObj.source === 'string' && tweetObj.source.toLowerCase().includes('promoted'))
        );

        const vInfo = extractVideoMedia(legacy, tweetObj);

        seenIds.add(tweetId);
        tweetsList.push({
          id: tweetId,
          author: authorHandle,
          name: authorName,
          text: legacy.full_text || '',
          likes: parseMetricCount(legacy.favorite_count),
          retweets: parseMetricCount(legacy.retweet_count),
          replies: parseMetricCount(legacy.reply_count),
          quotes: parseMetricCount(legacy.quote_count),
          bookmarks: parseMetricCount(legacy.bookmark_count),
          views: parseMetricCount(tweetObj.views?.count),
          lang: legacy.lang || '',
          createdAt: legacy.created_at || '',
          url: cleanUrl,
          is_promoted: isPromoted,
          has_video: vInfo.has_video,
          video_url: vInfo.video_url,
          video_width: vInfo.width,
          video_height: vInfo.height,
          video_thumbnail: vInfo.thumbnail_url,
          has_metrics: true
        });
      }
    }
  }

  // Alt nesneleri tara
  if (Array.isArray(obj)) {
    for (const item of obj) {
      extractTweetsRecursively(item, tweetsList, seenIds);
    }
  } else {
    for (const key of Object.keys(obj)) {
      extractTweetsRecursively(obj[key], tweetsList, seenIds);
    }
  }
}

async function main() {
  const killTimer = setTimeout(() => {
    console.error('Hard timeout in x-search main (65s)');
    process.exit(1);
  }, 65000);
  killTimer.unref();

  try {
    const query = process.argv[2] || 'min_faves:5000 lang:tr';
    const authToken = process.env.TWITTER_AUTH_TOKEN || process.argv[3];
    const ct0 = process.env.TWITTER_CT0 || process.argv[4];

    const result = await searchTwitter(query, authToken, ct0);
    console.log(JSON.stringify(result));
  } catch (err) {
    console.error('Scraper main hatası:', err);
    console.log(JSON.stringify({ success: false, error: err.message || String(err), tweets: [] }));
  } finally {
    clearTimeout(killTimer);
    process.exit(0);
  }
}

if (require.main === module) {
  main();
}

module.exports = { searchTwitter };
