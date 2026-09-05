from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()
bearer_scheme = HTTPBearer()


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    # Timezone-aware UTC. python-jose normalises `exp` with utctimetuple(),
    # which converts an aware datetime to UTC before encoding, so the emitted
    # NumericDate is byte-for-byte identical to the previous naive utcnow().
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Security(bearer_scheme)],
) -> str:
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )
    return user_id
