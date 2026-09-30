"""Origin checks shared by HTTP requests and WebSocket connections."""

from starlette.requests import HTTPConnection

from app.config import settings


def own_origin(connection: HTTPConnection) -> str:
    """This server's origin as the client addressed it (tunnel names included)."""
    scheme = {"ws": "http", "wss": "https"}.get(connection.url.scheme, connection.url.scheme)
    host = connection.headers.get("host") or connection.url.netloc
    return f"{scheme}://{host}"


def origin_is_trusted(connection: HTTPConnection) -> bool:
    """Refuse browser traffic started by other sites.

    Cookies ride along on cross-site requests and WebSocket handshakes, so
    CORS alone does not stop another site from acting with them. Native apps
    send no Origin and authenticate with an explicit token instead.
    """
    allowed = {*settings.CORS_ORIGINS, own_origin(connection)}
    if settings.PUBLIC_URL:
        allowed.add(settings.PUBLIC_URL)
    origin = connection.headers.get("origin")
    if origin:
        return origin in allowed
    return connection.headers.get("sec-fetch-site") not in {"cross-site", "same-site"}
