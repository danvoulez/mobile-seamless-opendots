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
