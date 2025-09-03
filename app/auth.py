from __future__ import annotations

import os
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status


bearer_scheme = HTTPBearer(auto_error=False)


class AuthSettings:
    def __init__(self) -> None:
        self.secret = os.getenv("JWT_SECRET", "dev-secret-change-me")
        self.algorithms = [alg.strip() for alg in os.getenv("JWT_ALGORITHMS", "HS256").split(",")]
        self.issuer = os.getenv("JWT_ISSUER")
        self.audience = os.getenv("JWT_AUDIENCE")


settings = AuthSettings()


class User:
    def __init__(self, user_id: str):
        self.id = user_id


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> User:
    if not creds or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = creds.credentials
    try:
        options = {"require": ["sub", "exp", "iat"]}
        decoded = jwt.decode(
            token,
            settings.secret,
            algorithms=settings.algorithms,
            audience=settings.audience,
            issuer=settings.issuer,
            options=options,
        )
        sub = decoded.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Invalid token: missing sub")
        return User(user_id=str(sub))
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
