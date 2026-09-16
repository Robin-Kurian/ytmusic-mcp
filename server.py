import os

import requests
from mcp.server.mcpserver import MCPServer
from ytmusicapi import YTMusic
from ytmusicapi.auth.oauth import OAuthCredentials

# Initialize MCP Server (v2.x standard)
mcp = MCPServer("YT Music Manager")

ROOT_DIR = os.path.dirname(__file__)
AUTH_FILE = os.path.join(ROOT_DIR, "oauth.json")
ENV_FILE = os.path.join(ROOT_DIR, ".env")
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
VALID_PRIVACY = {"private", "unlisted", "public"}


def load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key, value)


load_env_file(ENV_FILE)


def get_ytmusic_client() -> YTMusic:
    if not os.path.exists(AUTH_FILE):
        raise FileNotFoundError(
            f"oauth.json not found at {AUTH_FILE}! Run 'ytmusicapi oauth' in terminal first."
        )
    client_id = os.environ.get("YTMUSIC_CLIENT_ID")
    client_secret = os.environ.get("YTMUSIC_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Missing YTMUSIC_CLIENT_ID or YTMUSIC_CLIENT_SECRET. "
            "Add them to a .env file next to server.py (see .env.example)."
        )
    return YTMusic(
        AUTH_FILE,
        oauth_credentials=OAuthCredentials(client_id, client_secret),
    )


def get_search_client() -> YTMusic:
    # OAuth currently breaks YouTube Music internal search endpoints (HTTP 400).
    return YTMusic()


def parse_playlist_id(playlist_id_or_url: str) -> str:
    if "list=" in playlist_id_or_url:
        return playlist_id_or_url.split("list=")[1].split("&")[0]
    return playlist_id_or_url.strip()


def playlist_url(playlist_id: str) -> str:
    return f"https://music.youtube.com/playlist?list={playlist_id}"


def get_youtube_data_api_headers() -> dict[str, str]:
    yt = get_ytmusic_client()
    return {
        "Authorization": yt._token.as_auth(),
        "Content-Type": "application/json",
    }


def youtube_api_request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
) -> dict | None:
    response = requests.request(
        method,
        f"{YOUTUBE_API}/{path}",
        params=params,
        json=json_body,
        headers=get_youtube_data_api_headers(),
        timeout=30,
    )
    if response.status_code >= 400:
        try:
            error = response.json().get("error", {})
            message = error.get("message", response.text)
        except ValueError:
            message = response.text
        raise RuntimeError(f"HTTP {response.status_code}: {message}")
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def normalize_privacy(privacy_status: str) -> str:
    value = (privacy_status or "").strip().lower()
    if value not in VALID_PRIVACY:
        raise ValueError(
            f"privacy_status must be one of {sorted(VALID_PRIVACY)}, got '{privacy_status}'."
        )
    return value


def search_songs(song_queries: list[str]) -> tuple[list[dict], list[str]]:
    yt = get_search_client()
    found: list[dict] = []
    failed_queries: list[str] = []

    for query in song_queries:
        query = query.strip()
        if not query:
            continue
        try:
            results = yt.search(query, filter="songs")
            if not results:
                failed_queries.append(query)
                continue
            result = results[0]
            artist = (
                result["artists"][0]["name"] if result.get("artists") else "Unknown"
            )
            found.append(
                {
                    "videoId": result["videoId"],
                    "label": f"{result.get('title', query)} - {artist}",
                }
            )
        except Exception as e:
            failed_queries.append(f"{query} (Error: {e})")

    return found, failed_queries


def match_playlist_items(
    playlist_items: list[dict], song_queries: list[str] | None
) -> tuple[list[dict], list[str]]:
    if not song_queries:
        return playlist_items, []

    matched_items: list[dict] = []
    not_found_queries: list[str] = []

    for query in song_queries:
        query_normalized = query.strip().lower()
        if not query_normalized:
            continue
        matches = [
            item
            for item in playlist_items
            if query_normalized in item["title"].lower()
        ]
        if matches:
            matched_items.extend(matches)
        else:
            not_found_queries.append(query)

    seen_item_ids: set[str] = set()
    unique_items: list[dict] = []
    for item in matched_items:
        if item["itemId"] in seen_item_ids:
            continue
        seen_item_ids.add(item["itemId"])
        unique_items.append(item)

    return unique_items, not_found_queries


def format_skipped(label: str, items: list[str]) -> str:
    if not items:
        return ""
    return f"\n\n{label} {len(items)} tracks:\n" + "\n".join(
        f"- {item}" for item in items
    )


