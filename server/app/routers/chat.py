"""Original per-thread chat API, kept for direct API clients.

Replies now run in the background (see turn_service); these endpoints store
messages and relay a turn's events in the same shape as before.
"""

import json
import uuid
from datetime import datetime
from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse
from typing import List, Optional

from app.schemas.contracts import TurnRequest, Message
from app.services.device_service import client_label
from app.services.event_bus import event_bus
from app.services.storage_service import derive_title, local_now, storage_service
from app.services.turn_service import TurnInProgressError, turn_service

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

@router.get("/history/{thread_id}", response_model=List[Message])
async def get_history(thread_id: str):
    return storage_service.get_messages(thread_id=thread_id)

@router.post("/send")
async def send_message(req: TurnRequest, request: Request):
    # Store user message
    user_msg = {
        "id": f"msg-{uuid.uuid4().hex[:12]}",
        "thread_id": req.thread_id,
        "bot_id": req.bot_id,
        "sender": "user",
        "text": req.user_text,
        "image_url": req.image_url,
        "created_at": datetime.now().isoformat(),
        "model": req.model or next(
            (bot.get("model") for bot in storage_service.get_bots() if bot.get("id") == req.bot_id),
            storage_service.get_settings().get("default_model", "gpt-5-mini"),
        ),
        "item_type": "user_text",
        "origin": client_label(request),
    }

    storage_service.add_message(user_msg)
    thread = storage_service.get_thread(req.thread_id)
    if thread is None:
        thread = {"id": req.thread_id, "bot_id": req.bot_id, "title": "", "created_at": local_now()}
        event_type = "thread.created"
    else:
        event_type = "thread.updated"
    thread["title"] = thread.get("title") or derive_title(req.user_text)
    thread["updated_at"] = local_now()
    thread["last_origin"] = user_msg["origin"]
    storage_service.save_thread(thread)
    event_bus.publish({"type": "message.created", "threadId": req.thread_id, "message": user_msg})
    turn_service.publish_thread(req.thread_id, event_type)
    return {"status": "ok", "message": user_msg}

@router.get("/stream/{thread_id}")
async def stream_turn(thread_id: str, model: Optional[str] = Query(None)):
    """
    SSE stream of real-time tokens & tool events for a thread's current turn.
    Starts a turn when none is running; joins the running one otherwise.
    """
    thread = storage_service.get_thread(thread_id)
    bot_id = thread.get("bot_id") if thread else thread_id

    async def event_generator():
        subscription = event_bus.subscribe()
        try:
            state = turn_service.active.get(thread_id)
            sent = 0
            if state is None:
                try:
                    state = turn_service.start(thread_id, bot_id, model)
                except TurnInProgressError:
                    state = turn_service.active[thread_id]
            else:
                # Joining halfway: replay what was streamed so far.
                yield {"event": "message", "data": json.dumps(
                    {"type": "turn.started", "botMsgId": state.bot_msg_id, "model": state.model}
                )}
                if state.text:
                    sent = len(state.text)
                    yield {"event": "message", "data": json.dumps(
                        {"type": "content.delta", "botMsgId": state.bot_msg_id, "delta": state.text}
                    )}

            while True:
                event = await subscription.next()
                if event.get("threadId") != thread_id or event["type"].startswith(("thread.", "message.")):
                    continue
                if event["type"] == "content.delta":
                    # Skip text already replayed to this client.
                    end = event["offset"] + len(event["delta"])
                    if end <= sent:
                        continue
                    event = {**event, "delta": event["delta"][max(0, sent - event["offset"]):]}
                    sent = end
                yield {"event": "message", "data": json.dumps(event)}
                if event["type"] == "turn.completed":
                    break
        finally:
            event_bus.unsubscribe(subscription)

    return EventSourceResponse(event_generator())
