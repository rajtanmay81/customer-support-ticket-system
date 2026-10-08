import asyncio
from typing import Dict, Optional, Set

from fastapi import WebSocket

from app.models import UserRole


class ConnectionManager:
    """In-memory WebSocket registry (single-process — fine for this POC).

    Tracks, per ticket id, the connected sockets (with each viewer's role, so
    internal-note broadcasts can be kept away from customer sockets), plus a
    separate "admin room" of admins watching every ticket at once.
    """

    def __init__(self):
        self.ticket_rooms: Dict[int, Dict[WebSocket, UserRole]] = {}
        self.admin_room: Dict[WebSocket, UserRole] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def join_ticket(self, ticket_id: int, websocket: WebSocket, role: UserRole) -> None:
        self.ticket_rooms.setdefault(ticket_id, {})[websocket] = role

    def leave_ticket(self, ticket_id: int, websocket: WebSocket) -> None:
        room = self.ticket_rooms.get(ticket_id)
        if room:
            room.pop(websocket, None)
            if not room:
                self.ticket_rooms.pop(ticket_id, None)

    async def join_admin(self, websocket: WebSocket, role: UserRole) -> None:
        self.admin_room[websocket] = role

    def leave_admin(self, websocket: WebSocket) -> None:
        self.admin_room.pop(websocket, None)

    async def _send_all(self, recipients: Dict[WebSocket, UserRole], message: dict, staff_only: bool) -> None:
        dead = []
        for websocket, role in list(recipients.items()):
            if staff_only and role not in (UserRole.agent, UserRole.admin):
                continue
            try:
                await websocket.send_json(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            recipients.pop(websocket, None)

    async def _broadcast_async(
        self, message: dict, ticket_id: Optional[int], also_admin: bool, staff_only: bool
    ) -> None:
        if ticket_id is not None:
            room = self.ticket_rooms.get(ticket_id, {})
            await self._send_all(room, message, staff_only)
        if also_admin:
            await self._send_all(self.admin_room, message, staff_only)

    def broadcast(
        self, message: dict, ticket_id: Optional[int] = None, also_admin: bool = True, staff_only: bool = False
    ) -> None:
        """Thread-safe entry point for sync (non-async) route handlers."""
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._broadcast_async(message, ticket_id, also_admin, staff_only), self._loop
        )


manager = ConnectionManager()
