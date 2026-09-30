import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from app.main import app
from app.routers import threads as threads_router
from app.services.auth_service import auth_service
from app.services.event_bus import EventBus
from app.services.storage_service import StorageService
from app.services.turn_service import TurnService


class ScriptedProvider:
    """Streams scripted deltas; optionally pauses until released."""

    def __init__(self, deltas=("Hello ", "from ", "the Mac."), ok=True):
        self.deltas = deltas
        self.ok = ok
        self.gate = None
        self.calls = []

    async def stream_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        for index, delta in enumerate(self.deltas):
            if self.gate is not None and index == 1:
                await self.gate.wait()
            yield {"type": "content.delta", "delta": delta}
        yield {"type": "turn.completed", "ok": self.ok}


class ThreadApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.directory.name))
        self.bus = EventBus()
        self.provider = ScriptedProvider()
        self.turns = TurnService(storage=self.storage, bus=self.bus, provider=self.provider)
        self.patches = [
            patch.object(threads_router, "storage_service", self.storage),
            patch.object(threads_router, "event_bus", self.bus),
            patch.object(threads_router, "turn_service", self.turns),
        ]
        for item in self.patches:
            item.start()
        self.events = self.bus.subscribe()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12345)),
            base_url="http://127.0.0.1",
        )
        await self.client.post("/api/v1/auth/login", json={"token": auth_service.token})

    async def asyncTearDown(self):
        await self.client.aclose()
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def drain(self):
        events = []
        while not self.events.queue.empty():
            events.append(self.events.queue.get_nowait())
        return events

    async def new_thread(self, bot_id="bot-open-dots-1"):
        response = await self.client.post("/api/v1/threads", json={"bot_id": bot_id})
        self.assertEqual(response.status_code, 201)
        return response.json()

    async def test_legacy_per_assistant_history_becomes_a_thread(self):
        threads = (await self.client.get("/api/v1/threads")).json()
        self.assertEqual([thread["id"] for thread in threads], ["bot-open-dots-1"])
        self.assertEqual(threads[0]["bot_id"], "bot-open-dots-1")
        self.assertEqual(threads[0]["last_message"]["sender"], "bot")
        # Backfill is idempotent across restarts.
        reopened = StorageService(Path(self.directory.name))
        self.assertEqual(len(reopened.get_threads()), 1)

    async def test_message_runs_a_background_turn_and_every_client_sees_it(self):
        thread = await self.new_thread()
        self.drain()
        response = await self.client.post(
            f"/api/v1/threads/{thread['id']}/messages",
            json={"text": "Plan my week\nwith details", "client_id": "c-1"},
        )
        self.assertEqual(response.status_code, 202)
        message = response.json()["message"]
        self.assertEqual(message["origin"], "Computer")
        self.assertEqual(message["client_id"], "c-1")
        await self.turns.wait(thread["id"])

        events = self.drain()
        types = [event["type"] for event in events]
        self.assertEqual(types[0], "message.created")
        self.assertIn("turn.started", types)
        self.assertEqual(types[-1], "thread.updated")
        self.assertTrue(all(event.get("threadId") == thread["id"] for event in events))
        deltas = [event for event in events if event["type"] == "content.delta"]
        self.assertEqual([event["offset"] for event in deltas], [0, 6, 11])
        completed = next(event for event in events if event["type"] == "turn.completed")
        self.assertTrue(completed["ok"])
        self.assertEqual(completed["message"]["text"], "Hello from the Mac.")

        detail = (await self.client.get(f"/api/v1/threads/{thread['id']}")).json()
        self.assertEqual([m["sender"] for m in detail["messages"]], ["user", "bot"])
        self.assertEqual(detail["thread"]["title"], "Plan my week")
        self.assertEqual(detail["thread"]["status"], "idle")
        self.assertEqual(detail["turn"]["status"], "completed")
        listed = (await self.client.get("/api/v1/threads")).json()
        self.assertEqual(listed[0]["id"], thread["id"])
        self.assertEqual(listed[0]["last_message"]["text"], "Hello from the Mac.")

    async def test_joining_mid_reply_sees_partial_text_and_second_message_waits(self):
        self.provider.gate = asyncio.Event()
        thread = await self.new_thread()
        await self.client.post(f"/api/v1/threads/{thread['id']}/messages", json={"text": "Hi"})
        for _ in range(20):
            await asyncio.sleep(0)
        detail = (await self.client.get(f"/api/v1/threads/{thread['id']}")).json()
        self.assertEqual(detail["thread"]["status"], "running")
        self.assertEqual(detail["turn"]["text"], "Hello ")
        busy = await self.client.post(f"/api/v1/threads/{thread['id']}/messages", json={"text": "Again"})
        self.assertEqual(busy.status_code, 409)
        self.assertEqual((await self.client.delete(f"/api/v1/threads/{thread['id']}")).status_code, 409)

        self.provider.gate.set()
        await self.turns.wait(thread["id"])
        detail = (await self.client.get(f"/api/v1/threads/{thread['id']}")).json()
        self.assertEqual(detail["messages"][-1]["text"], "Hello from the Mac.")

    async def test_failed_reply_is_kept_but_left_out_of_model_context(self):
        self.provider.ok = False
        self.provider.deltas = ("Inference request failed",)
        thread = await self.new_thread()
        await self.client.post(f"/api/v1/threads/{thread['id']}/messages", json={"text": "One"})
        await self.turns.wait(thread["id"])
        self.provider.ok = True
        await self.client.post(f"/api/v1/threads/{thread['id']}/messages", json={"text": "Two"})
        await self.turns.wait(thread["id"])

        messages = self.storage.get_messages(thread_id=thread["id"])
        self.assertTrue(messages[1]["is_error"])
        sent = self.provider.calls[-1]["messages"]
        self.assertEqual([m["content"] for m in sent], ["One", "Two"])

    async def test_approval_is_shared_and_resolved_from_any_client(self):
        thread = await self.new_thread()
        self.drain()
        await self.client.post(f"/api/v1/threads/{thread['id']}/messages", json={"text": "/workspace list ."})
        opened = None
        for _ in range(50):
            await asyncio.sleep(0)
            opened = next((e for e in self.drain() if e["type"] == "request.opened"), opened)
            if opened:
                break
        self.assertIsNotNone(opened)
        waiting = (await self.client.get("/api/v1/threads")).json()[0]
        self.assertEqual(waiting["status"], "waiting")

        answer = await self.client.post(
            "/api/v1/approvals/respond", json={"request_id": opened["requestId"], "action": "deny"}
        )
        self.assertEqual(answer.status_code, 200)
        await self.turns.wait(thread["id"])
        events = self.drain()
        resolved = next(e for e in events if e["type"] == "request.resolved")
        self.assertEqual(resolved["decision"], "deny")
        self.assertIn("tool.denied", [e["type"] for e in events])
        snapshot = (await self.client.get(f"/api/v1/threads/{thread['id']}")).json()["turn"]
        self.assertEqual(snapshot["approvals"][0]["status"], "deny")

    async def test_validation_rename_and_delete(self):
        self.assertEqual((await self.client.post("/api/v1/threads", json={"bot_id": "missing"})).status_code, 404)
        thread = await self.new_thread()
        empty = await self.client.post(f"/api/v1/threads/{thread['id']}/messages", json={"text": "  "})
        self.assertEqual(empty.status_code, 422)
        script = await self.client.post(
            f"/api/v1/threads/{thread['id']}/messages",
            json={"text": "x", "image_url": "javascript:alert(1)"},
        )
        self.assertEqual(script.status_code, 422)

        renamed = await self.client.patch(f"/api/v1/threads/{thread['id']}", json={"title": "Trip"})
        self.assertEqual(renamed.json()["title"], "Trip")
        self.drain()
        self.assertEqual((await self.client.delete(f"/api/v1/threads/{thread['id']}")).status_code, 200)
        self.assertEqual(self.drain()[-1], {"type": "thread.deleted", "threadId": thread["id"]})
        self.assertEqual((await self.client.get(f"/api/v1/threads/{thread['id']}")).status_code, 404)


class EventStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_greets_then_relays_published_events(self):
        from app.routers import events as events_router

        bus = EventBus()
        request = Mock()
        disconnected = iter([False, True])

        async def is_disconnected():
            return next(disconnected)

        request.is_disconnected = is_disconnected
        with patch.object(events_router, "event_bus", bus):
            response = await events_router.stream_events(request)
            stream = response.body_iterator
            hello = await stream.__anext__()
            self.assertEqual(json.loads(hello["data"])["type"], "hello")
            self.assertEqual(bus.subscriber_count, 1)
            bus.publish({"type": "thread.deleted", "threadId": "t"})
            relayed = await stream.__anext__()
            self.assertEqual(json.loads(relayed["data"])["threadId"], "t")
            with self.assertRaises(StopAsyncIteration):
                await stream.__anext__()
        self.assertEqual(bus.subscriber_count, 0)

    async def test_overflowing_client_is_told_to_resync(self):
        bus = EventBus(max_queue=2)
        subscription = bus.subscribe()
        for index in range(3):
            bus.publish({"type": "content.delta", "offset": index})
        self.assertEqual(await subscription.next(), {"type": "resync"})
        self.assertTrue(subscription.queue.empty())


if __name__ == "__main__":
    unittest.main()
