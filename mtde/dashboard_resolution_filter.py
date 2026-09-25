from __future__ import annotations

from flask import jsonify


DISPLAY_RESOLUTIONS = ("2160p", "1440p", "1080p", "720p", "480p", "360p")


def _filter_resolution_counts(raw) -> dict[str, int]:
    source = raw if isinstance(raw, dict) else {}
    result: dict[str, int] = {}
    for key in DISPLAY_RESOLUTIONS:
        try:
            result[key] = max(0, int(source.get(key, 0) or 0))
        except (TypeError, ValueError):
            result[key] = 0
    return result


def install_dashboard_resolution_filter() -> None:
    """Keep the dashboard resolution card focused on the six useful tiers.

    The underlying cached trailer height remains untouched. This only filters
    the dashboard breakdown response, so matching, downloads, upgrades and the
    Movies/TV library item resolution values keep their exact ffprobe height.
    """
    from . import web as web_module

    if getattr(web_module, "_mtde_dashboard_resolution_filter_installed", False):
        return

    original_create_app = web_module.create_app

    def create_app_filtered(service):
        app = original_create_app(service)
        original_breakdowns = app.view_functions.get("dashboard_breakdowns")
        if original_breakdowns is not None:
            def dashboard_breakdowns_filtered():
                response = app.make_response(original_breakdowns())
                data = response.get_json(silent=True)
                if response.status_code < 400 and isinstance(data, dict):
                    data["resolution"] = _filter_resolution_counts(data.get("resolution"))
                    data["resolution_plexpass"] = _filter_resolution_counts(data.get("resolution_plexpass"))
                    return jsonify(data)
                return response

            app.view_functions["dashboard_breakdowns"] = dashboard_breakdowns_filtered
        return app

    web_module.create_app = create_app_filtered
    web_module._mtde_dashboard_resolution_filter_installed = True
