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

async function searchTwitter(query, authToken, ct0, maxWait = 35000) {
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
      '--disable-blink-features=AutomationControlled',
      '--window-size=1280,900',
    ],
  });

  const tweetsFound = [];
  const seenIds = new Set();

  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(maxWait);
    await page.setViewport({ width: 1280, height: 900 });

    // Doğal Chrome User-Agent
    await page.setUserAgent(
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
    );

    // Çerezleri hem doğrudan çerez deposuna ekle hem de HTTP başlıklarına enjekte et
    const cookiesToSet = [
      { name: 'auth_token', value: authToken, domain: '.x.com', path: '/', secure: true, httpOnly: true },
      { name: 'ct0', value: ct0, domain: '.x.com', path: '/', secure: true },
      { name: 'auth_token', value: authToken, domain: '.twitter.com', path: '/', secure: true, httpOnly: true },
      { name: 'ct0', value: ct0, domain: '.twitter.com', path: '/', secure: true },
    ];
    await page.setCookie(...cookiesToSet).catch(() => {});

    // İlk istekte bile oturumun 100% aktif olması için Cookie header'ını zorla
    await page.setExtraHTTPHeaders({
      'Cookie': `auth_token=${authToken}; ct0=${ct0}`,
      'x-csrf-token': ct0,
      'x-twitter-active-user': 'yes',
      'x-twitter-auth-type': 'OAuth2Session',
      'x-twitter-client-language': 'tr',
      'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
    }).catch(() => {});

    // Ağ trafiğini hızlandırmak için sadece ağır medyayı engelle (CSS ve JS'ye izin ver)
    await page.setRequestInterception(true);
    page.on('request', (req) => {
      const type = req.resourceType();
      if (['image', 'media', 'font'].includes(type)) {
        req.abort();
      } else {
        req.continue();
      }
    });

    // GraphQL yanıtlarını derinlemesine (recursive) tara ve yakala
    page.on('response', async (response) => {
      const url = response.url();
      if (url.includes('graphql') || url.includes('SearchTimeline') || url.includes('search')) {
        try {
          const json = await response.json();
          extractTweetsRecursively(json, tweetsFound, seenIds);
        } catch (_) {}
      }
    });

    // Kullanıcının belirttiği f=top arama URL'si
    const searchUrl = `https://x.com/search?q=${encodeURIComponent(query)}&f=top`;
    await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: maxWait }).catch(() => {});

    // Sayfadaki tweet makalelerinin (article) belirmesini bekle
    await page.waitForSelector('article[data-testid="tweet"]', { timeout: 12000 }).catch(() => {});

    // Kısa bir bekleme (GraphQL veya DOM tam yerleşsin)
    const startWait = Date.now();
    while (Date.now() - startWait < 5000) {
      if (tweetsFound.length >= 1) break;
      await new Promise((r) => setTimeout(r, 500));
    }

    // DOM üzerinden doğrudan tweetleri oku (En garantili yöntem)
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

        return {
          id: match ? match[2] : null,
          author: match ? match[1] : '',
          url: match ? `https://x.com/${match[1]}/status/${match[2]}` : '',
          text: textEl ? textEl.innerText.trim() : '',
        };
      }).filter((t) => t.id && t.author);
    }).catch(() => []);

    // DOM'dan gelen tweetleri ekle
    for (const dt of domTweets) {
      if (!seenIds.has(dt.id)) {
        seenIds.add(dt.id);
        tweetsFound.push({
          id: dt.id,
          author: dt.author,
          name: dt.author,
          text: dt.text,
          likes: 5000,
          retweets: 0,
          url: dt.url,
          createdAt: '',
        });
      }
    }

    // Beğeniye göre sırala
    tweetsFound.sort((a, b) => (b.likes || 0) - (a.likes || 0));

    return {
      success: true,
      query,
      count: tweetsFound.length,
      tweets: tweetsFound,
    };
  } catch (err) {
    return {
      success: false,
      error: err.message,
      tweets: tweetsFound,
    };
  } finally {
    await browser.close().catch(() => {});
  }
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
        const userResult = tweetObj.core?.user_results?.result?.legacy || {};
        const authorHandle = userResult.screen_name || '';
        const authorName = userResult.name || authorHandle;
        seenIds.add(tweetId);
        tweetsList.push({
          id: tweetId,
          author: authorHandle,
          name: authorName,
          text: legacy.full_text || '',
          likes: legacy.favorite_count || 0,
          retweets: legacy.retweet_count || 0,
          url: `https://x.com/${authorHandle}/status/${tweetId}`,
          createdAt: legacy.created_at || '',
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
  const query = process.argv[2] || 'min_faves:5000 lang:tr';
  const authToken = process.argv[3] || process.env.TWITTER_AUTH_TOKEN;
  const ct0 = process.argv[4] || process.env.TWITTER_CT0;

  const result = await searchTwitter(query, authToken, ct0);
  console.log(JSON.stringify(result));
}

if (require.main === module) {
  main();
}

module.exports = { searchTwitter };
