"""Authentication primitives for the single-owner local deployment."""

import hashlib
import json
import os
import secrets
from time import time
from pathlib import Path
from typing import Dict, Optional

from fastapi import Request, Response

from app.config import settings


LOCAL_USER_ID = "local-user"
LOCAL_USERNAME = "local"
SESSION_COOKIE = "open_dots_session"
SIGNIN_CODE_TTL_SECONDS = 600


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthService:
    """Exchange an explicit owner credential for a revocable browser session.

    Peer addresses are not identity: container gateways and reverse proxies can
    make untrusted clients appear to originate from loopback. Session tokens are
    separate random values. Only their hashes are kept, on disk, so a restart
    (for example to install an update) doesn't sign the browser out.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = (data_dir or settings.DATA_DIR).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.token_path = self.data_dir / ".auth-token"
        self.configured_token = os.getenv("APP_AUTH_TOKEN", "").strip()
        self.token = self.configured_token or self._load_or_create_token()
        self.sessions_path = self.data_dir / ".auth-sessions.json"
        self._sessions: Dict[str, float] = self._load_sessions()
        # One-time codes that open the web client already signed in.
        self._signin_codes: Dict[str, float] = {}

    @property
    def user(self) -> Dict[str, str]:
        return {"id": LOCAL_USER_ID, "username": LOCAL_USERNAME, "role": "owner"}

    def _load_or_create_token(self) -> str:
        if self.token_path.exists():
            existing = self.token_path.read_text(encoding="utf-8").strip()
            if existing:
                os.chmod(self.token_path, 0o600)
                return existing

        token = secrets.token_urlsafe(32)
        self.token_path.write_text(token + "\n", encoding="utf-8")
        os.chmod(self.token_path, 0o600)
        return token

    def _load_sessions(self) -> Dict[str, float]:
        try:
            stored = json.loads(self.sessions_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(stored, dict):
            return {}
        now = time()
        return {
            key: float(expiry)
            for key, expiry in stored.items()
            if isinstance(key, str) and isinstance(expiry, (int, float)) and expiry > now
        }

    def _save_sessions(self) -> None:
        temporary = self.sessions_path.with_name(self.sessions_path.name + ".tmp")
        try:
            temporary.write_text(json.dumps(self._sessions), encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.sessions_path)
        except OSError:
            pass  # sessions still work until the next restart

    def authenticate_token(self, token: Optional[str]) -> bool:
        return bool(token) and secrets.compare_digest(token.encode("utf-8"), self.token.encode("utf-8"))

    def authenticate_session(self, token: Optional[str]) -> bool:
        if not token or len(token) > 128:
            return False
        digest = _digest(token)
        expires = self._sessions.get(digest)
        if expires is None:
            return False
        if time() >= expires:
            self._sessions.pop(digest, None)
            self._save_sessions()
            return False
        return True

    def authenticate_request(self, request: Request) -> Optional[Dict[str, str]]:
        authorization = request.headers.get("authorization", "")
        scheme, _, bearer = authorization.partition(" ")
        if scheme.lower() == "bearer" and self.authenticate_token(bearer.strip()):
            return self.user

        if self.authenticate_session(request.cookies.get(SESSION_COOKIE)):
            return self.user
        return None

    def can_bootstrap(self, request: Request) -> bool:
        # Retained for the status API's bootstrap_available field. Opening the
        # web client signed in takes a one-time code minted with the owner
        # token (see create_signin_code), never the caller's address.
        return False

    def create_signin_code(self) -> str:
        now = time()
        self._signin_codes = {key: expiry for key, expiry in self._signin_codes.items() if expiry > now}
        while len(self._signin_codes) >= 16:
            self._signin_codes.pop(next(iter(self._signin_codes)))
        code = secrets.token_urlsafe(24)
        self._signin_codes[_digest(code)] = now + SIGNIN_CODE_TTL_SECONDS
        return code

    def redeem_signin_code(self, code: Optional[str]) -> bool:
        if not code or len(code) > 128:
            return False
        expires = self._signin_codes.pop(_digest(code), None)
        return expires is not None and time() < expires

    def set_session_cookie(self, response: Response, previous_token: Optional[str] = None, *, secure: bool = False) -> None:
        self.revoke_session(previous_token, save=False)
        now = time()
        self._sessions = {key: expiry for key, expiry in self._sessions.items() if expiry > now}
        while len(self._sessions) >= 128:
            self._sessions.pop(next(iter(self._sessions)))
        session_token = secrets.token_urlsafe(32)
        self._sessions[_digest(session_token)] = now + settings.AUTH_SESSION_MAX_AGE
        self._save_sessions()
        response.set_cookie(
            SESSION_COOKIE,
            session_token,
            max_age=settings.AUTH_SESSION_MAX_AGE,
            httponly=True,
            secure=settings.AUTH_COOKIE_SECURE or secure,
            samesite="lax",
        )

    def revoke_session(self, token: Optional[str], save: bool = True) -> None:
        if token and self._sessions.pop(_digest(token), None) is not None and save:
            self._save_sessions()

    @staticmethod
    def clear_session_cookie(response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax")


auth_service = AuthService()
