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
    original_title: str = ""


# The same metadata shape is sufficient for Series. Keeping one lightweight
# dataclass avoids duplicating all media-server plumbing while the caller still
# selects Movie vs Series explicitly through iter_movies()/iter_series().
EmbySeries = EmbyMovie


class EmbyClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 120):
        root = base_url.rstrip("/")
        self.base_url = root if root.casefold().endswith("/emby") else root + "/emby"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Emby-Token": api_key, "Accept": "application/json"})
        self._library_ids: dict[str, str] = {}

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
        cache_key = name.casefold()
        cached = self._library_ids.get(cache_key)
        if cached:
            return cached

        media_error: Exception | None = None
        try:
            for folder in self.media_folders():
                if str(folder.get("Name", "")).casefold() == cache_key:
                    item_id = folder.get("Id") or folder.get("ItemId")
                    if item_id:
                        value = str(item_id)
                        self._library_ids[cache_key] = value
                        return value
        except requests.RequestException as exc:
            media_error = exc
        try:
            for folder in self.virtual_folders():
                if str(folder.get("Name", "")).casefold() == cache_key:
                    item_id = folder.get("ItemId") or folder.get("Id")
                    if item_id:
                        value = str(item_id)
                        self._library_ids[cache_key] = value
                        return value
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
            original_title=str(item.get("OriginalTitle") or ""),
        )

    @staticmethod
    def _fields() -> str:
        return "Path,Genres,ProviderIds,LocalTrailerCount,RemoteTrailers,DateCreated,ProductionYear,OriginalTitle"

    @staticmethod
    def _detail_fields() -> str:
        return (
            "Path,Genres,ProviderIds,LocalTrailerCount,RemoteTrailers,DateCreated,"
            "ProductionYear,OriginalTitle,Overview,OfficialRating,CommunityRating,RunTimeTicks,Studios,People"
        )

    def _iter_library_items(
        self,
        library_name: str,
        include_type: str,
        page_size: int = 500,
    ) -> Iterator[EmbyMovie]:
        parent_id = self.resolve_library(library_name)
        start = 0
        while True:
            params = {
                "ParentId": parent_id,
                "Recursive": "true",
                "IncludeItemTypes": include_type,
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
                media = self._movie_from_item(item)
                if media.path:
                    yield media
            start += len(items)
            total = int(payload.get("TotalRecordCount") or len(items))
            if not items or start >= total:
                break

    def iter_movies(self, library_name: str, page_size: int = 500) -> Iterator[EmbyMovie]:
        yield from self._iter_library_items(library_name, "Movie", page_size)

    def iter_series(self, library_name: str, page_size: int = 500) -> Iterator[EmbySeries]:
        # Direct Emby equivalent of upstream Plex tv_section.all().
        yield from self._iter_library_items(library_name, "Series", page_size)

    def _recent_items(self, library_name: str, include_type: str, limit: int = 50) -> list[EmbyMovie]:
        parent_id = self.resolve_library(library_name)
        params = {
            "ParentId": parent_id,
            "Recursive": "true",
            "IncludeItemTypes": include_type,
            "Fields": self._fields(),
            "StartIndex": 0,
            "Limit": limit,
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
        }
        r = self.session.get(self._url("Items"), params=params, timeout=self.timeout)
        r.raise_for_status()
        return [
            media
            for item in (r.json().get("Items") or [])
            if (media := self._movie_from_item(item)).path
        ]

    def recent_movies(self, library_name: str, limit: int = 50) -> list[EmbyMovie]:
        return self._recent_items(library_name, "Movie", limit)

    def recent_series(self, library_name: str, limit: int = 50) -> list[EmbySeries]:
        return self._recent_items(library_name, "Series", limit)

    def get_item(self, item_id: str) -> dict[str, Any]:
        """Fetch one item without requiring an Emby user id."""
        params = {
            "Ids": str(item_id),
            "Recursive": "true",
            "Fields": self._detail_fields(),
            "Limit": 1,
        }
        r = self.session.get(self._url("Items"), params=params, timeout=self.timeout)
        r.raise_for_status()
        items = (r.json().get("Items") or [])
        if items:
            return items[0]

        r = self.session.get(
            self._url(f"Items/{item_id}"),
            params={"Fields": self._detail_fields()},
            timeout=self.timeout,
        )
        r.raise_for_status()
        payload = r.json()
        if not payload:
            raise KeyError(f"Emby item not found: {item_id}")
        return payload

    def get_media(self, item_id: str) -> tuple[str, EmbyMovie]:
        raw = self.get_item(item_id)
        media = self._movie_from_item(raw)
        if not media.path:
            raise KeyError(f"Emby item has no path: {item_id}")
        return str(raw.get("Type") or ""), media

    def get_movie(self, item_id: str) -> EmbyMovie:
        item_type, media = self.get_media(item_id)
        if item_type and item_type.casefold() != "movie":
            raise KeyError(f"Emby item is not a movie: {item_id}")
        return media

    def get_series(self, item_id: str) -> EmbySeries:
        item_type, media = self.get_media(item_id)
        if item_type and item_type.casefold() != "series":
            raise KeyError(f"Emby item is not a series: {item_id}")
        return media

    def search_items(
        self,
        query: str,
        include_types: tuple[str, ...] = ("Movie", "Series"),
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        term = query.strip()
        if not term:
            return []
        params = {
            "Recursive": "true",
            "SearchTerm": term,
            "IncludeItemTypes": ",".join(include_types),
            "Fields": "Path,ProductionYear,LocalTrailerCount",
            "Limit": max(1, min(int(limit), 100)),
            "SortBy": "SortName",
            "SortOrder": "Ascending",
        }
        r = self.session.get(self._url("Items"), params=params, timeout=self.timeout)
        r.raise_for_status()
        items = r.json().get("Items") or []
        return [
            {
                "id": str(item.get("Id") or ""),
                "name": str(item.get("Name") or "Unknown"),
                "type": str(item.get("Type") or ""),
                "year": item.get("ProductionYear"),
                "path": str(item.get("Path") or ""),
                "local_trailer_count": int(item.get("LocalTrailerCount") or 0),
            }
            for item in items
            if item.get("Id")
        ]

    def fetch_primary_image(self, item_id: str, max_width: int = 600) -> requests.Response:
        return self.session.get(
            self._url(f"Items/{item_id}/Images/Primary"),
            params={"maxWidth": max_width, "quality": 90},
            timeout=self.timeout,
        )

    def refresh_item(self, item_id: str, recursive: bool = False) -> None:
        params = {
            "Recursive": "true" if recursive else "false",
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

    def refresh_library(self, library: str) -> str:
        item_id = self.resolve_library(library)
        self.refresh_item(item_id, recursive=True)
        return item_id
