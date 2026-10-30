'use strict';

/**
 * HTML renderer for the tweet card.
 *
 * Geometry was measured from a 540x291 reference export
 * (Ekran görüntüsü_2026-10-27_03-23-12.png):
 *   canvas   : 540 wide, #FCFCFB, padding 12px 20px 14px
 *   card     : 500 wide, #FFFFFF, 32px padding, square-ish corners
 *   avatar   : 40px, 8px gap
 *   name     : ~21px bold / 24px line-height
 *   handle   : 15px / 24px, muted
 *   body     : 16px / 24px, 16px paragraph gap
 *   meta     : 15px muted, 20px margin-top
 *   footer   : 13.5px muted
 */

const TZ = process.env.SCREENSHOT_TZ || 'Europe/Istanbul';
const FOOTER_TEXT = process.env.SCREENSHOT_FOOTER || 'Made with TwitterShots.com';

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

const ICONS = {
  reply:
    'M1.751 10c0-4.42 3.584-8 8.005-8h4.366c4.49 0 8.129 3.64 8.129 8.13 0 2.96-1.607 5.68-4.196 7.11l-8.054 4.46v-3.69h-.067c-4.49.1-8.183-3.51-8.183-8.01zm8.005-6c-3.317 0-6.005 2.69-6.005 6 0 3.37 2.77 6.08 6.138 6.01l.351-.01h1.761v2.3l5.087-2.81c1.951-1.08 3.163-3.13 3.163-5.36 0-3.39-2.744-6.13-6.129-6.13H9.756z',
  repost:
    'M4.5 3.88l4.432 4.14-1.364 1.46L5.5 7.55V16c0 1.1.896 2 2 2H13v2H7.5c-2.209 0-4-1.79-4-4V7.55L1.432 9.48.068 8.02 4.5 3.88zM16.5 6H11V4h5.5c2.209 0 4 1.79 4 4v8.45l2.068-1.93 1.364 1.46-4.432 4.14-4.432-4.14 1.364-1.46 2.068 1.93V8c0-1.1-.896-2-2-2z',
  like:
    'M16.697 5.5c-1.222-.06-2.679.51-3.89 2.16l-.805 1.09-.806-1.09C9.984 6.01 8.526 5.44 7.304 5.5c-1.243.07-2.349.78-2.91 1.91-.552 1.12-.633 2.78.479 4.82 1.074 1.97 3.257 4.27 7.129 6.61 3.87-2.34 6.052-4.64 7.126-6.61 1.111-2.04 1.03-3.7.477-4.82-.561-1.13-1.666-1.84-2.908-1.91zm4.187 7.69c-1.351 2.48-4.001 5.12-8.379 7.67l-.503.3-.504-.3c-4.379-2.55-7.029-5.19-8.382-7.67-1.36-2.5-1.41-4.86-.514-6.67.887-1.79 2.647-2.91 4.601-3.01 1.651-.09 3.368.56 4.798 2.01 1.429-1.45 3.146-2.1 4.796-2.01 1.954.1 3.714 1.22 4.601 3.01.896 1.81.846 4.17-.514 6.67z',
  bookmark:
    'M4 4.5C4 3.12 5.119 2 6.5 2h11C18.881 2 20 3.12 20 4.5v18.44l-8-5.71-8 5.71V4.5zM6.5 4c-.276 0-.5.22-.5.5v14.56l6-4.29 6 4.29V4.5c0-.28-.224-.5-.5-.5h-11z',
};

const X_LOGO =
  'M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z';

const BADGE =
  'M22.25 12c0-1.43-.88-2.67-2.19-3.34.46-1.39.2-2.9-.81-3.91s-2.52-1.27-3.91-.81c-.66-1.31-1.91-2.19-3.34-2.19s-2.67.88-3.33 2.19c-1.4-.46-2.91-.2-3.92.81s-1.26 2.52-.8 3.91c-1.31.67-2.2 1.91-2.2 3.34s.89 2.67 2.2 3.34c-.46 1.39-.21 2.9.8 3.91s2.52 1.26 3.91.81c.67 1.31 1.91 2.19 3.34 2.19s2.68-.88 3.34-2.19c1.39.45 2.9.2 3.91-.81s1.27-2.52.81-3.91c1.31-.67 2.19-1.91 2.19-3.34zm-11.71 4.2L6.8 12.46l1.41-1.42 2.26 2.26 4.8-5.23 1.47 1.36-6.2 6.77z';

const escapeHtml = (s) =>
  String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

