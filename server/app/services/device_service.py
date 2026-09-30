"""Linked devices: a phone that continues this computer's conversations.

Linking uses a short-lived, one-time code shown on the computer (scanned as a
QR code or typed). Redeeming it gives the phone its own durable, revocable
credential, stored here only as a hash. A linked device can read and continue
conversations, start new ones, and answer approvals; it cannot change
settings or credentials, manage assistants, or link other devices.
"""

import hashlib
import json
import re
import secrets
import uuid
from time import monotonic
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Request, Response

from app.config import settings
from app.services.database import Database
from app.services.host_info import device_label
from app.services.storage_service import local_now, storage_service


CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I
CODE_LENGTH = 8
MAX_ACTIVE_CODES = 5
MAX_FAILED_ATTEMPTS = 10
LAST_SEEN_WRITE_INTERVAL = 300
DEVICE_COOKIE = "open_dots_device"
DEVICE_TOKEN_PREFIX = "odd_"

_DEVICE_ROUTES = [
    (method, re.compile(pattern))
    for method, pattern in (
        ("GET", r"/api/v1/bots"),
        ("GET", r"/api/v1/models"),
        ("GET", r"/api/v1/threads"),
        ("POST", r"/api/v1/threads"),
        ("GET", r"/api/v1/threads/[^/]+"),
        ("PATCH", r"/api/v1/threads/[^/]+"),
        ("POST", r"/api/v1/threads/[^/]+/messages"),
        ("GET", r"/api/v1/events"),
        ("POST", r"/api/v1/approvals/respond"),
        ("POST", r"/api/v1/upload"),
        ("GET", r"/api/v1/devices/current"),
        ("DELETE", r"/api/v1/devices/current"),
    )
]


class PairingError(Exception):
    pass


def device_may_access(method: str, path: str) -> bool:
    return any(method == allowed and pattern.fullmatch(path) for allowed, pattern in _DEVICE_ROUTES)


def normalize_code(code: str) -> Optional[str]:
    cleaned = re.sub(r"[\s-]", "", str(code or "")).upper()
    if len(cleaned) != CODE_LENGTH or any(char not in CODE_ALPHABET for char in cleaned):
        return None
    return cleaned


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def device_name_from_user_agent(user_agent: str) -> str:
    for marker, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android phone")):
        if marker in (user_agent or ""):
            return name
    return "Phone"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def client_label(request: Request) -> str:
    """Where a request came from, as shown next to messages ("iPhone", "Mac")."""
    client = getattr(request.state, "client", None) or {}
    return client.get("name") or device_label()


class DeviceService:
    def __init__(self, database: Database, owner_id: str = storage_service.owner_id):
        self.database = database
        self.owner_id = owner_id
        self._codes: Dict[str, float] = {}
        self._failures = 0
        self._last_seen_writes: Dict[str, float] = {}

    # ----- one-time linking codes -------------------------------------------

    def create_pairing_code(self) -> Dict[str, Any]:
        now = monotonic()
        self._codes = {digest: expiry for digest, expiry in self._codes.items() if expiry > now}
        while len(self._codes) >= MAX_ACTIVE_CODES:
            self._codes.pop(next(iter(self._codes)))
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        self._codes[_digest(code)] = now + settings.PAIRING_CODE_TTL_SECONDS
        self._failures = 0
        return {"code": format_code(code), "expires_in": settings.PAIRING_CODE_TTL_SECONDS}

    def redeem(self, code: str, user_agent: str = "") -> Tuple[Dict[str, Any], str]:
        normalized = normalize_code(code)
        expiry = self._codes.pop(_digest(normalized), None) if normalized else None
        if expiry is None or expiry <= monotonic():
            self._failures += 1
            if self._failures >= MAX_FAILED_ATTEMPTS:
                # Too many guesses: void every outstanding code.
                self._codes.clear()
            raise PairingError("That code isn't valid anymore. Show a new one on your computer.")

        token = DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(32)
        now = local_now()
        device = {
            "id": f"dev-{uuid.uuid4().hex[:10]}",
            "name": device_name_from_user_agent(user_agent),
            "created_at": now,
            "last_seen_at": now,
        }
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO devices(id, owner_id, token_hash, payload) VALUES (?, ?, ?, ?)",
                (device["id"], self.owner_id, _digest(token), json.dumps(device)),
            )
        return device, token

    # ----- device credentials -----------------------------------------------

    def authenticate(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        if not token or not token.startswith(DEVICE_TOKEN_PREFIX) or len(token) > 128:
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM devices WHERE owner_id = ? AND token_hash = ?",
                (self.owner_id, _digest(token)),
            ).fetchone()
        if not row:
            return None
        device = json.loads(row[0])
        now = monotonic()
        if now - self._last_seen_writes.get(device["id"], -LAST_SEEN_WRITE_INTERVAL) >= LAST_SEEN_WRITE_INTERVAL:
            self._last_seen_writes[device["id"]] = now
            device["last_seen_at"] = local_now()
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE devices SET payload = ? WHERE owner_id = ? AND id = ?",
                    (json.dumps(device), self.owner_id, device["id"]),
                )
        return device

    def authenticate_request(self, request: Request) -> Optional[Dict[str, Any]]:
        scheme, _, bearer = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and bearer.strip().startswith(DEVICE_TOKEN_PREFIX):
            return self.authenticate(bearer.strip())
        return self.authenticate(request.cookies.get(DEVICE_COOKIE))

    def list_devices(self) -> List[Dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM devices WHERE owner_id = ? ORDER BY rowid", (self.owner_id,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def revoke(self, device_id: str) -> bool:
        with self.database.connect() as connection:
            deleted = connection.execute(
                "DELETE FROM devices WHERE owner_id = ? AND id = ?", (self.owner_id, device_id)
            ).rowcount
        self._last_seen_writes.pop(device_id, None)
        return bool(deleted)

    @staticmethod
    def set_cookie(response: Response, token: str, *, secure: bool) -> None:
        response.set_cookie(
            DEVICE_COOKIE,
            token,
            max_age=settings.DEVICE_SESSION_MAX_AGE,
            httponly=True,
            secure=settings.AUTH_COOKIE_SECURE or secure,
            samesite="lax",
        )

    @staticmethod
    def clear_cookie(response: Response) -> None:
        response.delete_cookie(DEVICE_COOKIE, httponly=True, samesite="lax")


device_service = DeviceService(storage_service.database)
