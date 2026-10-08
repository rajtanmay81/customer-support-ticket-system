from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session

from app.auth import decode_access_token
from app.database import get_db
from app.models import User, UserRole
from app.services.ticket_access import assert_can_view, get_ticket_or_404
from app.ws_manager import manager

router = APIRouter(tags=["websockets"])


def _authenticate(token: str, db: Session) -> Optional[User]:
    payload = decode_access_token(token)
    if payload is None:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None or not user.is_active:
        return None
    return user


@router.websocket("/ws/tickets/{ticket_id}")
async def ticket_socket(
    websocket: WebSocket,
    ticket_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    user = _authenticate(token, db)
    if user is None:
        await websocket.close(code=4401)
        return

    try:
        ticket = get_ticket_or_404(db, ticket_id)
        assert_can_view(ticket, user)
    except HTTPException:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    await manager.join_ticket(ticket_id, websocket, user.role)
    try:
        while True:
            await websocket.receive_text()  # no inbound protocol yet — connection is receive-only from the client
    except WebSocketDisconnect:
        pass
    finally:
        manager.leave_ticket(ticket_id, websocket)


@router.websocket("/ws/admin")
async def admin_socket(
    websocket: WebSocket,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    user = _authenticate(token, db)
    if user is None or user.role != UserRole.admin:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    await manager.join_admin(websocket, user.role)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.leave_admin(websocket)
