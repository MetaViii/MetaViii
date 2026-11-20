#!/usr/bin/env python3
"""Generate light/dark Now Playing SVGs from Spotify (or Last.fm) in multiple curated styles.

Supported styles (--style or env SPOTIFY_CARD_STYLE):
  - vinyl     : Minimalist album sleeve + peeking rotating vinyl disc (default)
  - glass     : Ambient blurred album-art backdrop + translucent Hi-Fi card
  - cassette  : Japanese retro cassette tape index + dual rotating reels (matches cel divider)
  - tui       : Minimalist terminal player (ncspot / spotify-tui aesthetic)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
LIGHT_OUT = ASSETS / "now-playing.svg"
DARK_OUT = ASSETS / "now-playing-dark.svg"
VALID_STYLES = ("vinyl", "glass", "cassette", "tui")

SPOTIFY_PATH = (
    "M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0z"
    "m5.503 17.308a.748.748 0 0 1-1.03.249c-2.82-1.723-6.37-2.113-10.551-1.158"
    "a.749.749 0 0 1-.334-1.461c4.576-1.046 8.5-.596 11.666 1.34a.75.75 0 0 1 .249 1.03z"
    "m1.468-3.266a.937.937 0 0 1-1.288.308c-3.227-1.984-8.148-2.559-11.965-1.4"
    "a.938.938 0 0 1-.545-1.795c4.361-1.324 9.781-.683 13.49 1.599a.937.937 0 0 1 .308 1.288z"
    "m.126-3.401C15.228 8.344 8.843 8.133 5.15 9.254a1.124 1.124 0 1 1-.653-2.152"
    "c4.24-1.287 11.292-1.038 15.744 1.605a1.124 1.124 0 0 1-1.144 1.934z"
)


def http_json(url: str, *, headers: dict[str, str] | None = None, data: bytes | None = None) -> tuple[int, dict | None]:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            if resp.status == 204 or not raw:
                return resp.status, None
            return resp.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {body[:300]}") from e


def fetch_image_data_uri(url: str | None) -> str | None:
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MetaViii-Profile/1.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            if not raw or not ctype.startswith("image/"):
                return None
            b64 = base64.b64encode(raw).decode("ascii")
            return f"data:{ctype};base64,{b64}"
    except Exception:
        return None


def pick_spotify_cover(images: list[dict]) -> str | None:
    if not images:
        return None
    sorted_imgs = sorted(images, key=lambda i: i.get("width") or 9999)
    for img in sorted_imgs:
        w = img.get("width") or 0
        if 120 <= w <= 320 and img.get("url"):
            return img["url"]
    return sorted_imgs[0].get("url")


def fetch_spotify(client_id: str, client_secret: str, refresh_token: str) -> dict:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    token_data = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    ).encode("utf-8")
    _, token_resp = http_json(
        "https://accounts.spotify.com/api/token",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=token_data,
    )
    access_token = (token_resp or {}).get("access_token")
    if not access_token:
        raise RuntimeError("Failed to obtain Spotify access_token")

    auth_headers = {"Authorization": f"Bearer {access_token}"}

    status, current = http_json(
        "https://api.spotify.com/v1/me/player/currently-playing",
        headers=auth_headers,
    )
    if status == 200 and current and current.get("item"):
        item = current["item"]
        album = item.get("album") or {}
        artists = ", ".join(a.get("name", "") for a in item.get("artists", []) if a.get("name"))
        return {
            "track": item.get("name") or "Unknown Track",
            "artist": artists or "Unknown Artist",
            "album": album.get("name") or "",
            "playing": bool(current.get("is_playing", False)),
            "progress_ms": int(current.get("progress_ms") or 0),
            "duration_ms": int(item.get("duration_ms") or 0),
            "cover_uri": fetch_image_data_uri(pick_spotify_cover(album.get("images") or [])),
            "source": "spotify",
        }

    _, recent = http_json(
        "https://api.spotify.com/v1/me/player/recently-played?limit=1",
        headers=auth_headers,
    )
    items = (recent or {}).get("items") or []
    if items and items[0].get("track"):
        item = items[0]["track"]
        album = item.get("album") or {}
        artists = ", ".join(a.get("name", "") for a in item.get("artists", []) if a.get("name"))
        return {
            "track": item.get("name") or "Unknown Track",
            "artist": artists or "Unknown Artist",
            "album": album.get("name") or "",
            "playing": False,
            "progress_ms": 0,
            "duration_ms": int(item.get("duration_ms") or 0),
            "cover_uri": fetch_image_data_uri(pick_spotify_cover(album.get("images") or [])),
            "source": "spotify",
        }

    return {
        "track": "Something In The Way",
        "artist": "Nirvana",
        "album": "Nevermind",
        "playing": False,
        "progress_ms": 0,
        "duration_ms": 232000,
        "cover_uri": None,
        "source": "spotify",
    }


def fetch_lastfm(api_key: str, username: str) -> dict:
    params = urllib.parse.urlencode(
        {
            "method": "user.getrecenttracks",
            "user": username,
            "api_key": api_key,
            "format": "json",
            "limit": "1",
        }
    )
    _, resp = http_json(f"https://ws.audioscrobbler.com/2.0/?{params}")
    tracks = ((resp or {}).get("recenttracks") or {}).get("track") or []
    if isinstance(tracks, dict):
        tracks = [tracks]
    if tracks:
        t = tracks[0]
        playing = (t.get("@attr") or {}).get("nowplaying") == "true"
        artist = (t.get("artist") or {}).get("#text") or "Unknown Artist"
        album = (t.get("album") or {}).get("#text") or ""
        imgs = t.get("image") or []
        cover_url = None
        for pref in ("large", "medium", "small"):
            for im in imgs:
                if im.get("size") == pref and im.get("#text"):
                    cover_url = im["#text"]
                    break
            if cover_url:
                break
        return {
            "track": t.get("name") or "Unknown Track",
            "artist": artist,
            "album": album,
            "playing": playing,
            "progress_ms": 0,
            "duration_ms": 0,
            "cover_uri": fetch_image_data_uri(cover_url),
            "source": "last.fm",
        }
    return {
        "track": "Something In The Way",
        "artist": "Nirvana",
        "album": "Nevermind",
        "playing": False,
        "progress_ms": 0,
        "duration_ms": 232000,
        "cover_uri": None,
        "source": "last.fm",
    }


def truncate(text: str, max_units: int) -> str:
    units = 0
    out: list[str] = []
    for ch in text.strip():
        w = 2 if ord(ch) > 0x2E80 else 1
        if units + w > max_units:
            return "".join(out).rstrip() + "…"
        out.append(ch)
        units += w
    return "".join(out)


def fmt_ms(ms: int) -> str:
    secs = max(0, ms // 1000)
    return f"{secs // 60:02d}:{secs % 60:02d}"


def progress_ratio_and_label(playing: bool, progress_ms: int, duration_ms: int, source: str) -> tuple[float, str]:
    if duration_ms > 0 and progress_ms > 0:
        return min(1.0, max(0.05, progress_ms / duration_ms)), f"{fmt_ms(progress_ms)} / {fmt_ms(duration_ms)}"
    if duration_ms > 0:
        return (0.38 if playing else 1.0), fmt_ms(duration_ms)
    return (0.45 if playing else 0.0), source.upper()


def make_demo_art_data_uri() -> str:
    """Crisp standalone minimalist abstract album cover SVG data URI for demo previews."""
    art_svg = """<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#172a3a"/>
      <stop offset="52%" stop-color="#2c5364"/>
      <stop offset="100%" stop-color="#d4a373"/>
    </linearGradient>
    <radialGradient id="s" cx="72%" cy="32%" r="48%">
      <stop offset="0%" stop-color="#f6e7cb" stop-opacity="0.72"/>
      <stop offset="100%" stop-color="#172a3a" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="128" height="128" fill="url(#g)"/>
  <rect width="128" height="128" fill="url(#s)"/>
  <circle cx="64" cy="64" r="34" fill="none" stroke="#ffffff" stroke-opacity="0.35" stroke-width="1.5"/>
  <circle cx="64" cy="64" r="18" fill="none" stroke="#ffffff" stroke-opacity="0.22" stroke-width="1"/>
  <path d="M16 96 Q48 76 80 94 T128 86 L128 128 L0 128 Z" fill="#0d1b2a" fill-opacity="0.45"/>
