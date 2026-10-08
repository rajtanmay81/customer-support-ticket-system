from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app import schemas
from app.auth import hash_password
from app.models import User, UserRole

router = APIRouter(prefix="/admin/users", tags=["admin"])


@router.get("", response_model=List[schemas.UserOut])
def list_users(db: Session = Depends(get_db), _=Depends(require_admin)):
    return db.query(User).order_by(User.created_at).all()


@router.post("", response_model=schemas.UserOut)
def create_staff_user(
    payload: schemas.AdminUserCreate,
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=schemas.UserOut)
def update_staff_user(
    user_id: int,
    payload: schemas.AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role == UserRole.customer:
        raise HTTPException(status_code=400, detail="Cannot modify customer accounts via user management")

    is_self = target.id == current_user.id
    demoting_self = is_self and payload.role is not None and payload.role != UserRole.admin
    deactivating_self = is_self and payload.is_active is False
    if demoting_self or deactivating_self:
        raise HTTPException(status_code=400, detail="You cannot deactivate or demote your own account")

    if payload.role is not None:
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active

    db.commit()
    db.refresh(target)
    return target
