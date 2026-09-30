from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import auth, bots, models, chat, approvals, upload, settings as settings_router, connectors, audit, computers, threads, events, devices
from app.services.auth_service import auth_service
from app.services.computer_provider import computer_provider
from app.services.device_service import device_may_access, device_service, format_code, normalize_code
from app.services.host_info import device_label
from app.services.storage_service import storage_service

app = FastAPI(
    title="Open Dots API",
    description="Open-source alternative to OpenAI Dots: self-hosted AI workspace API with a configurable inference adapter",
    version="1.0.0"
)

PUBLIC_API_PATHS = {
    "/api/v1/health",
    "/api/v1/auth/status",
    "/api/v1/auth/session",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/devices/pair",
}

# The phone app renders model output; keep it to its own scripts and styles.
MOBILE_HEADERS = {
    "Cache-Control": "no-cache",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob: https:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; font-src 'self'; manifest-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/v1") and request.method != "OPTIONS":
        origin = request.headers.get("origin")
        allowed_origins = {*settings.CORS_ORIGINS, str(request.base_url).rstrip("/")}
        if settings.PUBLIC_URL:
            allowed_origins.add(settings.PUBLIC_URL)
        # CORS alone does not stop credentialed requests from changing state.
        if (origin and origin not in allowed_origins) or (
            not origin and request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}
        ):
            return JSONResponse({"detail": "Untrusted request origin."}, status_code=403)
    if (
        request.method == "OPTIONS"
        or not path.startswith("/api/v1")
        or path in PUBLIC_API_PATHS
    ):
        response = await call_next(request)
        if path.startswith("/api/v1/auth/"):
            response.headers["Cache-Control"] = "no-store"
        if path == "/m" or path.startswith("/m/"):
            response.headers.update(MOBILE_HEADERS)
        return response

    user = auth_service.authenticate_request(request)
    if user:
        request.state.client = {"kind": "owner", "name": device_label()}
    elif device := device_service.authenticate_request(request):
        # Linked phones continue conversations; everything else stays on the computer.
        if not device_may_access(request.method, path):
            return JSONResponse(
                {"detail": "Linked devices can't do this. Use Open Dots on your computer."},
                status_code=403,
            )
        user = auth_service.user
        request.state.client = {"kind": "device", "name": device["name"], "device": device}
    if not user:
        return JSONResponse(
            {"detail": "Authentication is required."},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )
    request.state.user = user
    return await call_next(request)

# Wrap authentication so allowed browser clients can read 401 responses.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(bots.router)
app.include_router(models.router)
app.include_router(chat.router)
app.include_router(threads.router)
app.include_router(events.router)
app.include_router(devices.router)
app.include_router(upload.router)
app.include_router(approvals.router)
app.include_router(settings_router.router)
app.include_router(connectors.router)
app.include_router(audit.router)
app.include_router(computers.router)


@app.get("/api/v1/health")
async def health_check():
    return {
        "status": "online",
        "service": "Open Dots FastAPI Backend",
        "provider": "configured inference endpoint",
        "computer_provider": computer_provider.provider_name,
        "computer_kind": device_label(),
        "default_model": storage_service.get_settings().get("default_model") or settings.DEFAULT_MODEL
    }


# ----- Open Dots on iPhone ---------------------------------------------------
# The phone app is served by this computer, so it shares an origin with the
# API and needs no cloud service. A pairing code in the link survives "Add to
# Home Screen" through the page URL and the manifest start_url.

def _pair_code(request: Request) -> Optional[str]:
    code = normalize_code(request.query_params.get("pair", ""))
    return format_code(code) if code else None


def _with_pair(url: str, request: Request) -> str:
    code = _pair_code(request)
    return f"{url}?pair={code}" if code else url


@app.get("/", include_in_schema=False)
@app.get("/m", include_in_schema=False)
async def mobile_redirect(request: Request):
    return RedirectResponse(_with_pair("/m/", request))


@app.get("/m/", include_in_schema=False)
@app.get("/m/index.html", include_in_schema=False)
async def mobile_app(request: Request):
    try:
        page = (settings.MOBILE_DIR / "index.html").read_text(encoding="utf-8")
    except OSError:
        return JSONResponse({"detail": "The phone app is not installed."}, status_code=404)
    return HTMLResponse(page.replace("{{MANIFEST_HREF}}", _with_pair("/m/manifest.webmanifest", request)))


@app.get("/m/manifest.webmanifest", include_in_schema=False)
async def mobile_manifest(request: Request):
    return JSONResponse(
        {
            "name": "Open Dots",
            "short_name": "Open Dots",
            "description": "Continue your Open Dots conversations from your computer.",
            "start_url": _with_pair("/m/", request),
            "scope": "/m/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#09090b",
            "theme_color": "#09090b",
            "icons": [
                {"src": "/m/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/m/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
                {"src": "/m/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
        },
        media_type="application/manifest+json",
    )


app.mount("/m", StaticFiles(directory=settings.MOBILE_DIR, check_dir=False), name="mobile")
