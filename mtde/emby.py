from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import requests


@dataclass
class EmbyMovie:
    id: str
    name: str
    year: int | None
    path: str
    genres: list[str]
    local_trailer_count: int
    remote_trailers: list[dict[str, Any]]
    provider_ids: dict[str, str]
    date_created: str = ""


class EmbyClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 120):
        root = base_url.rstrip("/")
        self.base_url = root if root.casefold().endswith("/emby") else root + "/emby"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Emby-Token": api_key, "Accept": "application/json"})

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def system_info(self) -> dict[str, Any]:
        r = self.session.get(self._url("System/Info"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def media_folders(self) -> list[dict[str, Any]]:
        r = self.session.get(self._url("Library/MediaFolders"), timeout=self.timeout)
        r.raise_for_status()
        payload = r.json()
        return list(payload.get("Items", [])) if isinstance(payload, dict) else list(payload)

    def virtual_folders(self) -> list[dict[str, Any]]:
        r = self.session.get(self._url("Library/VirtualFolders/Query"), timeout=self.timeout)
        r.raise_for_status()
        payload = r.json()
        return list(payload.get("Items", [])) if isinstance(payload, dict) else list(payload)

    def resolve_library(self, name: str) -> str:
        media_error: Exception | None = None
        try:
            for folder in self.media_folders():
                if str(folder.get("Name", "")).casefold() == name.casefold():
                    item_id = folder.get("Id") or folder.get("ItemId")
                    if item_id:
                        return str(item_id)
        except requests.RequestException as exc:
            media_error = exc
        try:
            for folder in self.virtual_folders():
                if str(folder.get("Name", "")).casefold() == name.casefold():
                    item_id = folder.get("ItemId") or folder.get("Id")
                    if item_id:
                        return str(item_id)
        except requests.RequestException:
            if media_error is not None:
                raise media_error
            raise
        raise KeyError(f"Emby library not found: {name}")

    @staticmethod
    def _movie_from_item(item: dict[str, Any]) -> EmbyMovie:
        return EmbyMovie(
            id=str(item.get("Id")),
            name=str(item.get("Name") or "Unknown"),
            year=item.get("ProductionYear"),
            path=str(item.get("Path") or ""),
            genres=[str(x) for x in item.get("Genres", [])],
            local_trailer_count=int(item.get("LocalTrailerCount") or 0),
            remote_trailers=list(item.get("RemoteTrailers") or []),
            provider_ids={str(k): str(v) for k, v in (item.get("ProviderIds") or {}).items()},
            date_created=str(item.get("DateCreated") or ""),
        )

    @staticmethod
    def _fields() -> str:
        # ProductionYear must be requested explicitly so MTDE can use the same
        # year-aware search/matching behavior as upstream MTDP.
        return "Path,Genres,ProviderIds,LocalTrailerCount,RemoteTrailers,DateCreated,ProductionYear"

    def iter_movies(self, library_name: str, page_size: int = 500) -> Iterator[EmbyMovie]:
        parent_id = self.resolve_library(library_name)
        start = 0
        while True:
            params = {
                "ParentId": parent_id,
                "Recursive": "true",
                "IncludeItemTypes": "Movie",
                "Fields": self._fields(),
                "StartIndex": start,
                "Limit": page_size,
                "SortBy": "SortName",
                "SortOrder": "Ascending",
            }
            r = self.session.get(self._url("Items"), params=params, timeout=self.timeout)
            r.raise_for_status()
            payload = r.json()
            items = payload.get("Items", [])
            for item in items:
                movie = self._movie_from_item(item)
                if movie.path:
                    yield movie
            start += len(items)
            total = int(payload.get("TotalRecordCount") or len(items))
            if not items or start >= total:
                break

    def recent_movies(self, library_name: str, limit: int = 50) -> list[EmbyMovie]:
        parent_id = self.resolve_library(library_name)
        params = {
            "ParentId": parent_id,
            "Recursive": "true",
            "IncludeItemTypes": "Movie",
            "Fields": self._fields(),
            "StartIndex": 0,
            "Limit": limit,
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
        }
        r = self.session.get(self._url("Items"), params=params, timeout=self.timeout)
        r.raise_for_status()
        return [
            movie
            for item in (r.json().get("Items") or [])
            if (movie := self._movie_from_item(item)).path
        ]

    def get_item(self, item_id: str) -> dict[str, Any]:
        params = {
            "Fields": (
                "Path,Genres,ProviderIds,LocalTrailerCount,RemoteTrailers,DateCreated,"
                "ProductionYear,Overview,OfficialRating,CommunityRating,RunTimeTicks,Studios,People"
            )
        }
        r = self.session.get(self._url(f"Items/{item_id}"), params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_movie(self, item_id: str) -> EmbyMovie:
        item = self.get_item(item_id)
        movie = self._movie_from_item(item)
        if not movie.path:
            raise KeyError(f"Emby movie has no path: {item_id}")
        return movie

    def fetch_primary_image(self, item_id: str, max_width: int = 600) -> requests.Response:
        return self.session.get(
            self._url(f"Items/{item_id}/Images/Primary"),
            params={"maxWidth": max_width, "quality": 90},
            timeout=self.timeout,
        )

    def refresh_item(self, item_id: str) -> None:
        params = {
            "Recursive": "false",
            "MetadataRefreshMode": "Default",
            "ImageRefreshMode": "Default",
            "ReplaceAllMetadata": "false",
            "ReplaceAllImages": "false",
        }
        r = self.session.post(
            self._url(f"Items/{item_id}/Refresh"),
            params=params,
            json={},
            timeout=self.timeout,
        )
        r.raise_for_status()
