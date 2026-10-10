import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.services import coding_agent as coding_module
from app.services.approval_broker import approval_broker
from app.services.coding_agent import CodingAgentError, build_config, model_ref, validate_project_dir
from app.services.event_bus import EventBus
from app.services.storage_service import StorageService
from app.services.turn_service import TurnService, tool_subject

SESSION = "ses_test"


def assistant(message_id, completed=False, cost=0.0, tokens=None):
    info = {"id": message_id, "role": "assistant", "sessionID": SESSION, "cost": cost,
            "tokens": tokens or {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}},
            "time": {"created": 1, **({"completed": 2} if completed else {})}}
    return {"type": "message.updated", "properties": {"sessionID": SESSION, "info": info}}


def delta(message_id, part_id, text):
    return {"type": "message.part.delta", "properties": {
        "sessionID": SESSION, "messageID": message_id, "partID": part_id, "field": "text", "delta": text}}


def tool(message_id, status, **state):
    return {"type": "message.part.updated", "properties": {"sessionID": SESSION, "part": {
        "id": "prt_tool", "sessionID": SESSION, "messageID": message_id, "type": "tool", "callID": "call_1",
        "tool": "bash", "state": {"status": status, "input": {"command": "npm test"}, **state}}}}


class FakeAgent:
    """Stands in for OpenCode: replays a script of events for each prompt."""

    def __init__(self, script):
        self.script = script
        self.queues = []
        self.prompts = []
        self.replies = []
        self.created = 0
        self.aborted = 0
        self.fail_start = None
        self.replied = asyncio.Event()

    async def ensure_running(self):
        if self.fail_start:
            raise CodingAgentError(self.fail_start)

    def listen(self, session_id):
        queue = asyncio.Queue()
        self.queues.append(queue)
        return queue

    def unlisten(self, session_id, queue):
        self.queues.remove(queue)

    async def session_exists(self, session_id, directory):
        return session_id == SESSION

    async def create_session(self, directory, title):
        self.created += 1
        return SESSION

    async def prompt(self, session_id, directory, text, image_url, model):
        self.prompts.append({"text": text, "image_url": image_url, "model": model, "directory": directory})
        asyncio.get_running_loop().create_task(self._play())

    async def _play(self):
        for event in self.script:
            if event == "WAIT_FOR_REPLY":
                await self.replied.wait()
                continue
            for queue in list(self.queues):
                queue.put_nowait(event)
            await asyncio.sleep(0)

    async def abort(self, session_id, directory):
        self.aborted += 1

    async def reply_permission(self, request_id, directory, reply):
        self.replies.append((request_id, reply))
        self.replied.set()


SCRIPT = [
    assistant("msg_1"),
    delta("msg_1", "prt_a", "Running "),
    delta("msg_1", "prt_a", "the tests."),
    tool("msg_1", "running", time={"start": 1}),
    {"type": "permission.asked", "properties": {
        "id": "per_1", "sessionID": SESSION, "permission": "bash", "patterns": ["npm test"],
        "metadata": {"command": "npm test"}, "always": ["npm *"], "tool": {"messageID": "msg_1", "callID": "call_1"}}},
    "WAIT_FOR_REPLY",
    tool("msg_1", "completed", output="ok " * 2000, title="npm test", metadata={}, time={"start": 1, "end": 2}),
    assistant("msg_1", completed=True, cost=0.01,
              tokens={"input": 100, "output": 20, "reasoning": 5, "cache": {"read": 900, "write": 0}}),
    assistant("msg_2"),
    delta("msg_2", "prt_b", "All green."),
    assistant("msg_2", completed=True, cost=0.002,
              tokens={"input": 50, "output": 4, "reasoning": 0, "cache": {"read": 1000, "write": 0}}),
    {"type": "session.idle", "properties": {"sessionID": SESSION}},
]


class CodingTurnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.directory.name))
        self.storage.save_settings({"model_api_base_url": "https://ai-gateway.vercel.sh/v1", "model_api_key": "vck"})
        self.project = Path(self.directory.name) / "project"
        self.project.mkdir()
        bots = self.storage.get_bots()
        self.storage.save_bots([*bots, {**bots[0], "id": "bot-code", "engine": "opencode",
                                        "project_dir": str(self.project), "model": "moonshotai/kimi-k2"}])
        self.bus = EventBus()
        self.events = self.bus.subscribe()
        self.agent = FakeAgent(SCRIPT)
        self.turns = TurnService(storage=self.storage, bus=self.bus, coding=self.agent)
        self.thread = {"id": "thr-code", "bot_id": "bot-code", "title": "Tests", "created_at": "now"}
        self.storage.save_thread(self.thread)

    async def asyncTearDown(self):
        self.directory.cleanup()

    def say(self, text):
        self.storage.add_message({"id": f"m-{text}", "thread_id": "thr-code", "bot_id": "bot-code",
                                  "sender": "user", "text": text, "created_at": "now"})

    async def answer_approval(self, decision):
        while True:
            event = await self.events.next(timeout=5)
            if event["type"] == "request.opened":
                self.assertEqual(event["requestId"], "call_1")  # the same step as the tool call
                self.assertEqual(event["summary"], "bash: npm test")
                self.assertEqual(event["always"], ["npm *"])
                self.assertTrue(approval_broker.resolve(event["requestId"], decision))
                return

    async def test_reply_tools_approval_and_usage(self):
        self.say("run the tests")
        state = self.turns.start("thr-code", "bot-code")
        await self.answer_approval("always")
        await asyncio.wait_for(self.turns.wait("thr-code"), 5)

        self.assertEqual(self.agent.replies, [("per_1", "always")])
        self.assertEqual(self.agent.prompts[0]["text"], "run the tests")
        self.assertEqual(self.agent.prompts[0]["directory"], str(self.project))
        self.assertEqual(self.agent.prompts[0]["model"], {"providerID": "vercel", "modelID": "moonshotai/kimi-k2"})

        message = self.storage.get_last_message("thr-code")
        self.assertEqual(message["text"], "Running the tests.\n\nAll green.")
        self.assertFalse(message["is_error"])
        self.assertEqual(message["usage"]["input_tokens"], 100 + 900 + 50 + 1000)
        self.assertEqual(message["usage"]["cached_tokens"], 1900)
        self.assertEqual(message["usage"]["output_tokens"], 24)
        self.assertAlmostEqual(message["usage"]["cost_usd"], 0.012)
        self.assertEqual(message["usage"]["model_calls"], 2)

        steps = {step["requestId"]: step for step in state.tools}
        self.assertEqual(steps["call_1"]["type"], "tool.completed")
        self.assertEqual(steps["call_1"]["action"]["preview"], "bash: npm test")
        self.assertLessEqual(len(steps["call_1"]["result"]["output"]), 2002)
        self.assertEqual(state.approvals["call_1"]["status"], "always")
        audit = [event for event in self.storage.get_audit_events(50) if event.get("event") == "model.reply"]
        self.assertEqual(audit[0]["thread_id"], "thr-code")

        # The conversation keeps its OpenCode session.
        self.assertEqual(self.storage.get_thread("thr-code")["opencode_session_id"], SESSION)
        self.agent.replied = asyncio.Event()
        self.say("again")
        self.turns.start("thr-code", "bot-code")
        await self.answer_approval("deny")
        await asyncio.wait_for(self.turns.wait("thr-code"), 5)
        self.assertEqual(self.agent.created, 1)
        self.assertEqual(self.agent.replies[-1], ("per_1", "reject"))

    async def test_streamed_text_matches_offsets(self):
        self.say("run the tests")
        self.turns.start("thr-code", "bot-code")
        text = ""
        while True:
            event = await self.events.next(timeout=5)
            if event["type"] == "request.opened":
                approval_broker.resolve(event["requestId"], "allow")
            if event["type"] == "content.delta":
                self.assertEqual(event["offset"], len(text))
                text += event["delta"]
            if event["type"] == "turn.completed":
                self.assertEqual(event["message"]["text"], text)
                break

    async def test_missing_provider_fails_the_reply_with_a_reason(self):
        self.agent.fail_start = "Add your model provider first."
        self.say("hi")
        self.turns.start("thr-code", "bot-code")
        await asyncio.wait_for(self.turns.wait("thr-code"), 5)
        message = self.storage.get_last_message("thr-code")
        self.assertTrue(message["is_error"])
        self.assertIn("Add your model provider first.", message["text"])
        self.assertEqual(self.turns.status("thr-code"), "idle")

    async def test_lost_connection_ends_the_reply(self):
        self.agent.script = [assistant("msg_1"), delta("msg_1", "prt_a", "Half"),
                             {"type": "agent.disconnected", "properties": {}}]
        self.say("hi")
        self.turns.start("thr-code", "bot-code")
        await asyncio.wait_for(self.turns.wait("thr-code"), 5)
        message = self.storage.get_last_message("thr-code")
        self.assertTrue(message["is_error"])
        self.assertTrue(message["text"].startswith("Half"))

    async def test_text_without_deltas_still_arrives(self):
        part = {"id": "prt_x", "sessionID": SESSION, "messageID": "msg_1", "type": "text", "text": "Whole answer"}
        self.agent.script = [assistant("msg_1"),
                             {"type": "message.part.updated", "properties": {"sessionID": SESSION, "part": part}},
                             {"type": "session.idle", "properties": {"sessionID": SESSION}}]
        self.say("hi")
        self.turns.start("thr-code", "bot-code")
        await asyncio.wait_for(self.turns.wait("thr-code"), 5)
        self.assertEqual(self.storage.get_last_message("thr-code")["text"], "Whole answer")

    async def test_cancelled_reply_stops_opencode(self):
        self.agent.script = [assistant("msg_1"), "WAIT_FOR_REPLY"]
        self.say("hi")
        self.turns.start("thr-code", "bot-code")
        await asyncio.sleep(0.05)
        self.turns._tasks["thr-code"].cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.turns.wait("thr-code")
        self.assertEqual(self.agent.aborted, 1)