function formatCount(n) {
  n = Number(n) || 0;
  if (n < 1000) return String(n);
  if (n < 1e6) {
    const v = n / 1000;
    return (v < 10 ? v.toFixed(1).replace(/\.0$/, '') : Math.round(v)) + 'K';
  }
  const v = n / 1e6;
  return (v < 100 ? v.toFixed(1).replace(/\.0$/, '') : Math.round(v)) + 'M';
}

function displayUrl(url) {
  const clean = String(url).replace(/^https?:\/\//i, '').replace(/^www\./i, '').replace(/\/$/, '');
  return clean.length > 34 ? clean.slice(0, 33) + '…' : clean;
}

function renderText(text) {
  if (!text || !text.trim()) return '';
  const paragraphs = String(text)
    .replace(/\r\n?/g, '\n')
    .split(/\n{2,}/);
  return paragraphs
    .map((par) => {
      let html = escapeHtml(par)
        .replace(/(https?:\/\/[^\s<]+)/g, (m) => {
          const url = m.replace(/&amp;/g, '&');
          return `<span class="link">${escapeHtml(displayUrl(url))}</span>`;
        })
        .replace(/(^|[\s(])(@[A-Za-z0-9_]{1,15})/g, '$1<span class="link">$2</span>')
        .replace(/(^|[\s(])(#[\p{L}\p{N}_]+)/gu, '$1<span class="link">$2</span>')
        .replace(/\n/g, '<br>');
      return `<p>${html}</p>`;
    })
    .join('');
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: TZ,
  }).format(d);
}

function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: TZ,
  }).format(d);
}

function mediaBlock(media) {
  if (!media.length) return '';
  const items = media.slice(0, 4);
  const n = items.length;
  const cells = items
    .map((m, i) => {
      const cls = `mi m${i}`;
      const alt = escapeHtml(m.alt || '');
      const src = escapeHtml(m.thumb || m.url);
      const badge =
        m.type === 'video' || m.type === 'gif'
          ? `<span class="play"><svg viewBox="0 0 24 24" width="18" height="18" fill="#fff"><path d="M8 5.14v13.72L19 12 8 5.14z"/></svg></span>${
              m.type === 'video' && m.duration
                ? `<span class="dur">${formatDuration(m.duration)}</span>`
                : m.type === 'gif'
                ? '<span class="dur">GIF</span>'
                : ''
            }`
          : '';
      return `<div class="${cls}"><img src="${src}" alt="${alt}" referrerpolicy="no-referrer">${badge}</div>`;
    })
    .join('');
  return `<div class="media n${n}">${cells}</div>`;
}

function formatDuration(sec) {
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function quoteBlock(quote, opts) {
  if (!quote) return '';
  return `
  <div class="quote">
    <div class="quote-head">
      ${quote.author.avatar ? `<img class="quote-avatar" src="${escapeHtml(quote.author.avatar)}" alt="">` : ''}
      <span class="quote-name">${escapeHtml(quote.author.name)}</span>
      ${quote.author.verified ? `<svg class="badge small" viewBox="0 0 24 24" fill="#1d9bf0"><path d="${BADGE}"/></svg>` : ''}
      <span class="quote-handle">@${escapeHtml(quote.author.handle)}</span>
    </div>
    <div class="quote-text">${renderText(quote.text)}</div>
    ${
      opts.media && quote.media
        ? `<div class="quote-media"><img src="${escapeHtml(quote.media)}" alt="" referrerpolicy="no-referrer"></div>`
        : ''
    }
  </div>`;
}

function pollBlock(poll) {
  if (!poll || !poll.choices.length) return '';
  const rows = poll.choices
    .map((c) => {
      const pct = Math.max(0, Math.min(100, c.percent || 0));
      return `<div class="poll-row"><span class="poll-fill" style="width:${pct.toFixed(2)}%"></span>
        <span class="poll-label">${escapeHtml(c.label)}</span>
        <span class="poll-pct">${pct.toFixed(1).replace(/\.0$/, '')}%</span></div>`;
    })
    .join('');
  return `<div class="poll">${rows}<div class="poll-total">${formatCount(poll.total)} votes</div></div>`;
}

function metricsBlock(tweet) {
  const m = tweet.metrics;
  const item = (icon, value) =>
    `<span class="m"><svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="${icon}"/></svg>${formatCount(
      value
    )}</span>`;
  return `<div class="metrics">${item(ICONS.reply, m.replies)}${item(
    ICONS.repost,
    m.reposts
  )}${item(ICONS.like, m.likes)}${item(ICONS.bookmark, m.bookmarks)}</div>`;
}

function metaBlock(tweet, opts) {
  const parts = [];
  if (opts.time) {
    const t = formatTime(tweet.createdAt);
    if (t) parts.push(t);
  }
  if (opts.date) {
    const d = formatDate(tweet.createdAt);
    if (d) parts.push(d);
  }
  if (opts.views && tweet.metrics.views > 0) {
    parts.push(`${formatCount(tweet.metrics.views)} Views`);
  }
  if (!parts.length) return '';
  return `<div class="meta">${parts.map(escapeHtml).join(' · ')}</div>`;
}

const AVATAR_FALLBACK =
  "data:image/svg+xml;charset=utf-8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect width="80" height="80" fill="#cfd4d9"/></svg>'
  );

