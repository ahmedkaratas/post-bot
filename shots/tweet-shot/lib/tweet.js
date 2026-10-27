'use strict';

/**
 * Tweet retrieval + normalization.
 *
 * Confirmed during the reverse-engineering pass:
 *  - twittershots.com itself calls an internal API at api.twittershots.com
 *    (`/api/v1/screenshot/:id`) which requires an `X-API-KEY` (HTTP 401 otherwise).
 *  - The public X "syndication" endpoint is keyless and returns the core tweet
 *    payload, but it has no view count and poor media metadata.
 *  - fxtwitter / vxtwitter expose the full public payload (text, author, media,
 *    metrics, views, quote, poll) without authentication.
 *
 * We try the richest source first and gracefully degrade to the keyless
 * X syndication endpoint so the tool still works when the mirrors are down.
 */

const UA =
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36';

const HOSTS = [
  'twitter.com',
  'www.twitter.com',
  'mobile.twitter.com',
  'x.com',
  'www.x.com',
  'mobile.x.com',
  'vxtwitter.com',
  'fxtwitter.com',
  'fixupx.com',
];

/**
 * Accepts a full status URL (x.com / twitter.com / mirrors) or a bare numeric id.
 * @returns {{ id: string, handle?: string } | null}
 */
function parseTweetInput(input) {
  if (!input) return null;
  const raw = String(input).trim();
  if (/^\d{1,25}$/.test(raw)) return { id: raw };

  // handles URLs such as https://x.com/user/status/123?t=...&s=20
  const hostPart = HOSTS.map((h) => h.replace(/\./g, '\\.')).join('|');
  const re = new RegExp(
    `(?:${hostPart})\\/(?:([A-Za-z0-9_]{1,15})\\/)?(?:status|statuses|i\\/status)\\/(\\d{1,25})`,
    'i'
  );
  const m = raw.match(re);
  if (m) return { id: m[2], handle: m[1] && m[1] !== 'i' ? m[1] : undefined };

  // last resort: any URL containing a numeric status id
  const loose = raw.match(/status(?:es)?\/(\d{1,25})/i);
  if (loose) return { id: loose[1] };
  return null;
}

