from fastapi import Header, HTTPException


def get_current_user(authorization: str = Header(...)) -> str:
    """Very small auth helper.

    The specification calls for JWT verification. For the purposes of this
    reference implementation we treat the bearer token as the user identifier.
    """
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="invalid_token")
    user_id = authorization[len(prefix) :].strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_token")
    return user_id
