"""Dashboard WebSocket notifications (Phase 7; FR-48, SEC-04).

A browser opens ``/api/ws`` after logging in. The handshake is authenticated with the same
HttpOnly session cookie as the REST API (the Vite dev proxy keeps the socket same-origin), so
an unauthenticated client is rejected and no notification is ever sent to it. Messages are
deliberately lightweight: identifiers, lifecycle status, and the deterministic message. The
browser re-reads authorized details (attributes, evidence bytes) through REST, which keeps
the WebSocket free of evidence contents and sensitive fields.

The server also reads from the socket purely to detect disconnects; clients are not expected
to send application messages.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.auth.dependencies import resolve_session
from app.config import get_settings
from app.db import get_db
from app.services.event_broadcaster import get_event_broadcaster

LOGGER = logging.getLogger("app.realtime")

router = APIRouter(tags=["realtime"])


async def _send_loop(websocket: WebSocket, queue: asyncio.Queue) -> None:
    while True:
        message = await queue.get()
        await websocket.send_json(message)


async def _receive_loop(websocket: WebSocket) -> None:
    # Application messages are ignored; receiving is how we notice a client disconnect.
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))


def _consume_result(task: asyncio.Task) -> None:
    """Retrieve a finished task's exception so it is never logged as unretrieved.

    Used as a done-callback on the send/receive tasks so their outcome is observed
    once they finish, without the handler having to ``await`` them.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None and not isinstance(exc, WebSocketDisconnect):
        LOGGER.debug("dashboard websocket task ended with %s", type(exc).__name__)


@router.websocket("/api/ws")
async def dashboard_socket(websocket: WebSocket, db: Session = Depends(get_db)) -> None:
    """Authenticated, server-push notification stream for the dashboard."""
    settings = get_settings()
    auth = resolve_session(db, websocket.cookies.get(settings.session_cookie_name))
    user = auth.user if auth is not None else None
    # The socket needs no further database access; release the pooled connection now.
    db.close()

    await websocket.accept()
    if user is None:
        await websocket.send_json({"type": "error", "detail": "Not authenticated"})
        await websocket.close(code=1008)
        return

    broadcaster = get_event_broadcaster()
    broadcaster.bind_loop(asyncio.get_running_loop())
    queue = broadcaster.subscribe()
    sender: asyncio.Task | None = None
    receiver: asyncio.Task | None = None
    try:
        await websocket.send_json(
            {"type": "ready", "user": {"id": user.id, "username": user.username}}
        )
        sender = asyncio.create_task(_send_loop(websocket, queue))
        receiver = asyncio.create_task(_receive_loop(websocket))
        await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.unsubscribe(queue)
        # Cleanup must not ``await``: the server can cancel this handler at any
        # suspension point, and awaiting a cancelled task here would let a spurious
        # ``CancelledError`` escape the ASGI application. The tasks are cancelled
        # instead and their outcome is retrieved by a done-callback.
        for task in (sender, receiver):
            if task is None:
                continue
            task.add_done_callback(_consume_result)
            if not task.done():
                task.cancel()