async function getJson(url, timeout = 4000) {
  const res = await fetch(url, {
    headers: { 'user-agent': UA, accept: 'application/json' },
    signal: AbortSignal.timeout(timeout),
  });
  if (!res.ok) {
    const err = new Error(`upstream ${res.status} for ${url}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/* ------------------------------------------------------------------ *
 * Source 1: fxtwitter / vxtwitter (rich payload, no auth)
 * ------------------------------------------------------------------ */

function normalizeFx(payload) {
  const t = payload && payload.tweet;
  if (!t || !t.id) return null;
  const a = t.author || {};

  const media = []
    .concat((t.media && (t.media.all || t.media.photos || t.media.videos)) || [])
    .filter(Boolean)
    .map((m) => ({
      type: m.type === 'gif' ? 'gif' : m.type === 'video' ? 'video' : 'photo',
      url: m.url || m.thumbnail_url || '',
      thumb: m.thumbnail_url || m.url || '',
      width: m.width || 0,
      height: m.height || 0,
      alt: m.altText || m.alt_text || '',
      duration: m.duration || 0,
    }))
    .filter((m) => m.thumb || m.type === 'photo');

  let quote = null;
  if (t.quote && t.quote.id) {
    const q = t.quote;
    const qa = q.author || {};
    quote = {
      id: q.id,
      text: q.text || '',
      author: {
        name: qa.name || '',
        handle: qa.screen_name || '',
        avatar: upscaleAvatar(qa.avatar_url),
        verified: !!(qa.verification && qa.verification.verified),
      },
      media: q.media && q.media.all && q.media.all[0] ? q.media.all[0].thumbnail_url || q.media.all[0].url : null,
    };
  }

  let poll = null;
  if (t.poll && Array.isArray(t.poll.choices)) {
    poll = {
      total: t.poll.total_votes || 0,
      choices: t.poll.choices.map((c) => ({
        label: c.label || '',
        count: c.count || 0,
        percent: typeof c.percentage === 'number' ? c.percentage : 0,
      })),
    };
  }

  const rawText = t.text || '';
  const cleanedText = (media.length > 0)
    ? rawText.replace(/\s*https?:\/\/t\.co\/[a-zA-Z0-9]+\s*$/i, '')
    : rawText;

  return {
    id: String(t.id),
    url: t.url || `https://x.com/i/status/${t.id}`,
    text: cleanedText,
    lang: t.lang || 'en',
    createdAt: t.created_timestamp ? new Date(t.created_timestamp * 1000).toISOString() : null,
    author: {
      name: a.name || '',
      handle: a.screen_name || '',
      avatar: upscaleAvatar(a.avatar_url),
      verified: !!(a.verification && a.verification.verified),
      verifiedType: (a.verification && a.verification.type) || null,
    },
    metrics: {
      replies: t.replies || 0,
      reposts: t.retweets || 0,
      likes: t.likes || 0,
      bookmarks: t.bookmarks || 0,
      views: t.views || 0,
    },
    media,
    quote,
    poll,
    source: 'fxtwitter',
  };
}

function upscaleAvatar(url) {
  if (!url) return '';
  return String(url)
    .replace(/_normal(\.\w+)$/, '_400x400$1')
    .replace(/_200x200(\.\w+)$/, '_400x400$1')
    .replace(/_bigger(\.\w+)$/, '_400x400$1');
}

/* ------------------------------------------------------------------ *
 * Source 2: cdn.syndication.twimg.com (keyless, first-party)
 * ------------------------------------------------------------------ */

// Same trick every embed library uses: the "token" is derived from the id.
function syndicationToken(id) {
  const t = (Number(id) / 1e15) * Math.PI;
  return t
    .toString(36)
    .replace(/(0+|\.)/g, '');
}

function normalizeSyndication(payload) {
  if (!payload || !payload.id_str) return null;
  const u = payload.user || {};
  const media = [];
  (payload.photos || []).forEach((p) => {
    media.push({
      type: 'photo',
      url: p.url,
      thumb: p.url,
      width: p.width || 0,
      height: p.height || 0,
      alt: p.altText || '',
    });
  });
  if (payload.video) {
    const v = payload.video;
    media.push({
      type: 'video',
      url: v.url || '',
      thumb: v.poster || '',
      width: v.width || 0,
      height: v.height || 0,
      alt: v.altText || '',
      duration: 0,
    });
  }

  let quote = null;
  if (payload.quoted_tweet && payload.quoted_tweet.id_str) {
    const q = payload.quoted_tweet;
    quote = {
      id: q.id_str,
      text: q.text || '',
      author: {
        name: (q.user && q.user.name) || '',
        handle: (q.user && q.user.screen_name) || '',
        avatar: upscaleAvatar(q.user && q.user.profile_image_url_https),
        verified: !!(q.user && q.user.is_blue_verified),
      },
      media: q.photos && q.photos[0] ? q.photos[0].url : null,
    };
  }

  const rawText = payload.text || '';
  const cleanedText = (media.length > 0)
    ? rawText.replace(/\s*https?:\/\/t\.co\/[a-zA-Z0-9]+\s*$/i, '')
    : rawText;

  return {
    id: String(payload.id_str),
    url: u.screen_name
      ? `https://x.com/${u.screen_name}/status/${payload.id_str}`
      : `https://x.com/i/status/${payload.id_str}`,
    text: cleanedText,
    lang: payload.lang || 'en',
    createdAt: payload.created_at || null,
    author: {
      name: u.name || '',
      handle: u.screen_name || '',
      avatar: upscaleAvatar(u.profile_image_url_https),
      verified: !!u.is_blue_verified,
      verifiedType: u.verified_type || null,
    },
    metrics: {
      replies: payload.conversation_count || 0,
      reposts: 0,
      likes: payload.favorite_count || 0,
      bookmarks: 0,
      views: 0,
    },
    media,
    quote,
    poll: null,
    source: 'syndication',
  };
}

/* ------------------------------------------------------------------ */

async function fetchTweet(id) {
  const errors = [];

  // 1) rich mirrors
  for (const host of ['api.fxtwitter.com', 'api.vxtwitter.com']) {
    try {
      const data = await getJson(`https://${host}/i/status/${id}`);
      const tweet = normalizeFx(data);
      if (tweet && (tweet.text || (tweet.media && tweet.media.length) || tweet.quote)) return tweet;
      errors.push(`${host}: empty payload`);
    } catch (e) {
      errors.push(`${host}: ${e.message}`);
    }
  }

  // 2) first-party syndication
  try {
    const token = syndicationToken(id);
    const data = await getJson(
      `https://cdn.syndication.twimg.com/tweet-result?id=${id}&lang=en&token=${token}`
    );
    const tweet = normalizeSyndication(data);
    if (tweet) return tweet;
    errors.push('syndication: empty payload');
  } catch (e) {
    errors.push(`syndication: ${e.message}`);
  }

  const err = new Error('Tweet could not be loaded');
  err.details = errors;
  throw err;
}

module.exports = { parseTweetInput, fetchTweet, syndicationToken };