class ConfigTests(unittest.TestCase):
    def test_vercel_uses_opencodes_own_provider_and_keeps_the_key_out_of_the_file(self):
        prepared = build_config({"model_api_base_url": "https://ai-gateway.vercel.sh/v1", "model_api_key": "vck_secret",
                                 "model_ids": ["moonshotai/kimi-k2"], "default_model": "anthropic/claude-sonnet-4.5"})
        config = prepared["config"]
        self.assertEqual(prepared["env"], {"AI_GATEWAY_API_KEY": "vck_secret"})
        self.assertNotIn("vck_secret", json.dumps(config))
        self.assertEqual(config["model"], "vercel/anthropic/claude-sonnet-4.5")
        self.assertEqual(config["small_model"], config["model"])
        self.assertEqual(set(config["provider"]["vercel"]["models"]), {"moonshotai/kimi-k2", "anthropic/claude-sonnet-4.5"})
        self.assertEqual(config["permission"]["*"], "ask")
        self.assertEqual(config["permission"]["read"]["*.env"], "deny")
        self.assertFalse(config["autoupdate"])
        self.assertEqual(config["share"], "disabled")

    def test_other_services_use_an_openai_compatible_provider(self):
        prepared = build_config({"model_api_base_url": "https://llm.example.com/v1", "model_api_key": "sk",
                                 "model_api_headers": {"X-Team": "t1"}, "default_model": "m1"})
        provider = prepared["config"]["provider"]["opendots"]
        self.assertEqual(provider["npm"], "@ai-sdk/openai-compatible")
        self.assertEqual(provider["options"]["baseURL"], "https://llm.example.com/v1")
        self.assertEqual(provider["options"]["apiKey"], "{env:OPEN_DOTS_MODEL_API_KEY}")
        self.assertEqual(provider["options"]["headers"], {"X-Team": "{env:OPEN_DOTS_HEADER_0}"})
        self.assertEqual(prepared["env"], {"OPEN_DOTS_MODEL_API_KEY": "sk", "OPEN_DOTS_HEADER_0": "t1"})
        self.assertNotIn("t1", json.dumps(prepared["config"]))
        self.assertEqual(model_ref("m1", {"model_api_base_url": "https://llm.example.com/v1"}),
                         {"providerID": "opendots", "modelID": "m1"})

    def test_a_provider_is_required(self):
        with patch.object(settings, "MODEL_API_BASE_URL", ""), patch.object(settings, "MODEL_API_KEY", ""):
            with self.assertRaises(CodingAgentError):
                build_config({})

    def test_tool_subjects(self):
        self.assertEqual(tool_subject("edit", {"filePath": "/x/app.py"}), "edit: /x/app.py")
        self.assertEqual(tool_subject("bash", {"command": "ls\n  -la"}), "bash: ls -la")
        self.assertEqual(tool_subject("todowrite", {}), "todowrite")


class ProjectFolderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()

    def tearDown(self):
        self.directory.cleanup()

    def test_accepts_an_existing_folder(self):
        self.assertEqual(validate_project_dir(str(self.root)), str(self.root))
        self.assertEqual(validate_project_dir(""), "")

    def test_refuses_what_isnt_a_project(self):
        app_root = Path(coding_module.__file__).resolve().parents[3]
        for value in ("relative/path", str(self.root / "missing"), str(Path.home()), "/", str(app_root),
                      str(app_root / "server"), str(settings.DATA_DIR)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_project_dir(value)

    def test_accepts_a_folder_under_the_projects_folder(self):
        folder = settings.PROJECTS_DIR / "unit-test-project"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            self.assertEqual(validate_project_dir(str(folder)), str(folder))
        finally:
            folder.rmdir()


class AlwaysTests(unittest.IsolatedAsyncioTestCase):
    async def test_always_counts_as_allow_where_it_isnt_offered(self):
        call = type("Call", (), {"name": "workspace.write", "summary": "Write", "arguments_for_display": {}})()
        approval = approval_broker.open("thr", "bot", call)
        waiting = asyncio.create_task(approval_broker.wait(approval["request_id"]))
        await asyncio.sleep(0)
        self.assertTrue(approval_broker.resolve(approval["request_id"], "always"))
        self.assertEqual(await waiting, "allow")


if __name__ == "__main__":
    unittest.main()