function renderCard(tweet, opts) {
  const hasProof = tweet.author.verified;
  const avatar = tweet.author.avatar || AVATAR_FALLBACK;
  const body = `
  <div class="card">
    <div class="head">
      <img class="avatar" src="${escapeHtml(avatar)}" alt="" referrerpolicy="no-referrer">
      <div class="who">
        <div class="name-row">
          <span class="name">${escapeHtml(tweet.author.name)}</span>
          ${
            hasProof
              ? `<svg class="badge" viewBox="0 0 24 24" fill="#1d9bf0" aria-label="Verified"><path d="${BADGE}"/></svg>
                 <span class="sr">Verified</span>`
              : ''
          }
        </div>
        <div class="handle">@${escapeHtml(tweet.author.handle)}</div>
      </div>
      <div class="brand"><svg viewBox="0 0 24 24" width="30" height="30" fill="currentColor"><path d="${X_LOGO}"/></svg></div>
    </div>

    ${tweet.text && tweet.text.trim() ? `<div class="text${tweet.text.length > 200 ? ' long' : ''}">${renderText(tweet.text)}</div>` : ''}
    ${quoteBlock(tweet.quote, opts)}
    ${opts.media ? mediaBlock(tweet.media || []) : ''}
    ${pollBlock(tweet.poll)}
    ${metaBlock(tweet, opts)}
    ${opts.metrics ? metricsBlock(tweet) : ''}
    ${opts.footer ? `<div class="footer">${escapeHtml(FOOTER_TEXT)}</div>` : ''}
  </div>`;

  return `<!doctype html>
<html lang="en" data-theme="${opts.theme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=540">
<title>tweet</title>
<link rel="preload" as="font" type="font/woff2" href="/fonts/chirp-regular-web.woff2" crossorigin>
<link rel="preload" as="font" type="font/woff2" href="/fonts/chirp-bold-web.woff2" crossorigin>
<style>${css(opts)}</style>
</head>
<body>
<div id="shot">${body}</div>
<script>
(function () {
  function done() {
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { document.documentElement.dataset.ready = '1'; });
    });
  }
  function imagesReady() {
    var imgs = Array.prototype.slice.call(document.images);
    return Promise.all(imgs.map(function (img) {
      if (img.complete) return img.decode ? img.decode().catch(function () {}) : Promise.resolve();
      return new Promise(function (resolve) { img.addEventListener('load', resolve, { once: true }); img.addEventListener('error', resolve, { once: true }); });
    }));
  }
  var fallback = setTimeout(done, 6000);
  Promise.all([imagesReady(), document.fonts ? document.fonts.ready : Promise.resolve()])
    .then(function () { clearTimeout(fallback); setTimeout(done, 40); })
    .catch(function () { clearTimeout(fallback); done(); });
})();
</script>
</body>
</html>`;
}

