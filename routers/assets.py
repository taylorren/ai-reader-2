"""Cache-busting versions for the stylesheets and scripts a page loads."""

from __future__ import annotations

from .app_state import BASE_DIR


def get_asset_version(*relative_paths: str) -> int:
    """A stable cache-busting token from the assets' modification times."""
    mtimes = []
    for relative_path in relative_paths:
        asset_path = BASE_DIR / relative_path
        if asset_path.exists():
            mtimes.append(asset_path.stat().st_mtime_ns)
    return max(mtimes, default=0)
