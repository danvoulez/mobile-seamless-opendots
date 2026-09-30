# Open Dots: Open-Source Alternative to OpenAI Dots


<p align="center">
  <video src="https://github.com/Anil-matcha/open-dots/raw/main/assets/open-dots-demo.mp4" poster="assets/open-dots-demo-poster.png" controls muted width="800"></video>
</p>

<p align="center"><a href="https://youtu.be/b4ZTfs0KwR0"><img src="https://i.ytimg.com/vi/b4ZTfs0KwR0/maxresdefault.jpg" width="720"></a></p>
<p align="center"><a href="https://youtu.be/b4ZTfs0KwR0"><b>▶ Watch: OpenAI Dots Alternative: Free, Open Source & Any Model </b></a></p>

**Open Dots is an open-source alternative to OpenAI Dots:** a self-hosted AI workspace for chat, tool use, approvals, connectors, and computer tasks. It brings model conversations, a governed action gateway, approval prompts, and an optional isolated browser runtime into one local-first app.

Open Dots is independently built and is not affiliated with or endorsed by OpenAI, xAI, or any model provider. It offers a self-hostable, inspectable alternative for people looking for an open-source OpenAI Dots alternative, with local data and explicit approval for higher-risk actions.

> **Status:** Prototype / active development. Intended for local experimentation; multi-user hosting and hostile-web isolation are not production ready.

## What it does

- Continue any conversation on your iPhone. Everything runs on your Mac; the phone opens the same chats, follows replies as they stream, starts new chats, and answers approvals. No cloud service sits in between.
- Create assistant personas with separate instructions, model IDs, and visual identities.
- Stream chat responses, persist conversations locally, render Markdown, attach images, and dictate messages where the browser supports speech input.
- Connect to models through the included inference adapter and choose from its configured model catalog.
- Request confined workspace reads and writes or computer actions through a deny-by-default gateway. Higher-risk actions pause for approval and produce audit events.
- Connect apps through Composio, with explicit OAuth and narrow GitHub issue lookup/create actions.
- Search the web from chat with `/search <query>`. It runs through the governed action gateway like the other tools, works with the keyless You.com free profile, and produces audit events.
- Run an optional bot-scoped Docker/Playwright computer runtime or connect a compatible remote computer service.
- Keep application state in SQLite and encrypt provider credentials at rest.

## Why Open Dots

Open Dots gives developers and individuals a self-hosted AI workspace they can inspect and adapt. Use it as an open-source alternative to OpenAI Dots when you want local-first conversation storage, configurable model access, visible approval steps, and an optional computer runtime under your control. It is a separate project with its own implementation and current limitations; see the provider and runtime notes below before deploying it.

## Quick start

### Requirements

- Node.js and npm
- Python 3.10+ and pip
- An inference API key and base URL for live model responses

Clone and start the API:

```bash
git clone https://github.com/Anil-matcha/open-dots.git
cd open-dots/server
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export MODEL_API_KEY="your_api_key"
export MODEL_API_BASE_URL="https://your-inference-host.example/api/v1"
python run.py
```

The API is available at `http://127.0.0.1:8000`; interactive docs are at `/docs`.

In a second terminal, start the web client:

```bash
cd open-dots/client
npm install
npm run dev
```

Open `http://127.0.0.1:3000` and sign in with the Open Dots owner token. On first start, the server creates `.auth-token` under `DATA_DIR` (default `~/.open-dots`). Read that file locally and paste its value into the sign-in form, or use the value of `APP_AUTH_TOKEN` if you configured one. This is a separate credential from your model provider API key, which you enter in App Settings after signing in. Never commit, share, or put the owner token in a public frontend environment variable.

Browser sessions use distinct HttpOnly cookies with server-enforced expiry. Sign out revokes the current session, and restarting the API invalidates all browser sessions. Direct API clients can continue to send the owner token as a Bearer credential. Loopback requests, including container gateway and reverse-proxy traffic, must authenticate too.

## Continue on iPhone

Open Dots runs on your Mac. Your iPhone picks up the same conversations: open a chat and keep talking, or start a new one. Every reply, tool, and approval still runs on the Mac, and the phone connects straight to it over your network. There is no cloud relay and no separate phone account.

### Start Open Dots on your Mac

You need Python 3.10+ and Node.js (`brew install python node`). From the project folder, run:

```bash
./scripts/start-mac.sh
```

The first run creates the Python environment, installs and builds the web client, then opens `http://localhost:3000`. Sign in with the owner token (`cat ~/.open-dots/.auth-token`) and add your model provider under **Settings → Model provider**.

The script makes the API listen on your local network so the phone can reach it (the web client itself stays on the Mac), and it keeps the Mac from idle-sleeping while Open Dots runs. The display can still sleep; set `OPEN_DOTS_ALLOW_SLEEP=1` to allow system sleep too. If macOS asks whether Python may accept incoming connections, choose **Allow**.

