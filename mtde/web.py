from __future__ import annotations

from datetime import datetime
import threading

from flask import Flask, jsonify, render_template, request

from .service import MTDE


def create_app(service: MTDE) -> Flask:
    app = Flask(__name__)
    state = {"running": False, "last_run": None, "results": []}
    lock = threading.Lock()

    def run_scan(download: bool):
        with lock:
            if state["running"]:
                return
            state["running"] = True
        try:
            results = service.scan(download=download)
            state["results"] = service.serialize(results)
            state["last_run"] = datetime.now().isoformat(timespec="seconds")
        finally:
            state["running"] = False

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/status")
    def status():
        return jsonify(state)

    @app.get("/api/server")
    def server():
        try:
            info = service.test_connection()
            return jsonify({"ok": True, "name": info.get("ServerName"), "version": info.get("Version")})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.post("/api/scan")
    def scan():
        download = request.args.get("download", "true").lower() not in {"0", "false", "no"}
        if state["running"]:
            return jsonify({"ok": False, "error": "scan already running"}), 409
        threading.Thread(target=run_scan, args=(download,), daemon=True).start()
        return jsonify({"ok": True, "download": download}), 202

    return app
