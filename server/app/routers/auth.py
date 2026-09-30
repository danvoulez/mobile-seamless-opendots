from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.services.auth_service import SIGNIN_CODE_TTL_SECONDS, auth_service, SESSION_COOKIE


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)


class SignInRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)


def _authentication_error() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Authentication is required.",
        headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
    )


def _session_payload():
    return {
        "authenticated": True,
        "user": auth_service.user,
    }


@router.get("/status")
async def auth_status(request: Request):
    user = auth_service.authenticate_request(request)
    return {
        "auth_required": True,
        "authenticated": bool(user),
        "bootstrap_available": auth_service.can_bootstrap(request),
        "user": user,
    }


@router.get("/session")
async def establish_session(request: Request, response: Response):
    user = auth_service.authenticate_request(request)
    if not user:
        raise _authentication_error()
    if not auth_service.authenticate_session(request.cookies.get(SESSION_COOKIE)):
        auth_service.set_session_cookie(response, secure=request.url.scheme == "https")
    return _session_payload()


@router.post("/login")
async def login(credentials: LoginRequest, request: Request, response: Response):
    if not auth_service.authenticate_token(credentials.token):
        raise _authentication_error()
    auth_service.set_session_cookie(response, request.cookies.get(SESSION_COOKIE), secure=request.url.scheme == "https")
    return _session_payload()


@router.post("/signin-links")
async def create_signin_link(request: Request):
    """A link that opens the web client already signed in, once, for ten
    minutes. The installer and ``start-mac.sh --sign-in`` use it (with the
    owner token) so nobody has to copy the token by hand."""
    if getattr(request.state, "client", {}).get("kind") != "owner":
        raise HTTPException(status_code=403, detail="Only this computer can do that.")
    code = auth_service.create_signin_code()
    return {"url": f"{settings.WEB_URL}/?signin={code}", "expires_in": SIGNIN_CODE_TTL_SECONDS}


@router.post("/signin")
async def sign_in_with_code(body: SignInRequest, request: Request, response: Response):
    if not auth_service.redeem_signin_code(body.code):
        raise HTTPException(
            status_code=401,
            detail="This sign-in link has expired or was already used.",
            headers={"Cache-Control": "no-store"},
        )
    auth_service.set_session_cookie(response, request.cookies.get(SESSION_COOKIE), secure=request.url.scheme == "https")
    return _session_payload()


@router.post("/logout")
async def logout(request: Request, response: Response):
    auth_service.revoke_session(request.cookies.get(SESSION_COOKIE))
    auth_service.clear_session_cookie(response)
    return {"authenticated": False}
