"""Music Assistant tool for Smart Assist.

This tool provides advanced music control using the Music Assistant integration.
It supports playing music, searching, radio stations, and the radio mode feature
for dynamic playlists.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceNotFound

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)

# Music Assistant domain
DOMAIN = "music_assistant"


class MusicAssistantTool(BaseTool):
    """Tool to control music playback via Music Assistant.
    
    Music Assistant provides advanced music control with:
    - Multi-provider support (Spotify, YouTube Music, local files, radio, etc.)
    - Intelligent search across all configured providers
    - Radio mode for dynamic playlists
    - Internet radio stations (TuneIn, Radio Browser)
    - Queue management
    """

    name = "music_assistant"
    description = "Play, search, or queue music via Music Assistant. Supports tracks, albums, artists, playlists, radio stations. radio_mode for endless similar music."
    
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Action",
            required=True,
            enum=["play", "search", "queue_add"],
        ),
        ToolParameter(
            name="query",
            type="string",
            description="Search query (song, artist, album, playlist, station)",
            required=True,
        ),
        ToolParameter(
            name="media_type",
            type="string",
            description="Media type ('radio' for internet radio)",
            required=False,
            enum=["track", "album", "artist", "playlist", "radio"],
        ),
        ToolParameter(
            name="artist",
            type="string",
            description="Artist name filter",
            required=False,
        ),
        ToolParameter(
            name="album",
            type="string",
            description="Album name filter",
            required=False,
        ),
        ToolParameter(
            name="player",
            type="string",
            description="Target player entity_id (default: active)",
            required=False,
        ),
        ToolParameter(
            name="enqueue",
            type="string",
            description="Queue mode",
            required=False,
            enum=["play", "replace", "next", "add"],
        ),
        ToolParameter(
            name="radio_mode",
            type="boolean",
            description="Endless similar music mode",
            required=False,
        ),
    ]

    async def execute(
        self,
        action: str,
        query: str,
        media_type: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        player: str | None = None,
        enqueue: str | None = None,
        radio_mode: bool | None = None,
    ) -> ToolResult:
        """Execute music assistant action."""
        
        try:
            if action == "play":
                return await self._play_media(
                    query, media_type, artist, album, player, enqueue, radio_mode
                )
            elif action == "search":
                return await self._search_media(query, media_type, artist, album)
            elif action == "queue_add":
                return await self._play_media(
                    query, media_type, artist, album, player, "add", radio_mode
                )
            else:
                return ToolResult(
                    success=False,
                    message=f"Unknown action: {action}. Use: play, search, queue_add",
                )
        except ServiceNotFound:
            return ToolResult(
                success=False,
                message="Music Assistant integration not found. Please install and configure Music Assistant.",
            )
        except Exception as err:
            _LOGGER.error("Music Assistant error: %s", err, exc_info=True)
            return ToolResult(
                success=False,
                message=f"Failed to execute music action: {err}",
            )

    async def _get_ma_player(self, player: str | None) -> str | None:
        """Get Music Assistant player entity_id.
        
        If player is specified, validates it exists.
        If not specified, tries to find a Music Assistant media player.
        """
        if player:
            # Validate the player exists
            state = self._hass.states.get(player)
            if state is None:
                return None
            return player
        
        # Try to find a Music Assistant media player
        # MA players typically have attributes from the integration
        for state in self._hass.states.async_all("media_player"):
            # Check if it's a Music Assistant player
            attrs = state.attributes
            if attrs.get("mass_player_id") or "music_assistant" in state.entity_id:
                return state.entity_id
        
        # Fall back to any playing media player
        for state in self._hass.states.async_all("media_player"):
            if state.state == "playing":
                return state.entity_id
        
        # Fall back to first available media player
        media_players = self._hass.states.async_all("media_player")
        if media_players:
            return media_players[0].entity_id
        
        return None

    async def _play_media(
        self,
        query: str,
        media_type: str | None,
        artist: str | None,
        album: str | None,
        player: str | None,
        enqueue: str | None,
        radio_mode: bool | None,
    ) -> ToolResult:
        """Play media using Music Assistant."""
        
        # Get target player
        target_player = await self._get_ma_player(player)
        if not target_player:
            return ToolResult(
                success=False,
                message="No media player found. Please specify a player entity_id.",
            )
        
        # Build service data
        service_data: dict[str, Any] = {
            "entity_id": target_player,
            "media_id": query,
        }
        
        # Add optional parameters
        if media_type:
            service_data["media_type"] = media_type
        if artist:
            service_data["artist"] = artist
        if album:
            service_data["album"] = album
        if enqueue:
            service_data["enqueue"] = enqueue
        if radio_mode:
            service_data["radio_mode"] = radio_mode
        
        _LOGGER.debug("Calling music_assistant.play_media with: %s", service_data)
        
        # Call the Music Assistant play_media service
        # Use blocking=False to avoid hanging if MA takes too long
        await self._hass.services.async_call(
            DOMAIN,
            "play_media",
            service_data,
            blocking=False,
        )
        
        # Build response message
        type_str = media_type or "media"
        player_name = target_player.split(".")[-1].replace("_", " ").title()
        
        if radio_mode:
            msg = f"Started radio mode based on '{query}' on {player_name}"
        elif enqueue == "add":
            msg = f"Added '{query}' to queue on {player_name}"
        elif enqueue == "next":
            msg = f"'{query}' will play next on {player_name}"
        else:
            msg = f"Playing {type_str} '{query}' on {player_name}"
        
        return ToolResult(
            success=True,
            message=msg,
            data={
                "player": target_player,
                "query": query,
                "media_type": media_type,
                "radio_mode": radio_mode or False,
            },
        )

    async def _search_media(
        self,
        query: str,
        media_type: str | None,
        artist: str | None,
        album: str | None,
    ) -> ToolResult:
        """Search for media using Music Assistant."""
        
        # Build service data
        service_data: dict[str, Any] = {
            "name": query,
            "limit": 5,  # Reasonable limit for LLM context
        }
        
        if media_type:
            service_data["media_type"] = media_type
        if artist:
            service_data["artist"] = artist
        if album:
            service_data["album"] = album
        
        _LOGGER.debug("Calling music_assistant.search with: %s", service_data)
        
        # Call the Music Assistant search service
        response = await self._hass.services.async_call(
            DOMAIN,
            "search",
            service_data,
            blocking=True,
            return_response=True,
        )
        
        if not response:
            return ToolResult(
                success=True,
                message=f"No results found for '{query}'",
                data={"results": []},
            )
        
        # Format results for the LLM
        results = self._format_search_results(response, query)
        
        return ToolResult(
            success=True,
            message=results["summary"],
            data=results,
        )

    def _format_search_results(
        self, response: dict[str, Any], query: str
    ) -> dict[str, Any]:
        """Format search results for LLM consumption."""
        formatted: dict[str, Any] = {
            "query": query,
            "tracks": [],
            "albums": [],
            "artists": [],
            "playlists": [],
            "radio": [],
        }
        
        # Extract tracks
        if "tracks" in response:
            for track in response["tracks"][:5]:
                formatted["tracks"].append({
                    "name": track.get("name", "Unknown"),
                    "artist": track.get("artists", [{}])[0].get("name", "Unknown") if track.get("artists") else "Unknown",
                    "album": track.get("album", {}).get("name", "") if track.get("album") else "",
                    "uri": track.get("uri", ""),
                })
        
        # Extract albums
        if "albums" in response:
            for album in response["albums"][:3]:
                formatted["albums"].append({
                    "name": album.get("name", "Unknown"),
                    "artist": album.get("artists", [{}])[0].get("name", "Unknown") if album.get("artists") else "Unknown",
                    "uri": album.get("uri", ""),
                })
        
        # Extract artists
        if "artists" in response:
            for artist in response["artists"][:3]:
                formatted["artists"].append({
                    "name": artist.get("name", "Unknown"),
                    "uri": artist.get("uri", ""),
                })
        
        # Extract playlists
        if "playlists" in response:
            for playlist in response["playlists"][:3]:
                formatted["playlists"].append({
                    "name": playlist.get("name", "Unknown"),
                    "uri": playlist.get("uri", ""),
                })
        
        # Extract radio stations
        if "radio" in response:
            for radio in response["radio"][:3]:
                formatted["radio"].append({
                    "name": radio.get("name", "Unknown"),
                    "uri": radio.get("uri", ""),
                })
        
        # Build summary
        parts = []
        if formatted["tracks"]:
            track_names = [f"'{t['name']}' by {t['artist']}" for t in formatted["tracks"][:3]]
            parts.append(f"Tracks: {', '.join(track_names)}")
        if formatted["artists"]:
            artist_names = [a["name"] for a in formatted["artists"]]
            parts.append(f"Artists: {', '.join(artist_names)}")
        if formatted["albums"]:
            album_names = [f"'{a['name']}' by {a['artist']}" for a in formatted["albums"]]
            parts.append(f"Albums: {', '.join(album_names)}")
        if formatted["playlists"]:
            playlist_names = [p["name"] for p in formatted["playlists"]]
            parts.append(f"Playlists: {', '.join(playlist_names)}")
        if formatted["radio"]:
            radio_names = [r["name"] for r in formatted["radio"]]
            parts.append(f"Radio: {', '.join(radio_names)}")
        
        if parts:
            formatted["summary"] = f"Found for '{query}': " + "; ".join(parts)
        else:
            formatted["summary"] = f"No results found for '{query}'"
        
        return formatted
