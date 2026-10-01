# Open Dots phone protocol (version 1)

How a phone talks to the Mac running Open Dots. The Home Screen app in
`mobile/` uses it today; a native iPhone app can use it unchanged.

One WebSocket carries everything as [JSON-RPC 2.0](https://www.jsonrpc.org/specification):
the phone's requests, the Mac's responses, and every live event as a
notification. It works the same on the local network and through a tunnel
such as Cloudflare Tunnel. The server side is `server/app/routers/rpc.py`.

## Connecting

| | |
| --- | --- |
| Through Cloudflare Tunnel | `wss://dots.example.com/api/v1/rpc` (your `PUBLIC_URL`) |
| On the same Wi-Fi | `ws://your-mac.local:4747/api/v1/rpc` |

Authenticate with the device credential the phone received when it was
linked: send it as `Authorization: Bearer odd_…` (native apps) or let the
browser send the `open_dots_device` cookie. The owner's own session also works.

Browsers must connect from the Mac's own address or from `PUBLIC_URL`; other
origins are refused before the handshake completes. Native apps send no
`Origin` header.

| Close code | Meaning | What to do |
| --- | --- | --- |
| `4401` | Not linked, or the device was unlinked | Link again |
| `1008` | Refused origin | Fix the address |
| anything else | The connection dropped | Reconnect |

## Linking (HTTP)

Linking sets the credential, so it stays a plain HTTP call:

```http
POST /api/v1/devices/pair
Content-Type: application/json

{"code": "K7QM-2XRP"}
```

The response is `{"device": {...}, "computer_name": "..."}` with the credential
in `Set-Cookie: open_dots_device=odd_…`. A native app reads it from that
header, keeps it in the Keychain, and sends it as a Bearer token from then on.

Other plain HTTP calls: `POST /api/v1/upload` (multipart photo, returns
`{"url": ...}` for `messages.send`) and `DELETE /api/v1/devices/current`
(unlink this phone).

## Messages

```json
{"jsonrpc": "2.0", "id": 7, "method": "threads.get", "params": {"thread_id": "thr-…"}}
{"jsonrpc": "2.0", "id": 7, "result": {"thread": {...}, "messages": [...], "turn": null}}
{"jsonrpc": "2.0", "method": "event", "params": {"type": "content.delta", ...}}
```

`params` is always an object. Batches (arrays of requests) are supported.

## Methods

| Method | Params | Result |
| --- | --- | --- |
| `ping` | – | `{"pong": true}` |
| `bots.list` | – | The assistants |
| `threads.list` | – | Chat summaries, newest first |
| `threads.get` | `thread_id` | `{thread, messages, turn}`; `turn` is the running (or last) reply |
| `threads.create` | `bot_id`, `title?` | Chat summary |
| `threads.rename` | `thread_id`, `title` | Chat summary |
| `messages.send` | `thread_id` **or** `bot_id`, `text`, `image_url?`, `model?`, `client_id?` | `{thread, message, turn, duplicate?}` |
| `approvals.respond` | `request_id`, `action` (`allow` or `deny`) | `{request_id, action}` |

`messages.send` with a `bot_id` and no `thread_id` starts a new chat and
sends its first message in one call.

**Give every message a `client_id`** and resend it unchanged after any
failure. If the Mac already has that message (the first attempt arrived but
its response was lost), it returns it with `"duplicate": true` instead of
posting it twice.

## Events

Sent as `{"method": "event", "params": {...}}`. Everything about a chat carries
its `threadId`.

| `type` | Fields | Notes |
| --- | --- | --- |
| `hello` | `protocol`, `computer`, `device`, `version` | First message on every connection: reload your state. If `version` differs from the one you started with, the computer installed an update: reload the app |
| `update.status` | `update` | The computer's update state; phones can ignore it |
| `heartbeat` | – | Every 15 s when nothing else happens |
| `resync` | – | Events were dropped: reload your state |
| `thread.created`, `thread.updated` | `thread` | Summary with `status`: `idle`, `running`, `waiting` (needs approval) |
| `thread.deleted` | – | |
| `message.created` | `message` | Includes `client_id` for messages you sent |
| `turn.started` | `turnId`, `botMsgId`, `model` | A reply began |
| `content.delta` | `botMsgId`, `delta`, `offset` | `offset` is where `delta` starts in the reply text |
| `request.opened` | `requestId`, `tool`, `summary`, `arguments` | Approval needed |
| `request.resolved` | `requestId`, `decision` | `allow`, `deny` or `expired` |
| `tool.started`, `tool.completed`, `tool.failed`, `tool.denied`, `tool.expired` | `tool`, `requestId?`, `action?`, `result?`, `error?` | One step per `requestId`: a later event updates the step. The `turn` snapshot keeps the latest 30 steps in `tools` |
| `turn.completed` | `botMsgId`, `ok`, `message` | The stored reply; `ok: false` marks an error reply |
| `device.linked`, `device.unlinked` | `device` / `deviceId` | |

## Errors

| Code | Meaning |
| --- | --- |
| `-32700` | Not valid JSON |
| `-32600` | Not a valid JSON-RPC request |
| `-32601` | Unknown method |
| `-32602` | Invalid params; the message names the field |
| `-32603` | Unexpected server error |
| `-32004` | Not found (`data.status` 404) |
| `-32009` | A reply is still running in that chat (409): send again after `thread.updated` shows `idle` |
| `-32022` | Rejected content (422), for example an empty message |

## Staying connected

1. On every `hello`, reload the chat list and the open chat. Events are live
   from that moment on, so nothing is missed.
2. Apply `content.delta` when `offset` equals the length of the text you have.
   Skip deltas you already have; if `offset` is larger, reload the chat
   (`threads.get`).
3. If nothing arrives for 40 seconds, reconnect: the connection died without
   closing. Retry after 1, 2, 4, then every 5 seconds, and immediately when
   the app returns to the foreground or the network changes.
4. Keep unsent messages on the phone until the Mac confirms them, and send
   them again after reconnecting (see `client_id` above).

Heartbeats also keep tunnels from closing the socket as idle; Cloudflare, for
example, closes WebSockets that stay silent for about 100 seconds.
