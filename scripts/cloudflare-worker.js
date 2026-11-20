/**
 * Real-time Spotify Now Playing SVG — Frosted Translucent Cassette (Cloudflare Worker)
 *
 * Deploy in 2 minutes:
 *   1. Cloudflare Dashboard -> Workers & Pages -> Create Worker -> Paste this file -> Deploy.
 *   2. Worker -> Settings -> Variables and Secrets -> Add 3 Secrets:
 *        - SPOTIFY_CLIENT_ID
 *        - SPOTIFY_CLIENT_SECRET
 *        - SPOTIFY_REFRESH_TOKEN
 *   3. Use in GitHub README.md:
 *        <p align="center">
 *          <picture>
 *            <source media="(prefers-color-scheme: dark)" srcset="https://<your-worker>.workers.dev/?theme=dark">
 *            <img src="https://<your-worker>.workers.dev/?theme=light" width="100%" alt="Spotify Now Playing">
 *          </picture>
 *        </p>
 */

const SPOTIFY_PATH =
  "M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0z" +
  "m5.503 17.308a.748.748 0 0 1-1.03.249c-2.82-1.723-6.37-2.113-10.551-1.158" +
  "a.749.749 0 0 1-.334-1.461c4.576-1.046 8.5-.596 11.666 1.34a.75.75 0 0 1 .249 1.03z" +
  "m1.468-3.266a.937.937 0 0 1-1.288.308c-3.227-1.984-8.148-2.559-11.965-1.4" +
  "a.938.938 0 0 1-.545-1.795c4.361-1.324 9.781-.683 13.49 1.599a.937.937 0 0 1 .308 1.288z" +
  "m.126-3.401C15.228 8.344 8.843 8.133 5.15 9.254a1.124 1.124 0 1 1-.653-2.152" +
  "c4.24-1.287 11.292-1.038 15.744 1.605a1.124 1.124 0 0 1-1.144 1.934z";

let cachedToken = { token: null, expiresAt: 0 };

function escapeXml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function truncate(text, maxUnits) {
  let units = 0;
  let out = "";
  for (const ch of String(text ?? "").trim()) {
    const w = ch.codePointAt(0) > 0x2e80 ? 2 : 1;
    if (units + w > maxUnits) return out.trimEnd() + "…";
    out += ch;
    units += w;
  }
  return out;
}

