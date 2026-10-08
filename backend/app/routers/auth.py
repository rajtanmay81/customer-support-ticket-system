from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_staff
from app import schemas
from app.auth import hash_password, verify_password, create_access_token
from app.models import User, UserRole
from app.services import password_reset_service
from app.ws_manager import manager

router = APIRouter(prefix="/auth", tags=["auth"])

# Seed-time (name -> known plaintext password) for the one-tap demo logins on
# the login screen. Passwords can't be recovered from the DB (only the bcrypt
# hash is stored), so this stays a constant; email/role are looked up live so
# editing a demo user's row in the DB is reflected here on next page load.
DEMO_LOGINS = [
    ("Peter", "admin123", "a1", "P"),
    ("Mark", "agent123", "a2", "M"),
    ("Brock", "brock123", "a3", "B"),
    ("Bella", "bella123", "a5", "BE"),
    ("Emma", "emma123", "a2", "E"),
]


@router.post("/register", response_model=schemas.Token)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=UserRole.customer,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    return schemas.Token(access_token=token, user=schemas.UserOut.model_validate(user))


@router.post("/login", response_model=schemas.Token)
def login(payload: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account has been deactivated")

    token = create_access_token({"sub": str(user.id)})
    return schemas.Token(access_token=token, user=schemas.UserOut.model_validate(user))


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me/availability", response_model=schemas.UserOut)
def update_my_availability(
    payload: schemas.AvailabilityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    current_user.availability = payload.availability
    db.commit()
    db.refresh(current_user)

    manager.broadcast(
        {
            "type": "agent.availability_changed",
            "data": {"agent_id": current_user.id, "agent_name": current_user.name, "availability": current_user.availability.value},
        },
        also_admin=True,
    )
    return current_user


@router.post("/forgot-password", response_model=schemas.MessageOut)
def forgot_password(payload: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user and user.is_active:
        raw_token = password_reset_service.create_reset_token(db, user)
        print(
            f"[DEV EMAIL STAND-IN] Password reset link for {user.email}: "
            f"http://localhost:5173/reset-password?token={raw_token}"
        )
    return schemas.MessageOut(message="If that email is registered, a password reset link has been sent.")


@router.post("/reset-password", response_model=schemas.MessageOut)
def reset_password(payload: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    user = password_reset_service.validate_and_consume_token(db, payload.token)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return schemas.MessageOut(message="Password has been reset. You can now log in.")


@router.get("/demo-accounts", response_model=List[schemas.DemoAccountOut])
def demo_accounts(db: Session = Depends(get_db)):
    result = []
    for name, password, avatar_class, initials in DEMO_LOGINS:
        user = db.query(User).filter(User.name == name).first()
        if user and user.is_active:
            result.append(
                schemas.DemoAccountOut(
                    name=user.name,
                    role=user.role.value.capitalize(),
                    email=user.email,
                    password=password,
                    avatar_class=avatar_class,
                    initials=initials,
                )
            )
    return result
