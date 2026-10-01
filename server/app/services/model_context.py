"""What one reply sends to the model: the assistant's instructions, the part of
the conversation it needs, and this turn's context. Decides only; turn_service
sends it.

Ordered for prompt caching: providers reuse the longest unchanged beginning of
a request (and Vercel AI Gateway marks it for Anthropic), so everything that
changes per turn (the time, an action's result) goes at the very end, and the
conversation's oldest messages are dropped in large steps, not one at a time.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

# Kept from a conversation: everything up to MAX_HISTORY messages; past that,
# windows that start every HISTORY_STEP messages, so the window's start (and
# the cache) stays put for HISTORY_STEP replies at a time. It then holds
# between MAX_HISTORY - HISTORY_STEP and MAX_HISTORY messages.
MAX_HISTORY = 60
HISTORY_STEP = 30

# The newest photo is sent again while it is among the person's last few
# messages, for follow-up questions about it; then only a note stays.
PHOTO_KEPT_FOR = 3

EARLIER_LEFT_OUT = "(Earlier messages in this conversation are left out.)"
PHOTO_SENT_EARLIER = "(The person attached a photo here; you already saw it.)"

APP_NOTES = (
    "You are one of the person's assistants in Open Dots, which runs on their "
    "own computer; they talk to you from that computer or their iPhone, and "
    "replies are shown as Markdown. Answer in the language the person writes "
    "in. When the person runs a command such as /search, Open Dots runs it "
    "and adds the result at the end of their message."
)


def assistant_instructions(bot: Optional[Dict[str, Any]]) -> str:
    """Stable for as long as the assistant isn't edited, so it caches."""
    if not bot:
        return f"You are a helpful AI assistant.\n\n{APP_NOTES}"
    parts = [bot.get("system_prompt") or f"You are {bot.get('name') or 'an assistant'}."]
    role = (bot.get("role") or "").strip()
    # The role is what the person wrote under "What it's for".
    if role and role.lower() not in parts[0].lower():
        parts.append(f"What you're for: {role}.")
    parts.append(APP_NOTES)
    return "\n\n".join(parts)


def history_start(count: int) -> int:
    """Index of the first message kept from a conversation of `count` messages."""
    if count <= MAX_HISTORY:
        return 0
    return (count - (MAX_HISTORY - HISTORY_STEP)) // HISTORY_STEP * HISTORY_STEP


def model_messages(stored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The conversation as the model sees it: replies that failed left out, the
    oldest messages left out in steps, and only a recent photo sent again."""
    usable = [m for m in stored if m.get("sender") in ("user", "bot") and not m.get("is_error")]
    start = history_start(len(usable))
    # Models expect the conversation to open with the person speaking.
    while start < len(usable) and usable[start].get("sender") != "user":
        start += 1
    window = usable[start:]

    person = [i for i, m in enumerate(window) if m.get("sender") == "user"]
    recent = set(person[-PHOTO_KEPT_FOR:])
    newest_photo = max((i for i, m in enumerate(window) if m.get("image_url")), default=None)
    if newest_photo not in recent:
        newest_photo = None
    messages = []
    for index, message in enumerate(window):
        text = message.get("text") or ""
        image_url = message.get("image_url")
        if image_url and index != newest_photo:
            # Seen and answered already; sending it again costs every turn.
            text = f"{text}\n\n{PHOTO_SENT_EARLIER}" if text else PHOTO_SENT_EARLIER
            image_url = None
        messages.append({
            "role": "user" if message.get("sender") == "user" else "assistant",
            "content": text,
            "image_url": image_url,
        })
    if start > 0 and messages:
        messages[0]["content"] = f"{EARLIER_LEFT_OUT}\n\n{messages[0]['content']}"
    return messages


def with_turn_context(messages: List[Dict[str, Any]], now: datetime, action_note: str = "") -> List[Dict[str, Any]]:
    """Adds this turn's facts to the person's latest message, the end of the request."""
    if not messages or messages[-1]["role"] != "user":
        return messages
    lines = [f"Now: {now.strftime('%A, %d %B %Y, %H:%M')} {now.strftime('%Z')}".rstrip()]
    if action_note:
        lines.append(action_note)
    context = "\n".join(f"- {line}" for line in lines)
    last = messages[-1]
    content = f"{last['content']}\n\n---\nFrom Open Dots, not written by the person:\n{context}"
    return [*messages[:-1], {**last, "content": content}]
