"""
Spotify MCP Extended Server
Adds: queue, recommendations, playlist CRUD, shuffle, repeat, recently played.
Reuses credentials from the existing @tbrgeek/spotify-mcp-server (~/.spotify-mcp/credentials.json).
"""

import json
import time
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

server = FastMCP("spotify-mcp-extended")

CREDENTIALS_PATH = Path.home() / ".spotify-mcp" / "credentials.json"
SPOTIFY_API = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# --- Token management (shares credentials with existing MCP server) ---

_credentials: dict[str, Any] = {}


def _load_credentials() -> dict[str, Any]:
    global _credentials
    data = json.loads(CREDENTIALS_PATH.read_text())
    _credentials = data
    return data


def _save_credentials() -> None:
    CREDENTIALS_PATH.write_text(json.dumps(_credentials, indent=2))


def _get_headers() -> dict[str, str]:
    creds = _load_credentials()
    # Refresh if expired
    if creds.get("expiresAt", 0) < time.time() * 1000:
        _refresh_token()
        creds = _credentials
    return {
        "Authorization": f"Bearer {creds['accessToken']}",
        "Content-Type": "application/json",
    }


def _refresh_token() -> None:
    creds = _load_credentials()
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": creds["refreshToken"],
            "client_id": creds["clientId"],
            "client_secret": creds["clientSecret"],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    _credentials["accessToken"] = data["access_token"]
    _credentials["expiresAt"] = int(time.time() * 1000) + data["expires_in"] * 1000
    if "refresh_token" in data:
        _credentials["refreshToken"] = data["refresh_token"]
    _save_credentials()


def _api(method: str, path: str, **kwargs: Any) -> httpx.Response:
    """Make a Spotify API request with auto-retry on 401."""
    headers = _get_headers()
    resp = httpx.request(method, f"{SPOTIFY_API}{path}", headers=headers, **kwargs)
    if resp.status_code == 401:
        _refresh_token()
        headers = _get_headers()
        resp = httpx.request(method, f"{SPOTIFY_API}{path}", headers=headers, **kwargs)
    return resp


# --- Tools ---


@server.tool()
def spotify_add_to_queue(uri: str, device_id: str | None = None) -> str:
    """Add a track or episode to the playback queue.

    Args:
        uri: Spotify URI (e.g. spotify:track:4iV5W9uYEdYUVa79Axb7Rh)
        device_id: Target device ID (optional)
    """
    params: dict[str, str] = {"uri": uri}
    if device_id:
        params["device_id"] = device_id
    resp = _api("POST", "/me/player/queue", params=params)
    if resp.status_code in (200, 204):
        return f"Added to queue: {uri}"
    return f"Error: {resp.status_code} — {resp.text}"


@server.tool()
def spotify_get_queue() -> str:
    """Get the current playback queue."""
    resp = _api("GET", "/me/player/queue")
    if resp.status_code != 200:
        return f"Error: {resp.status_code} — {resp.text}"
    data = resp.json()
    lines = []
    current = data.get("currently_playing")
    if current:
        artists = ", ".join(a["name"] for a in current.get("artists", []))
        lines.append(f"Now playing: **{current['name']}** by {artists}")
    queue = data.get("queue", [])
    if queue:
        lines.append(f"\nQueue ({len(queue)} tracks):")
        for i, track in enumerate(queue[:20], 1):
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            lines.append(f"{i}. **{track['name']}** by {artists}")
        if len(queue) > 20:
            lines.append(f"... and {len(queue) - 20} more")
    else:
        lines.append("Queue is empty.")
    return "\n".join(lines)


@server.tool()
def spotify_my_playlists(limit: int = 20) -> str:
    """Get the current user's playlists.

    Args:
        limit: Max playlists to return (1-50, default 20)
    """
    resp = _api("GET", "/me/playlists", params={"limit": min(max(limit, 1), 50)})
    if resp.status_code != 200:
        return f"Error: {resp.status_code} — {resp.text}"
    playlists = resp.json().get("items", [])
    lines = [f"Your playlists ({len(playlists)}):\n"]
    for i, p in enumerate(playlists, 1):
        track_count = p.get("tracks", {}).get("total", "?")
        lines.append(
            f"{i}. **{p['name']}** — {track_count} tracks\n"
            f"   ID: `{p['id']}` | URI: `{p['uri']}`"
        )
    return "\n".join(lines)