</svg>"""
    return "data:image/svg+xml;base64," + base64.b64encode(art_svg.encode("utf-8")).decode("ascii")


def render_vinyl(info: dict, *, dark: bool) -> str:
    """Style A: Minimalist album sleeve + peeking rotating vinyl disc."""
    bg = "#161b22" if dark else "#ffffff"
    border = "#30363d" if dark else "#d0d7de"
    fg_main = "#e6edf3" if dark else "#1f2328"
    fg_muted = "#8b949e" if dark else "#656d76"
    fg_subtle = "#6e7681" if dark else "#8c959f"
    track_bg = "#21262d" if dark else "#eaeef2"
    track_fill = "#e6edf3" if dark else "#1f2328"
    sleeve_bg = "#21262d" if dark else "#f3f5f7"
    sleeve_stroke = "rgba(255,255,255,0.14)" if dark else "rgba(31,35,40,0.12)"
    vinyl_outer = "#0a0d12" if dark else "#1b1f24"
    vinyl_groove = "#30363d" if dark else "#3d444d"
    vinyl_shine = "rgba(255,255,255,0.18)" if dark else "rgba(255,255,255,0.22)"
    vinyl_label = "#d2b48c"
    playing = bool(info["playing"])
    spotify_color = "#1db954" if playing else fg_subtle
    wave_color = "#8b949e" if dark else "#57606a"
    wave_active = "#e6edf3" if dark else "#1f2328"

    safe_track = escape(truncate(info["track"], 44))
    subtitle = f"{info['artist']} · {info['album']}" if info.get("album") else info["artist"]
    safe_sub = escape(truncate(subtitle, 54))
    status_text = "NOW PLAYING" if playing else "LAST PLAYED"
    aria = escape(f"{status_text}: {info['track']} — {subtitle}")

    bar_w = 460
    ratio, time_label = progress_ratio_and_label(playing, info["progress_ms"], info["duration_ms"], info["source"])
    fill_w = round(bar_w * ratio, 1)

    if playing:
        anim_css = f"""
    .vinyl-spin {{ transform-origin: 62px 38px; animation: spin 9s linear infinite; }}
    @keyframes spin {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
    .wbar {{ transform-box: fill-box; transform-origin: center center; fill: {wave_active}; }}
    .w1 {{ animation: wv1 1.10s ease-in-out infinite 0.00s; }}
    .w2 {{ animation: wv2 0.90s ease-in-out infinite 0.12s; }}
    .w3 {{ animation: wv3 1.25s ease-in-out infinite 0.24s; }}
    .w4 {{ animation: wv1 0.85s ease-in-out infinite 0.36s; }}
    .w5 {{ animation: wv2 1.15s ease-in-out infinite 0.18s; }}
    .w6 {{ animation: wv3 0.95s ease-in-out infinite 0.30s; }}
    .w7 {{ animation: wv1 1.05s ease-in-out infinite 0.42s; }}
    @keyframes wv1 {{ 0%, 100% {{ transform: scaleY(0.35); }} 50% {{ transform: scaleY(1.0); }} }}
    @keyframes wv2 {{ 0%, 100% {{ transform: scaleY(0.95); }} 50% {{ transform: scaleY(0.32); }} }}
    @keyframes wv3 {{ 0%, 100% {{ transform: scaleY(0.50); }} 50% {{ transform: scaleY(0.95); }} }}"""
    else:
        anim_css = f".wbar {{ fill: {wave_color}; opacity: 0.45; }}"

    cover_uri = info.get("cover_uri")
    if cover_uri:
        sleeve_inner = f'<image x="14" y="12" width="52" height="52" preserveAspectRatio="xMidYMid slice" href="{cover_uri}" clip-path="url(#sleeve-clip)" />'
    else:
        sleeve_inner = f"""<g clip-path="url(#sleeve-clip)">
    <rect x="14" y="12" width="52" height="52" fill="{sleeve_bg}" />
    <circle cx="40" cy="38" r="16" fill="none" stroke="{fg_muted}" stroke-width="1.2" opacity="0.45" />
    <circle cx="40" cy="38" r="9.5" fill="none" stroke="{fg_muted}" stroke-width="1" opacity="0.3" />
    <circle cx="40" cy="38" r="3" fill="{fg_main}" opacity="0.7" />
  </g>"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="830" height="76" viewBox="0 0 830 76" role="img" aria-label="{aria}">
  <title>{aria}</title>
  <defs>
    <clipPath id="sleeve-clip"><rect x="14" y="12" width="52" height="52" rx="5" /></clipPath>
    <filter id="sleeve-shadow" x="-15%" y="-15%" width="130%" height="135%">
      <feDropShadow dx="1" dy="2" stdDeviation="2.5" flood-color="#000000" flood-opacity="{0.35 if dark else 0.14}" />
    </filter>
  </defs>
  <style>
    .sans {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; }}
    .track {{ font-size: 14px; font-weight: 600; fill: {fg_main}; }}
    .sub {{ font-size: 12px; fill: {fg_muted}; }}
    .time {{ font-size: 10.5px; fill: {fg_subtle}; }}
    .status {{ font-size: 10px; font-weight: 600; letter-spacing: 0.7px; fill: {fg_subtle}; }}
    {anim_css}
  </style>
  <rect x="0.5" y="0.5" width="829" height="75" rx="8" fill="{bg}" stroke="{border}" />
  <g class="vinyl-spin">
    <circle cx="62" cy="38" r="23" fill="{vinyl_outer}" stroke="{vinyl_groove}" stroke-width="0.9" />
    <circle cx="62" cy="38" r="19" fill="none" stroke="{vinyl_groove}" stroke-width="0.7" opacity="0.65" />
    <circle cx="62" cy="38" r="15" fill="none" stroke="{vinyl_groove}" stroke-width="0.7" opacity="0.5" />
    <circle cx="62" cy="38" r="11" fill="none" stroke="{vinyl_groove}" stroke-width="0.7" opacity="0.4" />
    <path d="M 62 17 A 21 21 0 0 1 80 28" fill="none" stroke="{vinyl_shine}" stroke-width="1.6" stroke-linecap="round" />
    <circle cx="62" cy="38" r="7.5" fill="{vinyl_label}" />
    <circle cx="62" cy="38" r="2.1" fill="{vinyl_outer}" />
  </g>
  <g filter="url(#sleeve-shadow)">
    {sleeve_inner}
    <rect x="14.5" y="12.5" width="51" height="51" rx="4.5" fill="none" stroke="{sleeve_stroke}" />
  </g>
  <text x="102" y="29" class="sans track">{safe_track}</text>
  <text x="102" y="46.5" class="sans sub">{safe_sub}</text>
  <rect x="102" y="57.5" width="{bar_w}" height="3" rx="1.5" fill="{track_bg}" />
  <rect x="102" y="57.5" width="{fill_w}" height="3" rx="1.5" fill="{track_fill}" />
  <text x="572" y="62.5" class="mono time">{escape(time_label)}</text>
  <text x="791" y="25.5" text-anchor="end" class="mono status">{status_text}</text>
  <g transform="translate(799 15) scale(0.583)" fill="{spotify_color}"><path d="{SPOTIFY_PATH}" /></g>
  <g>
    <rect class="wbar w1" x="762" y="47" width="2.4" height="10" rx="1.2" />
    <rect class="wbar w2" x="769" y="43" width="2.4" height="18" rx="1.2" />
    <rect class="wbar w3" x="776" y="45" width="2.4" height="14" rx="1.2" />
    <rect class="wbar w4" x="783" y="41" width="2.4" height="22" rx="1.2" />
    <rect class="wbar w5" x="790" y="44" width="2.4" height="16" rx="1.2" />
    <rect class="wbar w6" x="797" y="46" width="2.4" height="12" rx="1.2" />
    <rect class="wbar w7" x="804" y="48.5" width="2.4" height="7" rx="1.2" />
  </g>
