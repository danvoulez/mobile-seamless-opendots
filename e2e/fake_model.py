"""A stand-in model: an OpenAI Responses-compatible endpoint that streams a
fixed reply word by word, slowly enough to watch it arrive."""

import asyncio
import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
DELAY = float(os.getenv("FAKE_DELAY", "0.06"))


@app.post("/v1/responses")
async def responses(request: Request):
    body = await request.json()
    content = body["input"][-1]["content"]
    if isinstance(content, list):
        content = next((part["text"] for part in content if part.get("type") == "input_text"), "")
    if "Action result" in body.get("instructions", ""):
        reply = ("Here is what's in your workspace. The **server**, **client** and **mobile** folders "
                 "are all there — the iPhone app lives in `mobile/`.")
    else:
        reply = (f"Sure — picking this up from where we were.\n\nYou said: *{content[:80]}*\n\n"
                 "Here's a plan:\n\n1. Keep the conversation on your **Mac**\n2. Continue it on your **iPhone**\n"
                 "3. Approve actions from either one\n\n```bash\n./scripts/start-mac.sh\n```\n\nAnything else?")
    words = reply.split(" ")

    async def stream():
        for index, word in enumerate(words):
            delta = word + (" " if index < len(words) - 1 else "")
            yield f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': delta})}\n\n"
            await asyncio.sleep(DELAY)
        yield f"data: {json.dumps({'type': 'response.completed'})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# What a coding assistant's OpenCode sends: Chat Completions with tools. Asked
# to make a file, it first runs one command (which waits for an approval), then
# answers; anything else it simply answers. Requests without tools (OpenCode
# naming the conversation) get a short title.
CODING_COMMAND = "printf 'hello from opencode\\n' > hello.txt"


def _chunk(delta, finish=None, usage=None):
    body = {"id": "chatcmpl-fake", "object": "chat.completion.chunk", "created": 0, "model": "fake",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage:
        body["usage"] = usage
    return f"data: {json.dumps(body)}\n\n"


LAST_CODING_REQUEST: dict = {}


@app.get("/v1/_last_coding_request")
async def last_coding_request():
    """What OpenCode last sent with tools, for tests that check the context it keeps."""
    return LAST_CODING_REQUEST


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages") or []
    if body.get("tools"):
        LAST_CODING_REQUEST.clear()
        LAST_CODING_REQUEST.update(body)
    usage = {"prompt_tokens": 1200, "completion_tokens": 40, "total_tokens": 1240,
             "prompt_tokens_details": {"cached_tokens": 1000}}

    def text_of(message):
        content = message.get("content")
        if isinstance(content, list):
            return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
        return content or ""

    last_user = next((text_of(m) for m in reversed(messages) if m.get("role") == "user"), "")
    # Only this request's tools count: those after the person's latest message.
    latest = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    ran_tool = any(m.get("role") == "tool" for m in messages[latest + 1:])
    tool_output = next((text_of(m) for m in reversed(messages[latest + 1:]) if m.get("role") == "tool"), "")
    asked = last_user.lower()

    async def call(name, arguments):
        arguments = json.dumps(arguments)
        yield _chunk({"tool_calls": [{"index": 0, "id": f"call_fake_{name}", "type": "function",
                                      "function": {"name": name, "arguments": ""}}]})
        for start in range(0, len(arguments), 16):
            yield _chunk({"tool_calls": [{"index": 0, "function": {"arguments": arguments[start:start + 16]}}]})
            await asyncio.sleep(DELAY / 4)
        yield _chunk({}, "tool_calls", usage)

    async def stream():
        yield _chunk({"role": "assistant", "content": ""})
        if not body.get("tools"):
            yield _chunk({"content": "Making hello.txt"})
            yield _chunk({}, "stop", usage)
        elif "make a file" in asked and not ran_tool:
            yield _chunk({"content": "I'll create it."})
            async for chunk in call("bash", {"command": CODING_COMMAND, "description": "Create hello.txt"}):
                yield chunk
        elif "ask me" in asked and not ran_tool:
            # OpenCode's question tool: the person picks on their Mac or iPhone.
            async for chunk in call("question", {"questions": [{
                "question": "Which database?", "header": "Database",
                "options": [{"label": "SQLite", "description": "One file"},
                            {"label": "Postgres", "description": "A server"}]}]}):
                yield chunk
        elif "use a subagent" in asked and not ran_tool:
            # A subagent in a session of its own; it makes the file, which asks for approval.
            async for chunk in call("task", {"description": "Make the file", "subagent_type": "general",
                                             "prompt": "SUBTASK: please make a file called hello.txt"}):
                yield chunk
        else:
            if "ask me" in asked:
                reply = f"Noted: {tool_output[:200]}"
            elif ran_tool:
                reply = "Done: **hello.txt** is in the project folder."
            else:
                reply = f"You said: {last_user[:80]}"
            for word in reply.split(" "):
                yield _chunk({"content": word + " "})
                await asyncio.sleep(DELAY)
            yield _chunk({}, "stop", usage)
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