@server.tool()
def spotify_shuffle(state: bool, device_id: str | None = None) -> str:
    """Toggle shuffle mode.

    Args:
        state: True to enable shuffle, False to disable
        device_id: Target device ID (optional)
    """
    params: dict[str, Any] = {"state": str(state).lower()}
    if device_id:
        params["device_id"] = device_id
    resp = _api("PUT", "/me/player/shuffle", params=params)
    if resp.status_code in (200, 204):
        return f"Shuffle {'on' if state else 'off'}"
    return f"Error: {resp.status_code} — {resp.text}"


@server.tool()
def spotify_repeat(state: str, device_id: str | None = None) -> str:
    """Set repeat mode.

    Args:
        state: "track" (repeat current), "context" (repeat playlist/album), "off"
        device_id: Target device ID (optional)
    """
    if state not in ("track", "context", "off"):
        return "Error: state must be 'track', 'context', or 'off'"
    params: dict[str, Any] = {"state": state}
    if device_id:
        params["device_id"] = device_id
    resp = _api("PUT", "/me/player/repeat", params=params)
    if resp.status_code in (200, 204):
        return f"Repeat: {state}"
    return f"Error: {resp.status_code} — {resp.text}"


@server.tool()
def spotify_recently_played(limit: int = 10) -> str:
    """Get recently played tracks.

    Args:
        limit: Number of tracks (1-50, default 10)
    """
    resp = _api(
        "GET", "/me/player/recently-played", params={"limit": min(max(limit, 1), 50)}
    )
    if resp.status_code != 200:
        return f"Error: {resp.status_code} — {resp.text}"
    items = resp.json().get("items", [])
    lines = [f"Recently played ({len(items)} tracks):\n"]
    for i, item in enumerate(items, 1):
        t = item["track"]
        artists = ", ".join(a["name"] for a in t.get("artists", []))
        lines.append(f"{i}. **{t['name']}** by {artists} — `{t['uri']}`")
    return "\n".join(lines)


@server.tool()
def spotify_get_track(track_id: str) -> str:
    """Get detailed info about a track.

    Args:
        track_id: Spotify track ID
    """
    resp = _api("GET", f"/tracks/{track_id}")
    if resp.status_code != 200:
        return f"Error: {resp.status_code} — {resp.text}"
    t = resp.json()
    artists = ", ".join(a["name"] for a in t.get("artists", []))
    return (
        f"**{t['name']}** by {artists}\n"
        f"Album: {t['album']['name']}\n"
        f"Duration: {t['duration_ms'] // 60000}:{(t['duration_ms'] % 60000) // 1000:02d}\n"
        f"Popularity: {t['popularity']}/100\n"
        f"URI: `{t['uri']}`\n"
        f"ID: `{t['id']}`"
    )


@server.tool()
def spotify_liked_tracks(limit: int = 20, offset: int = 0) -> str:
    """Get the user's liked (saved) tracks.

    Args:
        limit: Number of tracks (1-50, default 20)
        offset: Starting position (default 0)
    """
    resp = _api(
        "GET",
        "/me/tracks",
        params={"limit": min(max(limit, 1), 50), "offset": max(offset, 0)},
    )
    if resp.status_code != 200:
        return f"Error: {resp.status_code} — {resp.text}"
    data = resp.json()
    total = data.get("total", 0)
    items = data.get("items", [])
    lines = [f"Liked tracks ({offset + 1}-{offset + len(items)} of {total}):\n"]
    for i, item in enumerate(items, offset + 1):
        t = item["track"]
        artists = ", ".join(a["name"] for a in t.get("artists", []))
        lines.append(f"{i}. **{t['name']}** by {artists} — `{t['uri']}`")
    return "\n".join(lines)


if __name__ == "__main__":
    server.run(transport="stdio")
