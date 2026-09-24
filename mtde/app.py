from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

from flask import Flask, jsonify, request

from .service import MTDE
from .web import create_app as create_base_app


_REFRESH_CSS = r"""
<style id="mtde-emby-refresh-style">
#mtde-emby-refresh-launcher{display:none!important}
#mtde-emby-refresh-modal{display:none;position:fixed;inset:0;z-index:9998;background:rgba(5,4,14,.78);align-items:center;justify-content:center;padding:20px}
#mtde-emby-refresh-modal.open{display:flex}
#mtde-emby-refresh-card{width:min(760px,96vw);max-height:90vh;overflow:auto;background:#15112a;border:1px solid #3c2f66;border-radius:16px;padding:22px;color:#eee8ff;box-shadow:0 18px 60px rgba(0,0,0,.55)}
#mtde-emby-refresh-card h2{margin:0 0 8px;font-size:24px}
#mtde-emby-refresh-card h3{margin:22px 0 8px;font-size:16px}
#mtde-emby-refresh-card p{color:#aaa0c7;line-height:1.45}
.mtde-emby-refresh-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.mtde-emby-refresh-row input,.mtde-emby-refresh-row select{flex:1;min-width:220px;background:#0f0c20;color:#eee8ff;border:1px solid #40336b;border-radius:9px;padding:10px 12px}
.mtde-emby-refresh-row button,#mtde-emby-refresh-close{border:1px solid #7254d8;background:#8b6cf0;color:#fff;border-radius:9px;padding:10px 14px;font-weight:700;cursor:pointer}
#mtde-emby-refresh-close{float:right;background:transparent;color:#cfc6ec}
#mtde-emby-refresh-results{width:100%;min-height:130px;margin-top:10px;background:#0f0c20;color:#eee8ff;border:1px solid #40336b;border-radius:9px;padding:7px}
#mtde-emby-refresh-status{margin-top:14px;padding:10px 12px;border-radius:9px;background:#0f0c20;color:#bcb2d8;white-space:pre-wrap}
.mtde-emby-refresh-note{font-size:13px;color:#8f86aa}
#mtde-emby-toolbar-btn{white-space:nowrap}
.mtde-detail-emby-refresh{margin-top:12px}
@media(max-width:700px){
  #mtde-emby-refresh-card{padding:16px}
  .mtde-emby-refresh-row input,.mtde-emby-refresh-row select{min-width:100%;width:100%}
  #mtde-emby-toolbar-btn{margin-left:0!important}
}
</style>
"""

_REFRESH_HTML = r"""
<div id="mtde-emby-refresh-modal" aria-hidden="true">
  <div id="mtde-emby-refresh-card">
    <button id="mtde-emby-refresh-close" type="button">Schließen</button>
    <h2>Emby aktualisieren</h2>
    <p>Du kannst eine komplette Emby-Library oder nur einen einzelnen Film bzw. eine Serie aktualisieren. Ein kompletter Library-Scan ist für einen einzelnen Film nicht nötig.</p>

    <h3>Library aktualisieren</h3>
    <div class="mtde-emby-refresh-row">
      <select id="mtde-emby-library-select"><option value="">Libraries werden geladen …</option></select>
      <button id="mtde-emby-library-refresh" type="button">Library in Emby aktualisieren</button>
    </div>
    <p class="mtde-emby-refresh-note">Die ausgewählte Library wird rekursiv aktualisiert. Emby verarbeitet den Refresh asynchron.</p>

    <h3>Film / Serie aktualisieren</h3>
    <div class="mtde-emby-refresh-row">
      <input id="mtde-emby-item-search" type="search" placeholder="Titel eingeben, z. B. Elemental oder Snowfall">
      <button id="mtde-emby-item-search-btn" type="button">Suchen</button>
    </div>
    <select id="mtde-emby-refresh-results" size="7"></select>
    <div class="mtde-emby-refresh-row" style="margin-top:10px">
      <button id="mtde-emby-item-refresh" type="button">Ausgewähltes Element aktualisieren</button>
    </div>
    <p class="mtde-emby-refresh-note">Filme werden einzeln aktualisiert. Bei Serien wird rekursiv aktualisiert, damit auch die Episoden unter der Serie neu eingelesen werden.</p>
    <div id="mtde-emby-refresh-status">Bereit.</div>
  </div>
</div>
"""

