import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.routers import devices as devices_router
from app.routers import rpc as rpc_router
from app.services.auth_service import auth_service
from app.services.conversation_service import ConversationService
from app.services.device_service import DeviceService
from app.services.event_bus import EventBus
from app.services.storage_service import StorageService
from app.services.turn_service import TurnService

IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"


class ScriptedProvider:
    def __init__(self):
        self.calls = []

    async def stream_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        for delta in ("Hi ", "from ", "the Mac."):
            yield {"type": "content.delta", "delta": delta}
        yield {"type": "turn.completed", "ok": True}


class RpcSocketTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.directory.name))
        self.bus = EventBus()
        self.provider = ScriptedProvider()
        self.turns = TurnService(storage=self.storage, bus=self.bus, provider=self.provider)
        self.devices = DeviceService(self.storage.database)
        self.patches = [
            patch.object(rpc_router, "conversations", ConversationService(self.storage, self.bus, self.turns)),
            patch.object(rpc_router, "event_bus", self.bus),
            patch.object(rpc_router, "device_service", self.devices),
            patch.object(devices_router, "device_service", self.devices),
            patch.object(devices_router, "event_bus", self.bus),
            patch("app.main.device_service", self.devices),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(app)
        _, self.token = self.devices.redeem(self.devices.create_pairing_code()["code"], IPHONE_UA)
        self.next_id = 0

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def connect(self, **kwargs):
        headers = kwargs.pop("headers", {"Authorization": f"Bearer {self.token}"})
        return self.client.websocket_connect("/api/v1/rpc", headers=headers, **kwargs)

    def call(self, ws, method, params=None):
        """Send a request; return its response and the notifications seen meanwhile."""
        self.next_id += 1
        ws.send_json({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        events = []
        while True:
            message = ws.receive_json()
            if message.get("id") == self.next_id:
                return message, events
            events.append(message["params"])

    @staticmethod
    def events_until(ws, event_type, events=None):
        events = list(events or [])
        while not any(event["type"] == event_type for event in events):
            events.append(ws.receive_json()["params"])
        return events

    def test_unlinked_and_cross_site_connections_are_refused(self):
        with self.connect(headers={}) as ws:
            with self.assertRaises(WebSocketDisconnect) as closed:
                ws.receive_json()
        self.assertEqual(closed.exception.code, rpc_router.CLOSE_NOT_LINKED)

        with self.assertRaises(WebSocketDisconnect) as refused:
            with self.connect(headers={"Authorization": f"Bearer {self.token}", "Origin": "https://evil.example"}):
                pass
        self.assertEqual(refused.exception.code, 1008)

    def test_greets_then_lists(self):
        with self.connect() as ws:
            hello = ws.receive_json()
            self.assertEqual(hello["method"], "event")
            self.assertEqual(hello["params"]["type"], "hello")
            self.assertEqual(hello["params"]["protocol"], 1)
            self.assertEqual(hello["params"]["device"]["name"], "iPhone")
            threads, _ = self.call(ws, "threads.list")
            self.assertEqual([t["id"] for t in threads["result"]], ["bot-open-dots-1"])
            bots, _ = self.call(ws, "bots.list")
            self.assertEqual(len(bots["result"]), 4)

    def test_send_starts_a_chat_and_streams_the_reply_as_notifications(self):
        with self.connect() as ws:
            ws.receive_json()  # hello
            response, events = self.call(ws, "messages.send", {"bot_id": "bot-claude-1", "text": "Plan the trip", "client_id": "c-1"})
            result = response["result"]
            self.assertEqual(result["message"]["origin"], "iPhone")
            self.assertEqual(result["thread"]["title"], "Plan the trip")
            events = self.events_until(ws, "turn.completed", events)
            types = [event["type"] for event in events]
            self.assertIn("thread.created", types)
            self.assertIn("message.created", types)
            deltas = "".join(event["delta"] for event in events if event["type"] == "content.delta")
            self.assertEqual(deltas, "Hi from the Mac.")

            detail, _ = self.call(ws, "threads.get", {"thread_id": result["thread"]["id"]})
            self.assertEqual([m["sender"] for m in detail["result"]["messages"]], ["user", "bot"])

            # A retry after a lost response returns the first message instead of posting twice.
            again, _ = self.call(ws, "messages.send", {"bot_id": "bot-claude-1", "text": "Plan the trip", "client_id": "c-1"})
            self.assertTrue(again["result"]["duplicate"])
            self.assertEqual(again["result"]["message"]["id"], result["message"]["id"])
            self.assertEqual(len(self.provider.calls), 1)

    def test_protocol_errors(self):
        with self.connect() as ws:
            ws.receive_json()
            ws.send_text("{not json")
            self.assertEqual(ws.receive_json()["error"]["code"], rpc_router.PARSE_ERROR)
            ws.send_json({"id": 1, "method": "ping"})
            self.assertEqual(ws.receive_json()["error"]["code"], rpc_router.INVALID_REQUEST)
            unknown, _ = self.call(ws, "settings.save")
            self.assertEqual(unknown["error"]["code"], rpc_router.METHOD_NOT_FOUND)
            invalid, _ = self.call(ws, "messages.send", {"thread_id": "t", "text": "x", "image_url": "javascript:alert(1)"})
            self.assertEqual(invalid["error"]["code"], rpc_router.INVALID_PARAMS)
            missing, _ = self.call(ws, "threads.get", {"thread_id": "nope"})
            self.assertEqual(missing["error"]["data"]["status"], 404)
            answered, _ = self.call(ws, "approvals.respond", {"request_id": "req-gone", "action": "allow"})
            self.assertEqual(answered["error"]["data"]["status"], 404)

            ws.send_json([
                {"jsonrpc": "2.0", "id": "a", "method": "ping"},
                {"jsonrpc": "2.0", "method": "ping"},  # a notification gets no response
                {"jsonrpc": "2.0", "id": "b", "method": "nope"},
            ])
            batch = ws.receive_json()
            while not isinstance(batch, list):  # skip heartbeats or other events
                batch = ws.receive_json()
            self.assertEqual([item["id"] for item in batch], ["a", "b"])
            self.assertEqual(batch[0]["result"], {"pong": True})

    def test_approval_answered_over_the_socket(self):
        with self.connect() as ws:
            ws.receive_json()
            self.call(ws, "messages.send", {"bot_id": "bot-open-dots-1", "text": "/workspace list ."})
            events = self.events_until(ws, "request.opened")
            request = next(event for event in events if event["type"] == "request.opened")
            answer, events = self.call(ws, "approvals.respond", {"request_id": request["requestId"], "action": "deny"})
            self.assertEqual(answer["result"]["action"], "deny")
            events = self.events_until(ws, "turn.completed", events)
            self.assertIn("tool.denied", [event["type"] for event in events])

    def test_unlinking_closes_the_socket(self):
        device_id = self.devices.list_devices()[0]["id"]
        # A separate client, so the phone's socket doesn't carry the owner's cookie.
        with self.client, TestClient(app) as owner:
            owner.post("/api/v1/auth/login", json={"token": auth_service.token})
            with self.connect() as ws:
                ws.receive_json()
                self.assertEqual(owner.delete(f"/api/v1/devices/{device_id}").status_code, 200)
                with self.assertRaises(WebSocketDisconnect) as closed:
                    while True:
                        ws.receive_json()
        self.assertEqual(closed.exception.code, rpc_router.CLOSE_NOT_LINKED)

    def test_unlinked_device_is_cut_off_even_if_the_event_is_lost(self):
        with self.connect() as ws:
            ws.receive_json()
            device_id = self.devices.list_devices()[0]["id"]
            self.devices.revoke(device_id)  # no device.unlinked event reaches the socket
            with self.assertRaises(WebSocketDisconnect) as closed:
                self.call(ws, "messages.send", {"bot_id": "bot-open-dots-1", "text": "Still here?"})
        self.assertEqual(closed.exception.code, rpc_router.CLOSE_NOT_LINKED)
        self.assertFalse(any(m.get("text") == "Still here?" for m in self.storage.get_messages()))

    def test_tunnel_address_is_a_trusted_origin(self):
        headers = {"Authorization": f"Bearer {self.token}", "Origin": "https://dots.example.com", "Host": "dots.example.com"}
        with patch.object(rpc_router.origin_is_trusted.__globals__["settings"], "PUBLIC_URL", "https://dots.example.com"):
            with self.connect(headers=headers) as ws:
                self.assertEqual(ws.receive_json()["params"]["type"], "hello")
            listed = self.client.get("/api/v1/threads", headers=headers)
            self.assertEqual(listed.status_code, 200)
            elsewhere = self.client.get("/api/v1/threads", headers={**headers, "Origin": "https://evil.example"})
            self.assertEqual(elsewhere.status_code, 403)

    def test_owner_session_can_connect(self):
        with self.client as owner:
            owner.post("/api/v1/auth/login", json={"token": auth_service.token})
            with owner.websocket_connect("/api/v1/rpc") as ws:
                self.assertEqual(ws.receive_json()["params"]["type"], "hello")
                pong, _ = self.call(ws, "ping")
                self.assertEqual(pong["result"], {"pong": True})


if __name__ == "__main__":
    unittest.main()