def get_playlist_items_via_youtube_data_api(playlist_id: str) -> list[dict]:
    items: list[dict] = []
    page_token: str | None = None

    while True:
        params: dict[str, str | int] = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token

        data = youtube_api_request("GET", "playlistItems", params=params) or {}
        for item in data.get("items", []):
            snippet = item["snippet"]
            resource = snippet.get("resourceId") or {}
            items.append(
                {
                    "itemId": item["id"],
                    "videoId": resource.get("videoId", ""),
                    "title": snippet.get("title", ""),
                }
            )

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return items


def get_playlist_metadata(playlist_id: str) -> dict:
    data = youtube_api_request(
        "GET",
        "playlists",
        params={"part": "snippet,contentDetails,status", "id": playlist_id},
    ) or {}
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"Playlist '{playlist_id}' was not found.")
    return items[0]


def list_my_playlists() -> list[dict]:
    playlists: list[dict] = []
    page_token: str | None = None

    while True:
        params: dict[str, str | int] = {
            "part": "snippet,contentDetails,status",
            "mine": "true",
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token

        data = youtube_api_request("GET", "playlists", params=params) or {}
        playlists.extend(data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return playlists


def create_playlist_via_youtube_data_api(
    title: str, description: str, privacy_status: str
) -> dict:
    data = youtube_api_request(
        "POST",
        "playlists",
        params={"part": "snippet,status"},
        json_body={
            "snippet": {"title": title, "description": description},
            "status": {"privacyStatus": privacy_status},
        },
    )
    if not data or not data.get("id"):
        raise RuntimeError("YouTube created the playlist but did not return an id.")
    return data


def update_playlist_via_youtube_data_api(
    playlist_id: str,
    title: str | None,
    description: str | None,
    privacy_status: str | None,
) -> dict:
    current = get_playlist_metadata(playlist_id)
    snippet = current.get("snippet") or {}
    status = current.get("status") or {}

    new_title = title if title is not None else snippet.get("title", "")
    new_description = (
        description if description is not None else snippet.get("description", "")
    )
    new_privacy = (
        privacy_status
        if privacy_status is not None
        else status.get("privacyStatus", "private")
    )

    data = youtube_api_request(
        "PUT",
        "playlists",
        params={"part": "snippet,status"},
        json_body={
            "id": playlist_id,
            "snippet": {"title": new_title, "description": new_description},
            "status": {"privacyStatus": new_privacy},
        },
    )
    return data or current


def delete_playlist_via_youtube_data_api(playlist_id: str) -> None:
    youtube_api_request("DELETE", "playlists", params={"id": playlist_id})


def add_videos_via_youtube_data_api(playlist_id: str, video_ids: list[str]) -> None:
    for video_id in video_ids:
        youtube_api_request(
            "POST",
            "playlistItems",
            params={"part": "snippet"},
            json_body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                }
            },
        )


def remove_playlist_items_via_youtube_data_api(playlist_item_ids: list[str]) -> None:
    for item_id in playlist_item_ids:
        youtube_api_request("DELETE", "playlistItems", params={"id": item_id})


def playlist_heading(playlist: dict) -> str:
    playlist_id = playlist["id"]
    snippet = playlist.get("snippet") or {}
    status = playlist.get("status") or {}
    details = playlist.get("contentDetails") or {}
    title = snippet.get("title") or "(untitled)"
    count = details.get("itemCount", "?")
    privacy = status.get("privacyStatus", "unknown")
    return (
        f"{title} ({count} tracks, {privacy})\n"
        f"{playlist_id}\n"
        f"{playlist_url(playlist_id)}"
    )


@mcp.tool()
def list_playlists() -> str:
    """
    Lists playlists on the signed-in YouTube account (title, id, track count, privacy, URL).
    """
    try:
        playlists = list_my_playlists()
    except Exception as e:
        return f"Failed to list playlists: {e}"

    if not playlists:
        return "No playlists found on this YouTube account."

    lines = [f"Your playlists ({len(playlists)}):\n"]
    for playlist in playlists:
        lines.append(f"- {playlist_heading(playlist).replace(chr(10), chr(10) + '  ')}")
        lines.append("")
    return "\n".join(lines).strip()


@mcp.tool()
def list_playlist_songs(playlist_id_or_url: str) -> str:
    """
    Lists the tracks currently on a playlist. Pass a playlist ID (PLxxxxx) or a YouTube Music URL.
    """
    playlist_id = parse_playlist_id(playlist_id_or_url)
    try:
        playlist = get_playlist_metadata(playlist_id)
        items = get_playlist_items_via_youtube_data_api(playlist_id)
    except Exception as e:
        return f"Failed to list playlist '{playlist_id}': {e}"

    heading = playlist_heading(playlist)
    if not items:
        return f"{heading}\n\nThis playlist is empty."

    tracks = "\n".join(
        f"{index}. {item['title']}" for index, item in enumerate(items, 1)
    )
    return f"{heading}\n\n{tracks}"


