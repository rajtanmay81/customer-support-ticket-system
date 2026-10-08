import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models import PasswordResetToken, User


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_reset_token(db: Session, user: User) -> str:
    now = datetime.utcnow()
    outstanding = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > now,
    ).all()
    for t in outstanding:
        t.used_at = now

    raw_token = secrets.token_urlsafe(32)
    token = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash(raw_token),
        expires_at=now + timedelta(minutes=settings.password_reset_token_ttl_minutes),
    )
    db.add(token)
    db.commit()
    return raw_token


def validate_and_consume_token(db: Session, raw_token: str) -> User | None:
    now = datetime.utcnow()
    token = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == _hash(raw_token)).first()
    if token is None or token.used_at is not None or token.expires_at <= now:
        return None
    token.used_at = now

    others = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == token.user_id,
        PasswordResetToken.id != token.id,
        PasswordResetToken.used_at.is_(None),
    ).all()
    for t in others:
        t.used_at = now

    db.commit()
    return token.user
