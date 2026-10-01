import tempfile
import unittest
from pathlib import Path

from app.routers.audit import summarize_model_usage
from app.services.event_bus import EventBus
from app.services.storage_service import StorageService
from app.services.turn_service import TurnService

USAGE = {"input_tokens": 1200, "cached_tokens": 1000, "output_tokens": 40, "reasoning_tokens": 0, "cost_usd": 0.0045}


class FakeProvider:
    def __init__(self, usage):
        self.usage = usage

    async def stream_chat_completion(self, **kwargs):
        yield {"type": "content.delta", "delta": "Done."}
        yield {"type": "turn.completed", "ok": True, **({"usage": self.usage} if self.usage else {})}


class ModelUsageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage = StorageService(Path(self.directory.name))
        self.bot = self.storage.get_bots()[0]

    async def reply(self, usage):
        turns = TurnService(storage=self.storage, bus=EventBus(), provider=FakeProvider(usage))
        thread = {"id": f"thr-{len(self.storage.get_audit_events(500))}", "bot_id": self.bot["id"], "title": ""}
        self.storage.save_thread(thread)
        self.storage.add_message({"id": f"m-{thread['id']}", "thread_id": thread["id"], "sender": "user", "text": "hi"})
        turns.start(thread["id"], self.bot["id"], "anthropic/claude-sonnet-5.5")
        await turns.wait(thread["id"])
        return thread["id"]

    async def test_a_reply_records_its_usage_on_the_message_and_in_the_audit_trail(self):
        thread_id = await self.reply(USAGE)
        reply = self.storage.get_messages(thread_id)[-1]
        self.assertEqual(reply["usage"], USAGE)
        events = self.storage.get_audit_events_since("2000-01-01", "model.reply")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["model"], "anthropic/claude-sonnet-5.5")
        self.assertEqual(events[0]["thread_id"], thread_id)
        self.assertEqual(events[0]["cost_usd"], 0.0045)

    async def test_a_reply_without_usage_records_nothing(self):
        await self.reply(None)
        self.assertEqual(self.storage.get_audit_events_since("2000-01-01", "model.reply"), [])

    def test_the_summary_adds_up_per_model_costliest_first(self):
        summary = summarize_model_usage([
            {"model": "a", **USAGE},
            {"model": "b", **USAGE, "cost_usd": 0.01},
            {"model": "a", **USAGE, "cost_usd": None},
        ])
        self.assertEqual(summary["replies"], 3)
        self.assertEqual(summary["input_tokens"], 3600)
        self.assertEqual(summary["cached_tokens"], 3000)
        self.assertAlmostEqual(summary["cost_usd"], 0.0145)
        self.assertEqual(summary["replies_without_cost"], 1)
        self.assertEqual([m["model"] for m in summary["models"]], ["b", "a"])
        self.assertEqual(summary["models"][1]["replies"], 2)


if __name__ == "__main__":
    unittest.main()
