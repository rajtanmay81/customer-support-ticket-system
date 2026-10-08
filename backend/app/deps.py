from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import decode_access_token
from app.models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account has been deactivated")
    return user


def require_staff(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.agent, UserRole.admin):
        raise HTTPException(status_code=403, detail="Agent or admin access required")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