function css(opts) {
  const oled = opts.theme === 'oled';
  const dark = opts.theme === 'dark' || oled;
  const vars = oled
    ? `--bg:#000000; --card:#000000; --text:#f7f9f9; --muted:#71767b; --line:#2f3336; --shadow:none;`
    : dark
    ? `--bg:#0b0b0c; --card:#16181c; --text:#e7e9ea; --muted:#71767b; --line:#2f3336; --shadow:0 1px 2px rgba(0,0,0,.5), 0 10px 30px rgba(0,0,0,.35);`
    : `--bg:#fcfcfb; --card:#ffffff; --text:#0f1419; --muted:#536471; --line:#e7e9e8; --shadow:0 1px 2px rgba(0,0,0,.04), 0 8px 22px rgba(0,0,0,.05);`;

  return `
@font-face{font-family:'Chirp';src:url('/fonts/chirp-regular-web.woff2') format('woff2');font-weight:400;font-style:normal;font-display:block}
@font-face{font-family:'Chirp';src:url('/fonts/chirp-medium-web.woff2') format('woff2');font-weight:500;font-style:normal;font-display:block}
@font-face{font-family:'Chirp';src:url('/fonts/chirp-bold-web.woff2') format('woff2');font-weight:700;font-style:normal;font-display:block}
@font-face{font-family:'Chirp';src:url('/fonts/chirp-heavy-web.woff2') format('woff2');font-weight:800;font-style:normal;font-display:block}

:root{${vars}}
*{box-sizing:border-box;-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}
html,body{margin:0;padding:0;background:${oled ? '#000000' : dark ? '#0b0b0c' : '#fcfcfb'}}
body{font-family:'Chirp','TwitterChirp','Helvetica Neue',Helvetica,Arial,sans-serif;color:var(--text)}
#shot{width:540px;background:var(--bg);padding:${oled ? '8px 10px' : '12px 20px 14px'};}
.card{background:var(--card);padding:${oled ? '12px 10px' : '32px'};box-shadow:var(--shadow);border-radius:${oled ? '0px' : '2px'}}

.head{display:flex;align-items:center}
.avatar{width:48px;height:48px;border-radius:50%;object-fit:cover;margin-right:10px;background:var(--line);flex:none}
.who{flex:1;min-width:0}
.name-row{display:flex;align-items:flex-end;height:24px;gap:5px;overflow:hidden}
.name{font-size:18px;line-height:24px;font-weight:700;letter-spacing:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.badge{width:18px;height:18px;flex:none;margin-top:0}
.badge.small{width:16px;height:16px}
.handle{font-size:16px;line-height:22px;margin-top:1px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.brand{margin-left:12px;margin-top:2px;color:${dark ? '#e7e9ea' : '#0f1419'};flex:none;display:flex}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}

.text{margin-top:14px;font-size:24px;line-height:34px;letter-spacing:-0.3px;overflow-wrap:anywhere}
.text.long{font-size:19px;line-height:27px}
.text p{margin:0}
.text p+p{margin-top:16px}
.link{color:#1d9bf0}

.media{margin-top:14px;display:grid;gap:2px;border-radius:14px;overflow:hidden;border:1px solid var(--line);background:var(--line)}
.mi{position:relative;overflow:hidden;background:var(--line);min-height:80px}
.mi img{display:block;width:100%;height:100%;object-fit:cover}
.media.n1{display:block}
.media.n1 .mi{min-height:auto}
.media.n1 .mi img{width:100%;height:auto;max-height:480px;object-fit:cover;object-position:top}
.media.n2{grid-template-columns:1fr 1fr;height:220px}
.media.n3{grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;height:300px}
.media.n3 .m0{grid-row:span 2}
.media.n4{grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;height:300px}
.play{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:44px;height:44px;border-radius:50%;background:rgba(15,20,25,.72);display:flex;align-items:center;justify-content:center;backdrop-filter:blur(2px)}
.play svg{margin-left:2px}
.dur{position:absolute;left:8px;bottom:8px;background:rgba(15,20,25,.75);color:#fff;font-size:12px;font-weight:500;padding:2px 5px;border-radius:4px;line-height:14px}

.quote{margin-top:14px;border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.quote-head{display:flex;align-items:center;gap:5px;font-size:14px}
.quote-avatar{width:20px;height:20px;border-radius:50%;object-fit:cover;margin-right:2px}
.quote-name{font-weight:700}
.quote-handle{color:var(--muted)}
.quote-text{margin-top:6px;font-size:15px;line-height:21px}
.quote-text p{margin:0}
.quote-media{margin-top:8px;border-radius:10px;overflow:hidden}
.quote-media img{display:block;width:100%;max-height:200px;object-fit:cover}

.poll{margin-top:14px;display:flex;flex-direction:column;gap:8px}
.poll-row{position:relative;display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border-radius:8px;overflow:hidden;background:var(--bg);font-size:14px}
.poll-fill{position:absolute;left:0;top:0;bottom:0;background:${dark ? '#1d3a52' : '#dbeaf7'}}
.poll-label{position:relative;z-index:1;font-weight:500}
.poll-pct{position:relative;z-index:1;color:var(--muted);font-variant-numeric:tabular-nums}
.poll-total{font-size:13px;color:var(--muted)}

.meta{margin-top:20px;font-size:14.5px;line-height:20px;color:var(--muted)}
.metrics{margin-top:16px;display:flex;align-items:center;gap:26px;font-size:14px;color:var(--muted)}
.metrics .m{display:flex;align-items:center;gap:6px;font-variant-numeric:tabular-nums}
.metrics svg{opacity:.85}

.footer{margin-top:18px;font-size:13.8px;line-height:20px;color:var(--muted);letter-spacing:.1px}
`;
}

module.exports = { renderCard, DEFAULTS, formatCount, formatDate, formatTime };