@mcp.tool()
def create_playlist(
    title: str,
    description: str = "",
    privacy_status: str = "private",
    song_queries: list[str] | None = None,
) -> str:
    """
    Creates a new YouTube Music playlist. Optionally searches for song_queries and adds the first match of each.
    privacy_status: private, unlisted, or public. Returns the new playlist ID and URL.
    """
    title = (title or "").strip()
    if not title:
        return "A playlist title is required."

    try:
        privacy = normalize_privacy(privacy_status)
    except ValueError as e:
        return str(e)

    try:
        created = create_playlist_via_youtube_data_api(
            title, description or "", privacy
        )
    except Exception as e:
        return f"Failed to create playlist '{title}': {e}"

    playlist_id = created["id"]
    res = (
        f"Created playlist '{title}' ({privacy}).\n"
        f"ID: {playlist_id}\n"
        f"URL: {playlist_url(playlist_id)}"
    )

    queries = [query.strip() for query in (song_queries or []) if query.strip()]
    if not queries:
        return res

    try:
        found, failed_queries = search_songs(queries)
    except Exception as e:
        return f"{res}\n\nPlaylist was created, but search failed: {e}"

    if not found:
        return (
            f"{res}\n\nFailed to find any matching tracks."
            + format_skipped("Skipped", failed_queries)
        )

    try:
        add_videos_via_youtube_data_api(
            playlist_id, [item["videoId"] for item in found]
        )
    except Exception as e:
        return (
            f"{res}\n\nFound {len(found)} tracks but failed to add them: {e}"
            + format_skipped("Could not find/add", failed_queries)
        )

    res += f"\n\nAdded {len(found)} tracks:\n"
    res += "\n".join(f"- {item['label']}" for item in found)
    res += format_skipped("Could not find/add", failed_queries)
    return res


@mcp.tool()
def update_playlist(
    playlist_id_or_url: str,
    title: str | None = None,
    description: str | None = None,
    privacy_status: str | None = None,
) -> str:
    """
    Updates a playlist's title, description, and/or privacy (private, unlisted, public).
    """
    playlist_id = parse_playlist_id(playlist_id_or_url)
    if title is None and description is None and privacy_status is None:
        return "Provide at least one of title, description, or privacy_status."

    privacy = None
    if privacy_status is not None:
        try:
            privacy = normalize_privacy(privacy_status)
        except ValueError as e:
            return str(e)

    new_title = title.strip() if isinstance(title, str) else title
    if new_title is not None and not new_title:
        return "title cannot be empty."

    try:
        updated = update_playlist_via_youtube_data_api(
            playlist_id, new_title, description, privacy
        )
    except Exception as e:
        return f"Failed to update playlist '{playlist_id}': {e}"

    return f"Updated playlist:\n{playlist_heading(updated)}"


@mcp.tool()
def delete_playlist(playlist_id_or_url: str) -> str:
    """
    Permanently deletes a playlist you own. This cannot be undone. Tracks themselves are not deleted from YouTube.
    """
    playlist_id = parse_playlist_id(playlist_id_or_url)
    try:
        playlist = get_playlist_metadata(playlist_id)
        title = (playlist.get("snippet") or {}).get("title") or playlist_id
        delete_playlist_via_youtube_data_api(playlist_id)
    except Exception as e:
        return f"Failed to delete playlist '{playlist_id}': {e}"

    return f"Deleted playlist '{title}' ({playlist_id})."


@mcp.tool()
def add_songs_to_playlist(playlist_id_or_url: str, song_queries: list[str]) -> str:
    """
    Searches YouTube Music for a list of song queries and appends them to a target playlist.
    """
    playlist_id = parse_playlist_id(playlist_id_or_url)
    queries = [query.strip() for query in song_queries if query.strip()]
    if not queries:
        return "No song queries provided."

    try:
        found, failed_queries = search_songs(queries)
    except Exception as e:
        return f"Failed to initialize YouTube Music search client: {e}"

    if not found:
        return f"Failed to find any matching tracks.{format_skipped('Skipped', failed_queries)}"

    try:
        add_videos_via_youtube_data_api(
            playlist_id, [item["videoId"] for item in found]
        )
    except Exception as e:
        return (
            f"Found {len(found)} tracks but failed to add them to playlist "
            f"'{playlist_id}': {e}"
        )

    res = f"Successfully added {len(found)} tracks to playlist '{playlist_id}':\n"
    res += "\n".join(f"- {item['label']}" for item in found)
    res += format_skipped("Could not find/add", failed_queries)
    return res


