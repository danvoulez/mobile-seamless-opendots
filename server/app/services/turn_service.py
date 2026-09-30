"""Assistant turns that run on this computer, independent of any one client.

A turn used to live inside the requesting browser's SSE connection, so closing
the tab (or locking the phone) cancelled the reply. Turns now run as background
tasks and publish their progress on the event bus: any open client can watch a
reply, join it halfway through, or answer its approval request.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.action_gateway import (
    ActionGatewayError,
    ActionPolicyError,
    action_gateway,
)
from app.services.connector_actions import ConnectorCommandError, parse_connector_command
from app.services.event_bus import EventBus, event_bus
from app.services.provider_service import provider_service
from app.services.search_actions import SearchCommandError, parse_search_command
from app.services.storage_service import StorageService, local_now, storage_service
from app.services.workspace_service import WorkspaceToolError, parse_workspace_command


logger = logging.getLogger(__name__)

PREVIEW_LENGTH = 200
KEPT_TOOL_EVENTS = 5


class TurnInProgressError(Exception):
    """A conversation already has a reply in progress."""


@dataclass
class TurnState:
    turn_id: str
    thread_id: str
    bot_id: str
    bot_msg_id: str
    model: str
    started_at: str
    text: str = ""
    status: str = "running"  # running | completed | failed
    approvals: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tools: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def waiting(self) -> bool:
        return any(approval["status"] == "pending" for approval in self.approvals.values())

    def snapshot(self) -> Dict[str, Any]:
        return {
            "turnId": self.turn_id,
            "threadId": self.thread_id,
            "botMsgId": self.bot_msg_id,
            "model": self.model,
            "startedAt": self.started_at,
            "status": self.status,
            "text": self.text,
            "approvals": list(self.approvals.values()),
            "tools": list(self.tools),
        }


def message_preview(message: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not message:
        return None
    text = " ".join(str(message.get("text") or "").split())
    if len(text) > PREVIEW_LENGTH:
        text = text[: PREVIEW_LENGTH - 1] + "…"
    return {
        "id": message.get("id"),
        "sender": message.get("sender"),
        "text": text,
        "created_at": message.get("created_at"),
        "origin": message.get("origin"),
        "is_error": bool(message.get("is_error")),
        "has_image": bool(message.get("image_url")),
    }


class TurnService:
    def __init__(
        self,
        storage: StorageService = storage_service,
        bus: EventBus = event_bus,
        provider: Any = provider_service,
        gateway: Any = action_gateway,
    ):
        self.storage = storage
        self.bus = bus
        self.provider = provider
        self.gateway = gateway
        self.active: Dict[str, TurnState] = {}
        # The last finished turn per conversation, so a client that opens the
        # conversation afterwards still sees its approval and tool cards.
        self.recent: Dict[str, TurnState] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    # ----- state for clients -------------------------------------------------

    def status(self, thread_id: str) -> str:
        state = self.active.get(thread_id)
        if not state:
            return "idle"
        return "waiting" if state.waiting else "running"

    def snapshot(self, thread_id: str) -> Optional[Dict[str, Any]]:
        state = self.active.get(thread_id) or self.recent.get(thread_id)
        return state.snapshot() if state else None

    def summarize(self, thread: Dict[str, Any], last_message: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "id": thread["id"],
            "bot_id": thread.get("bot_id"),
            "title": thread.get("title") or "",
            "created_at": thread.get("created_at"),
            "updated_at": thread.get("updated_at") or thread.get("created_at"),
            # Where the conversation was last written from ("Mac", "iPhone").
            "last_origin": thread.get("last_origin"),
            "last_message": message_preview(last_message),
            "status": self.status(thread["id"]),
        }

    def thread_summary(self, thread_id: str) -> Optional[Dict[str, Any]]:
        thread = self.storage.get_thread(thread_id)
        if not thread:
            return None
        return self.summarize(thread, self.storage.get_last_message(thread_id))

    def publish_thread(self, thread_id: str, event_type: str = "thread.updated") -> None:
        summary = self.thread_summary(thread_id)
        if summary:
            self.bus.publish({"type": event_type, "threadId": thread_id, "thread": summary})

    # ----- running turns -----------------------------------------------------

    def _bot(self, bot_id: str) -> Optional[Dict[str, Any]]:
        return next((bot for bot in self.storage.get_bots() if bot.get("id") == bot_id), None)

    def start(self, thread_id: str, bot_id: str, model: Optional[str] = None) -> TurnState:
        if thread_id in self.active:
            raise TurnInProgressError("A reply is already in progress in this conversation.")
        bot = self._bot(bot_id)
        selected_model = model or (bot or {}).get("model") or (
            self.storage.get_settings().get("default_model") or settings.DEFAULT_MODEL
        )
        state = TurnState(
            turn_id=f"turn-{uuid.uuid4().hex[:10]}",
            thread_id=thread_id,
            bot_id=bot_id,
            bot_msg_id=f"msg-{uuid.uuid4().hex[:12]}",
            model=selected_model,
            started_at=local_now(),
        )
        self.active[thread_id] = state
        self.recent.pop(thread_id, None)
        self._tasks[thread_id] = asyncio.create_task(self._run(state, bot))
        self.publish_thread(thread_id)
        return state

    async def wait(self, thread_id: str) -> None:
        """Wait for the conversation's current turn to finish (used by tests)."""
        task = self._tasks.get(thread_id)
        if task:
            await asyncio.shield(task)

    def _emit(self, state: TurnState, event: Dict[str, Any]) -> None:
        event = {**event, "threadId": state.thread_id}
        if event["type"].startswith("tool."):
            state.tools = [*state.tools, {k: v for k, v in event.items() if k != "threadId"}][-KEPT_TOOL_EVENTS:]
        self.bus.publish(event)

    async def _run(self, state: TurnState, bot: Optional[Dict[str, Any]]) -> None:
        try:
            await self._run_turn(state, bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # A failed turn must never leave a thread stuck.
            logger.exception("Turn %s failed", state.turn_id)
            if state.status == "running":
                note = f"The reply stopped unexpectedly ({type(exc).__name__})."
                state.text = f"{state.text}\n\n{note}" if state.text else note
                self._finish(state, ok=False)
        finally:
            if self.active.get(state.thread_id) is state:
                self.active.pop(state.thread_id, None)
                self.recent[state.thread_id] = state
            self._tasks.pop(state.thread_id, None)
            self.publish_thread(state.thread_id)

    async def _run_turn(self, state: TurnState, bot: Optional[Dict[str, Any]]) -> None:
        history = self.storage.get_messages(thread_id=state.thread_id)
        raw_prompt = bot["system_prompt"] if bot else "You are a helpful AI assistant."
        current_time_str = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        system_prompt = f"Current Date & Time: {current_time_str}.\n\n{raw_prompt}"

        formatted_history = [
            {
                "role": "user" if m["sender"] == "user" else "assistant",
                "content": m.get("text", ""),
                "image_url": m.get("image_url"),
            }
            for m in history
            if m.get("sender") in ("user", "bot") and not m.get("is_error")
        ]

        self._emit(state, {
            "type": "turn.started",
            "turnId": state.turn_id,
            "botMsgId": state.bot_msg_id,
            "model": state.model,
        })

        last_user_text = formatted_history[-1]["content"] if formatted_history else ""
        tool_context = await self._run_action(state, last_user_text)
        provider_prompt = f"{system_prompt}\n\n{tool_context}" if tool_context else system_prompt

        ok = False
        async for event in self.provider.stream_chat_completion(
            model=state.model,
            messages=formatted_history,
            system_prompt=provider_prompt,
        ):
            if event["type"] == "content.delta":
                offset = len(state.text)
                state.text += event["delta"]
                self._emit(state, {
                    "type": "content.delta",
                    "botMsgId": state.bot_msg_id,
                    "delta": event["delta"],
                    "offset": offset,
                })
            elif event["type"] == "turn.completed":
                ok = event.get("ok", True)
        self._finish(state, ok)

    def _finish(self, state: TurnState, ok: bool) -> None:
        # Failed replies are kept (marked as errors, and left out of the model
        # context) so every device shows the same conversation.
        message = {
            "id": state.bot_msg_id,
            "thread_id": state.thread_id,
            "bot_id": state.bot_id,
            "sender": "bot",
            "text": state.text or ("" if ok else "The reply could not be completed."),
            "created_at": local_now(),
            "model": state.model,
            "item_type": "assistant_text" if ok else "assistant_error",
            "is_error": not ok,
        }
        self.storage.add_message(message)
        thread = self.storage.get_thread(state.thread_id)
        if thread:
            thread["updated_at"] = message["created_at"]
            self.storage.save_thread(thread)
        state.status = "completed" if ok else "failed"
        self._emit(state, {
            "type": "turn.completed",
            "ok": ok,
            "botMsgId": state.bot_msg_id,
            "message": message,
        })

    async def _run_action(self, state: TurnState, last_user_text: str) -> str:
        """Run an explicit slash command through the action gateway.

        Returns the context line handed to the model about what happened.
        """
        try:
            action_call = parse_workspace_command(last_user_text)
            if action_call is None:
                action_call = parse_connector_command(last_user_text)
            if action_call is None:
                action_call = parse_search_command(last_user_text)
        except (WorkspaceToolError, ConnectorCommandError, SearchCommandError) as exc:
            lowered_text = last_user_text.lower()
            if lowered_text.startswith("/connector"):
                command_tool = "connector"
            elif lowered_text.startswith("/search"):
                command_tool = "search"
            else:
                command_tool = "workspace"
            self._emit(state, {"type": "tool.failed", "tool": command_tool, "error": str(exc)})
            return f"A {command_tool} request was rejected before execution: {exc}"

        if not action_call:
            return ""

        try:
            action_request, approval = self.gateway.open(state.thread_id, state.bot_id, action_call)
        except ActionPolicyError as exc:
            self._emit(state, {
                "type": "tool.failed",
                "tool": action_call.name,
                "requestId": exc.request_id,
                "error": str(exc),
            })
            return f"Action rejected by policy: {exc}"

        if approval:
            state.approvals[action_request.request_id] = {
                "requestId": action_request.request_id,
                "tool": approval["tool"],
                "summary": approval["summary"],
                "arguments": approval["arguments"],
                "status": "pending",
            }
            self._emit(state, {
                "type": "request.opened",
                "requestType": "permission",
                "requestId": action_request.request_id,
                "tool": approval["tool"],
                "summary": approval["summary"],
                "arguments": approval["arguments"],
                "action": action_request.model_dump(),
            })
            self.publish_thread(state.thread_id)

        decision = await self.gateway.wait_for_decision(action_request)
        if approval:
            state.approvals[action_request.request_id]["status"] = decision
            self._emit(state, {
                "type": "request.resolved",
                "requestId": action_request.request_id,
                "decision": decision,
            })
            self.publish_thread(state.thread_id)

        action_name = f"{action_request.tool}.{action_request.action}"
        if decision == "deny":
            self._emit(state, {"type": "tool.denied", "tool": action_name, "requestId": action_request.request_id})
            return f"Action denied by the user: {action_name}"
        if decision != "allow":
            self._emit(state, {"type": "tool.expired", "tool": action_name, "requestId": action_request.request_id})
            return f"Action expired before approval: {action_name}"

        self._emit(state, {
            "type": "tool.started",
            "tool": action_name,
            "requestId": action_request.request_id,
            "action": action_request.model_dump(),
        })
        try:
            action_result = await self.gateway.execute(action_request)
        except ActionGatewayError as exc:
            self._emit(state, {
                "type": "tool.failed",
                "tool": action_name,
                "requestId": action_request.request_id,
                "error": str(exc),
            })
            return f"Action could not execute ({action_name}): {exc}"

        if action_result.status == "completed":
            result = action_result.result or {}
            self._emit(state, {
                "type": "tool.completed",
                "tool": action_name,
                "requestId": action_request.request_id,
                "result": result,
            })
            return f"Action result ({action_name}): {json.dumps(result)}"

        error = action_result.error or "The action failed."
        self._emit(state, {
            "type": "tool.failed",
            "tool": action_name,
            "requestId": action_request.request_id,
            "error": error,
        })
        return f"Action failed ({action_name}): {error}"


turn_service = TurnService()
