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
    return playlist_id_or_url


def get_youtube_data_api_headers() -> dict[str, str]:
    yt = get_ytmusic_client()
    return {
        "Authorization": yt._token.as_auth(),
        "Content-Type": "application/json",
    }


def get_playlist_items_via_youtube_data_api(playlist_id: str) -> list[dict]:
    headers = get_youtube_data_api_headers()
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

        response = requests.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params=params,
            headers=headers,
            timeout=30,
        )
        if response.status_code >= 400:
            error = response.json().get("error", {})
            message = error.get("message", response.text)
            raise RuntimeError(
                f"Failed to list playlist items: HTTP {response.status_code}: {message}"
            )

        data = response.json()
        for item in data.get("items", []):
            snippet = item["snippet"]
            items.append(
                {
                    "itemId": item["id"],
                    "videoId": snippet["resourceId"]["videoId"],
                    "title": snippet["title"],
                }
            )

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return items


def remove_playlist_items_via_youtube_data_api(playlist_item_ids: list[str]) -> None:
    headers = get_youtube_data_api_headers()
    for item_id in playlist_item_ids:
        response = requests.delete(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={"id": item_id},
            headers=headers,
            timeout=30,
        )
        if response.status_code >= 400:
            error = response.json().get("error", {})
            message = error.get("message", response.text)
            raise RuntimeError(
                f"Failed to remove playlist item {item_id}: "
                f"HTTP {response.status_code}: {message}"
            )


def add_videos_via_youtube_data_api(playlist_id: str, video_ids: list[str]) -> None:
    headers = get_youtube_data_api_headers()
    for video_id in video_ids:
        response = requests.post(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={"part": "snippet"},
            headers=headers,
            json={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                }
            },
            timeout=30,
        )
        if response.status_code >= 400:
            error = response.json().get("error", {})
            message = error.get("message", response.text)
            raise RuntimeError(
                f"Failed to add video {video_id}: HTTP {response.status_code}: {message}"
            )


@mcp.tool()
def add_songs_to_playlist(playlist_id_or_url: str, song_queries: list[str]) -> str:
    """
    Searches YouTube Music for a list of song queries and appends them to a target playlist.
    """
    try:
        yt = get_search_client()
    except Exception as e:
        return f"Failed to initialize YouTube Music search client: {e}"

    playlist_id = parse_playlist_id(playlist_id_or_url)

    video_ids = []
    added_titles = []
    failed_queries = []

    for query in song_queries:
        try:
            results = yt.search(query, filter="songs")
            if results and len(results) > 0:
                video_id = results[0]["videoId"]
                title = results[0].get("title", query)
                artist = (
                    results[0]["artists"][0]["name"]
                    if results[0].get("artists")
                    else "Unknown"
                )
                
                video_ids.append(video_id)
                added_titles.append(f"{title} - {artist}")
            else:
                failed_queries.append(query)
        except Exception as e:
            failed_queries.append(f"{query} (Error: {str(e)})")

    if not video_ids:
        return f"Failed to find any matching tracks. Skipped: {failed_queries}"

    try:
        add_videos_via_youtube_data_api(playlist_id, video_ids)
    except Exception as e:
        return (
            f"Found {len(video_ids)} tracks but failed to add them to playlist "
            f"'{playlist_id}': {e}"
        )

    res = f"Successfully added {len(video_ids)} tracks to playlist '{playlist_id}':\n"
    res += "\n".join([f"- {item}" for item in added_titles])
    
    if failed_queries:
        res += f"\n\nCould not find/add {len(failed_queries)} tracks:\n"
        res += "\n".join([f"- {item}" for item in failed_queries])

    return res


@mcp.tool()
def remove_songs_from_playlist(playlist_id_or_url: str, song_queries: list[str]) -> str:
    """
    Removes songs from a playlist by matching track titles (case-insensitive partial match).
    """
    playlist_id = parse_playlist_id(playlist_id_or_url)
    normalized_queries = [query.strip().lower() for query in song_queries if query.strip()]

    if not normalized_queries:
        return "No song queries provided."

    try:
        playlist_items = get_playlist_items_via_youtube_data_api(playlist_id)
    except Exception as e:
        return f"Failed to list playlist '{playlist_id}': {e}"

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

    if not matched_items:
        return f"No matching tracks found in playlist '{playlist_id}'. Skipped: {not_found_queries}"

    # Deduplicate by playlist item id while preserving order.
    seen_item_ids: set[str] = set()
    unique_items: list[dict] = []
    for item in matched_items:
        if item["itemId"] in seen_item_ids:
            continue
        seen_item_ids.add(item["itemId"])
        unique_items.append(item)

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
    res += "\n".join([f"- {item['title']}" for item in unique_items])

    if not_found_queries:
        res += f"\n\nCould not find {len(not_found_queries)} tracks:\n"
        res += "\n".join([f"- {item}" for item in not_found_queries])

    return res


if __name__ == "__main__":
    mcp.run()