</svg>
"""


def render_glass(info: dict, *, dark: bool) -> str:
    """Style B: Ambient blurred album-art backdrop + translucent frosted glass card."""
    cover_uri = info.get("cover_uri") or make_demo_art_data_uri()
    playing = bool(info["playing"])

    # Frosted veil keeps text razor-sharp over ANY bright or dark album cover
    veil_a = "rgba(13,17,23,0.54)" if dark else "rgba(255,255,255,0.62)"
    veil_b = "rgba(13,17,23,0.80)" if dark else "rgba(248,250,252,0.84)"
    border = "rgba(255,255,255,0.14)" if dark else "rgba(31,35,40,0.12)"
    inner_sheen = "rgba(255,255,255,0.08)" if dark else "rgba(255,255,255,0.85)"
    fg_main = "#f0f6fc" if dark else "#161b22"
    fg_muted = "#b1bac4" if dark else "#4b5563"
    fg_subtle = "#8b949e" if dark else "#6e7781"
    pill_bg = "rgba(29,185,84,0.16)" if playing else ("rgba(255,255,255,0.08)" if dark else "rgba(31,35,40,0.06)")
    pill_fg = "#3fb950" if (playing and dark) else ("#168f40" if playing else fg_muted)
    track_bg = "rgba(255,255,255,0.15)" if dark else "rgba(31,35,40,0.11)"
    track_fill = "#f0f6fc" if dark else "#1f2328"

    safe_track = escape(truncate(info["track"], 42))
    subtitle = f"{info['artist']} · {info['album']}" if info.get("album") else info["artist"]
    safe_sub = escape(truncate(subtitle, 54))
    status_text = "PLAYING" if playing else "LAST PLAYED"
    aria = escape(f"{status_text}: {info['track']} — {subtitle}")

    bar_w = 500
    ratio, time_label = progress_ratio_and_label(playing, info["progress_ms"], info["duration_ms"], info["source"])
    fill_w = round(bar_w * ratio, 1)

    wave_css = """
    .wb { transform-box: fill-box; transform-origin: bottom center; }
    .wb1 { animation: g1 1.0s ease-in-out infinite; }
    .wb2 { animation: g2 0.8s ease-in-out infinite 0.15s; }
    .wb3 { animation: g3 1.15s ease-in-out infinite 0.30s; }
    .wb4 { animation: g2 0.9s ease-in-out infinite 0.45s; }
    @keyframes g1 { 0%,100% { transform: scaleY(0.3); } 50% { transform: scaleY(1); } }
    @keyframes g2 { 0%,100% { transform: scaleY(1); } 50% { transform: scaleY(0.28); } }
    @keyframes g3 { 0%,100% { transform: scaleY(0.45); } 50% { transform: scaleY(0.92); } }""" if playing else ""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="830" height="84" viewBox="0 0 830 84" role="img" aria-label="{aria}">
  <title>{aria}</title>
  <defs>
    <clipPath id="card-clip"><rect x="0.5" y="0.5" width="829" height="83" rx="10" /></clipPath>
    <clipPath id="art-clip"><rect x="14" y="12" width="60" height="60" rx="8" /></clipPath>
    <filter id="ambient-blur" x="-15%" y="-30%" width="130%" height="160%">
      <feGaussianBlur stdDeviation="26" edgeMode="duplicate" />
    </filter>
    <linearGradient id="glass-veil" x1="0" y1="0" x2="1" y2="0.4">
      <stop offset="0%" stop-color="{veil_a}" />
      <stop offset="100%" stop-color="{veil_b}" />
    </linearGradient>
    <filter id="art-shadow" x="-15%" y="-15%" width="130%" height="135%">
      <feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#000000" flood-opacity="{0.42 if dark else 0.18}" />
    </filter>
  </defs>
  <style>
    .sans {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; }}
    .track {{ font-size: 15px; font-weight: 600; fill: {fg_main}; }}
    .sub {{ font-size: 12.5px; fill: {fg_muted}; }}
    .time {{ font-size: 10.5px; fill: {fg_subtle}; }}
    .pill {{ font-size: 10px; font-weight: 600; letter-spacing: 0.6px; fill: {pill_fg}; }}
    {wave_css}
  </style>

  <!-- Ambient blurred album art background -->
  <g clip-path="url(#card-clip)">
    <image x="0" y="0" width="830" height="84" preserveAspectRatio="none" href="{cover_uri}" filter="url(#ambient-blur)" opacity="{0.82 if dark else 0.72}" />
    <rect width="830" height="84" fill="url(#glass-veil)" />
    <line x1="10" y1="1.5" x2="820" y2="1.5" stroke="{inner_sheen}" stroke-width="1" />
  </g>
  <rect x="0.5" y="0.5" width="829" height="83" rx="10" fill="none" stroke="{border}" />

  <!-- Crisp foreground album cover -->
  <g filter="url(#art-shadow)">
    <image x="14" y="12" width="60" height="60" preserveAspectRatio="xMidYMid slice" href="{cover_uri}" clip-path="url(#art-clip)" />
    <rect x="14.5" y="12.5" width="59" height="59" rx="7.5" fill="none" stroke="{border}" />
  </g>

  <!-- Track & artist -->
  <text x="90" y="32" class="sans track">{safe_track}</text>
  <text x="90" y="50" class="sans sub">{safe_sub}</text>

  <!-- Progress bar + timestamp -->
  <rect x="90" y="63" width="{bar_w}" height="3.5" rx="1.75" fill="{track_bg}" />
  <rect x="90" y="63" width="{fill_w}" height="3.5" rx="1.75" fill="{track_fill}" />
  <circle cx="{round(90 + fill_w, 1)}" cy="64.75" r="3" fill="{track_fill}" />
  <text x="602" y="68" class="mono time">{escape(time_label)}</text>

  <!-- Right frosted status pill + Spotify logo + live bars -->
  <rect x="706" y="15" width="108" height="22" rx="11" fill="{pill_bg}" />
  <g transform="translate(715 20) scale(0.5)" fill="{pill_fg}"><path d="{SPOTIFY_PATH}" /></g>
  <text x="733" y="29.5" class="mono pill">{status_text}</text>

  <g fill="{pill_fg}" opacity="{0.9 if playing else 0.4}">
    <rect class="wb wb1" x="782" y="52" width="3" height="14" rx="1.5" />
    <rect class="wb wb2" x="789" y="48" width="3" height="18" rx="1.5" />
    <rect class="wb wb3" x="796" y="50" width="3" height="16" rx="1.5" />
    <rect class="wb wb4" x="803" y="54" width="3" height="12" rx="1.5" />
  </g>
</svg>
"""


