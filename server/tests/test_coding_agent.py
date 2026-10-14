import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import settings
from app.services import coding_agent as coding_module
from app.services.approval_broker import approval_broker
from app.services.coding_agent import (
    PERMISSIONS, CodingAgentError, agent_environment, build_config, coding_instructions, enforced_config, model_ref,
    opencode_can_reply, project_plugins, uses_opencode, validate_project_dir,
)
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


def tool(message_id, status, call_id="call_1", **state):
    return {"type": "message.part.updated", "properties": {"sessionID": SESSION, "part": {
        "id": f"prt_{call_id}", "sessionID": SESSION, "messageID": message_id, "type": "tool", "callID": call_id,
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
        self.fail_prompt = None
        self.replied = asyncio.Event()

    def model(self, model):
        return {"providerID": "vercel", "modelID": model}

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

    async def prompt(self, session_id, directory, text, image_url, model, system="", context=""):
        if self.fail_prompt:
            raise CodingAgentError(self.fail_prompt)
        self.prompts.append({"text": text, "image_url": image_url, "model": model, "directory": directory,
                             "system": system, "context": context})
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


class CodingTurnCase(unittest.IsolatedAsyncioTestCase):
    """A coding assistant, its project folder and a stand-in OpenCode."""

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



class CodingTurnTests(CodingTurnCase):
    async def test_reply_tools_approval_and_usage(self):
        self.say("run the tests")
        state = self.turns.start("thr-code", "bot-code")
        await self.answer_approval("always")
        await asyncio.wait_for(self.turns.wait("thr-code"), 5)

        self.assertEqual(self.agent.replies, [("per_1", "always")])
        self.assertEqual(self.agent.prompts[0]["text"], "run the tests")
        self.assertEqual(self.agent.prompts[0]["directory"], str(self.project))
        self.assertEqual(self.agent.prompts[0]["model"], {"providerID": "vercel", "modelID": "moonshotai/kimi-k2"})
        self.assertIn("approves them on one of their devices", self.agent.prompts[0]["system"])

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

    async def test_a_project_with_plugins_is_refused_before_opencode_sees_it(self):
        (self.project / ".opencode" / "plugin").mkdir(parents=True)
        (self.project / ".opencode" / "plugin" / "x.js").write_text("export const X = async () => ({})")
        self.say("hi")
        self.turns.start("thr-code", "bot-code")
        await asyncio.wait_for(self.turns.wait("thr-code"), 5)
        message = self.storage.get_last_message("thr-code")
        self.assertTrue(message["is_error"])
        self.assertIn("plugins", message["text"])
        self.assertEqual(self.agent.prompts, [])
        self.assertEqual(self.agent.created, 0)

    async def test_cancelled_reply_stops_opencode(self):
        self.agent.script = [assistant("msg_1"), "WAIT_FOR_REPLY"]
        self.say("hi")
        self.turns.start("thr-code", "bot-code")
        await asyncio.sleep(0.05)
        self.turns._tasks["thr-code"].cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.turns.wait("thr-code")
        self.assertEqual(self.agent.aborted, 1)


QUICK_REPLY = [
    assistant("msg_q"),
    delta("msg_q", "prt_q", "Sure."),
    assistant("msg_q", completed=True),
    {"type": "session.idle", "properties": {"sessionID": SESSION}},
]


class StraightFromTheModel:
    """Stands in for the model provider, for assistants that reply without OpenCode."""

    def __init__(self):
        self.calls = 0

    async def stream_chat_completion(self, **kwargs):
        self.calls += 1
        yield {"type": "content.delta", "delta": "Text only."}
        yield {"type": "turn.completed", "ok": True}


class SearchGateway:
    """Stands in for the action gateway: every command runs, with a fixed result."""

    def __init__(self):
        self.opened = []

    def open(self, thread_id, bot_id, call):
        self.opened.append(call.name)
        tool, action = call.name.split(".", 1)
        return SimpleNamespace(request_id="req-1", tool=tool, action=action, model_dump=lambda: {}), None

    async def wait_for_decision(self, request):
        return "allow"

    async def execute(self, request):
        return SimpleNamespace(status="completed", result={"results": ["opendots.dev"]}, error=None)


class EveryAssistantTests(unittest.IsolatedAsyncioTestCase):
    """Every assistant replies through OpenCode, unless it is text only or the
    provider is one OpenCode can't use."""

    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage = StorageService(Path(self.directory.name))
        self.storage.save_settings({"model_api_base_url": "https://provider.example/v1", "model_api_key": "key",
                                    "model_api_wire_api": "responses"})
        base = {key: value for key, value in self.storage.get_bots()[0].items() if key != "engine"}
        self.storage.save_bots([
            {**base, "id": "bot-default"},  # made before engines existed
            {**base, "id": "bot-text", "engine": "model"},
        ])
        self.agent = FakeAgent(QUICK_REPLY)
        self.provider = StraightFromTheModel()
        self.gateway = SearchGateway()
        self.turns = TurnService(storage=self.storage, bus=EventBus(), provider=self.provider,
                                 gateway=self.gateway, coding=self.agent)
        patcher = patch.object(settings, "PROJECTS_DIR", Path(self.directory.name) / "projects")
        patcher.start()
        self.addCleanup(patcher.stop)

    async def reply(self, bot_id, text, thread_id="thr-1"):
        if not self.storage.get_thread(thread_id):
            self.storage.save_thread({"id": thread_id, "bot_id": bot_id, "title": "", "created_at": "now"})
        count = len(self.storage.get_messages(thread_id=thread_id))
        self.storage.add_message({"id": f"m-{thread_id}-{count}", "thread_id": thread_id, "bot_id": bot_id,
                                  "sender": "user", "text": text, "created_at": "now"})
        self.turns.start(thread_id, bot_id)
        await asyncio.wait_for(self.turns.wait(thread_id), 5)
        return self.storage.get_last_message(thread_id)

    async def test_an_assistant_replies_through_opencode_by_default(self):
        message = await self.reply("bot-default", "hi")
        self.assertEqual(message["text"], "Sure.")
        self.assertEqual(len(self.agent.prompts), 1)
        self.assertEqual(self.provider.calls, 0)

    async def test_a_text_only_assistant_replies_straight_from_the_model(self):
        message = await self.reply("bot-text", "hi")
        self.assertEqual(message["text"], "Text only.")
        self.assertEqual(self.agent.prompts, [])

    async def test_a_provider_opencode_cant_use_keeps_replies_straight_from_the_model(self):
        self.storage.save_settings({"model_api_wire_api": "prediction", "model_api_base_url": "https://predict.example"})
        message = await self.reply("bot-default", "hi")
        self.assertEqual(message["text"], "Text only.")
        self.assertEqual(self.agent.prompts, [])

    async def test_opencode_is_told_the_conversation_so_far_once(self):
        # A conversation that began with the assistant replying straight from the model.
        self.storage.save_thread({"id": "thr-1", "bot_id": "bot-default", "title": "", "created_at": "now"})
        self.storage.add_message({"id": "m-old-1", "thread_id": "thr-1", "bot_id": "bot-default",
                                  "sender": "user", "text": "My cat is called Lua.", "created_at": "now"})
        self.storage.add_message({"id": "m-old-2", "thread_id": "thr-1", "bot_id": "bot-default",
                                  "sender": "bot", "text": "Lovely name!", "created_at": "now"})
        await self.reply("bot-default", "What's my cat called?")
        first = self.agent.prompts[0]
        self.assertEqual(first["text"], "What's my cat called?")
        self.assertIn("The person: My cat is called Lua.", first["context"])
        self.assertIn("You: Lovely name!", first["context"])
        self.assertNotIn("What's my cat called?", first["context"])
        # The session remembers from then on: nothing is sent twice.
        await self.reply("bot-default", "And her age?")
        self.assertEqual(self.agent.created, 1)
        self.assertEqual(self.agent.prompts[1]["context"], "")

    async def test_a_session_is_kept_only_once_opencode_has_the_message(self):
        self.storage.save_thread({"id": "thr-1", "bot_id": "bot-default", "title": "", "created_at": "now"})
        self.storage.add_message({"id": "m-old", "thread_id": "thr-1", "bot_id": "bot-default",
                                  "sender": "user", "text": "My cat is called Lua.", "created_at": "now"})
        self.agent.fail_prompt = "OpenCode didn't answer."
        failed = await self.reply("bot-default", "Hello?")
        self.assertTrue(failed["is_error"])
        self.assertNotIn("opencode_session_id", self.storage.get_thread("thr-1"))
        # The next message starts again and still sends the conversation so far.
        self.agent.fail_prompt = None
        await self.reply("bot-default", "What's my cat called?")
        self.assertIn("My cat is called Lua.", self.agent.prompts[0]["context"])
        self.assertEqual(self.storage.get_thread("thr-1")["opencode_session_id"], SESSION)

    async def test_a_command_runs_and_its_result_goes_with_the_message(self):
        message = await self.reply("bot-default", "/search open dots")
        self.assertEqual(self.gateway.opened, ["search.web"])
        prompt = self.agent.prompts[0]
        self.assertEqual(prompt["text"], "/search open dots")
        self.assertIn("From Open Dots, not written by the person:", prompt["context"])
        self.assertIn("Action result (search.web)", prompt["context"])
        self.assertIn("opendots.dev", prompt["context"])
        self.assertEqual(message["text"], "Sure.")
        self.assertEqual([tool["type"] for tool in self.turns.recent["thr-1"].tools], ["tool.completed"])


def child_session(child_id):
    return {"type": "session.created", "properties": {"sessionID": child_id, "info": {
        "id": child_id, "parentID": SESSION, "directory": "/p", "title": "subagent"}}}


def in_session(event, session_id):
    """The same event, from another session (a subagent's)."""
    event = json.loads(json.dumps(event))
    props = event["properties"]
    props["sessionID"] = session_id
    for key in ("info", "part"):
        if isinstance(props.get(key), dict):
            props[key]["sessionID"] = session_id
    return event


QUESTION = {"type": "question.asked", "properties": {
    "id": "que_1", "sessionID": SESSION, "tool": {"messageID": "msg_1", "callID": "call_q"},
    "questions": [{"question": "Which database?", "header": "Database", "multiple": False,
                   "options": [{"label": "SQLite", "description": "One file"},
                               {"label": "Postgres", "description": "A server"}]}]}}


class QuestionAndSubagentTests(CodingTurnCase):
    """OpenCode's questions and subagents, followed on every device."""

    async def next_opened(self):
        while True:
            event = await self.events.next(timeout=5)
            if event["type"] == "request.opened":
                return event

    async def test_a_question_reaches_every_device_and_the_answer_goes_back(self):
        self.agent.script = [assistant("msg_1"), QUESTION, "WAIT_FOR_REPLY",
                             delta("msg_1", "prt_a", "SQLite it is."),
                             {"type": "session.idle", "properties": {"sessionID": SESSION}}]
        self.agent.reply_question = self.record("question")
        self.say("set up storage")
        self.turns.start("thr-code", "bot-code")
        opened = await self.next_opened()
        self.assertEqual(opened["requestType"], "question")
        self.assertEqual(opened["requestId"], "call_q")
        self.assertEqual(opened["summary"], "Which database?")
        self.assertEqual([o["label"] for o in opened["questions"][0]["options"]], ["SQLite", "Postgres"])
        self.assertTrue(opened["questions"][0]["custom"])
        self.assertEqual(self.turns.status("thr-code"), "waiting")
        # A question can't be "allowed"; it is answered.
        self.assertFalse(approval_broker.resolve("call_q", "allow"))
        self.assertTrue(approval_broker.resolve("call_q", "answer", [["SQLite"]]))
        await asyncio.wait_for(self.turns.wait("thr-code"), 5)
        self.assertEqual(self.agent.replies, [("que_1", [["SQLite"]])])
        self.assertEqual(self.storage.get_last_message("thr-code")["text"], "SQLite it is.")
        approval = self.turns.recent["thr-code"].approvals["call_q"]
        self.assertEqual((approval["status"], approval["answers"]), ("answer", [["SQLite"]]))

    async def test_an_unanswered_question_is_rejected(self):
        self.agent.script = [assistant("msg_1"), QUESTION, "WAIT_FOR_REPLY",
                             {"type": "session.idle", "properties": {"sessionID": SESSION}}]
        self.agent.reject_question = self.record("reject")
        self.say("set up storage")
        self.turns.start("thr-code", "bot-code")
        opened = await self.next_opened()
        self.assertTrue(approval_broker.resolve(opened["requestId"], "deny"))
        await asyncio.wait_for(self.turns.wait("thr-code"), 5)
        self.assertEqual(self.agent.replies, [("que_1", "rejected")])

    async def test_a_subagents_approval_steps_and_cost_belong_to_the_reply_but_not_its_text(self):
        child = "ses_child"
        child_permission = in_session({"type": "permission.asked", "properties": {
            "id": "per_c", "sessionID": child, "permission": "bash", "patterns": ["ls"],
            "metadata": {"command": "ls"}, "always": ["ls *"], "tool": {"messageID": "msg_c", "callID": "call_c"}}}, child)
        agent = coding_module.OpenCodeAgent(storage=self.storage, binary="/nonexistent")
        queue = agent.listen(SESSION)
        for event in [child_session(child),
                      in_session(assistant("msg_c"), child),
                      in_session(delta("msg_c", "prt_c", "subagent notes"), child),
                      child_permission,
                      in_session({"type": "session.idle", "properties": {"sessionID": child}}, child)]:
            agent._dispatch(event)
        routed = [queue.get_nowait() for _ in range(queue.qsize())]
        self.assertEqual(len(routed), 5)  # everything a subagent does reaches the reply that started it

        self.agent.script = [
            assistant("msg_1"),
            *routed[1:3],  # the subagent's message and its text
            in_session(tool("msg_c", "running", call_id="call_c"), child),
            routed[3], "WAIT_FOR_REPLY",  # its permission
            routed[4],  # its session going idle
            in_session(assistant("msg_c", completed=True, cost=0.5, tokens={
                "input": 10, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}}), child),
            delta("msg_1", "prt_a", "Done."),
            {"type": "session.idle", "properties": {"sessionID": SESSION}},
        ]
        self.say("look around")
        self.turns.start("thr-code", "bot-code")
        opened = await self.next_opened()
        self.assertEqual(opened["requestId"], "call_c")  # the subagent's step asks on the devices
        self.assertTrue(approval_broker.resolve("call_c", "allow"))
        await asyncio.wait_for(self.turns.wait("thr-code"), 5)
        message = self.storage.get_last_message("thr-code")
        self.assertEqual(message["text"], "Done.")  # the subagent's idle didn't end the reply, its text isn't shown
        self.assertEqual(message["usage"]["cost_usd"], 0.5)
        self.assertEqual(self.agent.replies, [("per_c", "once")])
        steps = {step["requestId"] for step in self.turns.recent["thr-code"].tools}
        self.assertIn("call_c", steps)

    def record(self, kind):
        async def recorder(request_id, directory, answers=None):
            self.agent.replies.append((request_id, answers if kind == "question" else "rejected"))
            self.agent.replied.set()
        return recorder


class BrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_questions_take_answers_and_permissions_dont(self):
        call = type("Call", (), {"name": "code.bash", "summary": "ls", "arguments_for_display": {}})()
        approval_broker.open("t", "b", call, request_id="perm-1")
        self.assertFalse(approval_broker.resolve("perm-1", "answer", [["x"]]))
        self.assertTrue(approval_broker.resolve("perm-1", "allow"))
        approval_broker.open("t", "b", call, request_id="q-1", kind="question")
        self.assertFalse(approval_broker.resolve("q-1", "answer", []))
        self.assertTrue(approval_broker.resolve("q-1", "answer", [["SQLite"]]))
        self.assertEqual(await approval_broker.wait("q-1"), "answer")
        self.assertEqual(approval_broker.take_answers("q-1"), [["SQLite"]])
        self.assertIsNone(approval_broker.take_answers("q-1"))


class ConfigTests(unittest.TestCase):
    def test_which_assistants_and_providers_opencode_serves(self):
        self.assertTrue(uses_opencode({}))
        self.assertTrue(uses_opencode({"engine": "opencode"}))
        self.assertFalse(uses_opencode({"engine": "model"}))
        self.assertTrue(opencode_can_reply({"model_api_wire_api": "responses"}))
        self.assertTrue(opencode_can_reply({"model_api_wire_api": "prediction",
                                            "model_api_base_url": "https://ai-gateway.vercel.sh/v1"}))
        self.assertFalse(opencode_can_reply({"model_api_wire_api": "prediction",
                                             "model_api_base_url": "https://predict.example"}))
        self.assertFalse(opencode_can_reply(None))
    def test_vercel_uses_opencodes_own_provider_and_keeps_the_key_out_of_the_environment(self):
        prepared = build_config({"model_api_base_url": "https://ai-gateway.vercel.sh/v1", "model_api_key": "vck_secret",
                                 "model_ids": ["moonshotai/kimi-k2"], "default_model": "anthropic/claude-sonnet-4.5"})
        config = prepared["config"]
        # Commands OpenCode runs inherit its environment: the key lives in the 0600 file instead.
        self.assertEqual(prepared["env"], {})
        self.assertEqual(config["provider"]["vercel"]["options"]["apiKey"], "vck_secret")
        self.assertEqual(config["model"], "vercel/anthropic/claude-sonnet-4.5")
        self.assertEqual(config["small_model"], config["model"])
        self.assertEqual(set(config["provider"]["vercel"]["models"]), {"moonshotai/kimi-k2", "anthropic/claude-sonnet-4.5"})
        self.assertEqual(config["permission"]["*"], "ask")
        self.assertEqual(config["permission"]["read"]["*.env"], "deny")
        # Subagents and questions are on: their approvals and questions reach every device.
        self.assertEqual(config["permission"]["task"], "allow")
        self.assertEqual(config["permission"]["question"], "allow")
        self.assertFalse(config["autoupdate"])
        self.assertEqual(config["share"], "disabled")

    def test_other_services_use_an_openai_compatible_provider(self):
        prepared = build_config({"model_api_base_url": "https://llm.example.com/v1", "model_api_key": "sk",
                                 "model_api_headers": {"X-Team": "t1"}, "default_model": "m1"})
        provider = prepared["config"]["provider"]["opendots"]
        self.assertEqual(provider["npm"], "@ai-sdk/openai-compatible")
        self.assertEqual(provider["options"]["baseURL"], "https://llm.example.com/v1")
        self.assertEqual(provider["options"]["apiKey"], "sk")
        self.assertEqual(provider["options"]["headers"], {"X-Team": "t1"})
        self.assertEqual(prepared["env"], {})
        self.assertEqual(model_ref("m1", {"model_api_base_url": "https://llm.example.com/v1"}),
                         {"providerID": "opendots", "modelID": "m1"})

    def test_opencode_gets_none_of_open_dots_secrets(self):
        env = agent_environment({"PATH": "/usr/bin", "HOME": "/Users/dan", "LC_ALL": "pt_PT.UTF-8",
                                 "APP_AUTH_TOKEN": "owner", "MODEL_API_KEY": "sk", "APP_ENCRYPTION_KEY": "k",
                                 "COMPOSIO_API_KEY": "c", "YDC_API_KEY": "y", "AI_GATEWAY_API_KEY": "v"})
        self.assertEqual(env, {"PATH": "/usr/bin", "HOME": "/Users/dan", "LC_ALL": "pt_PT.UTF-8"})

    def test_the_assistants_instructions_go_to_opencode(self):
        text = coding_instructions({"system_prompt": "You write Rust.", "role": "crates"})
        self.assertTrue(text.startswith("You write Rust."))
        self.assertIn("What you're for: crates.", text)
        self.assertIn("approves them on one of their devices", text)
        # The same assistant always gives the same text, so it stays in the provider's cache.
        self.assertEqual(text, coding_instructions({"system_prompt": "You write Rust.", "role": "crates"}))

    def test_every_coding_assistants_model_is_in_the_catalog(self):
        prepared = build_config({"model_api_base_url": "https://llm.example.com/v1", "model_api_key": "sk",
                                 "model_ids": ["m1"], "default_model": "m1"}, ["older-model", None, "m1"])
        self.assertEqual(list(prepared["config"]["provider"]["opendots"]["models"]), ["m1", "older-model"])

    def test_a_reply_uses_the_provider_opencode_is_running_with(self):
        # Settings may have switched provider while a reply ran; OpenCode
        # restarts only once nothing runs, so replies name the running one.
        agent = coding_module.OpenCodeAgent()
        agent.provider_id = "vercel"
        self.assertEqual(agent.model("anthropic/claude-sonnet-4.5"),
                         {"providerID": "vercel", "modelID": "anthropic/claude-sonnet-4.5"})

    def test_a_provider_is_required(self):
        with patch.object(settings, "MODEL_API_BASE_URL", ""), patch.object(settings, "MODEL_API_KEY", ""):
            with self.assertRaises(CodingAgentError):
                build_config({})

    def test_tool_subjects(self):
        self.assertEqual(tool_subject("edit", {"filePath": "/x/app.py"}), "edit: /x/app.py")
        self.assertEqual(tool_subject("bash", {"command": "ls\n  -la"}), "bash: ls -la")
        self.assertEqual(tool_subject("todowrite", {}), "todowrite")


class ProjectSafetyTests(unittest.TestCase):
    """A project folder may come from anywhere (a cloned repo): it can give the
    model instructions, but it can't turn approvals off or run code."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()

    def tearDown(self):
        self.directory.cleanup()

    def test_every_permission_that_acts_is_named(self):
        # OpenCode merges configurations key by key: "*" alone would leave room.
        for key in ("bash", "edit", "webfetch", "websearch", "external_directory"):
            self.assertEqual(PERMISSIONS[key], "ask", key)
        self.assertEqual(enforced_config()["agent"]["build"]["permission"], PERMISSIONS)
        self.assertNotIn("apiKey", json.dumps(enforced_config()))

    def test_plugins_in_the_project_or_above_are_found(self):
        project = self.root / "repo" / "app"
        project.mkdir(parents=True)
        self.assertEqual(project_plugins(project), [])
        (self.root / "repo" / ".opencode" / "plugins").mkdir(parents=True)
        plugin = self.root / "repo" / ".opencode" / "plugins" / "x.ts"
        plugin.write_text("export const X = async () => ({})")
        (self.root / "repo" / ".opencode" / "plugins" / "notes.md").write_text("not code")
        self.assertEqual(project_plugins(project), [plugin])

    def test_the_projects_agents_md_goes_with_the_instructions(self):
        (self.root / "AGENTS.md").write_text("Use tabs.")
        text = coding_instructions({"system_prompt": "You write Go."}, self.root)
        self.assertTrue(text.startswith("You write Go."))
        self.assertIn(f"Instructions from: {self.root / 'AGENTS.md'}\nUse tabs.", text)
        (self.root / "AGENTS.md").write_text("x" * 40_000)
        self.assertIn("(The rest of AGENTS.md is left out.)", coding_instructions({}, self.root))

    def test_claude_md_when_there_is_no_agents_md(self):
        (self.root / "CLAUDE.md").write_text("Run make test.")
        self.assertIn("Run make test.", coding_instructions({}, self.root))


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
