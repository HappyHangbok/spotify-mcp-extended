# Spotify MCP Extended

Extended Spotify MCP server for Claude Code. Adds features missing from the base server.

## New Tools

| Tool | Description |
|:-----|:------------|
| `spotify_add_to_queue` | Add a track to the playback queue |
| `spotify_get_queue` | View the current queue |
| `spotify_get_recommendations` | Get recommendations by seed tracks/artists/genres |
| `spotify_create_playlist` | Create a playlist (optionally with tracks) |
| `spotify_add_to_playlist` | Add tracks to an existing playlist |
| `spotify_my_playlists` | List your playlists |
| `spotify_shuffle` | Toggle shuffle on/off |
| `spotify_repeat` | Set repeat mode (track/context/off) |
| `spotify_recently_played` | View recently played tracks |
| `spotify_save_tracks` | Save tracks to library (Like) |
| `spotify_available_genres` | List genre seeds for recommendations |
| `spotify_get_track` | Get detailed track info |

## Prerequisites

- Existing `@tbrgeek/spotify-mcp-server` with authenticated credentials (`~/.spotify-mcp/credentials.json`)
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
# Register with Claude Code
claude mcp add spotify-extended -- uv run mcp run --transport stdio main.py --cwd /path/to/spotify-mcp-extended
```

Or add to `.mcp.json`:

```json
{
  "mcpServers": {
    "spotify-extended": {
      "command": "uv",
      "args": ["run", "mcp", "run", "--transport", "stdio", "main.py"],
      "cwd": "/path/to/spotify-mcp-extended"
    }
  }
}
```

## Usage Examples

```
"이 노래 큐에 추가해줘"
"Lana Del Rey Love랑 비슷한 곡 추천해줘"
"추천 곡들로 플레이리스트 만들어줘"
"셔플 켜줘"
"최근에 들은 곡 보여줘"
```
