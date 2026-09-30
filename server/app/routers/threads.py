"""Conversations shared by this computer and every device linked to it."""

import uuid

from fastapi import APIRouter, HTTPException, Request

from app.schemas.contracts import ThreadCreate, ThreadMessageRequest, ThreadUpdate
from app.services.device_service import client_label
from app.services.event_bus import event_bus
from app.services.storage_service import derive_title, local_now, storage_service
from app.services.turn_service import TurnInProgressError, turn_service

router = APIRouter(prefix="/api/v1/threads", tags=["threads"])


def _thread_or_404(thread_id: str):
    thread = storage_service.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return thread


@router.get("")
async def list_threads():
    last_messages = storage_service.get_last_messages()
    return [
        turn_service.summarize(thread, last_messages.get(thread["id"]))
        for thread in storage_service.get_threads()
    ]


@router.post("", status_code=201)
async def create_thread(body: ThreadCreate):
    if not any(bot.get("id") == body.bot_id for bot in storage_service.get_bots()):
        raise HTTPException(status_code=404, detail="Assistant not found.")
    now = local_now()
    thread = {
        "id": f"thr-{uuid.uuid4().hex[:12]}",
        "bot_id": body.bot_id,
        "title": body.title.strip(),
        "created_at": now,
        "updated_at": now,
    }
    storage_service.save_thread(thread)
    summary = turn_service.summarize(thread)
    event_bus.publish({"type": "thread.created", "threadId": thread["id"], "thread": summary})
    return summary


@router.get("/{thread_id}")
async def get_thread(thread_id: str):
    thread = _thread_or_404(thread_id)
    messages = storage_service.get_messages(thread_id=thread_id)
    return {
        "thread": turn_service.summarize(thread, messages[-1] if messages else None),
        "messages": messages,
        "turn": turn_service.snapshot(thread_id),
    }


@router.patch("/{thread_id}")
async def rename_thread(thread_id: str, body: ThreadUpdate):
    thread = _thread_or_404(thread_id)
    thread["title"] = body.title.strip()
    storage_service.save_thread(thread)
    turn_service.publish_thread(thread_id)
    return turn_service.thread_summary(thread_id)


@router.delete("/{thread_id}")
async def delete_thread(thread_id: str):
    _thread_or_404(thread_id)
    if turn_service.status(thread_id) != "idle":
        raise HTTPException(status_code=409, detail="Wait for the reply to finish before deleting.")
    storage_service.delete_thread(thread_id)
    turn_service.recent.pop(thread_id, None)
    event_bus.publish({"type": "thread.deleted", "threadId": thread_id})
    return {"status": "ok", "deleted_id": thread_id}


@router.post("/{thread_id}/messages", status_code=202)
async def post_message(thread_id: str, body: ThreadMessageRequest, request: Request):
    thread = _thread_or_404(thread_id)
    if not body.text.strip() and not body.image_url:
        raise HTTPException(status_code=422, detail="Write a message or attach an image.")
    if turn_service.status(thread_id) != "idle":
        raise HTTPException(status_code=409, detail="A reply is still in progress in this conversation.")

    bot = next((b for b in storage_service.get_bots() if b.get("id") == thread.get("bot_id")), None)
    model = body.model or (bot or {}).get("model") or storage_service.get_settings().get("default_model")
    now = local_now()
    message = {
        "id": f"msg-{uuid.uuid4().hex[:12]}",
        "thread_id": thread_id,
        "bot_id": thread.get("bot_id"),
        "sender": "user",
        "text": body.text,
        "image_url": body.image_url,
        "created_at": now,
        "model": model,
        "item_type": "user_text",
        "origin": client_label(request),
        "client_id": body.client_id,
    }
    storage_service.add_message(message)
    if not thread.get("title"):
        thread["title"] = derive_title(body.text) or "Photo"
    thread["updated_at"] = now
    thread["last_origin"] = message["origin"]
    storage_service.save_thread(thread)
    event_bus.publish({"type": "message.created", "threadId": thread_id, "message": message})

    try:
        state = turn_service.start(thread_id, thread.get("bot_id"), model)
    except TurnInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"message": message, "turn": state.snapshot()}
