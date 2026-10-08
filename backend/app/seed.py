"""
One-time setup script: creates reference data (categories, priorities,
SLA policies) and a handful of demo users so the app is usable right away.

Run with: python -m app.seed
"""
from app.database import Base, engine, SessionLocal, ensure_pgvector_extension
from app.models import Category, Priority, SLAPolicy, User, UserRole
from app.auth import hash_password

CATEGORIES = ["technical_issue", "billing", "access_issue", "product_bug", "urgent_escalation"]

# (name, level, response_time_hours, resolution_time_hours)
PRIORITIES = [
    ("low", 1, 24, 120),
    ("medium", 2, 8, 48),
    ("high", 3, 4, 24),
    ("critical", 4, 1, 8),
]

DEMO_USERS = [
    ("Peter", "peter@gmail.com", "admin123", UserRole.admin),
    ("Mark", "mark@gmail.com", "agent123", UserRole.agent),
    ("Brock", "brock@gmail.com", "brock123", UserRole.agent),
    ("Emma", "emma@gmail.com", "emma123", UserRole.agent),
    ("Bella", "bella@gmail.com", "bella123", UserRole.agent),
]


def seed():
    ensure_pgvector_extension()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for name in CATEGORIES:
            if not db.query(Category).filter(Category.name == name).first():
                db.add(Category(name=name))

        for name, level, response_h, resolution_h in PRIORITIES:
            priority = db.query(Priority).filter(Priority.name == name).first()
            if not priority:
                priority = Priority(name=name, level=level)
                db.add(priority)
                db.flush()
            if not db.query(SLAPolicy).filter(SLAPolicy.priority_id == priority.id).first():
                db.add(
                    SLAPolicy(
                        priority_id=priority.id,
                        response_time_hours=response_h,
                        resolution_time_hours=resolution_h,
                    )
                )

        for name, email, password, role in DEMO_USERS:
            if not db.query(User).filter(User.email == email).first():
                db.add(User(name=name, email=email, hashed_password=hash_password(password), role=role))

        db.commit()
        print("Seed complete. Demo logins:")
        for name, email, password, role in DEMO_USERS:
            print(f"  {role.value:9s} -> {email} / {password}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
