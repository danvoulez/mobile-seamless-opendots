"""Operations on conversations, shared by every way a client connects.

The REST API (used by the browser on the computer) and the JSON-RPC
WebSocket (used by the iPhone, locally or through a tunnel) both call these,
so a message behaves the same whichever way it arrives, and every change is
announced to all clients on the event bus.
"""

import uuid
from typing import Any, Dict, List, Optional

from app.services.event_bus import EventBus, event_bus
from app.services.storage_service import StorageService, derive_title, local_now, storage_service
from app.services.turn_service import TurnInProgressError, TurnService, turn_service


class ConversationError(Exception):
    status = 400


class NotFound(ConversationError):
    status = 404


class Busy(ConversationError):
    status = 409


class Invalid(ConversationError):
    status = 422


class ConversationService:
    def __init__(
        self,
        storage: StorageService = storage_service,
        bus: EventBus = event_bus,
        turns: TurnService = turn_service,
    ):
        self.storage = storage
        self.bus = bus
        self.turns = turns

    def _thread(self, thread_id: str) -> Dict[str, Any]:
        thread = self.storage.get_thread(thread_id)
        if not thread:
            raise NotFound("Conversation not found.")
        return thread

    def _bot(self, bot_id: Optional[str]) -> Optional[Dict[str, Any]]:
        return next((bot for bot in self.storage.get_bots() if bot.get("id") == bot_id), None)

    def _new_thread(self, bot_id: str, title: str = "") -> Dict[str, Any]:
        if not self._bot(bot_id):
            raise NotFound("Assistant not found.")
        now = local_now()
        thread = {
            "id": f"thr-{uuid.uuid4().hex[:12]}",
            "bot_id": bot_id,
            "title": title.strip(),
            "created_at": now,
            "updated_at": now,
        }
        self.storage.save_thread(thread)
        self.bus.publish({"type": "thread.created", "threadId": thread["id"], "thread": self.turns.summarize(thread)})
        return thread

    def list_threads(self) -> List[Dict[str, Any]]:
        last_messages = self.storage.get_last_messages()
        return [
            self.turns.summarize(thread, last_messages.get(thread["id"]))
            for thread in self.storage.get_threads()
        ]

    def get_thread(self, thread_id: str) -> Dict[str, Any]:
        thread = self._thread(thread_id)
        messages = self.storage.get_messages(thread_id=thread_id)
        return {
            "thread": self.turns.summarize(thread, messages[-1] if messages else None),
            "messages": messages,
            "turn": self.turns.snapshot(thread_id),
        }

    def create_thread(self, bot_id: str, title: str = "") -> Dict[str, Any]:
        return self.turns.summarize(self._new_thread(bot_id, title))

    def rename_thread(self, thread_id: str, title: str) -> Dict[str, Any]:
        thread = self._thread(thread_id)
        thread["title"] = title.strip()
        self.storage.save_thread(thread)
        self.turns.publish_thread(thread_id)
        return self.turns.thread_summary(thread_id)

    def delete_thread(self, thread_id: str) -> None:
        self._thread(thread_id)
        if self.turns.status(thread_id) != "idle":
            raise Busy("Wait for the reply to finish before deleting.")
        self.storage.delete_thread(thread_id)
        self.turns.recent.pop(thread_id, None)
        self.bus.publish({"type": "thread.deleted", "threadId": thread_id})

    def send_message(
        self,
        *,
        text: str,
        origin: str,
        thread_id: Optional[str] = None,
        bot_id: Optional[str] = None,
        image_url: Optional[str] = None,
        model: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store a message and start the reply; starts a new conversation without a thread_id.

        Retrying is safe: a message is identified by the client's own id, so a
        send repeated after a lost response returns the first one instead of
        posting it twice.
        """
        if client_id and (existing := self.storage.find_message_by_client_id(client_id)):
            existing_thread = existing.get("thread_id")
            return {
                "thread": self.turns.thread_summary(existing_thread),
                "message": existing,
                "turn": self.turns.snapshot(existing_thread),
                "duplicate": True,
            }
        if not text.strip() and not image_url:
            raise Invalid("Write a message or add a photo.")
        if thread_id:
            thread = self._thread(thread_id)
        elif bot_id:
            thread = self._new_thread(bot_id)
        else:
            raise Invalid("Choose a conversation or an assistant.")
        thread_id = thread["id"]
        if self.turns.status(thread_id) != "idle":
            raise Busy("Wait for the reply to finish.")

        bot = self._bot(thread.get("bot_id"))
        model = model or (bot or {}).get("model") or self.storage.get_settings().get("default_model")
        now = local_now()
        message = {
            "id": f"msg-{uuid.uuid4().hex[:12]}",
            "thread_id": thread_id,
            "bot_id": thread.get("bot_id"),
            "sender": "user",
            "text": text,
            "image_url": image_url,
            "created_at": now,
            "model": model,
            "item_type": "user_text",
            "origin": origin,
            "client_id": client_id,
        }
        self.storage.add_message(message)
        if not thread.get("title"):
            thread["title"] = derive_title(text) or "Photo"
        thread["updated_at"] = now
        thread["last_origin"] = origin
        self.storage.save_thread(thread)
        self.bus.publish({"type": "message.created", "threadId": thread_id, "message": message})

        try:
            state = self.turns.start(thread_id, thread.get("bot_id"), model)
        except TurnInProgressError as exc:
            raise Busy(str(exc)) from exc
        return {"thread": self.turns.thread_summary(thread_id), "message": message, "turn": state.snapshot()}


conversations = ConversationService()
