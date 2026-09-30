"""One live stream per open client: the same events on the computer and the phone."""

import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.services.auth_service import auth_service
from app.services.event_bus import event_bus
from app.services.host_info import computer_name

router = APIRouter(prefix="/api/v1", tags=["events"])

HEARTBEAT_SECONDS = 15


@router.get("/events")
async def stream_events(request: Request):
    async def event_generator():
        # Subscribe before greeting: a client reloads its state on "hello", so
        # nothing published after that reload can be missed.
        subscription = event_bus.subscribe()
        try:
            # retry: how soon a browser tries again after the stream drops.
            yield {
                "event": "message",
                "retry": 2000,
                "data": json.dumps({"type": "hello", "computer": computer_name()}),
            }
            while not await request.is_disconnected():
                try:
                    event = await subscription.next(timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    # A visible heartbeat lets clients notice a connection that
                    # died silently (SSE comment pings never reach the page).
                    event = {"type": "heartbeat"}
                    if not auth_service.authenticate_request(request):
                        break  # signed out: stop streaming
                yield {"event": "message", "data": json.dumps(event)}
        finally:
            event_bus.unsubscribe(subscription)

    return EventSourceResponse(event_generator(), ping=15)
