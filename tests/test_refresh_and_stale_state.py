from pathlib import Path
from types import SimpleNamespace

from flask import Flask, Response, jsonify

from mtde.app import create_app
from mtde.emby import EmbyClient, EmbyMovie
from mtde.service import MTDE


class FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload or {}
        self.ok = True
        self.status_code = 200
        self.headers = {}
        self.content = b""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class RecordingSession:
    def __init__(self):
        self.posts = []
        self.gets = []
        self.headers = {}

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse()

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return FakeResponse({"Items": []})


def test_emby_refresh_item_can_be_single_or_recursive():
    client = EmbyClient("http://emby:8096", "key")
    session = RecordingSession()
    client.session = session

    client.refresh_item("movie-1")
    client.refresh_item("series-1", recursive=True)

    assert session.posts[0][0].endswith("/Items/movie-1/Refresh")
    assert session.posts[0][1]["params"]["Recursive"] == "false"
    assert session.posts[1][0].endswith("/Items/series-1/Refresh")
    assert session.posts[1][1]["params"]["Recursive"] == "true"


def test_stale_emby_local_count_does_not_count_as_local(tmp_path: Path):
    service = MTDE.__new__(MTDE)
    service.settings = SimpleNamespace(
        map_path=lambda value: value,
        trailer_folder="Trailers",
        check_remote_trailers=False,
        genres_for_library=lambda _library: [],
    )
    movie = EmbyMovie(
        id="1",
        name="Example",
        year=2025,
        path=str(tmp_path),
        genres=[],
        local_trailer_count=1,
        remote_trailers=[],
        provider_ids={},
    )

    ui = service.movie_ui("Movies", movie)

    assert ui["trailerStatus"] == "missing"
    assert ui["trailerFile"] == ""
    assert ui["staleEmbyLocalTrailer"] is True


def test_scan_continues_after_stale_emby_local_count(tmp_path: Path):
    class Downloader:
        def search(self, title, year):
            return []

        def choose(self, candidates, title, year):
            return None

    service = MTDE.__new__(MTDE)
    service.settings = SimpleNamespace(
        map_path=lambda value: value,
        trailer_folder="Trailers",
        check_remote_trailers=False,
        genres_for_library=lambda _library: [],
        upgrade_trailers="local",
        trailer_resolution_min=480,
        preferred_language="german",
    )
    service.downloader = Downloader()
    movie = EmbyMovie(
        id="1",
        name="Example",
        year=2025,
        path=str(tmp_path),
        genres=[],
        local_trailer_count=1,
        remote_trailers=[],
        provider_ids={},
    )
    log = []

    result = service._process_movie("Movies", movie, False, progress=log.append)

    assert result.status == "no_match"
    assert any("STALE_EMBY_TRAILER_STATE" in line for line in log)


def test_refresh_ui_and_endpoints(monkeypatch):
    class FakeEmby:
        def __init__(self):
            self.refreshes = []

        def media_folders(self):
            return [
                {"Id": "lib-movies", "Name": "Movies", "CollectionType": "movies"},
                {"Id": "lib-tv", "Name": "TV", "CollectionType": "tvshows"},
            ]

        def search_items(self, query, include_types, limit=25):
            return [{"id": "m1", "name": "Movie One", "type": "Movie", "year": 2025, "path": "/media/movie", "local_trailer_count": 1}]

        def get_item(self, item_id):
            if item_id == "s1":
                return {"Id": "s1", "Name": "Series One", "Type": "Series"}
            return {"Id": item_id, "Name": "Movie One", "Type": "Movie"}

        def refresh_item(self, item_id, recursive=False):
            self.refreshes.append((item_id, recursive))

        def resolve_library(self, name):
            return "lib-movies"

    def fake_base_app(_service):
        app = Flask("test-base")

        @app.get("/")
        def index():
            return Response("<html><head></head><body>base</body></html>", content_type="text/html")

        @app.get("/api/log")
        def log():
            return jsonify({"lines": []})

        return app

    import mtde.app as app_module
    monkeypatch.setattr(app_module, "create_base_app", fake_base_app)

    service = SimpleNamespace(emby=FakeEmby())
    app = create_app(service)
    client = app.test_client()

    page = client.get("/")
    assert b"Emby Refresh" in page.data

    libs = client.get("/api/emby/refresh/libraries").get_json()
    assert [item["name"] for item in libs["libraries"]] == ["Movies", "TV"]

    search = client.get("/api/emby/search?q=Movie").get_json()
    assert search["items"][0]["id"] == "m1"

    response = client.post("/api/emby/refresh/item", json={"item_id": "m1"})
    assert response.status_code == 200
    assert service.emby.refreshes[-1] == ("m1", False)

    response = client.post("/api/emby/refresh/item", json={"item_id": "s1"})
    assert response.status_code == 200
    assert service.emby.refreshes[-1] == ("s1", True)

    response = client.post("/api/emby/refresh/library", json={"library_id": "lib-movies", "library_name": "Movies"})
    assert response.status_code == 200
    assert service.emby.refreshes[-1] == ("lib-movies", True)
