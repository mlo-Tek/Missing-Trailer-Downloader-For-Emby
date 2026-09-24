from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any

from flask import Flask, jsonify, request


_BLOCKED_CONTENT_PHRASES = (
    "soundtrack",
    "reversed",
    "trailer remake",
    "remake trailer",
    "synchrontrailer",
    "synchron trailer",
    "synchronsprecher",
    "die deutschen stimmen",
    "deutsche stimmen",
    "voice cast",
    "hauptmenü",
    "hauptmenu",
    "dvd menu",
    "dvd menü",
    "alle trailer",
    "all trailers",
    "trailer compilation",
    "trailersammlung",
    "trailer sammlung",
    "ganzer film",
    "ganze film",
    "full movie",
    "full film",
)

_ALLOWED_SUFFIX_WORDS = {
    "official", "offiziell", "offizieller", "offizieller", "offizielle", "offizielles",
    "deutsch", "deutscher", "german", "english", "englisch",
    "hd", "uhd", "4k", "full", "final", "finaler", "erster", "erste", "first",
    "trailer", "teaser", "movie", "film", "kino", "kinotrailer", "tv", "spot",
    "disney", "pixar", "dreamworks", "netflix", "universal", "paramount", "sony",
}

_PARTIAL_FILE_RE = re.compile(r"\.f\d+\.[^.]+$", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_CANDIDATE_PREFIX_RE = re.compile(r"^candidate\s+\d+/\d+:\s*", re.IGNORECASE)


@dataclass
class SuspiciousTrailer:
    library: str
    title: str
    year: int | None
    item_id: str
    path: str
    candidate: str
    reason: str
    kind: str = "download"


def _normalized(text: str) -> str:
    from .trailer import normalize_title_for_match

    return normalize_title_for_match(text)


def _unexpected_short_title_suffix(video_title: str, movie_title: str) -> bool:
    """Reject obvious spin-off/subtitle matches for short base movie titles.

    Examples: Cars -> Cars On The Road, Die Croods -> Die Croods Alles auf Anfang.
    The regular upstream matcher remains responsible for normal title matching.
    """
    movie_norm = _normalized(movie_title)
    video_norm = _normalized(video_title)
    movie_words = movie_norm.split()
    if not movie_norm or (len(movie_words) > 3 and len(movie_norm) > 18):
        return False

    match = re.search(r"\b" + re.escape(movie_norm) + r"\b", video_norm)
    if not match:
        return False

    suffix = video_norm[match.end():].strip()
    if not suffix:
        return False

    # Only inspect the words before the first trailer/teaser marker. Anything
    # after that is normally channel/language/release noise.
    marker = re.search(r"\b(?:trailer|teaser)\b", suffix)
    before = suffix[: marker.start()].strip() if marker else suffix
    if not before:
        return False

    tokens = [token for token in before.split() if not token.isdigit()]
    significant = [token for token in tokens if token not in _ALLOWED_SUFFIX_WORDS]
    return bool(significant)


def candidate_safety_reason(video_title: str, movie_title: str, year: int | None) -> str | None:
    """Return a reason when a verified MTDP candidate is unsafe for auto-download.

    This deliberately sits *after* the upstream-style MTDP matcher. It does not
    replace MTDP scoring; it only rejects clear false positives observed during
    real MTDE runs.
    """
    title_lower = video_title.casefold()

    for phrase in _BLOCKED_CONTENT_PHRASES:
        if phrase in title_lower:
            return f"blocked content marker: {phrase}"

    # Automatic downloads must explicitly identify themselves as a trailer or
    # teaser. This rejects soundtrack songs, normal clips and unrelated scenes.
    if not re.search(r"\b(?:trailer|teaser)\b", title_lower):
        return "missing trailer/teaser keyword"

    if year is not None:
        years = [int(value) for value in _YEAR_RE.findall(video_title)]
        if years and all(abs(value - int(year)) > 1 for value in years):
            return f"year mismatch: movie {year}, candidate {', '.join(map(str, years))}"

    if _unexpected_short_title_suffix(video_title, movie_title):
        return "short-title spin-off/subtitle mismatch"

    return None


def is_partial_output_path(path: str | Path) -> bool:
    value = Path(path)
    name = value.name
    lower = name.casefold()
    return (
        bool(_PARTIAL_FILE_RE.search(name))
        or lower.endswith(".part")
        or lower.endswith(".ytdl")
        or ".part." in lower
        or name.startswith(".mtde-upgrade-")
    )


def install_trailer_hardening() -> None:
    """Patch the trailer adapter while leaving upstream MTDP matching intact."""
    from . import trailer as trailer_module

    if getattr(trailer_module, "_mtde_hardening_installed", False):
        return

    original_ranked = trailer_module.TrailerDownloader.ranked_candidates
    original_download = trailer_module.TrailerDownloader.download
    original_find = trailer_module.find_local_trailers

    def safe_ranked(self, candidates, movie_title, year):
        ranked = original_ranked(self, candidates, movie_title, year)
        return [
            candidate
            for candidate in ranked
            if candidate_safety_reason(candidate.title, movie_title, year) is None
        ]

    def safe_download(self, candidate, output_stem, ignore_minimum=False):
        path = original_download(self, candidate, output_stem, ignore_minimum=ignore_minimum)
        if is_partial_output_path(path):
            self._cleanup_partial_outputs(Path(output_stem))
            raise RuntimeError(f"yt-dlp returned an intermediate/fragment file instead of a final trailer: {path.name}")
        return path

    def safe_find_local_trailers(movie_path, trailer_folder):
        return [path for path in original_find(movie_path, trailer_folder) if not is_partial_output_path(path)]

    trailer_module.TrailerDownloader.ranked_candidates = safe_ranked
    trailer_module.TrailerDownloader.download = safe_download
    trailer_module.find_local_trailers = safe_find_local_trailers
    trailer_module._mtde_hardening_installed = True


def _config_root() -> Path:
    return Path(os.environ.get("MTDE_CONFIG", "/config/config.yml")).parent


def _repair_log(message: str) -> None:
    entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {message}"
    print(entry, flush=True)
    path = _config_root() / "logs" / "mtde.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(entry + "\n")
    except OSError:
        pass


def _parse_download_history(log_root: Path) -> dict[str, dict[str, Any]]:
    """Return the latest successful MTDE download record for each output path."""
    records: dict[str, dict[str, Any]] = {}
    active: dict[tuple[str, str], str] = {}
    movie_logs = log_root / "Movies"
    if not movie_logs.is_dir():
        return records

    for log_file in sorted(movie_logs.glob("log_*.txt"), key=lambda p: p.name):
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            parts = line.split(" | ", 4)
            if len(parts) < 4:
                continue
            status = parts[1].strip().upper()
            library = parts[2].strip()
            title = parts[3].strip()
            message = parts[4].strip() if len(parts) > 4 else ""
            key = (library, title)
            if status in {"DOWNLOADING", "UPGRADE_DOWNLOADING"}:
                active[key] = _CANDIDATE_PREFIX_RE.sub("", message)
            elif status in {"DOWNLOADED", "UPGRADED"} and message:
                candidate = active.get(key, "")
                # UPGRADED logs currently store the final path only in the
                # progress message, so this parser intentionally treats the
                # message as a path only when it looks absolute.
                path = message if message.startswith("/") else ""
                if path:
                    years = [int(value) for value in _YEAR_RE.findall(path)]
                    records[path] = {
                        "library": library,
                        "title": title,
                        "year": years[-1] if years else None,
                        "candidate": candidate,
                        "log_file": str(log_file),
                    }
    return records


def _movie_index(service) -> tuple[dict[tuple[str, str, int | None], Any], list[tuple[str, Any]]]:
    index: dict[tuple[str, str, int | None], Any] = {}
    all_movies: list[tuple[str, Any]] = []
    for library in service.settings.movie_libraries:
        for movie in service.emby.iter_movies(library):
            key = (library, movie.name.casefold(), movie.year)
            index[key] = movie
            all_movies.append((library, movie))
    return index, all_movies


def find_suspicious_trailers(service) -> list[SuspiciousTrailer]:
    from .trailer import trailer_directories

    history = _parse_download_history(_config_root() / "logs")
    movie_index, all_movies = _movie_index(service)
    found: dict[str, SuspiciousTrailer] = {}

    for path_text, record in history.items():
        path = Path(path_text)
        candidate = str(record.get("candidate") or "")
        if not candidate or not path.exists():
            continue
        library = str(record.get("library") or "")
        title = str(record.get("title") or "")
        year = record.get("year")
        movie = movie_index.get((library, title.casefold(), year))
        if movie is None:
            # Fall back to exact library/title where the year could not be
            # parsed from an unusual filename.
            movie = next(
                (m for lib, m in all_movies if lib == library and m.name.casefold() == title.casefold()),
                None,
            )
        effective_year = movie.year if movie is not None else year
        reason = candidate_safety_reason(candidate, title, effective_year)
        if reason:
            found[str(path)] = SuspiciousTrailer(
                library=library,
                title=title,
                year=effective_year,
                item_id=str(movie.id) if movie is not None else "",
                path=str(path),
                candidate=candidate,
                reason=reason,
            )

    # Also find deterministic yt-dlp fragments in trailer folders. These are
    # never valid final trailers and can safely be removed/reprocessed.
    for library, movie in all_movies:
        mapped = service._mapped_movie_path(movie)
        for trailer_dir in trailer_directories(mapped, service.settings.trailer_folder):
            try:
                children = list(trailer_dir.iterdir())
            except OSError:
                continue
            for path in children:
                if not path.is_file() or not is_partial_output_path(path):
                    continue
                found.setdefault(
                    str(path),
                    SuspiciousTrailer(
                        library=library,
                        title=movie.name,
                        year=movie.year,
                        item_id=str(movie.id),
                        path=str(path),
                        candidate="",
                        reason="yt-dlp intermediate/fragment file",
                        kind="fragment",
                    ),
                )

    return sorted(found.values(), key=lambda item: (item.library.casefold(), item.title.casefold(), item.path.casefold()))


def repair_suspicious_trailers(service, *, progress=None) -> list[dict[str, Any]]:
    if service.settings.dry_run:
        raise RuntimeError("DRY_RUN is active. Switch to real-run mode before repairing files.")
    if not service.settings.download_trailers:
        raise RuntimeError("DOWNLOAD_TRAILERS is disabled.")

    suspicious = find_suspicious_trailers(service)
    _, all_movies = _movie_index(service)
    movie_lookup = {(lib, str(movie.id)): movie for lib, movie in all_movies}
    results: list[dict[str, Any]] = []

    for item in suspicious:
        path = Path(item.path)
        movie = movie_lookup.get((item.library, item.item_id))
        if movie is None:
            results.append({**asdict(item), "repair_status": "skipped", "repair_message": "Emby item could not be resolved"})
            continue

        movie_dir = service._mapped_movie_path(movie)
        movie_dir = movie_dir if movie_dir.is_dir() else movie_dir.parent
        try:
            resolved_path = path.resolve()
            resolved_movie = movie_dir.resolve()
            if resolved_movie not in resolved_path.parents:
                raise PermissionError("recorded trailer path is outside the resolved Emby movie folder")
        except OSError as exc:
            results.append({**asdict(item), "repair_status": "skipped", "repair_message": str(exc)})
            continue

        _repair_log(f"REPAIR_DELETE       | {item.library} | {item.title} | {item.reason} | {item.path}")
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            results.append({**asdict(item), "repair_status": "delete_error", "repair_message": str(exc)})
            continue

        try:
            service.emby.refresh_item(movie.id)
        except Exception as exc:
            _repair_log(f"REPAIR_EMBY_WARNING | {item.library} | {item.title} | {exc}")

        _repair_log(f"REPAIR_SEARCH       | {item.library} | {item.title} | searching safe replacement")
        result = service._process_movie(item.library, movie, True, progress=progress or _repair_log)
        results.append({
            **asdict(item),
            "repair_status": result.status,
            "repair_message": result.message,
            "replacement_path": result.trailer_path,
        })

    return results


_REPAIR_CSS = r"""
<style id="mtde-repair-style">
#mtde-repair-modal{display:none;position:fixed;inset:0;z-index:10020;background:rgba(5,4,14,.8);align-items:center;justify-content:center;padding:18px}
#mtde-repair-modal.open{display:flex}
#mtde-repair-card{width:min(900px,97vw);max-height:90vh;overflow:auto;background:#15112a;border:1px solid #3c2f66;border-radius:16px;padding:20px;color:#eee8ff}
#mtde-repair-card h2{margin:0 0 8px}
#mtde-repair-card p{color:#aaa0c7;line-height:1.45}
#mtde-repair-list{margin:14px 0;max-height:45vh;overflow:auto;background:#0f0c20;border:1px solid #40336b;border-radius:9px;padding:10px;white-space:pre-wrap;font:12px/1.45 monospace}
.mtde-repair-actions{display:flex;gap:10px;flex-wrap:wrap}
.mtde-repair-actions button,#mtde-repair-close{border:1px solid #7254d8;background:#8b6cf0;color:white;border-radius:9px;padding:9px 13px;font-weight:700;cursor:pointer}
#mtde-repair-close{float:right;background:transparent;color:#cfc6ec}
#mtde-repair-live{background:#c94444;border-color:#d65a5a}
</style>
"""

_REPAIR_HTML = r"""
<div id="mtde-repair-modal" aria-hidden="true">
  <div id="mtde-repair-card">
    <button id="mtde-repair-close" type="button">Schließen</button>
    <h2>Verdächtige MTDE-Trailer reparieren</h2>
    <p>MTDE prüft nur Trailer, deren Download anhand der eigenen persistenten Logs eindeutig zugeordnet werden kann, sowie eindeutige yt-dlp-Fragmentdateien. Fremde oder manuell vorhandene Trailer werden nicht gelöscht.</p>
    <div class="mtde-repair-actions">
      <button id="mtde-repair-analyze" type="button">Analysieren</button>
      <button id="mtde-repair-live" type="button">Gefundene Trailer reparieren</button>
    </div>
    <div id="mtde-repair-list">Noch nicht analysiert.</div>
  </div>
</div>
"""

_REPAIR_JS = r"""
<script id="mtde-repair-script">
(function(){
  const $=id=>document.getElementById(id);
  async function req(url,opts={}){const r=await fetch(url,opts);const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);return d;}
  function render(items){
    const box=$('mtde-repair-list');
    if(!items?.length){box.textContent='Keine eindeutig verdächtigen MTDE-Downloads gefunden.';return;}
    box.textContent=items.map((x,i)=>`${i+1}. ${x.title}${x.year?` (${x.year})`:''}\n   Grund: ${x.reason}\n   Kandidat: ${x.candidate||'(yt-dlp Fragment)'}\n   Datei: ${x.path}${x.repair_status?`\n   Ergebnis: ${x.repair_status}${x.replacement_path?` -> ${x.replacement_path}`:''}`:''}`).join('\n\n');
  }
  function open(){ $('mtde-repair-modal')?.classList.add('open'); analyze(); }
  function close(){ $('mtde-repair-modal')?.classList.remove('open'); }
  async function analyze(){try{$('mtde-repair-list').textContent='Analysiere persistente MTDE-Logs und Trailerdateien …';const d=await req('/api/repair/suspicious');render(d.items||[]);}catch(e){$('mtde-repair-list').textContent='Analyse fehlgeschlagen: '+e.message;}}
  async function repair(){
    if(!confirm('Nur eindeutig anhand der MTDE-Logs zugeordnete falsche Downloads und yt-dlp-Fragmente werden gelöscht. Anschließend sucht MTDE sofort einen sicheren Ersatz. Fortfahren?')) return;
    try{$('mtde-repair-list').textContent='Reparatur läuft …';const d=await req('/api/repair/suspicious',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});render(d.items||[]);if(window.refreshMovies) window.refreshMovies();}catch(e){$('mtde-repair-list').textContent='Reparatur fehlgeschlagen: '+e.message;}
  }
  function install(){
    if($('mtde-repair-toolbar-btn')) return;
    const toolbar=document.querySelector('#page-movies .library-toolbar'); if(!toolbar)return;
    const btn=document.createElement('button');btn.id='mtde-repair-toolbar-btn';btn.type='button';btn.className='btn btn-sm';btn.textContent='MTDE Repair';btn.title='Eindeutig falsche MTDE-Downloads analysieren und korrigieren';btn.style.cssText='margin-left:8px;padding:4px 10px;font-size:12px;';btn.addEventListener('click',open);toolbar.appendChild(btn);
  }
  document.addEventListener('click',e=>{if(e.target?.id==='mtde-repair-close'||e.target?.id==='mtde-repair-modal')close();if(e.target?.id==='mtde-repair-analyze')analyze();if(e.target?.id==='mtde-repair-live')repair();});
  install();new MutationObserver(install).observe(document.body,{childList:true,subtree:true});
})();
</script>
"""


def install_repair_routes(app: Flask, service) -> None:
    if "mtde_repair_suspicious" in app.view_functions:
        return

    @app.get("/api/repair/suspicious", endpoint="mtde_repair_suspicious")
    def repair_preview():
        try:
            items = find_suspicious_trailers(service)
            return jsonify({"items": [asdict(item) for item in items], "count": len(items), "dry_run": service.settings.dry_run})
        except Exception as exc:
            return jsonify({"items": [], "error": str(exc)}), 500

    @app.post("/api/repair/suspicious", endpoint="mtde_repair_execute")
    def repair_execute():
        try:
            items = repair_suspicious_trailers(service, progress=_repair_log)
            return jsonify({"items": items, "count": len(items), "ok": True})
        except Exception as exc:
            _repair_log(f"REPAIR_ERROR        | {exc}")
            return jsonify({"items": [], "ok": False, "error": str(exc)}), 409

    @app.after_request
    def inject_repair_ui(response):
        if request.path != "/" or not response.content_type.startswith("text/html"):
            return response
        try:
            html = response.get_data(as_text=True)
            if "mtde-repair-script" not in html:
                html = html.replace("</head>", _REPAIR_CSS + "\n</head>", 1)
                html = html.replace("</body>", _REPAIR_HTML + _REPAIR_JS + "\n</body>", 1)
                response.set_data(html)
                response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            pass
        return response
