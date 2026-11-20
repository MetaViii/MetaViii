#!/usr/bin/env python3
"""One-time local helper to obtain a Spotify refresh_token for GitHub Actions.

Usage:
  python scripts/get_spotify_token.py

Prerequisites in Spotify Developer Dashboard (https://developer.spotify.com/dashboard):
  1. Create an App (Web API).
  2. Add Redirect URI: http://127.0.0.1:8888/callback
  3. Copy Client ID and Client Secret when prompted below.
"""

from __future__ import annotations

import base64
import http.server
import json
import urllib.parse
import urllib.request
import webbrowser

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "user-read-currently-playing user-read-recently-played"


def main() -> None:
    client_id = input("Spotify Client ID: ").strip()
    client_secret = input("Spotify Client Secret: ").strip()
    if not client_id or not client_secret:
        raise SystemExit("Client ID and Client Secret are required.")

    auth_code: dict[str, str] = {}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            if "code" in qs:
                auth_code["code"] = qs["code"][0]
                body = b"<h2>Authorization received! You can close this tab and return to your terminal.</h2>"
                self.send_response(200)
            else:
                auth_code["error"] = qs.get("error", ["unknown"])[0]
                body = b"<h2>Authorization failed. Check your terminal.</h2>"
                self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            return

    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
        }
    )

    server = http.server.HTTPServer(("127.0.0.1", 8888), CallbackHandler)
    print(f"\nOpening browser for Spotify authorization...\nIf it does not open automatically, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    while "code" not in auth_code and "error" not in auth_code:
        server.handle_request()
    server.server_close()

    if "error" in auth_code:
        raise SystemExit(f"Spotify authorization error: {auth_code['error']}")

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    payload = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": auth_code["code"],
            "redirect_uri": REDIRECT_URI,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=payload,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        tokens = json.loads(resp.read().decode("utf-8"))

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise SystemExit(f"No refresh_token returned: {tokens}")

    print("\nSuccess! Add these three secrets in GitHub Repo -> Settings -> Secrets and variables -> Actions:\n")
    print(f"SPOTIFY_CLIENT_ID     = {client_id}")
    print(f"SPOTIFY_CLIENT_SECRET = {client_secret}")
    print(f"SPOTIFY_REFRESH_TOKEN = {refresh_token}\n")


if __name__ == "__main__":
    main()