@mcp.tool()
def remove_songs_from_playlist(playlist_id_or_url: str, song_queries: list[str]) -> str:
    """
    Removes songs from a playlist by matching track titles (case-insensitive partial match).
    """
    playlist_id = parse_playlist_id(playlist_id_or_url)
    queries = [query.strip() for query in song_queries if query.strip()]
    if not queries:
        return "No song queries provided."

    try:
        playlist_items = get_playlist_items_via_youtube_data_api(playlist_id)
    except Exception as e:
        return f"Failed to list playlist '{playlist_id}': {e}"

    unique_items, not_found_queries = match_playlist_items(playlist_items, queries)
    if not unique_items:
        return (
            f"No matching tracks found in playlist '{playlist_id}'."
            + format_skipped("Skipped", not_found_queries)
        )

    try:
        remove_playlist_items_via_youtube_data_api(
            [item["itemId"] for item in unique_items]
        )
    except Exception as e:
        return (
            f"Found {len(unique_items)} tracks but failed to remove them from playlist "
            f"'{playlist_id}': {e}"
        )

    res = f"Successfully removed {len(unique_items)} tracks from playlist '{playlist_id}':\n"
    res += "\n".join(f"- {item['title']}" for item in unique_items)
    res += format_skipped("Could not find", not_found_queries)
    return res


def transfer_songs(
    source_playlist_id_or_url: str,
    destination_playlist_id_or_url: str,
    song_queries: list[str] | None,
    *,
    remove_from_source: bool,
) -> str:
    source_id = parse_playlist_id(source_playlist_id_or_url)
    dest_id = parse_playlist_id(destination_playlist_id_or_url)
    action = "move" if remove_from_source else "copy"

    if source_id == dest_id:
        return "Source and destination playlists are the same."

    queries = [query.strip() for query in (song_queries or []) if query.strip()]

    try:
        source_items = get_playlist_items_via_youtube_data_api(source_id)
        dest_items = get_playlist_items_via_youtube_data_api(dest_id)
    except Exception as e:
        return f"Failed to read playlists for {action}: {e}"

    if queries:
        unique_items, not_found_queries = match_playlist_items(source_items, queries)
        if not unique_items:
            return (
                f"No matching tracks found in playlist '{source_id}'."
                + format_skipped("Skipped", not_found_queries)
            )
    else:
        unique_items = source_items
        not_found_queries = []
        if not unique_items:
            return f"Source playlist '{source_id}' is empty."

    dest_video_ids = {item["videoId"] for item in dest_items if item.get("videoId")}
    to_add: list[dict] = []
    already_in_dest: list[dict] = []
    for item in unique_items:
        if item.get("videoId") and item["videoId"] in dest_video_ids:
            already_in_dest.append(item)
        else:
            to_add.append(item)

    if to_add:
        try:
            add_videos_via_youtube_data_api(
                dest_id, [item["videoId"] for item in to_add]
            )
        except Exception as e:
            return (
                f"Failed to {action} tracks to playlist '{dest_id}' after matching "
                f"{len(unique_items)} in the source: {e}"
            )

    if remove_from_source:
        try:
            remove_playlist_items_via_youtube_data_api(
                [item["itemId"] for item in unique_items]
            )
        except Exception as e:
            return (
                f"Added {len(to_add)} tracks to '{dest_id}' but failed to remove them "
                f"from '{source_id}': {e}"
            )

    verb = "Moved" if remove_from_source else "Copied"
    res = (
        f"{verb} {len(unique_items)} tracks from '{source_id}' to '{dest_id}'.\n"
        f"{playlist_url(dest_id)}"
    )
    if to_add:
        res += "\n\nAdded to destination:\n" + "\n".join(
            f"- {item['title']}" for item in to_add
        )
    if already_in_dest:
        res += "\n\nAlready on destination (not duplicated):\n" + "\n".join(
            f"- {item['title']}" for item in already_in_dest
        )
    res += format_skipped("Could not find", not_found_queries)
    return res


@mcp.tool()
def copy_songs_to_playlist(
    source_playlist_id_or_url: str,
    destination_playlist_id_or_url: str,
    song_queries: list[str] | None = None,
) -> str:
    """
    Copies matching songs from one playlist to another without removing them from the source.
    Match is case-insensitive substring on titles. Omit song_queries to copy every track.
    """
    return transfer_songs(
        source_playlist_id_or_url,
        destination_playlist_id_or_url,
        song_queries,
        remove_from_source=False,
    )


@mcp.tool()
def move_songs_to_playlist(
    source_playlist_id_or_url: str,
    destination_playlist_id_or_url: str,
    song_queries: list[str] | None = None,
) -> str:
    """
    Moves matching songs from one playlist to another (copy, then remove from the source).
    Match is case-insensitive substring on titles. Omit song_queries to move every track.
    """
    return transfer_songs(
        source_playlist_id_or_url,
        destination_playlist_id_or_url,
        song_queries,
        remove_from_source=True,
    )


if __name__ == "__main__":
    mcp.run()
