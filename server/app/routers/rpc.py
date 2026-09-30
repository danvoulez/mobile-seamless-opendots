"""JSON-RPC 2.0 over one WebSocket: how a phone talks to this computer.

One connection carries both directions. The phone sends requests (list
chats, open one, send a message, answer an approval) and receives every live
event (new messages, reply text as it streams, approvals) as notifications.
It works the same on the local network and through a tunnel such as
Cloudflare Tunnel. The protocol is described in docs/iphone-protocol.md.
"""

import asyncio
import inspect
import json
import logging
from time import monotonic
from typing import Any, Callable, Dict, Optional, Tuple, Type

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from app.schemas.contracts import ApprovalDecision, ThreadCreate, ThreadMessageRequest
from app.services.approval_broker import approval_broker
from app.services.auth_service import auth_service
from app.services.conversation_service import ConversationError, conversations
from app.services.device_service import device_service
from app.services.event_bus import event_bus
from app.services.host_info import computer_name, device_label
from app.services.request_guard import origin_is_trusted
from app.services.update_service import update_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["rpc"])

PROTOCOL_VERSION = 1
HEARTBEAT_SECONDS = 15
RECHECK_SECONDS = 1  # how often an open connection re-checks its credentials
CLOSE_NOT_LINKED = 4401  # the device must be linked (again) before connecting

# JSON-RPC 2.0 errors, plus application errors that carry an HTTP-style status.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
APP_ERRORS = {403: -32003, 404: -32004, 409: -32009, 422: -32022}


class ThreadRef(BaseModel):
    thread_id: str = Field(min_length=1, max_length=128)


class RenameThread(ThreadRef):
    title: str = Field(max_length=200)


class SendMessage(ThreadMessageRequest):
    # Without a thread_id, the message starts a new chat with bot_id.
    thread_id: Optional[str] = Field(default=None, max_length=128)
    bot_id: Optional[str] = Field(default=None, max_length=128)


class Empty(BaseModel):
    pass


