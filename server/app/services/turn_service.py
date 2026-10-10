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
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.action_gateway import (
    ActionGatewayError,
    ActionPolicyError,
    action_gateway,
)
from app.services.approval_broker import approval_broker
from app.services.coding_agent import (
    CodingAgentError, coding_agent, coding_instructions, project_dir_for, project_plugins,
)
from app.services.connector_actions import ConnectorCommandError, parse_connector_command
from app.services.event_bus import EventBus, event_bus
from app.services.model_context import assistant_instructions, model_messages, with_turn_context
from app.services.provider_service import provider_service
from app.services.search_actions import SearchCommandError, parse_search_command
from app.services.storage_service import StorageService, local_now, storage_service
from app.services.workspace_service import WorkspaceToolError, parse_workspace_command


logger = logging.getLogger(__name__)

PREVIEW_LENGTH = 200
KEPT_STEPS = 30  # actions kept per reply, so a busy reply still shows its whole run


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


def keep_tool_event(tools: List[Dict[str, Any]], event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One entry per action: a later event for the same action updates it in
    place (keeping what it said when it started), a new action is added."""

    request_id = event.get("requestId")
    for index, known in enumerate(tools):
        if request_id and known.get("requestId") == request_id:
            return [*tools[:index], {**known, **event}, *tools[index + 1:]]
    return [*tools, event][-KEPT_STEPS:]


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
        coding: Any = None,
    ):
        self.storage = storage
        self.bus = bus
        self.provider = provider
        self.gateway = gateway
        self.coding = coding  # OpenCode, for coding assistants (None: the shared one)
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
            raise TurnInProgressError("Wait for the reply to finish.")
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
            state.tools = keep_tool_event(state.tools, {k: v for k, v in event.items() if k != "threadId"})
        self.bus.publish(event)

    async def _run(self, state: TurnState, bot: Optional[Dict[str, Any]]) -> None:
        try:
            await self._run_turn(state, bot)
        except asyncio.CancelledError:
            raise
        except Exception:  # A failed turn must never leave a thread stuck.
            logger.exception("Turn %s failed", state.turn_id)
            if state.status == "running":
                note = "The reply stopped unexpectedly."
                state.text = f"{state.text}\n\n{note}" if state.text else note
                self._finish(state, ok=False)
        finally:
            if self.active.get(state.thread_id) is state:
                self.active.pop(state.thread_id, None)
                self.recent[state.thread_id] = state
            self._tasks.pop(state.thread_id, None)
            self.publish_thread(state.thread_id)

    async def _run_turn(self, state: TurnState, bot: Optional[Dict[str, Any]]) -> None:
        if (bot or {}).get("engine") == "opencode":
            await CodingTurn(self, state, bot, self.coding).run()
            return
        stored = self.storage.get_messages(thread_id=state.thread_id)
        messages = model_messages(stored)

        self._emit(state, {
            "type": "turn.started",
            "turnId": state.turn_id,
            "botMsgId": state.bot_msg_id,
            "model": state.model,
        })

        latest = next((m for m in reversed(stored) if m.get("sender") == "user"), None)
        action_note = await self._run_action(state, (latest or {}).get("text") or "")

        ok = False
        usage = None
        async for event in self.provider.stream_chat_completion(
            model=state.model,
            messages=with_turn_context(messages, datetime.now().astimezone(), action_note),
            system_prompt=assistant_instructions(bot),
            session_id=state.thread_id,
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
                usage = event.get("usage")
        self._finish(state, ok, usage)

    def _finish(self, state: TurnState, ok: bool, usage: Optional[Dict[str, Any]] = None) -> None:
        # Failed replies are kept (marked as errors, and left out of the model
        # context) so every device shows the same conversation.
        message = {
            "id": state.bot_msg_id,
            "thread_id": state.thread_id,
            "bot_id": state.bot_id,
            "sender": "bot",
            "text": state.text or ("" if ok else "The reply couldn't be completed."),
            "created_at": local_now(),
            "model": state.model,
            "item_type": "assistant_text" if ok else "assistant_error",
            "is_error": not ok,
        }
        if usage:
            message["usage"] = usage
            # Every model call is billed, so each one goes in the audit trail,
            # where the spending summary is added up (routers/audit.py).
            self.storage.add_audit_event({
                "event": "model.reply",
                "thread_id": state.thread_id,
                "bot_id": state.bot_id,
                "model": state.model,
                **usage,
            })
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


TOOL_OUTPUT_KEPT = 2000  # characters of a coding tool's output shown under "Details"
SUBJECT_KEYS = ("command", "filePath", "path", "pattern", "url", "query", "description")


def tool_subject(tool: str, data: Dict[str, Any]) -> str:
    """One line saying what a coding tool call is about: its command, file or pattern."""
    for key in SUBJECT_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            line = " ".join(value.split())
            return f"{tool}: {line[:160]}"
    return tool


class CodingTurn:
    """One reply from a coding assistant: the person's message goes to OpenCode,
    and OpenCode's events come back as this turn's text, steps and approvals."""

    def __init__(self, turns: "TurnService", state: TurnState, bot: Dict[str, Any], agent: Any = None):
        self.turns = turns
        self.state = state
        self.bot = bot
        self.agent = agent or coding_agent
        self.directory = ""
        self.session_id = ""
        self.assistant_ids: set = set()
        self.part_text: Dict[str, str] = {}
        self.last_part: Optional[str] = None
        self.started_tools: set = set()
        self.permission_ids: Dict[str, str] = {}  # approval request id → OpenCode permission id
        self.waiters: List[asyncio.Task] = []
        self.usage: Dict[str, Dict[str, Any]] = {}  # per assistant message, its final tokens and cost
        self.error: Optional[str] = None

    async def run(self) -> None:
        state = self.state
        self.turns._emit(state, {
            "type": "turn.started",
            "turnId": state.turn_id,
            "botMsgId": state.bot_msg_id,
            "model": state.model,
        })
        stored = self.turns.storage.get_messages(thread_id=state.thread_id)
        latest = next((m for m in reversed(stored) if m.get("sender") == "user"), None) or {}
        try:
            self.directory = str(project_dir_for(self.bot))
            plugins = project_plugins(Path(self.directory))
            if plugins:
                raise CodingAgentError(
                    "This project has OpenCode plugins, which would run code on this computer without asking: "
                    + ", ".join(str(plugin) for plugin in plugins[:5])
                    + ". Remove them (or choose another project folder), then send your message again."
                )
            await self.agent.ensure_running()
            self.session_id = await self._session()
        except (CodingAgentError, OSError) as exc:
            self._say(str(exc))
            self.turns._finish(state, ok=False)
            return

        events = self.agent.listen(self.session_id)
        try:
            await self.agent.prompt(
                self.session_id, self.directory, latest.get("text") or "", latest.get("image_url"),
                self.agent.model(state.model), coding_instructions(self.bot, Path(self.directory)),
            )
            await self._follow(events)
        except asyncio.CancelledError:
            await self._abort()
            raise
        except CodingAgentError as exc:
            self.error = str(exc)
        finally:
            self.agent.unlisten(self.session_id, events)
            for waiter in self.waiters:
                waiter.cancel()
        if self.error:
            self._say(self.error)
        self.turns._finish(state, ok=not self.error, usage=self._total_usage())

    async def _session(self) -> str:
        """The OpenCode session behind this conversation, made on its first reply."""
        thread = self.turns.storage.get_thread(self.state.thread_id) or {}
        session_id = thread.get("opencode_session_id")
        if session_id and thread.get("opencode_directory") == self.directory:
            if await self.agent.session_exists(session_id, self.directory):
                return session_id
        session_id = await self.agent.create_session(self.directory, thread.get("title") or "")
        if thread:
            thread["opencode_session_id"] = session_id
            thread["opencode_directory"] = self.directory
            self.turns.storage.save_thread(thread)
        return session_id

    async def _abort(self) -> None:
        try:
            await self.agent.abort(self.session_id, self.directory)
        except Exception:
            logger.warning("Couldn't stop OpenCode session %s", self.session_id)

    def _say(self, text: str) -> None:
        """Add text to the reply as it streams (also used for notes and errors)."""
        state = self.state
        if state.text and not state.text.endswith("\n\n"):
            text = ("\n\n" if not state.text.endswith("\n") else "\n") + text
        offset = len(state.text)
        state.text += text
        self.turns._emit(state, {"type": "content.delta", "botMsgId": state.bot_msg_id, "delta": text, "offset": offset})

    def _text(self, part_id: str, delta: str) -> None:
        if not delta:
            return
        state = self.state
        if part_id != self.last_part and state.text and not state.text.endswith("\n\n"):
            delta = ("\n\n" if not state.text.endswith("\n") else "\n") + delta
        self.last_part = part_id
        offset = len(state.text)
        state.text += delta
        self.turns._emit(state, {"type": "content.delta", "botMsgId": state.bot_msg_id, "delta": delta, "offset": offset})

    async def _follow(self, events: asyncio.Queue) -> None:
        while True:
            event = await events.get()
            kind = event.get("type")
            props = event.get("properties") or {}
            if kind == "session.idle":
                return
            if kind == "agent.disconnected":
                self.error = "OpenCode stopped answering before the reply finished."
                return
            if kind == "session.error":
                error = props.get("error") or {}
                if error.get("name") != "MessageAbortedError":
                    data = error.get("data") or {}
                    self.error = data.get("message") or error.get("name") or "OpenCode reported an error."
            elif kind == "message.updated":
                self._message(props.get("info") or {})
            elif kind == "message.part.delta":
                if props.get("messageID") in self.assistant_ids and props.get("field") == "text":
                    part_id = props.get("partID") or ""
                    self.part_text[part_id] = self.part_text.get(part_id, "") + (props.get("delta") or "")
                    self._text(part_id, props.get("delta") or "")
            elif kind == "message.part.updated":
                self._part(props.get("part") or {})
            elif kind == "permission.asked":
                self._permission(props)
            elif kind == "permission.replied":
                request_id = next((key for key, value in self.permission_ids.items() if value == props.get("requestID")), None)
                if request_id:
                    # Answered without us (an earlier "always"): close our copy too.
                    approval_broker.resolve(request_id, "deny" if props.get("reply") == "reject" else "allow")

    def _message(self, info: Dict[str, Any]) -> None:
        if info.get("role") != "assistant":
            return
        self.assistant_ids.add(info.get("id"))
        tokens = info.get("tokens") or {}
        if (info.get("time") or {}).get("completed") or tokens.get("input") or tokens.get("output"):
            cache = tokens.get("cache") or {}
            self.usage[info["id"]] = {
                "input_tokens": int(tokens.get("input") or 0) + int(cache.get("read") or 0) + int(cache.get("write") or 0),
                "cached_tokens": int(cache.get("read") or 0),
                "output_tokens": int(tokens.get("output") or 0),
                "reasoning_tokens": int(tokens.get("reasoning") or 0),
                "cost_usd": float(info["cost"]) if isinstance(info.get("cost"), (int, float)) else None,
            }
        error = info.get("error")
        if isinstance(error, dict) and error.get("name") not in (None, "MessageAbortedError"):
            self.error = (error.get("data") or {}).get("message") or error.get("name")

    def _total_usage(self) -> Optional[Dict[str, Any]]:
        if not self.usage:
            return None
        total: Dict[str, Any] = {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}
        costs = [usage["cost_usd"] for usage in self.usage.values() if usage["cost_usd"] is not None]
        for usage in self.usage.values():
            for key in total:
                total[key] += usage[key]
        # OpenCode prices calls from its model catalog; a model it doesn't know costs 0 there.
        total["cost_usd"] = sum(costs) if costs and any(costs) else None
        total["model_calls"] = len(self.usage)
        return total

    def _part(self, part: Dict[str, Any]) -> None:
        if part.get("messageID") not in self.assistant_ids:
            return
        if part.get("type") == "text":
            # Text that arrived without deltas (or the rest of it) is added here.
            part_id = part.get("id") or ""
            known = self.part_text.get(part_id, "")
            text = part.get("text") or ""
            if len(text) > len(known) and text.startswith(known):
                self.part_text[part_id] = text
                self._text(part_id, text[len(known):])
        elif part.get("type") == "tool":
            self._tool(part)

    def _tool(self, part: Dict[str, Any]) -> None:
        tool_state = part.get("state") or {}
        status = tool_state.get("status")
        call_id = part.get("callID") or part.get("id")
        name = f"code.{part.get('tool')}"
        subject = tool_state.get("title") or tool_subject(part.get("tool") or "tool", tool_state.get("input") or {})
        if status in ("running", "completed", "error") and call_id not in self.started_tools:
            self.started_tools.add(call_id)
            self.turns._emit(self.state, {
                "type": "tool.started", "tool": name, "requestId": call_id,
                "action": {"preview": subject, "arguments": tool_state.get("input") or {}},
            })
        if status == "completed":
            output = tool_state.get("output") or ""
            if len(output) > TOOL_OUTPUT_KEPT:
                output = output[:TOOL_OUTPUT_KEPT] + "\n…"
            self.turns._emit(self.state, {
                "type": "tool.completed", "tool": name, "requestId": call_id,
                "result": {"title": subject, "output": output},
            })
        elif status == "error":
            error = tool_state.get("error") or "The step failed."
            denied = call_id in self.permission_ids and "reject" in error.lower()
            self.turns._emit(self.state, {
                "type": "tool.denied" if denied else "tool.failed", "tool": name, "requestId": call_id, "error": error,
            })

    def _permission(self, request: Dict[str, Any]) -> None:
        """OpenCode wants to act: ask on every device, then pass the answer back."""
        permission_id = request.get("id")
        tool = request.get("tool") or {}
        request_id = tool.get("callID") or permission_id  # one step per tool call on every device
        metadata = request.get("metadata") or {}
        patterns = request.get("patterns") or []
        subject = tool_subject(request.get("permission") or "action", metadata)
        if subject == (request.get("permission") or "action") and patterns:
            subject = f"{subject}: {', '.join(patterns)[:160]}"
        name = f"code.{request.get('permission')}"
        call = SimpleNamespace(name=name, summary=subject, arguments_for_display={**metadata, "patterns": patterns})
        approval_broker.open(self.state.thread_id, self.state.bot_id, call, request_id=request_id,
                             always=request.get("always") or [])
        self.permission_ids[request_id] = permission_id
        self.state.approvals[request_id] = {
            "requestId": request_id, "tool": name, "summary": subject,
            "arguments": call.arguments_for_display, "always": request.get("always") or [], "status": "pending",
        }
        self.turns._emit(self.state, {
            "type": "request.opened", "requestType": "permission", "requestId": request_id,
            "tool": name, "summary": subject, "arguments": call.arguments_for_display,
            "always": request.get("always") or [],
        })
        self.turns.publish_thread(self.state.thread_id)
        self.waiters.append(asyncio.create_task(self._answer(request_id, permission_id)))

    async def _answer(self, request_id: str, permission_id: str) -> None:
        decision = await approval_broker.wait(request_id)
        reply = {"allow": "once", "always": "always"}.get(decision, "reject")
        if request_id in self.state.approvals:
            self.state.approvals[request_id]["status"] = decision
        self.turns._emit(self.state, {"type": "request.resolved", "requestId": request_id, "decision": decision})
        self.turns.publish_thread(self.state.thread_id)
        try:
            await self.agent.reply_permission(permission_id, self.directory, reply)
        except CodingAgentError as exc:
            logger.warning("Couldn't pass an approval to OpenCode: %s", exc)


turn_service = TurnService()