_REFRESH_JS = r"""
<script id="mtde-emby-refresh-script">
(function(){
  const $ = id => document.getElementById(id);
  const status = msg => { const el=$('mtde-emby-refresh-status'); if(el) el.textContent=msg; };
  async function jsonFetch(url, options={}){
    const res=await fetch(url,options);
    const data=await res.json().catch(()=>({}));
    if(!res.ok) throw new Error(data.error || data.message || `HTTP ${res.status}`);
    return data;
  }
  async function loadLibraries(){
    try{
      const data=await jsonFetch('/api/emby/refresh/libraries');
      const sel=$('mtde-emby-library-select');
      sel.innerHTML='';
      for(const lib of (data.libraries||[])){
        const o=document.createElement('option');
        o.value=lib.id;
        o.textContent=lib.name + (lib.collection_type ? ` (${lib.collection_type})` : '');
        o.dataset.name=lib.name;
        sel.appendChild(o);
      }
      if(!sel.options.length) sel.innerHTML='<option value="">Keine Library gefunden</option>';
    }catch(e){ status('Libraries konnten nicht geladen werden: '+e.message); }
  }
  function openRefreshModal(){
    $('mtde-emby-refresh-modal')?.classList.add('open');
    $('mtde-emby-refresh-modal')?.setAttribute('aria-hidden','false');
    loadLibraries();
  }
  function closeRefreshModal(){
    $('mtde-emby-refresh-modal')?.classList.remove('open');
    $('mtde-emby-refresh-modal')?.setAttribute('aria-hidden','true');
  }
  async function searchItems(){
    const q=($('mtde-emby-item-search').value||'').trim();
    if(q.length<2){ status('Bitte mindestens 2 Zeichen eingeben.'); return; }
    status('Suche in Emby …');
    try{
      const data=await jsonFetch('/api/emby/search?q='+encodeURIComponent(q));
      const sel=$('mtde-emby-refresh-results');
      sel.innerHTML='';
      for(const item of (data.items||[])){
        const o=document.createElement('option');
        o.value=item.id;
        o.dataset.type=item.type||'';
        const year=item.year ? ` (${item.year})` : '';
        o.textContent=`${item.type||'Item'} | ${item.name}${year}`;
        sel.appendChild(o);
      }
      status(sel.options.length ? `${sel.options.length} Treffer gefunden.` : 'Keine passenden Filme/Serien gefunden.');
    }catch(e){ status('Suche fehlgeschlagen: '+e.message); }
  }
  async function refreshLibrary(){
    const sel=$('mtde-emby-library-select');
    if(!sel.value){ status('Bitte eine Library auswählen.'); return; }
    const name=sel.selectedOptions[0]?.dataset.name || sel.selectedOptions[0]?.textContent || sel.value;
    status(`Library-Refresh für „${name}“ wird an Emby gesendet …`);
    try{
      await jsonFetch('/api/emby/refresh/library',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({library_id:sel.value,library_name:name})});
      status(`Library-Refresh für „${name}“ wurde gestartet. Emby verarbeitet den Scan im Hintergrund.`);
    }catch(e){ status('Library-Refresh fehlgeschlagen: '+e.message); }
  }
  async function refreshItemById(itemId, recursive=false, label='Element'){
    const data=await jsonFetch('/api/emby/refresh/item',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:String(itemId),recursive})});
    if(window.showToast) showToast(`Emby-Refresh gestartet: ${data.name||label}`, 'success');
    return data;
  }
  async function refreshSelectedItem(){
    const sel=$('mtde-emby-refresh-results');
    const opt=sel.selectedOptions[0];
    if(!opt){ status('Bitte zuerst einen Film oder eine Serie auswählen.'); return; }
    const recursive=(opt.dataset.type||'').toLowerCase()==='series';
    status(`Refresh für „${opt.textContent}“ wird an Emby gesendet …`);
    try{
      const data=await refreshItemById(opt.value,recursive,opt.textContent);
      status(`Emby-Refresh gestartet: ${data.name||opt.textContent}. ${recursive?'Serie inkl. untergeordneter Inhalte.':'Nur dieses Element.'}`);
    }catch(e){ status('Item-Refresh fehlgeschlagen: '+e.message); }
  }
  function installToolbarButton(){
    if($('mtde-emby-toolbar-btn')) return;
    const toolbar=document.querySelector('#page-movies .library-toolbar');
    if(!toolbar) return;
    const normalRefresh=toolbar.querySelector('button[onclick*="refreshMovies"]');
    const btn=document.createElement('button');
    btn.id='mtde-emby-toolbar-btn';
    btn.type='button';
    btn.className='btn btn-sm';
    btn.textContent='Emby Refresh';
    btn.title='Emby-Library oder einzelnes Element aktualisieren';
    btn.style.cssText='margin-left:8px;padding:4px 10px;font-size:12px;';
    btn.addEventListener('click',openRefreshModal);
    if(normalRefresh) normalRefresh.insertAdjacentElement('afterend',btn); else toolbar.appendChild(btn);
  }

  // Replace the generic upstream detail error with the actual API error and add
  // a one-click Emby refresh for the currently opened movie.
  window.openDetail = async function(ratingKey){
    const modal=$('detail-modal');
    const content=$('detail-content');
    content.innerHTML='<div class="library-loading"><span class="spinner"></span> Loading...</div>';
    modal.classList.add('show');
    try{
      const res=await apiFetch(`/api/library/item/${ratingKey}`);
      const item=await res.json().catch(()=>({}));
      if(!res.ok) throw new Error(item.error || `HTTP ${res.status}`);
      renderDetail(item);
      const target=content.querySelector('.detail-right') || content;
      const btn=document.createElement('button');
      btn.type='button';
      btn.className='btn btn-sm mtde-detail-emby-refresh';
      btn.textContent='In Emby aktualisieren';
      btn.addEventListener('click',async ev=>{
        ev.stopPropagation();
        btn.disabled=true;
        btn.textContent='Emby aktualisiert …';
        try{
          await refreshItemById(ratingKey,false,item.title||'Film');
          btn.textContent='Refresh gestartet';
          setTimeout(()=>window.openDetail(ratingKey),1800);
        }catch(e){
          btn.disabled=false;
          btn.textContent='In Emby aktualisieren';
          if(window.showToast) showToast('Emby-Refresh fehlgeschlagen: '+e.message,'error');
        }
      });
      target.appendChild(btn);
    }catch(e){
      content.innerHTML=`<div class="library-empty">Film konnte nicht geladen werden.<br><small>${escapeHtml(e.message||String(e))}</small></div>`;
    }
  };

  // The upstream Refresh button only re-requested the 30s server cache. Force
  // one backend rebuild first, then let the normal renderer consume that cache.
  window.refreshMovies = async function(){
    try{
      const grid=$('movies-grid');
      if(grid) grid.innerHTML='<div class="library-loading"><span class="spinner"></span> Refreshing movies...</div>';
      await apiFetch('/api/library/movies?refresh=true');
      moviesData=[];
      _moviesLoaded=false;
      await fetchMovies();
    }catch(e){
      if(window.showToast) showToast('Movies refresh failed: '+e.message,'error');
      fetchMovies();
    }
  };

  document.addEventListener('click',ev=>{
    if(ev.target?.id==='mtde-emby-refresh-close' || ev.target?.id==='mtde-emby-refresh-modal') closeRefreshModal();
    if(ev.target?.id==='mtde-emby-library-refresh') refreshLibrary();
    if(ev.target?.id==='mtde-emby-item-search-btn') searchItems();
    if(ev.target?.id==='mtde-emby-item-refresh') refreshSelectedItem();
  });
  document.addEventListener('keydown',ev=>{
    if(ev.key==='Escape') closeRefreshModal();
    if(ev.key==='Enter' && document.activeElement?.id==='mtde-emby-item-search'){ ev.preventDefault(); searchItems(); }
  });
  installToolbarButton();
  new MutationObserver(installToolbarButton).observe(document.body,{childList:true,subtree:true});
})();
</script>
"""


