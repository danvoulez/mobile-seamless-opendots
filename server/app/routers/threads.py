"""Conversations shared by this computer and every device linked to it."""

from fastapi import APIRouter, HTTPException, Request

from app.schemas.contracts import ThreadCreate, ThreadMessageRequest, ThreadUpdate
from app.services.conversation_service import ConversationError, conversations
from app.services.device_service import client_label

router = APIRouter(prefix="/api/v1/threads", tags=["threads"])


def _http_error(exc: ConversationError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("")
async def list_threads():
    return conversations.list_threads()


@router.post("", status_code=201)
async def create_thread(body: ThreadCreate):
    try:
        return conversations.create_thread(body.bot_id, body.title)
    except ConversationError as exc:
        raise _http_error(exc) from exc


@router.get("/{thread_id}")
async def get_thread(thread_id: str):
    try:
        return conversations.get_thread(thread_id)
    except ConversationError as exc:
        raise _http_error(exc) from exc


@router.patch("/{thread_id}")
async def rename_thread(thread_id: str, body: ThreadUpdate):
    try:
        return conversations.rename_thread(thread_id, body.title)
    except ConversationError as exc:
        raise _http_error(exc) from exc


@router.delete("/{thread_id}")
async def delete_thread(thread_id: str):
    try:
        conversations.delete_thread(thread_id)
    except ConversationError as exc:
        raise _http_error(exc) from exc
    return {"status": "ok", "deleted_id": thread_id}


@router.post("/{thread_id}/messages", status_code=202)
async def post_message(thread_id: str, body: ThreadMessageRequest, request: Request):
    try:
        return conversations.send_message(
            thread_id=thread_id,
            text=body.text,
            image_url=body.image_url,
            model=body.model,
            client_id=body.client_id,
            origin=client_label(request),
        )
    except ConversationError as exc:
        raise _http_error(exc) from exc