The first time, the script offers to keep Open Dots running in the background, so it is always there for your iPhone, even after a restart. You can turn that on or off later with `--install-login-item` and `--remove-login-item`.

### Link your iPhone

1. On the Mac, choose **Continue on iPhone** at the bottom of the sidebar.
2. Scan the code with the iPhone camera while both are on the same Wi-Fi. Safari opens Open Dots.
3. Tap **Share → Add to Home Screen**, then open Open Dots from the Home Screen. You can also choose **Use in Safari instead**.

The code works once and expires after 10 minutes. You can also type the address shown on the Mac into Safari and enter the code by hand.

### What carries over

- **Conversations:** both devices show the same chats, newest first, and the phone offers a **Continue** card for the conversation you were just in. Messages record which device sent them, so a thread shows where it was *Continued on iPhone* or on the Mac.
- **Replies:** a reply runs on the Mac, not in the browser. Locking the phone or closing the tab doesn't stop it. Open the chat on either device, even mid-reply, and it catches up.
- **Approvals:** a request for approval appears on every open device and can be answered on any of them.
- **Staying connected:** the phone keeps its connection to the Mac on its own. It reconnects after the phone wakes or changes networks, notices a connection that died silently, and never asks you to retry. If the Mac sleeps or leaves the network, your chats stay on screen, and anything you write, including a new chat, waits on the phone and is sent as soon as the Mac is back.
- **Opening the app while the Mac is away:** the app itself is served by the Mac, so this only works over HTTPS (see Tailscale below), where the phone keeps a copy of the app. Over plain local-network HTTP, iOS shows a connection error until the Mac is back.

### Linked devices

Linking gives the iPhone its own long-lived credential, stored only as a hash on the Mac. A linked phone can read and continue conversations, start new ones, attach images, and answer approvals. It cannot change settings or keys, manage assistants, use the computer or connector panels, delete conversations, or link other devices. Unlink a phone from the **Continue on iPhone** panel on the Mac, or from the phone's own settings sheet; it stops working immediately.

### Network and encryption

On your own Wi-Fi the phone reaches the Mac over plain HTTP at its Bonjour name (`your-mac.local:8000`), like other local-network apps, so anyone on the same network could read that traffic. Use a network you trust.

