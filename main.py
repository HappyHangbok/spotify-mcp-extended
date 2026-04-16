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
    if resp.status_code == 204:
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
def spotify_get_recommendations(
    seed_tracks: list[str] | None = None,
    seed_artists: list[str] | None = None,
    seed_genres: list[str] | None = None,
    limit: int = 10,
) -> str:
    """Get track recommendations based on seeds.

    Args:
        seed_tracks: List of Spotify track IDs (max 5 total seeds)
        seed_artists: List of Spotify artist IDs (max 5 total seeds)
        seed_genres: List of genre names (max 5 total seeds)
        limit: Number of recommendations (1-100, default 10)
    """
    params: dict[str, Any] = {"limit": min(max(limit, 1), 100)}
    if seed_tracks:
        params["seed_tracks"] = ",".join(seed_tracks)
    if seed_artists:
        params["seed_artists"] = ",".join(seed_artists)
    if seed_genres:
        params["seed_genres"] = ",".join(seed_genres)
    if not any(k.startswith("seed_") for k in params):
        return "Error: At least one seed (tracks, artists, or genres) is required."
    resp = _api("GET", "/recommendations", params=params)
    if resp.status_code != 200:
        return f"Error: {resp.status_code} — {resp.text}"
    tracks = resp.json().get("tracks", [])
    lines = [f"Recommendations ({len(tracks)} tracks):\n"]
    for i, t in enumerate(tracks, 1):
        artists = ", ".join(a["name"] for a in t.get("artists", []))
        lines.append(
            f"{i}. **{t['name']}** by {artists}\n"
            f"   URI: `{t['uri']}`"
        )
    return "\n".join(lines)


@server.tool()
def spotify_create_playlist(
    name: str,
    description: str = "",
    public: bool = False,
    track_uris: list[str] | None = None,
) -> str:
    """Create a new playlist and optionally add tracks.

    Args:
        name: Playlist name
        description: Playlist description
        public: Whether the playlist is public
        track_uris: List of Spotify track URIs to add
    """
    # Get current user ID
    resp = _api("GET", "/me")
    if resp.status_code != 200:
        return f"Error getting user: {resp.status_code}"
    user_id = resp.json()["id"]

    resp = _api(
        "POST",
        f"/users/{user_id}/playlists",
        json={"name": name, "description": description, "public": public},
    )
    if resp.status_code not in (200, 201):
        return f"Error creating playlist: {resp.status_code} — {resp.text}"
    playlist = resp.json()
    result = f"Created playlist: **{playlist['name']}**\nURI: `{playlist['uri']}`"

    if track_uris:
        # Add tracks in batches of 100
        for i in range(0, len(track_uris), 100):
            batch = track_uris[i : i + 100]
            add_resp = _api(
                "POST",
                f"/playlists/{playlist['id']}/tracks",
                json={"uris": batch},
            )
            if add_resp.status_code != 201:
                result += f"\nWarning: Failed to add some tracks: {add_resp.text}"
        result += f"\nAdded {len(track_uris)} track(s)."
    return result


@server.tool()
def spotify_add_to_playlist(playlist_id: str, track_uris: list[str]) -> str:
    """Add tracks to an existing playlist.

    Args:
        playlist_id: Spotify playlist ID
        track_uris: List of Spotify track URIs to add
    """
    for i in range(0, len(track_uris), 100):
        batch = track_uris[i : i + 100]
        resp = _api(
            "POST",
            f"/playlists/{playlist_id}/tracks",
            json={"uris": batch},
        )
        if resp.status_code != 201:
            return f"Error: {resp.status_code} — {resp.text}"
    return f"Added {len(track_uris)} track(s) to playlist."


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
        lines.append(
            f"{i}. **{p['name']}** — {p['tracks']['total']} tracks\n"
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
    if resp.status_code == 204:
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
    if resp.status_code == 204:
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
def spotify_save_tracks(track_ids: list[str]) -> str:
    """Save tracks to your library (Like).

    Args:
        track_ids: List of Spotify track IDs
    """
    resp = _api("PUT", "/me/tracks", json={"ids": track_ids})
    if resp.status_code == 200:
        return f"Saved {len(track_ids)} track(s) to library."
    return f"Error: {resp.status_code} — {resp.text}"


@server.tool()
def spotify_available_genres() -> str:
    """Get available genre seeds for recommendations."""
    resp = _api("GET", "/recommendations/available-genre-seeds")
    if resp.status_code != 200:
        return f"Error: {resp.status_code} — {resp.text}"
    genres = resp.json().get("genres", [])
    return f"Available genres ({len(genres)}):\n" + ", ".join(genres)


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


if __name__ == "__main__":
    server.run(transport="stdio")
