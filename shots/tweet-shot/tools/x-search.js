#!/usr/bin/env node
'use strict';

/**
 * X/Twitter Search Scraper via Puppeteer
 * 
 * Verilen arama sorgusunu (örn: min_faves:5000 lang:tr since:2026-10-25) 
 * Puppeteer ve kullanıcının oturum çerezleri (auth_token, ct0) ile çalıştırır.
 * SearchTimeline GraphQL isteğini yakalar ve yapılandırılmış tweet listesi döner.
 */

const puppeteer = require('puppeteer-core');
const { findChrome } = require('../lib/shot');

async function searchTwitter(query, authToken, ct0, maxWait = 25000) {
  if (!authToken || !ct0) {
    return {
      success: false,
      error: 'TWITTER_AUTH_TOKEN ve TWITTER_CT0 çerezleri gerekli.',
      tweets: []
    };
  }

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
      '--window-size=1280,800',
    ],
  });

  const tweetsFound = [];
  const seenIds = new Set();

  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(maxWait);
    await page.setViewport({ width: 1280, height: 800 });
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36');

    // Ağ trafiğini hızlandırmak için gereksiz medya ve fontları engelle
    await page.setRequestInterception(true);
    page.on('request', (req) => {
      const type = req.resourceType();
      if (['image', 'media', 'font', 'video'].includes(type)) {
        req.abort();
      } else {
        req.continue();
      }
    });

    // Çerezleri enjekte et
    await page.setCookie(
      {
        name: 'auth_token',
        value: authToken,
        domain: '.x.com',
        path: '/',
        secure: true,
        httpOnly: true,
      },
      {
        name: 'ct0',
        value: ct0,
        domain: '.x.com',
        path: '/',
        secure: true,
      },
      {
        name: 'auth_token',
        value: authToken,
        domain: '.twitter.com',
        path: '/',
        secure: true,
        httpOnly: true,
      },
      {
        name: 'ct0',
        value: ct0,
        domain: '.twitter.com',
        path: '/',
        secure: true,
      }
    );

    // GraphQL SearchTimeline yanıtlarını yakala
    page.on('response', async (response) => {
      const url = response.url();
      if (url.includes('/SearchTimeline') || url.includes('search_timeline')) {
        try {
          const json = await response.json();
          parseSearchTimelineJson(json, tweetsFound, seenIds);
        } catch (_) {}
      }
    });

    const searchUrl = `https://x.com/search?q=${encodeURIComponent(query)}&f=top`;
    await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: maxWait }).catch(() => {});

    // Sayfanın yüklenmesi ve GraphQL yanıtının gelmesi için bekle
    const startWait = Date.now();
    while (Date.now() - startWait < 8000) {
      if (tweetsFound.length >= 5) break;
      await new Promise((r) => setTimeout(r, 800));
    }

    // DOM üzerinden ek kontrol (Yedek mekanizma)
    if (tweetsFound.length === 0) {
      const domTweets = await page.$$eval('article[data-testid="tweet"]', (articles) => {
        return articles.map((art) => {
          const link = art.querySelector('a[href*="/status/"]');
          const href = link ? link.getAttribute('href') : '';
          const match = href.match(/\/([a-zA-Z0-9_]+)\/status\/(\d+)/);
          const textEl = art.querySelector('div[data-testid="tweetText"]');
          return {
            id: match ? match[2] : null,
            author: match ? match[1] : '',
            url: match ? `https://x.com${match[0]}` : '',
            text: textEl ? textEl.innerText : '',
          };
        }).filter((t) => t.id);
      }).catch(() => []);

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
          });
        }
      }
    }

    // Beğeni sayısına göre büyükten küçüğe sırala
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

function parseSearchTimelineJson(json, tweetsList, seenIds) {
  try {
    const instructions =
      json?.data?.search_by_raw_query?.search_timeline?.timeline?.instructions ||
      json?.data?.search_timeline?.timeline?.instructions ||
      [];

    for (const inst of instructions) {
      const entries = inst.entries || (inst.entry ? [inst.entry] : []);
      for (const entry of entries) {
        const itemContent = entry.content?.itemContent;
        if (!itemContent || itemContent.itemType !== 'TimelineTweet') continue;

        const result = itemContent.tweet_results?.result;
        if (!result) continue;

        // Retweet ise orijinal tweeti al veya normal tweet
        const tweetObj = result.tweet || result;
        const legacy = tweetObj.legacy;
        if (!legacy) continue;

        const tweetId = tweetObj.rest_id || legacy.id_str;
        if (!tweetId || seenIds.has(tweetId)) continue;

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
  } catch (_) {}
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
