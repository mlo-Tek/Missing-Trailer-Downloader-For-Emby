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


class EmbyClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 60):
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

    def virtual_folders(self) -> list[dict[str, Any]]:
        # Emby 4.8+ documents the paged Query endpoint for virtual libraries.
        r = self.session.get(self._url("Library/VirtualFolders/Query"), timeout=self.timeout)
        r.raise_for_status()
        payload = r.json()
        return list(payload.get("Items", [])) if isinstance(payload, dict) else list(payload)

    def resolve_library(self, name: str) -> str:
        for folder in self.virtual_folders():
            if str(folder.get("Name", "")).casefold() == name.casefold():
                item_id = folder.get("ItemId")
                if item_id:
                    return str(item_id)
        raise KeyError(f"Emby library not found: {name}")

    def iter_movies(self, library_name: str, page_size: int = 500) -> Iterator[EmbyMovie]:
        parent_id = self.resolve_library(library_name)
        start = 0
        fields = ",".join([
            "Path", "Genres", "ProviderIds", "LocalTrailerCount", "RemoteTrailers", "ProductionYear"
        ])
        while True:
            params = {
                "ParentId": parent_id,
                "Recursive": "true",
                "IncludeItemTypes": "Movie",
                "Fields": fields,
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
                path = item.get("Path") or ""
                if not path:
                    continue
                yield EmbyMovie(
                    id=str(item.get("Id")),
                    name=str(item.get("Name") or "Unknown"),
                    year=item.get("ProductionYear"),
                    path=str(path),
                    genres=[str(x) for x in item.get("Genres", [])],
                    local_trailer_count=int(item.get("LocalTrailerCount") or 0),
                    remote_trailers=list(item.get("RemoteTrailers") or []),
                    provider_ids={str(k): str(v) for k, v in (item.get("ProviderIds") or {}).items()},
                )
            start += len(items)
            total = int(payload.get("TotalRecordCount") or len(items))
            if not items or start >= total:
                break

    def refresh_item(self, item_id: str) -> None:
        params = {
            "Recursive": "false",
            "MetadataRefreshMode": "Default",
            "ImageRefreshMode": "Default",
            "ReplaceAllMetadata": "false",
            "ReplaceAllImages": "false",
        }
        r = self.session.post(self._url(f"Items/{item_id}/Refresh"), params=params, json={}, timeout=self.timeout)
        r.raise_for_status()
