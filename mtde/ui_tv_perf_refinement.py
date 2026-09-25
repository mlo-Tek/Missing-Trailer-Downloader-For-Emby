from __future__ import annotations

import time


def install_ui_tv_performance_refinement() -> None:
    from .ui_tv_perf import _UICache, _UI_CACHE_TTL_SECONDS

    if getattr(_UICache, "_mtde_empty_cache_refinement_installed", False):
        return

    def snapshot(self, kind: str, force: bool = False):
        now = time.time()
        with self.lock:
            items = list(self.items[kind])
            saved_at = float(self.saved_at[kind] or 0.0)
            age = now - saved_at if saved_at else float("inf")
            refreshing = self.refreshing[kind]
            error = self.errors[kind]

        # An empty cache can be a valid result (for example before any TV
        # libraries are configured). Only the never-built state should rebuild
        # immediately; a successfully-built empty snapshot obeys the normal TTL.
        if force or (not items and not saved_at) or age >= _UI_CACHE_TTL_SECONDS:
            self.request_refresh(kind)
            with self.lock:
                refreshing = self.refreshing[kind]
                error = self.errors[kind]
        return items, refreshing, error

    _UICache.snapshot = snapshot
    _UICache._mtde_empty_cache_refinement_installed = True
