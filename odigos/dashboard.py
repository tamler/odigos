from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DEFAULT_DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")


def mount_dashboard(app: FastAPI, dashboard_dir: str | None = None) -> None:
    dist = dashboard_dir or DEFAULT_DASHBOARD_DIR
    index_html = os.path.join(dist, "index.html")

    if not os.path.isfile(index_html):
        return

    # Mount static subdirectories
    for subdir in ("vendor", "css", "js", "lib", "components", "pages"):
        subdir_path = os.path.join(dist, subdir)
        if os.path.isdir(subdir_path):
            app.mount(f"/dashboard/{subdir}", StaticFiles(directory=subdir_path), name=f"dashboard_{subdir}")

    # Catch-all: serve index.html for SPA routing
    @app.get("/{path:path}")
    async def serve_spa(path: str):
        file_path = os.path.join(dist, path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(index_html)
