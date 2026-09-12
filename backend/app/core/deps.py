from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError

from .security import decode_token

bearer_scheme = HTTPBearer()


async def require_full_auth(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """Validates a JWT issued after password + TOTP both succeeded and
    returns the authenticated username."""
    try:
        payload = decode_token(creds.credentials)
    except PyJWTError:
        raise HTTPException(401, "invalid or expired token")

    if payload.get("scope") != "full":
        raise HTTPException(401, "2FA verification required")

    return payload["sub"]