def render_cassette(info: dict, *, dark: bool) -> str:
    """Style C: Frosted-glass translucent retro cassette tape with album-adaptive ambient tint."""
    cover_uri = info.get("cover_uri") or make_demo_art_data_uri()
    veil_a = "rgba(13,17,23,0.62)" if dark else "rgba(255,255,255,0.68)"
    veil_b = "rgba(13,17,23,0.82)" if dark else "rgba(248,250,252,0.86)"
    strip_bg = "rgba(22,27,34,0.64)" if dark else "rgba(255,255,255,0.52)"
    window_bg = "rgba(13,17,23,0.44)" if dark else "rgba(255,255,255,0.56)"
    window_inner = "rgba(13,17,23,0.65)" if dark else "rgba(255,255,255,0.78)"
    border = "rgba(255,255,255,0.16)" if dark else "rgba(31,35,40,0.18)"
    inner_sheen = "rgba(255,255,255,0.09)" if dark else "rgba(255,255,255,0.85)"
    hairline = "rgba(255,255,255,0.12)" if dark else "rgba(31,35,40,0.12)"
    fg_main = "#f0f6fc" if dark else "#161b22"
    fg_muted = "#b1bac4" if dark else "#4b5563"
    fg_subtle = "#8b949e" if dark else "#656d76"
    accent = "#e3b341" if dark else "#d97706"  # warm vintage TDK amber stripe
    playing = bool(info["playing"])
    spotify_color = "#1db954" if playing else fg_subtle

    safe_track = escape(truncate(info["track"], 38))
    subtitle = f"{info['artist']} // {info['album']}" if info.get("album") else info["artist"]
    safe_sub = escape(truncate(subtitle, 46))
    status_text = "REC · PLAY" if playing else "STANDBY"
    _, time_label = progress_ratio_and_label(playing, info["progress_ms"], info["duration_ms"], info["source"])
    aria = escape(f"{status_text}: {info['track']} — {subtitle}")

    reel_css = """
    .reel-l { transform-origin: 696px 53px; animation: rspin 5.5s linear infinite; }
    .reel-r { transform-origin: 766px 53px; animation: rspin 5.5s linear infinite; }
    @keyframes rspin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }""" if playing else ""

    def reel_spokes(cx: int, cy: int) -> str:
        return f"""<circle cx="{cx}" cy="{cy}" r="14" fill="none" stroke="{fg_muted}" stroke-width="1.1" />
    <circle cx="{cx}" cy="{cy}" r="6.5" fill="none" stroke="{fg_main}" stroke-width="1.2" />
    <line x1="{cx}" y1="{cy - 12}" x2="{cx}" y2="{cy - 6.5}" stroke="{fg_main}" stroke-width="1.4" />
    <line x1="{cx}" y1="{cy + 6.5}" x2="{cx}" y2="{cy + 12}" stroke="{fg_main}" stroke-width="1.4" />
    <line x1="{cx - 10.4}" y1="{cy - 6}" x2="{cx - 5.6}" y2="{cy - 3.2}" stroke="{fg_main}" stroke-width="1.4" />
    <line x1="{cx + 5.6}" y1="{cy + 3.2}" x2="{cx + 10.4}" y2="{cy + 6}" stroke="{fg_main}" stroke-width="1.4" />
    <line x1="{cx + 10.4}" y1="{cy - 6}" x2="{cx + 5.6}" y2="{cy - 3.2}" stroke="{fg_main}" stroke-width="1.4" />
    <line x1="{cx - 5.6}" y1="{cy + 3.2}" x2="{cx - 10.4}" y2="{cy + 6}" stroke="{fg_main}" stroke-width="1.4" />"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="830" height="84" viewBox="0 0 830 84" role="img" aria-label="{aria}">
  <title>{aria}</title>
  <defs>
    <clipPath id="cassette-clip"><rect x="0.5" y="0.5" width="829" height="83" rx="8" /></clipPath>
    <clipPath id="tape-thumb"><rect x="14" y="31" width="44" height="44" rx="4" /></clipPath>
    <filter id="cassette-blur" x="-15%" y="-30%" width="130%" height="160%">
      <feGaussianBlur stdDeviation="26" edgeMode="duplicate" />
    </filter>
    <linearGradient id="cassette-veil" x1="0" y1="0" x2="1" y2="0.4">
      <stop offset="0%" stop-color="{veil_a}" />
      <stop offset="100%" stop-color="{veil_b}" />
    </linearGradient>
    <filter id="tape-shadow" x="-15%" y="-15%" width="130%" height="135%">
      <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#000000" flood-opacity="{0.36 if dark else 0.14}" />
    </filter>
  </defs>
  <style>
    .mono {{ font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; }}
    .sans {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif; }}
    .hdr {{ font-size: 9.5px; font-weight: 600; letter-spacing: 1px; fill: {fg_subtle}; }}
    .track {{ font-size: 14px; font-weight: 600; fill: {fg_main}; }}
    .sub {{ font-size: 11.5px; fill: {fg_muted}; }}
    {reel_css}
  </style>

  <!-- Frosted album-adaptive ambient glass backdrop -->
  <g clip-path="url(#cassette-clip)">
    <image x="0" y="0" width="830" height="84" preserveAspectRatio="none" href="{cover_uri}" filter="url(#cassette-blur)" opacity="{0.82 if dark else 0.72}" />
    <rect width="830" height="84" fill="url(#cassette-veil)" />
    <!-- Frosted top index header bar -->
    <rect x="0" y="0" width="830" height="23" fill="{strip_bg}" />
    <line x1="8" y1="1.5" x2="822" y2="1.5" stroke="{inner_sheen}" stroke-width="1" />
    <line x1="1" y1="23" x2="829" y2="23" stroke="{hairline}" stroke-width="1" />
  </g>
  <!-- Crisp outer glass shell border -->
  <rect x="0.5" y="0.5" width="829" height="83" rx="8" fill="none" stroke="{border}" stroke-width="1" />

  <!-- Top index metadata -->
  <rect x="14" y="9.5" width="20" height="4" rx="1" fill="{accent}" />
  <text x="42" y="15" class="mono hdr">TYPE II · CHROME · {status_text}</text>
  <text x="790" y="15" text-anchor="end" class="mono hdr">[{escape(time_label)}]</text>
  <g transform="translate(800 6) scale(0.46)" fill="{spotify_color}"><path d="{SPOTIFY_PATH}" /></g>

  <!-- Left crisp album cover thumbnail -->
  <g filter="url(#tape-shadow)">
    <image x="14" y="31" width="44" height="44" preserveAspectRatio="xMidYMid slice" href="{cover_uri}" clip-path="url(#tape-thumb)" />
    <rect x="14.5" y="31.5" width="43" height="43" rx="3.5" fill="none" stroke="{border}" />
  </g>

  <!-- Track typography with ruled notebook guide line -->
  <text x="72" y="49" class="sans track">{safe_track}</text>
  <line x1="72" y1="54.5" x2="626" y2="54.5" stroke="{hairline}" stroke-width="1" stroke-dasharray="2 3" />
  <text x="72" y="70" class="mono sub">{safe_sub}</text>

  <!-- Right frosted cassette dual-reel window -->
  <rect x="652" y="32" width="160" height="42" rx="21" fill="{window_bg}" stroke="{hairline}" stroke-width="1" />
  <rect x="713" y="43" width="36" height="20" rx="2" fill="{window_inner}" stroke="{hairline}" stroke-width="0.9" />
  <line x1="719" y1="53" x2="743" y2="53" stroke="{fg_subtle}" stroke-width="1" stroke-dasharray="3 2" />
  <g class="reel-l">{reel_spokes(696, 53)}</g>
  <g class="reel-r">{reel_spokes(766, 53)}</g>
</svg>
"""


