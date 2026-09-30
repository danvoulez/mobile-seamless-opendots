"""One live stream per open client: the same events on the computer and the phone."""

import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.services.event_bus import event_bus
from app.services.host_info import computer_name

router = APIRouter(prefix="/api/v1", tags=["events"])


@router.get("/events")
async def stream_events(request: Request):
    async def event_generator():
        # Subscribe before greeting: a client reloads its state on "hello", so
        # nothing published after that reload can be missed.
        subscription = event_bus.subscribe()
        try:
            yield {"event": "message", "data": json.dumps({"type": "hello", "computer": computer_name()})}
            while not await request.is_disconnected():
                try:
                    event = await subscription.next(timeout=15)
                except asyncio.TimeoutError:
                    continue
                yield {"event": "message", "data": json.dumps(event)}
        finally:
            event_bus.unsubscribe(subscription)

    return EventSourceResponse(event_generator(), ping=15)