To reach your Mac from anywhere with encryption, put both devices on [Tailscale](https://tailscale.com/kb/1242/tailscale-serve) and let it serve Open Dots over HTTPS. For example, run `tailscale serve --bg 8000`, then start Open Dots with the resulting address:

```bash
HOST=127.0.0.1 PUBLIC_URL=https://your-mac.your-tailnet.ts.net ./scripts/start-mac.sh
```

With `HOST=127.0.0.1` the API is only reachable through Tailscale. Your conversations still live on the Mac; Tailscale only connects the two devices.

## Model provider

The default inference adapter sends a prediction request to `{MODEL_API_BASE_URL}/{model_id}` and uploads images to `{MODEL_API_BASE_URL}/upload_file`. Configure it with a service that implements this request and response contract and supports the model IDs you select.

Open **Settings → Model provider** and expand the collapsed panel to enter the API base URL, choose Responses or Prediction, save an API key, and configure model IDs and the default model. Use the API root (usually ending in `/v1`), without appending `/responses`. Model IDs accept one per line or comma-separated values. Saving refreshes the model menus and sets the default for newly created assistants; existing assistants keep their selected model.

For an OpenAI Responses-compatible service, choose **Responses API**. Requests stream from `/responses` with Bearer authentication, preserve conversation roles, and send attached images as data URLs. The Chat Completions protocol is not implemented. Under **Custom headers**, keep stored headers, replace the complete set, or explicitly remove them. Keys and header values are encrypted locally and are not displayed after saving; a blank API key preserves its stored value.

The same settings are available through the authenticated settings API (`POST /api/v1/settings`): `model_api_wire_api`, `model_api_base_url`, `model_api_key`, and `model_api_headers`. Use `clear_model_api_headers: true` to remove stored headers explicitly.

Set `model_ids` to the service's supported chat model IDs and `default_model` to one of those exact IDs. Both model menus use the configured catalog; the application does not rewrite model IDs. Omitted settings retain their previous values, and empty credential/header values retain stored secrets.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MODEL_API_KEY` | empty | Provider key fallback when no key is saved in settings |
| `MODEL_API_BASE_URL` | empty | Required base URL for the configured inference API |
| `DEFAULT_MODEL` | `gpt-5-mini` | Initial model for new assistants |
| `COMPOSIO_API_KEY` | empty | Optional connector credential |
| `YDC_API_KEY` | empty | Optional You.com API key for `/search`; the keyless free profile is used when unset |
| `DATA_DIR` | `~/.open-dots` | SQLite state and local keys |
| `APP_ENCRYPTION_KEY` | generated in `DATA_DIR` | Optional Fernet key for encrypted credentials |
| `APP_AUTH_TOKEN` | generated in `DATA_DIR` | Server-side owner credential for sign-in and direct API access |
| `WORKSPACE_ROOT` | project root | Directory boundary for approved workspace actions |
| `COMPUTER_PROVIDER` | `fake` | Computer provider: `fake`, `docker`, or `remote` |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | API bind address (`scripts/start-mac.sh` uses `0.0.0.0` so a linked iPhone can connect) |
| `PUBLIC_URL` | detected | Address linked phones use to reach this computer, e.g. a Tailscale HTTPS name; defaults to the Bonjour name or LAN address |
| `PAIRING_CODE_TTL_SECONDS` | `600` | How long a Continue on iPhone code stays valid |
| `DEVICE_SESSION_MAX_AGE` | 400 days | Lifetime of a linked device's cookie; unlinking revokes it at once |

For non-loopback access, set `APP_AUTH_TOKEN` only on the server, use HTTPS with `AUTH_COOKIE_SECURE=1`, and set a narrow `CORS_ORIGINS` list. Configure the public API address with `NEXT_PUBLIC_API_URL`, and sign in through the form; do not embed credentials in `NEXT_PUBLIC_*` variables. Keep the UI and API on the same site so the browser can send the session cookie. The built-in session store targets one API process; sessions are not shared between workers or instances.

If you previously built with `NEXT_PUBLIC_API_TOKEN`, rotate the owner credential, remove that variable, and rebuild/redeploy the client. Existing public assets may contain the old credential. Old cookies containing the master token are no longer accepted; users must sign in again.

## Web search

`/search <query>` in chat runs a governed, read-only web lookup through the [You.com MCP server](https://you.com/docs/build-with-agents/mcp-server) and hands the results to the assistant as action context, so it can answer with current information.

- No key is required: without `YDC_API_KEY` the keyless free profile is used, which serves a reduced read-only tool set.
- Set `YDC_API_KEY` to use the authenticated endpoint with higher limits.
- The lookup registers as `search.web` (risk `external`). Like `connector.github_list_issues`, it is an explicit, read-only command typed by the user, so it does not pause for approval; every run still produces the standard gateway audit events.

## Optional computer runtime

The default `fake` adapter is for local development and deterministic behavior. To enable the Docker/Playwright computer provider:

```bash
docker build -t open-dots-computer:1.62.1 ./runtime
export COMPUTER_PROVIDER=docker
export COMPUTER_DOCKER_IMAGE=open-dots-computer:1.62.1
```

The daemon must be running. Containers use a separate workspace per assistant, a read-only root filesystem, dropped capabilities, and resource limits. Computer navigation and other higher-risk operations go through the action gateway and approval flow. This is not a hardened sandbox for hostile websites; review network egress, image provenance, and credential exposure before using it with untrusted content.

For a remote computer service, configure `COMPUTER_PROVIDER=remote` and the `COMPUTER_REMOTE_*` variables in `server/app/config.py`.

## Architecture

```text
Next.js client (Mac) ──┐
                        ├── HTTP + live events (SSE) ── FastAPI API
iPhone app (/m/) ──────┘                                 ├── conversations + background turns
                                                          ├── SQLite + encrypted settings
                                  ├── configurable inference adapter
                                  ├── Composio connector adapter
                                  └── action gateway + approvals + audit
                                        ├── confined workspace tools
                                        └── fake / Docker / remote computer
```

The main code areas are `client/` (Next.js UI), `mobile/` (the iPhone app, served by the API at `/m/` with no build step), `server/app/routers/` (HTTP API), `server/app/services/` (providers, persistence, background turns, live events, device linking, approvals, and tools), and `runtime/` (Docker computer driver).

Run the tests with `python -m unittest discover -s tests` in `server/` and `npm test` in `mobile/`.

## Current limitations

- One local owner; user provisioning, roles, and multi-user grants are not implemented.
- SQLite is local state; coordinated multi-instance storage and backup workflows are not included.
- Inference supports the original prediction API and Responses-compatible services; Chat Completions and a generic provider plugin interface are not implemented.
- The computer runtime is opt-in and is not a hardened security boundary for arbitrary web content.
- Connector actions are intentionally narrow; arbitrary tool discovery and writes are not implemented.
- The iPhone app is a Home Screen web app served by your Mac, not an App Store app, so it has no push notifications; it catches up when you open it. There is no native desktop app, durable memory service, or scheduled routine engine.

## Contributing

Issues and pull requests are welcome. Keep the documentation aligned with behavior, avoid committing credentials or local transcripts, and describe API or persistence changes clearly.

## License

MIT. See [LICENSE](LICENSE).