def render_tui(info: dict, *, dark: bool) -> str:
    """Style D: Minimalist terminal music player (ncspot / spotify-tui aesthetic)."""
    bg = "#161b22" if dark else "#f6f8fa"
    border = "#30363d" if dark else "#d0d7de"
    fg_main = "#e6edf3" if dark else "#1f2328"
    fg_muted = "#8b949e" if dark else "#656d76"
    fg_subtle = "#6e7681" if dark else "#8c959f"
    playing = bool(info["playing"])
    accent = "#3fb950" if (playing and dark) else ("#1a7f37" if playing else fg_muted)

    safe_track = escape(truncate(info["track"], 46))
    subtitle = f"{info['artist']} — {info['album']}" if info.get("album") else info["artist"]
    safe_sub = escape(truncate(subtitle, 56))
    ratio, time_label = progress_ratio_and_label(playing, info["progress_ms"], info["duration_ms"], info["source"])
    status_badge = "[▶ PLAYING]" if playing else "[■ LAST]"
    aria = escape(f"{status_badge} {info['track']} — {subtitle}")

    # Monospace block progress bar (38 chars wide)
    total_chars = 38
    filled = max(1 if playing else 0, min(total_chars, round(total_chars * ratio)))
    bar_done = "━" * filled
    bar_rest = "─" * (total_chars - filled)

    cover_uri = info.get("cover_uri")
    if cover_uri:
        left_art = f"""<image x="14" y="14" width="44" height="44" preserveAspectRatio="xMidYMid slice" href="{cover_uri}" clip-path="url(#tui-clip)" />
  <rect x="14.5" y="14.5" width="43" height="43" rx="3.5" fill="none" stroke="{border}" />"""
        tx = 72
    else:
        left_art = f"""<rect x="14.5" y="14.5" width="43" height="43" rx="4" fill="none" stroke="{border}" stroke-dasharray="3 2" />
  <text x="36" y="42" text-anchor="middle" class="mono" font-size="18" fill="{fg_muted}">♪</text>"""
        tx = 72

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="830" height="72" viewBox="0 0 830 72" role="img" aria-label="{aria}">
  <title>{aria}</title>
  <defs>
    <clipPath id="tui-clip"><rect x="14" y="14" width="44" height="44" rx="4" /></clipPath>
  </defs>
  <style>
    .mono {{ font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace; }}
    .title {{ font-size: 13px; font-weight: 600; fill: {fg_main}; }}
    .sub {{ font-size: 11.5px; fill: {fg_muted}; }}
    .bar-done {{ font-size: 11.5px; fill: {fg_main}; }}
    .bar-rest {{ font-size: 11.5px; fill: {"#484f58" if dark else "#adb5bd"}; }}
    .meta {{ font-size: 11px; fill: {fg_subtle}; }}
    .st {{ font-size: 11px; font-weight: 600; fill: {accent}; }}
  </style>
  <rect x="0.5" y="0.5" width="829" height="71" rx="6" fill="{bg}" stroke="{border}" />
  {left_art}
  <text x="{tx}" y="27" class="mono title">{safe_track}</text>
  <text x="814" y="27" text-anchor="end" class="mono st">{status_badge}</text>
  <text x="{tx}" y="43.5" class="mono sub">{safe_sub}</text>
  <text x="814" y="43.5" text-anchor="end" class="mono meta">spotify-tui</text>
  <text x="{tx}" y="59" class="mono">
    <tspan class="bar-done">{bar_done}</tspan><tspan class="bar-rest">{bar_rest}</tspan>
    <tspan class="meta" dx="10">{escape(time_label)}</tspan>
  </text>