function fmtMs(ms) {
  const secs = Math.max(0, Math.floor((ms || 0) / 1000));
  const m = String(Math.floor(secs / 60)).padStart(2, "0");
  const s = String(secs % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

async function getAccessToken(env) {
  const now = Date.now();
  if (cachedToken.token && now < cachedToken.expiresAt) {
    return cachedToken.token;
  }
  const basic = btoa(`${env.SPOTIFY_CLIENT_ID}:${env.SPOTIFY_CLIENT_SECRET}`);
  const resp = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: {
      Authorization: `Basic ${basic}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: env.SPOTIFY_REFRESH_TOKEN,
    }),
  });
  if (!resp.ok) throw new Error(`Spotify token error: ${resp.status}`);
  const data = await resp.json();
  cachedToken = {
    token: data.access_token,
    expiresAt: now + Math.max(60, (data.expires_in || 3600) - 120) * 1000,
  };
  return data.access_token;
}

function pickCover(images) {
  if (!Array.isArray(images) || images.length === 0) return null;
  const sorted = [...images].sort((a, b) => (a.width || 9999) - (b.width || 9999));
  for (const img of sorted) {
    if (img.width >= 120 && img.width <= 320 && img.url) return img.url;
  }
  return sorted[0]?.url || null;
}

async function fetchCoverDataUri(url) {
  if (!url) return null;
  try {
    const resp = await fetch(url);
    if (!resp.ok) return null;
    const ctype = (resp.headers.get("content-type") || "image/jpeg").split(";")[0].trim();
    const b64 = arrayBufferToBase64(await resp.arrayBuffer());
    return `data:${ctype};base64,${b64}`;
  } catch {
    return null;
  }
}

async function fetchSpotifyTrack(env) {
  const token = await getAccessToken(env);
  const headers = { Authorization: `Bearer ${token}` };

  // 1. Currently playing
  const curResp = await fetch("https://api.spotify.com/v1/me/player/currently-playing", { headers });
  if (curResp.status === 200) {
    const cur = await curResp.json();
    if (cur?.item) {
      const item = cur.item;
      const album = item.album || {};
      const artist = (item.artists || []).map((a) => a.name).filter(Boolean).join(", ");
      return {
        track: item.name || "Unknown Track",
        artist: artist || "Unknown Artist",
        album: album.name || "",
        playing: Boolean(cur.is_playing),
        progressMs: Number(cur.progress_ms || 0),
        durationMs: Number(item.duration_ms || 0),
        coverUri: await fetchCoverDataUri(pickCover(album.images)),
      };
    }
  }

  // 2. Recently played fallback
  const recResp = await fetch("https://api.spotify.com/v1/me/player/recently-played?limit=1", { headers });
  if (recResp.ok) {
    const rec = await recResp.json();
    const item = rec?.items?.[0]?.track;
    if (item) {
      const album = item.album || {};
      const artist = (item.artists || []).map((a) => a.name).filter(Boolean).join(", ");
      return {
        track: item.name || "Unknown Track",
        artist: artist || "Unknown Artist",
        album: album.name || "",
        playing: false,
        progressMs: 0,
        durationMs: Number(item.duration_ms || 0),
        coverUri: await fetchCoverDataUri(pickCover(album.images)),
      };
    }
  }

  return {
    track: "Something In The Way",
    artist: "Nirvana",
    album: "Nevermind",
    playing: false,
    progressMs: 0,
    durationMs: 232000,
    coverUri: null,
  };
}

function fallbackArtUri() {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">` +
    `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">` +
    `<stop offset="0%" stop-color="#172a3a"/><stop offset="55%" stop-color="#2c5364"/><stop offset="100%" stop-color="#d4a373"/>` +
    `</linearGradient></defs><rect width="128" height="128" fill="url(#g)"/></svg>`;
  return `data:image/svg+xml;base64,${btoa(svg)}`;
}

function renderFrostedCassette(info, dark) {
  const coverUri = info.coverUri || fallbackArtUri();
  // Lighter veil + boosted color saturation so album hues genuinely glow through the frosted shell
  const veilA = dark ? "rgba(13,17,23,0.44)" : "rgba(255,255,255,0.42)";
  const veilB = dark ? "rgba(13,17,23,0.66)" : "rgba(244,247,250,0.62)";
  const stripBg = dark ? "rgba(13,17,23,0.48)" : "rgba(255,255,255,0.46)";
  const windowBg = dark ? "rgba(13,17,23,0.38)" : "rgba(255,255,255,0.48)";
  const windowInner = dark ? "rgba(13,17,23,0.58)" : "rgba(255,255,255,0.72)";
  const border = dark ? "rgba(255,255,255,0.22)" : "rgba(31,35,40,0.16)";
  const innerRim = dark ? "rgba(255,255,255,0.18)" : "rgba(255,255,255,0.92)";
  const hairline = dark ? "rgba(255,255,255,0.15)" : "rgba(31,35,40,0.14)";
  const fgMain = dark ? "#f8fafc" : "#111827";
  const fgMuted = dark ? "#cbd5e1" : "#374151";
  const fgSubtle = dark ? "#94a3b8" : "#4b5563";
  const accent = dark ? "#e3b341" : "#d97706";
  const spotifyColor = info.playing ? "#1db954" : fgSubtle;

  const safeTrack = escapeXml(truncate(info.track, 38));
  const subtitle = info.album ? `${info.artist} // ${info.album}` : info.artist;
  const safeSub = escapeXml(truncate(subtitle, 46));
  const statusText = info.playing ? "REC · PLAY" : "STANDBY";

  let timeLabel = "SPOTIFY";
  if (info.durationMs > 0 && info.progressMs > 0) {
    timeLabel = `${fmtMs(info.progressMs)} / ${fmtMs(info.durationMs)}`;
  } else if (info.durationMs > 0) {
    timeLabel = fmtMs(info.durationMs);
  }
  const aria = escapeXml(`${statusText}: ${info.track} — ${subtitle}`);

  const reelCss = info.playing
    ? `.reel-l { transform-origin: 696px 53px; animation: rspin 5.5s linear infinite; }
       .reel-r { transform-origin: 766px 53px; animation: rspin 5.5s linear infinite; }
       @keyframes rspin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`
    : "";

  const reelSpokes = (cx, cy) =>
    `<circle cx="${cx}" cy="${cy}" r="14" fill="none" stroke="${fgMuted}" stroke-width="1.15" />` +
    `<circle cx="${cx}" cy="${cy}" r="6.5" fill="none" stroke="${fgMain}" stroke-width="1.25" />` +
    `<line x1="${cx}" y1="${cy - 12}" x2="${cx}" y2="${cy - 6.5}" stroke="${fgMain}" stroke-width="1.4" />` +
    `<line x1="${cx}" y1="${cy + 6.5}" x2="${cx}" y2="${cy + 12}" stroke="${fgMain}" stroke-width="1.4" />` +
    `<line x1="${cx - 10.4}" y1="${cy - 6}" x2="${cx - 5.6}" y2="${cy - 3.2}" stroke="${fgMain}" stroke-width="1.4" />` +
    `<line x1="${cx + 5.6}" y1="${cy + 3.2}" x2="${cx + 10.4}" y2="${cy + 6}" stroke="${fgMain}" stroke-width="1.4" />` +
    `<line x1="${cx + 10.4}" y1="${cy - 6}" x2="${cx + 5.6}" y2="${cy - 3.2}" stroke="${fgMain}" stroke-width="1.4" />` +
    `<line x1="${cx - 5.6}" y1="${cy + 3.2}" x2="${cx - 10.4}" y2="${cy + 6}" stroke="${fgMain}" stroke-width="1.4" />`;

  return `<svg xmlns="http://www.w3.org/2000/svg" width="830" height="84" viewBox="0 0 830 84" role="img" aria-label="${aria}">
  <title>${aria}</title>
  <defs>
    <clipPath id="cassette-clip"><rect x="0.5" y="0.5" width="829" height="83" rx="8" /></clipPath>
    <clipPath id="tape-thumb"><rect x="14" y="31" width="44" height="44" rx="4" /></clipPath>
    <filter id="cassette-blur" x="-15%" y="-30%" width="130%" height="160%">
      <feColorMatrix type="saturate" values="1.75" result="vivid" />
      <feGaussianBlur in="vivid" stdDeviation="18" edgeMode="duplicate" />
    </filter>
    <filter id="frost-grain" x="0%" y="0%" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.82" numOctaves="2" stitchTiles="stitch" />
      <feColorMatrix type="saturate" values="0" />
    </filter>
    <linearGradient id="cassette-veil" x1="0" y1="0" x2="1" y2="0.45">
      <stop offset="0%" stop-color="${veilA}" />
      <stop offset="100%" stop-color="${veilB}" />
    </linearGradient>
    <linearGradient id="glass-sheen" x1="0" y1="0" x2="0.85" y2="1">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="${dark ? 0.14 : 0.62}" />
      <stop offset="32%" stop-color="#ffffff" stop-opacity="${dark ? 0.03 : 0.14}" />
      <stop offset="56%" stop-color="#ffffff" stop-opacity="0" />
      <stop offset="100%" stop-color="#ffffff" stop-opacity="${dark ? 0.08 : 0.34}" />
    </linearGradient>
    <filter id="tape-shadow" x="-15%" y="-15%" width="130%" height="135%">
      <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#000000" flood-opacity="${dark ? 0.42 : 0.18}" />
    </filter>
  </defs>
  <style>
    .mono { font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; }
    .sans { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif; }
    .hdr { font-size: 9.5px; font-weight: 600; letter-spacing: 1px; fill: ${fgSubtle}; }
    .track { font-size: 14px; font-weight: 600; fill: ${fgMain}; }
    .sub { font-size: 11.5px; fill: ${fgMuted}; }
    ${reelCss}
  </style>

  <!-- Frosted acrylic shell backdrop: vivid blurred cover + frosted veil + diagonal glass sheen + micro-grain -->
  <g clip-path="url(#cassette-clip)">
    <image x="0" y="0" width="830" height="84" preserveAspectRatio="none" href="${coverUri}" filter="url(#cassette-blur)" opacity="${dark ? 0.92 : 0.88}" />
    <rect width="830" height="84" fill="url(#cassette-veil)" />
    <rect width="830" height="84" fill="url(#glass-sheen)" />
    <rect width="830" height="84" filter="url(#frost-grain)" opacity="${dark ? 0.055 : 0.045}" />
    <!-- Frosted top index strip -->
    <rect x="0" y="0" width="830" height="23" fill="${stripBg}" />
    <line x1="8" y1="1.5" x2="822" y2="1.5" stroke="${innerRim}" stroke-width="1" />
    <line x1="1" y1="23" x2="829" y2="23" stroke="${hairline}" stroke-width="1" />
  </g>
  <!-- Crisp glass outer edge + subtle inner rim -->
  <rect x="0.5" y="0.5" width="829" height="83" rx="8" fill="none" stroke="${border}" stroke-width="1" />
  <rect x="1.5" y="1.5" width="827" height="81" rx="7" fill="none" stroke="${innerRim}" stroke-opacity="${dark ? 0.25 : 0.55}" stroke-width="0.8" />

  <rect x="14" y="9.5" width="20" height="4" rx="1" fill="${accent}" />
  <text x="42" y="15" class="mono hdr">TYPE II · CHROME · ${statusText}</text>
  <text x="790" y="15" text-anchor="end" class="mono hdr">[${escapeXml(timeLabel)}]</text>
  <g transform="translate(800 6) scale(0.46)" fill="${spotifyColor}"><path d="${SPOTIFY_PATH}" /></g>

  <g filter="url(#tape-shadow)">
    <image x="14" y="31" width="44" height="44" preserveAspectRatio="xMidYMid slice" href="${coverUri}" clip-path="url(#tape-thumb)" />
    <rect x="14.5" y="31.5" width="43" height="43" rx="3.5" fill="none" stroke="${border}" />
  </g>

  <text x="72" y="49" class="sans track">${safeTrack}</text>
  <line x1="72" y1="54.5" x2="626" y2="54.5" stroke="${hairline}" stroke-width="1" stroke-dasharray="2 3" />
  <text x="72" y="70" class="mono sub">${safeSub}</text>

  <rect x="652" y="32" width="160" height="42" rx="21" fill="${windowBg}" stroke="${hairline}" stroke-width="1" />
  <rect x="713" y="43" width="36" height="20" rx="2" fill="${windowInner}" stroke="${hairline}" stroke-width="0.9" />
  <line x1="719" y1="53" x2="743" y2="53" stroke="${fgSubtle}" stroke-width="1" stroke-dasharray="3 2" />
  <g class="reel-l">${reelSpokes(696, 53)}</g>
  <g class="reel-r">${reelSpokes(766, 53)}</g>
</svg>`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const dark = url.searchParams.get("theme") === "dark";

    let info;
    try {
      info = await fetchSpotifyTrack(env);
    } catch {
      info = {
        track: "Something In The Way",
        artist: "Nirvana",
        album: "Nevermind",
        playing: false,
        progressMs: 0,
        durationMs: 232000,
        coverUri: null,
      };
    }

    const svg = renderFrostedCassette(info, dark);
    return new Response(svg, {
      headers: {
        "Content-Type": "image/svg+xml; charset=utf-8",
        "Cache-Control": "no-cache, no-store, max-age=0, must-revalidate",
        Pragma: "no-cache",
        Expires: "0",
      },
    });
  },
};
