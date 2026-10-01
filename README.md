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

## Install on your Mac

```bash
curl -fsSL https://raw.githubusercontent.com/danvoulez/mobile-seamless-opendots/main/scripts/install.sh | bash
```

The installer checks for Python 3.11+, Node.js 20+ and git, and offers to install whatever is missing with Homebrew. It then downloads Open Dots to `~/.open-dots/app`, sets it up, keeps it running in the background (it starts again when you log in), and opens it in your browser already signed in. Add your model provider under **Settings → Model provider** and you're ready. Run the same line again to repair an install.

Prefer to do it by hand? Clone the repository anywhere and run `./scripts/start-mac.sh`; the first run sets everything up.

**Signing in.** On this Mac, `~/.open-dots/app/scripts/start-mac.sh --sign-in` opens Open Dots signed in (it makes a one-time link that works for 10 minutes). You can also paste the owner token from `~/.open-dots/.auth-token` into the sign-in form. The owner token is separate from your model provider key; never commit or share it. Browser sessions last 30 days, survive restarts and updates, and end when you sign out. Direct API clients can send the owner token as a Bearer credential.

**From your other computers.** Open Dots answers on your local network at one address, `http://your-mac.local:4747` (the installer prints yours). Open it in Safari on another Mac and choose **File → Add to Dock**: it becomes an app with the Open Dots icon and its own window. Sign it in once with the owner token from `~/.open-dots/.auth-token` on the Mac that runs Open Dots; that app keeps its own sign-in for 30 days. Like the iPhone, it travels over plain HTTP on your network (see [On your Wi-Fi](#on-your-wi-fi)).

**Your data** lives in `~/.open-dots`: the database, encrypted settings, linked devices, the owner token, and database backups taken before each update. Settings that should survive updates, such as `PUBLIC_URL` for a tunnel, go in `~/.open-dots/open-dots.env` as `KEY=value` lines.

### Updates

Open Dots keeps itself up to date. Every few minutes it checks for a new tested version; when one is ready, the Mac shows an **Update** pill next to the new-chat button. One click installs it: Open Dots restarts for a few seconds (your iPhone shows *Reconnecting…* and picks up where it was), and both the Mac page and the iPhone app reload into the new version.

With **Settings → Updates → Install updates automatically** on (the default), you don't even need the click: new versions install as soon as no reply is running. Before each update Open Dots backs up its database. If a new version doesn't start, it goes back to the previous one by itself, database included, tells you on the Mac, and skips that version until a newer one arrives.

From a terminal: `./scripts/update.sh check` shows what's new, `./scripts/update.sh` updates now.

### Uninstall

```bash
~/.open-dots/app/scripts/uninstall.sh
```

It stops Open Dots, removes it from your login items, and deletes the app. It asks before deleting your chats, settings and linked devices; keep them and a reinstall picks them up again. Afterwards, remove the Open Dots icon from your iPhone's Home Screen, and any Cloudflare Tunnel or Tailscale setup you made for it.

### Develop

For hot reload while you work on the code, run the server and the web client yourself:

```bash
cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.lock && CORS_ORIGINS=http://localhost:3000 .venv/bin/python run.py
cd client && npm ci && npm run dev    # in a second terminal
```

The server is at `http://127.0.0.1:4747` (interactive docs at `/docs`); the hot-reloading web client at `http://localhost:3000`, which `CORS_ORIGINS` allows to use the server. Installed copies don't run Next.js: `next build` exports the Mac page to `client/out`, and the server serves it on its own address.

## Continue on iPhone

Open Dots runs on your Mac. Your iPhone picks up the same conversations: open a chat and keep talking, or start a new one. Every reply, tool, and approval still runs on the Mac, and the phone connects straight to it over your network. There is no cloud relay and no separate phone account.

### Start Open Dots on your Mac

The [installer](#install-on-your-mac) sets this up. By hand, from the project folder:

```bash
./scripts/start-mac.sh
```

The first run creates the Python environment, installs and builds the web client, then opens `http://localhost:4747` signed in. Add your model provider under **Settings → Model provider**.

The script runs one process that serves the Mac page, the iPhone app and the API at one address, port 4747 (set `OPEN_DOTS_PORT` in `~/.open-dots/open-dots.env` to change it). It listens on your local network so your iPhone and your other computers can reach it, and it keeps the Mac from idle-sleeping while Open Dots runs. The display can still sleep; set `OPEN_DOTS_ALLOW_SLEEP=1` to allow system sleep too. If macOS asks whether Python may accept incoming connections, choose **Allow**.

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
- **Opening the app while the Mac is away:** the app itself is served by the Mac, so this only works over HTTPS (see Cloudflare Tunnel or Tailscale below), where the phone keeps a copy of the app. Over plain local-network HTTP, iOS shows a connection error until the Mac is back.

### Linked devices

Linking gives the iPhone its own long-lived credential, stored only as a hash on the Mac. A linked phone can read and continue conversations, start new ones, attach images, and answer approvals. It cannot change settings or keys, manage assistants, use the computer or connector panels, delete conversations, or link other devices. Unlink a phone from the **Continue on iPhone** panel on the Mac, or from the phone's own settings sheet; it stops working immediately.

### How the iPhone connects

The iPhone keeps one WebSocket open to the Mac and speaks JSON-RPC over it: its requests (open a chat, send, approve) and the Mac's live events (new messages, replies as they stream) share that connection. The protocol is described in [docs/iphone-protocol.md](docs/iphone-protocol.md), so a native iPhone app can use it as is.

Settings that should survive restarts go in `~/.open-dots/open-dots.env`, one `KEY=value` per line; the start script and the background login item both read it.

#### On your Wi-Fi

The phone reaches the Mac at its Bonjour name (`your-mac.local:4747`) over plain HTTP, like other local-network apps, so anyone on the same network could read that traffic. The same goes for the Mac page opened from another computer. Use a network you trust.

#### From anywhere: Cloudflare Tunnel

A [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) gives your Mac a stable HTTPS address, such as `dots.example.com`, without opening ports on your router. You need a Cloudflare account and a domain on Cloudflare.

1. In the Cloudflare dashboard, create a tunnel and give it a public hostname, for example `dots.example.com`, that points to `http://localhost:4747`.
2. On the Mac, run `brew install cloudflared`, then the macOS install command the dashboard shows. The tunnel then starts with the Mac.
3. Give Open Dots that address, and keep it off the local network:

   ```bash
   mkdir -p ~/.open-dots
   printf 'PUBLIC_URL=https://dots.example.com\nHOST=127.0.0.1\n' >> ~/.open-dots/open-dots.env
   ```

4. Restart Open Dots and link the iPhone again from **Continue on iPhone**; the code now points to the tunnel address. The phone reaches the Mac at home and away, and because the address is HTTPS, the app also opens while the Mac is away.

Before you rely on it:

- **Cloudflare can read this traffic.** The HTTPS connection ends at Cloudflare's servers, which pass it on to your Mac, so Cloudflare could see your messages in transit. Conversations are still stored and processed only on your Mac. End-to-end encryption on top of the tunnel is not implemented; if you need it today, use Tailscale.
- **The address is public.** Only linked devices and the owner token get in, and every linking code works once, for 10 minutes. Unlink a lost phone from the Mac. You can add Cloudflare Access for an extra sign-in, but the phone then has to pass it too.

#### From anywhere, encrypted end to end: Tailscale

Put both devices on [Tailscale](https://tailscale.com/kb/1242/tailscale-serve) and let it serve Open Dots over HTTPS, for example with `tailscale serve --bg 4747`. Then set `PUBLIC_URL` to the address it shows (such as `https://your-mac.your-tailnet.ts.net`) and `HOST=127.0.0.1` in `~/.open-dots/open-dots.env`. Traffic is encrypted between your own devices, and only devices on your tailnet can reach the Mac.

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
| `OPEN_DOTS_PORT` | `4747` | The one port `scripts/start-mac.sh` serves the Mac page, the iPhone app and the API on |
| `HOST` / `PORT` | `127.0.0.1` / `4747` | Bind address of a server started by hand (`scripts/start-mac.sh` uses `0.0.0.0` and `OPEN_DOTS_PORT`, so your iPhone and other computers can connect) |
| `CORS_ORIGINS` | empty | Other origins allowed to use the API from a browser, such as `http://localhost:3000` for `npm run dev`; pages this server serves are always allowed |
| `PUBLIC_URL` | detected | Address linked phones use to reach this computer, e.g. a Cloudflare Tunnel or Tailscale HTTPS name; defaults to the Bonjour name or LAN address |
| `PAIRING_CODE_TTL_SECONDS` | `600` | How long a Continue on iPhone code stays valid |
| `DEVICE_SESSION_MAX_AGE` | 400 days | Lifetime of a linked device's cookie; unlinking revokes it at once |

The Mac page, the iPhone app and the API share one origin, so the browser sends the session cookie and no CORS is involved. Beyond your own network, use HTTPS (a tunnel, above) with `AUTH_COOKIE_SECURE=1`, set `APP_AUTH_TOKEN` only on the server, and sign in through the form. `NEXT_PUBLIC_API_URL` is only for a page served from elsewhere, as `npm run dev` is; never put credentials in `NEXT_PUBLIC_*` variables. The built-in session store targets one API process; sessions are not shared between workers or instances.

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
Mac page (any computer) ── HTTP + live events (SSE) ───────┐
iPhone ── JSON-RPC over one WebSocket (Wi-Fi or tunnel) ───┴── FastAPI, one address (:4747)
                                                                ├── the Mac page (client/out) and the iPhone app (/m/)
                                                                ├── conversations + background turns
                                                                ├── SQLite + encrypted settings
                                                                ├── configurable inference adapter
                                                                ├── Composio connector adapter
                                                                └── action gateway + approvals + audit
                                                                      ├── confined workspace tools
                                                                      └── fake / Docker / remote computer
```

The main code areas are `client/` (the Mac page: Next.js, exported to plain files the API serves), `mobile/` (the iPhone app, served by the API at `/m/` with no build step), `server/app/routers/` (HTTP API), `server/app/services/` (providers, persistence, background turns, live events, device linking, approvals, and tools), and `runtime/` (Docker computer driver).

## How changes reach your Mac

Open Dots is set up for one person shipping continuously: merge to `main`, and your Mac runs it minutes later, but only if every test passes.

```text
branch / pull request ──► CI: all tests ──► merge to main ──► CI again ──► stable ──► your Mac
                                                               (all green)    (checks every few minutes,
                                                                               installs when idle,
                                                                               rolls back if it won't start)
```

[CI](.github/workflows/ci.yml) runs on every push and pull request:

| Job | What it proves |
| --- | --- |
| Server (Python 3.11 and 3.13) | The API's unit tests |
| iPhone app | Syntax and unit tests for `mobile/` |
| Mac web client | Lint and a production build |
| Shell scripts | `bash -n` and ShellCheck |
| End to end | The iPhone app, the Mac web client, and the two together, in a real browser against a real server and a stand-in model: linking, live replies, joining a reply midway, approvals across devices, offline and reconnect ([`e2e/`](e2e/)). Screenshots are kept with each run. |
| Install, update, roll back, uninstall (Linux and macOS) | The installer, a one-time sign-in link, an update from the API, a broken version rolled back with its database, an automatic update, and the uninstaller, against a throwaway git origin ([`e2e/update-flow.sh`](e2e/update-flow.sh)). The macOS run uses the system bash 3.2 and also installs the launchd login item. |

When a commit on `main` passes all of them, CI moves the `stable` branch to it. Installed copies follow `stable` (set `UPDATE_CHANNEL` in `open-dots.env` to follow another branch). Dependabot opens grouped dependency updates monthly; they go through the same tests.

Installs and updates use exact dependency versions: `client/package-lock.json` and `server/requirements.lock`. After changing `server/requirements.txt`, regenerate the lock as its header explains.

Run the tests locally:

```bash
cd server && .venv/bin/python -m unittest discover -s tests   # API
cd mobile && npm test                                           # iPhone app
cd e2e && npm ci && ./run.sh                                    # browsers (needs a built client)
e2e/update-flow.sh                                              # install → update → rollback → uninstall
```

## Current limitations

- One local owner; user provisioning, roles, and multi-user grants are not implemented.
- SQLite is local state; the only backups are the five kept before updates, in `~/.open-dots/backups`.
- Inference supports the original prediction API and Responses-compatible services; Chat Completions and a generic provider plugin interface are not implemented.
- The computer runtime is opt-in and is not a hardened security boundary for arbitrary web content.
- Connector actions are intentionally narrow; arbitrary tool discovery and writes are not implemented.
- The iPhone app has no push notifications yet; it catches up when you open it. iOS allows notifications for Home Screen web apps only over HTTPS (for example through Cloudflare Tunnel), and they aren't implemented. There is no native desktop app, durable memory service, or scheduled routine engine.

## Contributing

Issues and pull requests are welcome. Keep the documentation aligned with behavior, avoid committing credentials or local transcripts, and describe API or persistence changes clearly.

## License

MIT. See [LICENSE](LICENSE).
