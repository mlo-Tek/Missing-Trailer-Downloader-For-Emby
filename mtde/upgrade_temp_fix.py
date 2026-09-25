from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
import re


_ALLOW_UPGRADE_TEMP: ContextVar[bool] = ContextVar("mtde_allow_upgrade_temp", default=False)
_FRAGMENT_RE = re.compile(r"\.f\d+\.[^.]+$", re.IGNORECASE)


def is_true_fragment_path(path: str | Path) -> bool:
    """Return True only for actual yt-dlp fragment/partial outputs.

    `.mtde-upgrade-*` files are intentionally used as temporary *complete* files
    while an upgrade is being validated. They must still stay hidden from local
    trailer discovery, but their prefix alone must not make a successful upgrade
    download look like an incomplete yt-dlp fragment.
    """
    name = Path(path).name
    lower = name.casefold()
    return (
        bool(_FRAGMENT_RE.search(name))
        or lower.endswith(".part")
        or lower.endswith(".ytdl")
        or ".part." in lower
    )


def is_intentional_upgrade_temp(path: str | Path, output_stem: str | Path) -> bool:
    """Return True for MTDE's own complete upgrade staging file only."""
    stem_name = Path(output_stem).name
    path_name = Path(path).name
    if not stem_name.startswith(".mtde-upgrade-"):
        return False
    if not (path_name == stem_name or path_name.startswith(stem_name + ".")):
        return False
    return not is_true_fragment_path(path)


def install_upgrade_temp_fix() -> None:
    """Fix 0.3.18 upgrade staging without weakening fragment protection.

    hardening.py intentionally marks `.mtde-upgrade-*` as non-library files so
    stale staging files never count as local trailers. Its download wrapper also
    used that same predicate, which caused every complete upgrade staging file to
    be rejected before service.py could probe and atomically replace the old
    trailer. This layer permits the prefix only during the exact download call
    whose requested output stem is MTDE's upgrade staging stem. Real `.fNNN`,
    `.part` and `.ytdl` outputs remain rejected.
    """
    from . import hardening
    from . import trailer as trailer_module

    if getattr(trailer_module, "_mtde_upgrade_temp_fix_installed", False):
        return

    original_partial_check = hardening.is_partial_output_path
    original_download = trailer_module.TrailerDownloader.download

    def contextual_partial_check(path: str | Path) -> bool:
        value = Path(path)
        if (
            _ALLOW_UPGRADE_TEMP.get()
            and value.name.startswith(".mtde-upgrade-")
            and not is_true_fragment_path(value)
        ):
            return False
        return original_partial_check(value)

    def download_with_upgrade_temp(self, candidate, output_stem, ignore_minimum=False):
        if Path(output_stem).name.startswith(".mtde-upgrade-"):
            token = _ALLOW_UPGRADE_TEMP.set(True)
            try:
                return original_download(
                    self,
                    candidate,
                    output_stem,
                    ignore_minimum=ignore_minimum,
                )
            finally:
                _ALLOW_UPGRADE_TEMP.reset(token)
        return original_download(
            self,
            candidate,
            output_stem,
            ignore_minimum=ignore_minimum,
        )

    # The existing hardening download wrapper resolves this module-global name
    # at call time, so the context-aware predicate is seen inside that wrapper.
    hardening.is_partial_output_path = contextual_partial_check
    trailer_module.TrailerDownloader.download = download_with_upgrade_temp
    trailer_module._mtde_upgrade_temp_fix_installed = True
