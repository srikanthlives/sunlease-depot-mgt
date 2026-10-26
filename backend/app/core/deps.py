from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    exc = HTTPException(status.HTTP_401_UNAUTHORIZED, "Could not validate credentials",
                        headers={"WWW-Authenticate": "Bearer"})
    payload = decode_access_token(token)
    if payload is None or payload.get("sub") is None:
        raise exc
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise exc
    return user