class RpcFailure(Exception):
    def __init__(self, code: int, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.status = status


def _respond_to_approval(client: Dict[str, Any], params: ApprovalDecision) -> Dict[str, Any]:
    if not approval_broker.resolve(params.request_id, params.action):
        raise RpcFailure(APP_ERRORS[404], "Already answered or expired.", 404)
    return {"request_id": params.request_id, "action": params.action}


Handler = Callable[[Dict[str, Any], Any], Any]
METHODS: Dict[str, Tuple[Type[BaseModel], Handler]] = {
    "ping": (Empty, lambda client, params: {"pong": True}),
    "bots.list": (Empty, lambda client, params: conversations.storage.get_bots()),
    "threads.list": (Empty, lambda client, params: conversations.list_threads()),
    "threads.get": (ThreadRef, lambda client, params: conversations.get_thread(params.thread_id)),
    "threads.create": (ThreadCreate, lambda client, params: conversations.create_thread(params.bot_id, params.title)),
    "threads.rename": (RenameThread, lambda client, params: conversations.rename_thread(params.thread_id, params.title)),
    "messages.send": (SendMessage, lambda client, params: conversations.send_message(
        thread_id=params.thread_id,
        bot_id=params.bot_id,
        text=params.text,
        image_url=params.image_url,
        model=params.model,
        client_id=params.client_id,
        origin=client["name"],
    )),
    "approvals.respond": (ApprovalDecision, _respond_to_approval),
}


def _error(request_id: Any, code: int, message: str, status: Optional[int] = None) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if status:
        error["data"] = {"status": status}
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def authenticate(websocket: WebSocket) -> Optional[Dict[str, Any]]:
    """Who is connecting: the computer's own owner, or a linked device."""
    if auth_service.authenticate_request(websocket):
        return {"kind": "owner", "name": device_label()}
    device = device_service.authenticate_request(websocket)
    if device:
        return {"kind": "device", "name": device["name"], "device": device}
    return None


class RpcConnection:
    def __init__(self, websocket: WebSocket, client: Dict[str, Any]):
        self.websocket = websocket
        self.client = client
        self.send_lock = asyncio.Lock()
        self.open = True
        self.checked_at = monotonic()

    async def still_authorized(self, force: bool = False) -> bool:
        """Close the connection once its device is unlinked or its session ends.

        The unlink event alone isn't enough: it can be dropped when a client
        falls behind. Re-checking also keeps the device's "last active" fresh.
        """
        if not self.open:
            return False
        if not force and monotonic() - self.checked_at < RECHECK_SECONDS:
            return True
        self.checked_at = monotonic()
        if authenticate(self.websocket):
            return True
        self.open = False
        try:
            await self.websocket.close(code=CLOSE_NOT_LINKED, reason="This device was unlinked.")
        except Exception:  # already closed
            pass
        return False

    async def send(self, payload: Any) -> None:
        if not self.open:
            return
        async with self.send_lock:
            try:
                await self.websocket.send_text(json.dumps(payload))
            except Exception:  # the peer went away mid-send
                self.open = False

    async def serve(self) -> None:
        # Subscribe before greeting: the client reloads its state on "hello",
        # so nothing published after that reload can be missed.
        subscription = event_bus.subscribe()
        await self.send(self._event({
            "type": "hello",
            "protocol": PROTOCOL_VERSION,
            "computer": computer_name(),
            "device": self.client.get("device"),
            # Changes after the computer updates Open Dots: the phone reloads.
            "version": update_service.version,
        }))
        forwarder = asyncio.create_task(self._forward_events(subscription))
        requests = set()
        try:
            while self.open:
                raw = await self.websocket.receive_text()
                task = asyncio.create_task(self._handle(raw))
                requests.add(task)
                task.add_done_callback(requests.discard)
        except (WebSocketDisconnect, RuntimeError, KeyError):  # KeyError: a binary frame
            pass
        finally:
            self.open = False
            forwarder.cancel()
            for task in requests:
                task.cancel()
            event_bus.unsubscribe(subscription)

    @staticmethod
    def _event(event: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "method": "event", "params": event}

    async def _forward_events(self, subscription) -> None:
        device_id = (self.client.get("device") or {}).get("id")
        while self.open:
            try:
                event = await subscription.next(timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                # Keeps tunnels from closing an idle socket and lets clients
                # notice a connection that died silently.
                event = {"type": "heartbeat"}
            unlinked = device_id and event.get("type") == "device.unlinked" and event.get("deviceId") == device_id
            if not await self.still_authorized(force=bool(unlinked)):
                return
            await self.send(self._event(event))

    async def _handle(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except ValueError:
            await self.send(_error(None, PARSE_ERROR, "Parse error."))
            return
        if isinstance(data, list):
            if not data:
                await self.send(_error(None, INVALID_REQUEST, "Empty batch."))
                return
            responses = [response for item in data if (response := await self._dispatch(item)) is not None]
            if responses:
                await self.send(responses)
            return
        response = await self._dispatch(data)
        if response is not None:
            await self.send(response)

    async def _dispatch(self, item: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(item, dict) or item.get("jsonrpc") != "2.0" or not isinstance(item.get("method"), str):
            return _error(item.get("id") if isinstance(item, dict) else None, INVALID_REQUEST, "Invalid request.")
        request_id = item.get("id")
        is_notification = "id" not in item
        response = await self._call(request_id, item["method"], item.get("params", {}))
        return None if is_notification else response

    async def _call(self, request_id: Any, name: str, params: Any) -> Dict[str, Any]:
        if not await self.still_authorized(force=True):
            return _error(request_id, APP_ERRORS[403], "This device was unlinked.", 403)
        method = METHODS.get(name)
        if not method:
            return _error(request_id, METHOD_NOT_FOUND, f"Unknown method: {name}")
        if not isinstance(params, dict):
            return _error(request_id, INVALID_PARAMS, "Params must be an object.")
        model, handler = method
        try:
            result = handler(self.client, model.model_validate(params))
            if inspect.isawaitable(result):
                result = await result
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(part) for part in first.get("loc", ())) or "params"
            return _error(request_id, INVALID_PARAMS, f"{field}: {first.get('msg')}")
        except ConversationError as exc:
            return _error(request_id, APP_ERRORS.get(exc.status, -32000), str(exc), exc.status)
        except RpcFailure as exc:
            return _error(request_id, exc.code, str(exc), exc.status)
        except Exception:
            logger.exception("RPC method %s failed", name)
            return _error(request_id, INTERNAL_ERROR, "Something went wrong.")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


@router.websocket("/api/v1/rpc")
async def rpc_socket(websocket: WebSocket):
    if not origin_is_trusted(websocket):
        await websocket.close(code=1008)  # refused before the handshake completes
        return
    client = authenticate(websocket)
    await websocket.accept()
    if not client:
        # Accept, then close with a code a client can act on (link again).
        await websocket.close(code=CLOSE_NOT_LINKED, reason="Link this device first.")
        return
    await RpcConnection(websocket, client).serve()
