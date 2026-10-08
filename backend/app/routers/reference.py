from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_staff
from app import schemas
from app.models import Category, Priority, User, UserRole
from app.services.assignment_service import compute_agent_load

router = APIRouter(tags=["reference"])


@router.get("/categories", response_model=List[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(Category).order_by(Category.name).all()


@router.get("/priorities", response_model=List[schemas.PriorityOut])
def list_priorities(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(Priority).order_by(Priority.level).all()


@router.get("/agents", response_model=List[schemas.AgentOut])
def list_agents(db: Session = Depends(get_db), _=Depends(require_staff)):
    agents = (
        db.query(User)
        .filter(User.role.in_([UserRole.agent, UserRole.admin]), User.is_active.is_(True))
        .all()
    )
    return [
        schemas.AgentOut(
            **schemas.UserOut.model_validate(agent).model_dump(),
            active_ticket_count=compute_agent_load(db, agent.id),
        )
        for agent in agents
    ]
