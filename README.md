# YT Music Manager

A local MCP server for your YouTube Music playlists. You clone it, sign in with **your** Google account, then point an AI coding tool at `server.py`. After that you can say things like "add Heart of Courage to this playlist" and it edits playlists on **your** account.

There is no hosted app and no public login page. Keys stay on your machine.

It talks to any MCP host that can start a local process (stdio). That includes Cursor, Codex, Antigravity, Claude, VS Code Copilot, Gemini CLI, and Windsurf. The Google setup is the same everywhere. Only the config file changes.

## What it can do

Two tools:

- **`add_songs_to_playlist`** searches YouTube Music for each query and appends the first match.
- **`remove_songs_from_playlist`** lists the playlist and removes tracks whose titles contain your query (case-insensitive).

You can pass a playlist ID (`PLxxxxx`) or a full YouTube Music URL.

Once it is connected, prompts like these work:

- Add Time by Hans Zimmer and Heart of Courage to playlist `PLxxxxx`
- Remove the Krrish flute remix from https://music.youtube.com/playlist?list=PLxxxxx

If you only want to listen to music, use [YouTube Music](https://music.youtube.com). You do not need this.

## What you need

- Python 3.10 or newer
- A Google account that can use YouTube Music
- A Google Cloud project with **YouTube Data API v3** enabled
- An editor or CLI that can run MCP servers over stdio

## Setup (once)

Do this in a terminal before you touch Cursor, Codex, or anything else.

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/ytmusic-mcp.git
cd ytmusic-mcp
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Swap `YOUR_USERNAME` for the GitHub user or org that hosts the repo.

### 2. Google OAuth credentials

`ytmusicapi` uses Google's TV / limited-input OAuth flow. A "Desktop app" client will not work.

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project, or pick one you already have.
2. Enable [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com).
3. Configure the OAuth consent screen. External is fine. Add your Google email as a **test user**.
4. Create credentials: **OAuth client ID**, application type **TVs and Limited Input devices**.
5. Copy the client ID and client secret.

Then:

```bash
cp .env.example .env
```

Put the values in `.env`:

```
YTMUSIC_CLIENT_ID=your-client-id.apps.googleusercontent.com
YTMUSIC_CLIENT_SECRET=your-client-secret
```

Do not commit `.env` or `oauth.json`. Both are already in `.gitignore`.

### 3. Sign in to YouTube

From the project folder, with the venv active:

```bash
ytmusicapi oauth --client-id "$YTMUSIC_CLIENT_ID" --client-secret "$YTMUSIC_CLIENT_SECRET"
```

If the env vars are not loaded in that shell, paste the values when `ytmusicapi oauth` asks for them.

It prints a URL and a code. Open the URL, enter the code, and approve access. That writes `oauth.json` next to `server.py`.

You are done with Google. The rest is telling your editor how to start the server.

## Connect it to an editor

Every client needs the same two things:

| | macOS / Linux | Windows |
| --- | --- | --- |
| **command** | `/absolute/path/to/ytmusic-mcp/.venv/bin/python` | `C:\absolute\path\to\ytmusic-mcp\.venv\Scripts\python.exe` |
| **args** | `["/absolute/path/to/ytmusic-mcp/server.py"]` | `["C:\\absolute\\path\\to\\ytmusic-mcp\\server.py"]` |

Use the venv Python, not the system `python`. The packages live in the venv. Relative paths often fail because the editor's working directory is not this repo.

`server.py` looks for `.env` and `oauth.json` next to itself, so you do not need extra env vars in the MCP config if those two files are already in place.

A copy of the Cursor-style JSON lives in `mcp.json.example`.

### Cursor

You can add it in the UI or with a file. Same result.

**UI**

1. Open **Cursor Settings**, then **MCP** (sometimes labeled **Tools & MCP**).
2. Add a new server.
3. Transport: stdio (a local command).
4. Paste the `command` and `args` from the table above.
5. Save, then reload MCP if Cursor does not pick it up on its own.

**File**

Project-only: `.cursor/mcp.json` in this repo.

Everywhere in Cursor: `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "yt-music-manager": {
      "command": "/absolute/path/to/ytmusic-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/ytmusic-mcp/server.py"]
    }
  }
}
```

You should see **YT Music Manager** with `add_songs_to_playlist` and `remove_songs_from_playlist`. If the server shows an error, open Output in Cursor and pick **MCP Logs**.

### Codex (CLI, IDE extension, ChatGPT desktop)

Codex does not use `mcp.json` for this. It uses TOML, shared across the Codex CLI, the IDE extension, and the ChatGPT desktop app.

Fastest:

```bash
codex mcp add yt-music-manager -- /absolute/path/to/ytmusic-mcp/.venv/bin/python /absolute/path/to/ytmusic-mcp/server.py
```

Then `codex mcp list` to confirm.

Or edit `~/.codex/config.toml` (user-wide) or `.codex/config.toml` in a trusted project:

```toml
[mcp_servers.yt-music-manager]
command = "/absolute/path/to/ytmusic-mcp/.venv/bin/python"
args = ["/absolute/path/to/ytmusic-mcp/server.py"]
```

The table key is `mcp_servers` with an underscore. Pasting Cursor's JSON into this file will not work.

In ChatGPT desktop or the Codex IDE extension: Settings → MCP servers → Add server → STDIO, then the same command and args. Restart the extension after you save.

### Antigravity

This is a custom stdio server, so skip the MCP Store and edit the config.

1. In the agent side panel, open **…** → **MCP Servers**.
2. **Manage MCP Servers** → **View raw config**.
3. Add the block below.

Global file: `~/.gemini/config/mcp_config.json`

This workspace only: `.agents/mcp_config.json`

```json
{
  "mcpServers": {
    "yt-music-manager": {
      "command": "/absolute/path/to/ytmusic-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/ytmusic-mcp/server.py"]
    }
  }
}
```

Use the full path to the venv Python. Antigravity does not always inherit your shell PATH, so a bare `python` often fails. Save, then refresh MCP in the panel.

This file is not the same as Gemini CLI's `~/.gemini/settings.json`.

### Other MCP hosts

Same `command` and `args`. Different file, sometimes a different JSON key.

**Claude Code**

```bash
claude mcp add --transport stdio yt-music-manager -- /absolute/path/to/ytmusic-mcp/.venv/bin/python /absolute/path/to/ytmusic-mcp/server.py
```

Or put the Cursor-style `mcpServers` JSON in `.mcp.json` (this project) or under `mcpServers` in `~/.claude.json` (your user). Claude Code does not read `~/.claude/settings.json` for MCP.

**Claude Desktop**

Same JSON as Cursor, inside:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Restart Claude Desktop.

**VS Code / GitHub Copilot**

Workspace file: `.vscode/mcp.json`

The root key is `servers`, not `mcpServers`:

```json
{
  "servers": {
    "yt-music-manager": {
      "type": "stdio",
      "command": "/absolute/path/to/ytmusic-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/ytmusic-mcp/server.py"]
    }
  }
}
```

Use Agent mode in Copilot Chat or the tools list stays empty. Command palette: **MCP: Open User Configuration** for a user-wide file.

**Gemini CLI**

`~/.gemini/settings.json` or `.gemini/settings.json`:

```json
{
  "mcpServers": {
    "yt-music-manager": {
      "command": "/absolute/path/to/ytmusic-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/ytmusic-mcp/server.py"]
    }
  }
}
```

Or: `gemini mcp add yt-music-manager /absolute/path/to/ytmusic-mcp/.venv/bin/python /absolute/path/to/ytmusic-mcp/server.py`

**Windsurf (Cascade)**

`~/.codeium/windsurf/mcp_config.json` (Windows: `%USERPROFILE%\.codeium\windsurf\mcp_config.json`). Same `mcpServers` JSON as Cursor. Refresh Cascade after you save.

**Anything else**

If the tool can run a local MCP server, give it that Python binary and `server.py`. If it wants a URL, this repo is not that. It only speaks stdio. It does not start an HTTP server.

## How search and edits actually work

Search uses a YouTube Music client that is not logged in. OAuth search currently returns HTTP 400, so the server splits the work: search without a login, then write with your OAuth token through the YouTube Data API.

That has a few practical effects:

- The first search hit is what gets added. `Time Hans Zimmer` beats `Time`.
- You can only change playlists your signed-in account can edit.
- Playlist IDs start with `PL`. Share-link junk like `si=` is ignored.
- Adding or removing a lot of tracks means a lot of YouTube Data API calls. Google's quota applies.

## If it does not start

| What you see | Likely cause |
| --- | --- |
| `oauth.json not found` | You skipped `ytmusicapi oauth`, or the editor is running a different copy of the repo. |
| `Missing YTMUSIC_CLIENT_ID or YTMUSIC_CLIENT_SECRET` | No `.env` next to `server.py`, or the names are wrong. |
| OAuth client failure / 401 | Wrong client type (use **TVs and Limited Input devices**), YouTube Data API not enabled, or you are not a test user on the consent screen. |
| Server never appears | Relative path, system Python without the packages, or JSON/TOML in the wrong file. |
| Tools listed, add fails with HTTP 4xx | API not enabled, token missing playlist scopes, or the playlist is not yours to edit. |

Do not run `python server.py` in a normal terminal to "test" it. It waits on stdin for MCP traffic and looks hung. If you want a sanity check before wiring an editor:

```bash
source .venv/bin/activate
python -c "from server import get_ytmusic_client; get_ytmusic_client(); print('auth ok')"
```

## Private files

| File | What it is |
| --- | --- |
| `.env` | OAuth client ID and secret |
| `oauth.json` | Your YouTube refresh token |

If someone gets `oauth.json` plus the client secret, they can act as you on YouTube. Keep both off GitHub.

## License

Hobby project. Use at your own risk. YouTube Music and the YouTube Data API have their own terms. This is an unofficial client.
