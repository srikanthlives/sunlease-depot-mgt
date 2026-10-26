import os
import sys
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.migrate import migrate
from app.routers import auth, masters, org, reports, rosters, scans, schedules, trip_sheets

try:
    print(f"[STARTUP] Database: {settings.DATABASE_URL}")
    migrate(verbose=True)
except Exception as e:  # noqa: BLE001
    print(f"[ERROR] Migration failed: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

app = FastAPI(title=settings.APP_NAME, version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(masters.router)
app.include_router(org.router)
app.include_router(schedules.router)
app.include_router(reports.router)
app.include_router(rosters.router)
app.include_router(scans.router)      # before trip_sheets: /trip-sheets/scans is not a sheet id
app.include_router(trip_sheets.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}


_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend_dist")
if os.path.isdir(_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist, "assets")), name="frontend-assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        candidate = os.path.join(_dist, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_dist, "index.html"))
