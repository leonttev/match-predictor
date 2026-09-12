"""Auth primitives for the backend (course requirement §2.4a: authorization,
authentication, and identity confirmation via 2FA).

Password hashing uses stdlib PBKDF2-HMAC (no compiled dependency) rather than
bcrypt/argon2 bindings, which is a deliberate tradeoff for a course project
running on a bleeding-edge Python where prebuilt wheels for those C-extension
libraries aren't always available yet; PBKDF2 with a high iteration count is
still an accepted password hash.
"""

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
import pyotp

from .config import settings

PBKDF2_ITERATIONS = 390_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(actual, expected)


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire, "scope": "full"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_pending_2fa_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.pending_2fa_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire, "scope": "pending_2fa"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="MatchPredictor")


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)
