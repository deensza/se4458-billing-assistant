"""JWT authentication and authorization.

* Tokens are HS256 JWTs issued by POST /api/v1/auth/token.
* Claims: sub (username), role (SUBSCRIBER | ADMIN), subscriberNo, iss, iat, exp.
* The API Gateway validates signature + exp (Kong jwt plugin, keyed by the `iss` claim);
  the API validates the token again and performs authorization (role and account ownership).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .errors import ApiError
from .models import UserRole

bearer_scheme = HTTPBearer(auto_error=False, description="JWT from POST /api/v1/auth/token")


@dataclass(frozen=True)
class CurrentUser:
    username: str
    role: UserRole
    subscriber_no: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(username: str, role: UserRole, subscriber_no: str | None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role.value,
        "subscriberNo": subscriber_no,
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> CurrentUser:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "role", "iss", "exp"]},
        )
        role = UserRole(claims["role"])
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "TOKEN_EXPIRED", "Access token has expired.")
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise ApiError(401, "INVALID_TOKEN", "Access token is invalid.")
    return CurrentUser(username=claims["sub"], role=role, subscriber_no=claims.get("subscriberNo"))


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "AUTHENTICATION_REQUIRED", "A Bearer access token is required.")
    return decode_access_token(credentials.credentials)


def ensure_account_access(user: CurrentUser, subscriber_no: str) -> None:
    """A subscriber may only access their own account; admins may access any account."""
    if user.is_admin:
        return
    if user.subscriber_no != subscriber_no:
        raise ApiError(
            403,
            "FORBIDDEN",
            "You are not authorized to access another subscriber's account.",
        )