</svg>
"""


RENDERERS = {
    "vinyl": render_vinyl,
    "glass": render_glass,
    "cassette": render_cassette,
    "tui": render_tui,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Update Now Playing SVG banners.")
    parser.add_argument("--style", default=os.environ.get("SPOTIFY_CARD_STYLE", "cassette"), choices=VALID_STYLES)
    parser.add_argument("--demo", action="store_true", help="Render a demo track without calling any API.")
    parser.add_argument("--all-demos", action="store_true", help="Render all styles into .preview_orig/spotify_styles/ for comparison.")
    parser.add_argument("--track", default="Something In The Way", help="Demo track title.")
    parser.add_argument("--artist", default="Nirvana", help="Demo artist name.")
    parser.add_argument("--album", default="Nevermind", help="Demo album name.")
    parser.add_argument("--playing", action="store_true", help="Mark demo track as actively playing.")
    parser.add_argument("--source", default="spotify", help="Demo source label.")
    args = parser.parse_args()

    if args.demo or args.all_demos:
        info = {
            "track": args.track,
            "artist": args.artist,
            "album": args.album,
            "playing": args.playing,
            "progress_ms": 108000 if args.playing else 0,
            "duration_ms": 232000,
            "cover_uri": make_demo_art_data_uri(),
            "source": args.source,
        }
    else:
        cid = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
        csec = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
        rtok = os.environ.get("SPOTIFY_REFRESH_TOKEN", "").strip()
        lfm_key = os.environ.get("LASTFM_API_KEY", "").strip()
        lfm_user = os.environ.get("LASTFM_USERNAME", "").strip()

        if cid and csec and rtok:
            info = fetch_spotify(cid, csec, rtok)
        elif lfm_key and lfm_user:
            info = fetch_lastfm(lfm_key, lfm_user)
        else:
            print("No SPOTIFY_* or LASTFM_* credentials found in environment; skipping update.", file=sys.stderr)
            return 0

    if args.all_demos:
        out_dir = ROOT / ".preview_orig" / "spotify_styles"
        out_dir.mkdir(parents=True, exist_ok=True)
        for st, fn in RENDERERS.items():
            (out_dir / f"{st}.svg").write_text(fn(info, dark=False), encoding="utf-8")
            (out_dir / f"{st}-dark.svg").write_text(fn(info, dark=True), encoding="utf-8")
        print(f"Generated all {len(RENDERERS)} style previews in {out_dir}")
        return 0

    renderer = RENDERERS[args.style]
    ASSETS.mkdir(parents=True, exist_ok=True)
    LIGHT_OUT.write_text(renderer(info, dark=False), encoding="utf-8")
    DARK_OUT.write_text(renderer(info, dark=True), encoding="utf-8")
    print(f"Updated {LIGHT_OUT.name} & {DARK_OUT.name} [{args.style}]: {info['track']} — {info['artist']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