def _service_log_path() -> Path:
    config_path = Path(os.environ.get("MTDE_CONFIG", "/config/config.yml"))
    return config_path.parent / "logs" / "mtde.log"


def _append_log(message: str) -> None:
    entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {message}"
    print(entry, flush=True)
    path = _service_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(entry + "\n")
    except OSError:
        pass


def _tail_log(limit: int) -> list[str]:
    try:
        lines = _service_log_path().read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-limit:]
    except OSError:
        return []


def create_app(service: MTDE) -> Flask:
    app = create_base_app(service)

    if "log" in app.view_functions:
        def persistent_log():
            limit = max(1, min(int(request.args.get("limit", 1000)), 3000))
            return jsonify({"lines": _tail_log(limit)})
        app.view_functions["log"] = persistent_log

    @app.get("/api/emby/refresh/libraries")
    def emby_refresh_libraries():
        try:
            libraries = []
            for folder in service.emby.media_folders():
                item_id = folder.get("Id") or folder.get("ItemId")
                if not item_id:
                    continue
                libraries.append({
                    "id": str(item_id),
                    "name": str(folder.get("Name") or "Unknown"),
                    "collection_type": str(folder.get("CollectionType") or ""),
                })
            libraries.sort(key=lambda item: item["name"].casefold())
            return jsonify({"libraries": libraries})
        except Exception as exc:
            return jsonify({"libraries": [], "error": str(exc)}), 502

    @app.get("/api/emby/search")
    def emby_search():
        query = str(request.args.get("q") or "").strip()
        if len(query) < 2:
            return jsonify({"items": [], "error": "query must contain at least 2 characters"}), 400
        try:
            return jsonify({"items": service.emby.search_items(query, ("Movie", "Series"), limit=40)})
        except Exception as exc:
            return jsonify({"items": [], "error": str(exc)}), 502

    @app.post("/api/emby/refresh/item")
    def emby_refresh_item():
        payload = request.get_json(silent=True) or {}
        item_id = str(payload.get("item_id") or "").strip()
        if not item_id:
            return jsonify({"ok": False, "error": "item_id is required"}), 400
        try:
            item = service.emby.get_item(item_id)
            item_type = str(item.get("Type") or "")
            recursive_value = payload.get("recursive")
            recursive = item_type.casefold() == "series" if recursive_value is None else bool(recursive_value)
            name = str(item.get("Name") or item_id)
            _append_log(f"REFRESH_ITEM_REQUESTED | {item_type or 'Item'} | {name} | id={item_id} | recursive={str(recursive).lower()}")
            service.emby.refresh_item(item_id, recursive=recursive)
            _append_log(f"REFRESH_ITEM_DONE      | {item_type or 'Item'} | {name} | request accepted by Emby")
            return jsonify({"ok": True, "item_id": item_id, "name": name, "type": item_type, "recursive": recursive})
        except Exception as exc:
            _append_log(f"REFRESH_ITEM_ERROR     | id={item_id} | {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.post("/api/emby/refresh/library")
    def emby_refresh_library():
        payload = request.get_json(silent=True) or {}
        library_id = str(payload.get("library_id") or "").strip()
        library_name = str(payload.get("library_name") or "").strip()
        if not library_id and not library_name:
            return jsonify({"ok": False, "error": "library_id or library_name is required"}), 400
        try:
            if not library_id:
                library_id = service.emby.resolve_library(library_name)
            if not library_name:
                try:
                    library_name = str(service.emby.get_item(library_id).get("Name") or library_id)
                except Exception:
                    library_name = library_id
            _append_log(f"REFRESH_LIBRARY_REQUESTED | {library_name} | id={library_id}")
            service.emby.refresh_item(library_id, recursive=True)
            _append_log(f"REFRESH_LIBRARY_DONE      | {library_name} | request accepted by Emby")
            return jsonify({"ok": True, "library_id": library_id, "library_name": library_name, "recursive": True})
        except Exception as exc:
            _append_log(f"REFRESH_LIBRARY_ERROR     | {library_name or library_id} | {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.after_request
    def inject_emby_refresh_ui(response):
        if request.path != "/" or not response.content_type.startswith("text/html"):
            return response
        try:
            html = response.get_data(as_text=True)
            if "mtde-emby-refresh-script" in html:
                return response
            html = html.replace("</head>", _REFRESH_CSS + "\n</head>", 1)
            html = html.replace("</body>", _REFRESH_HTML + _REFRESH_JS + "\n</body>", 1)
            response.set_data(html)
            response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            pass
        return response

    return app
