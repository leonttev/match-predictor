"""Authentication, authorization, and 2FA (course requirement §2.4a)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core import security
from ..core.deps import require_full_auth
from ..network.db_client import db_client

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    status: str  # "2fa_required" | "ok"
    token: str


class TwoFactorSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class TwoFactorVerifyRequest(BaseModel):
    code: str


class TwoFactorLoginRequest(BaseModel):
    pending_token: str
    code: str


@router.post("/register")
async def register(req: RegisterRequest):
    existing = await db_client.get_user_by_username(req.username)
    if existing:
        raise HTTPException(409, "username already taken")

    user = await db_client.create_user(
        username=req.username,
        email=req.email,
        hashed_password=security.hash_password(req.password),
    )
    return {"id": user["id"], "username": user["username"]}


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    user = await db_client.get_user_by_username(req.username)
    if not user or not security.verify_password(req.password, user["hashed_password"]):
        raise HTTPException(401, "invalid credentials")

    if user["totp_enabled"]:
        return LoginResponse(
            status="2fa_required", token=security.create_pending_2fa_token(req.username)
        )

    return LoginResponse(status="ok", token=security.create_access_token(req.username))


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(username: str = Depends(require_full_auth)):
    """Generates (but does not yet activate) a TOTP secret for the logged-in user."""
    user = await db_client.get_user_by_username(username)
    if not user:
        # A structurally valid JWT doesn't guarantee the user it names still
        # exists (deleted account, or — in dev — a DB reset since the token
        # was issued). Fail cleanly instead of crashing on user["id"] below.
        raise HTTPException(401, "user no longer exists — please log in again")
    secret = security.new_totp_secret()
    await db_client.update_user_totp(user["id"], totp_secret=secret, totp_enabled=False)
    return TwoFactorSetupResponse(
        secret=secret, provisioning_uri=security.totp_provisioning_uri(secret, username)
    )


@router.post("/2fa/enable")
async def enable_2fa(req: TwoFactorVerifyRequest, username: str = Depends(require_full_auth)):
    """Confirms the user can produce a valid code before turning 2FA on."""
    user = await db_client.get_user_by_username(username)
    if not user:
        raise HTTPException(401, "user no longer exists — please log in again")
    if not user["totp_secret"]:
        raise HTTPException(400, "call /auth/2fa/setup first")
    if not security.verify_totp(user["totp_secret"], req.code):
        raise HTTPException(400, "invalid code")

    await db_client.update_user_totp(user["id"], totp_enabled=True)
    return {"status": "enabled"}


@router.post("/2fa/login", response_model=LoginResponse)
async def login_2fa(req: TwoFactorLoginRequest):
    """Step 2 of login: exchanges a pending_2fa token + TOTP code for a full session token."""
    try:
        payload = security.decode_token(req.pending_token)
    except Exception:
        raise HTTPException(401, "invalid or expired pending token")

    if payload.get("scope") != "pending_2fa":
        raise HTTPException(401, "invalid token scope")

    username = payload["sub"]
    user = await db_client.get_user_by_username(username)
    if not user or not user["totp_enabled"] or not security.verify_totp(
        user["totp_secret"], req.code
    ):
        raise HTTPException(401, "invalid 2FA code")

    return LoginResponse(status="ok", token=security.create_access_token(username))
