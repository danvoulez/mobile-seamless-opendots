"""Coding assistants: OpenCode, run by this computer and driven over its API.

A coding assistant hands each reply to OpenCode (https://opencode.ai), which
brings the coding tools: reading and editing files, running commands,
searching code, and so on. Open Dots starts one `opencode serve` process on
loopback with a password only it knows, writes its configuration (the model
provider from Settings, and "ask before acting" for everything that changes
something), and follows its event stream. turn_service turns those events into
the replies, tool steps and approvals every device already shows.

This module is the only place that knows OpenCode's API. Another coding agent
would replace what is behind `OpenCodeAgent`, not the rest of Open Dots.

OpenCode keeps its own sessions on disk (under OPENCODE_DIR), so a conversation
keeps its context across restarts and updates of Open Dots.
"""

import asyncio
import hashlib
import json
import logging
import os
import secrets
import shutil
import signal
import socket
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.services.storage_service import StorageService, storage_service

logger = logging.getLogger(__name__)

PROVIDER_ID = "opendots"  # the model provider from Settings, for any service but Vercel's
VERCEL_PROVIDER_ID = "vercel"  # OpenCode's own Vercel AI Gateway provider
SERVER_USER = "opencode"

# Reading and searching are free; anything that changes files, runs commands,
# fetches from the web or leaves the project folder waits for an approval on
# one of the person's devices. `.env` files stay unreadable, as in OpenCode.
PERMISSIONS: Dict[str, Any] = {
    "*": "ask",
    "read": {"*": "allow", "*.env": "deny", "*.env.*": "deny", "*.env.example": "allow"},
    "glob": "allow",
    "grep": "allow",
    "list": "allow",
    "lsp": "allow",
    "todoread": "allow",
    "todowrite": "allow",
    "external_directory": "ask",
    "doom_loop": "ask",
}


class CodingAgentError(Exception):
    """OpenCode isn't installed, isn't configured, or didn't answer."""


def _is_vercel(base_url: str) -> bool:
    host = (urlsplit(base_url).hostname or "").lower()
    return host == "ai-gateway.vercel.sh" or host.endswith(".ai-gateway.vercel.sh")


def provider_id_for(base_url: str) -> str:
    return VERCEL_PROVIDER_ID if _is_vercel(base_url) else PROVIDER_ID


def build_config(app_settings: Dict[str, Any]) -> Dict[str, Any]:
    """OpenCode's configuration and environment for the provider in Settings.

    Returns {"config": ..., "env": ...}. Secrets go in the environment, which
    only the OpenCode process receives; the file holds `{env:...}` references.
    """
    base_url = (app_settings.get("model_api_base_url") or settings.MODEL_API_BASE_URL).rstrip("/")
    api_key = app_settings.get("model_api_key") or settings.MODEL_API_KEY
    if not base_url or not api_key:
        raise CodingAgentError(
            "Coding assistants use the model provider from Settings → Model provider. Add its address and key first."
        )
    default_model = app_settings.get("default_model") or settings.DEFAULT_MODEL
    model_ids = list(dict.fromkeys([*(app_settings.get("model_ids") or []), default_model]))
    provider = provider_id_for(base_url)

    env: Dict[str, str] = {}
    if provider == VERCEL_PROVIDER_ID:
        env["AI_GATEWAY_API_KEY"] = api_key
        providers = {VERCEL_PROVIDER_ID: {"models": {model: {} for model in model_ids}}}
    else:
        env["OPEN_DOTS_MODEL_API_KEY"] = api_key
        options: Dict[str, Any] = {"baseURL": base_url, "apiKey": "{env:OPEN_DOTS_MODEL_API_KEY}"}
        headers = app_settings.get("model_api_headers") or {}
        if headers:
            options["headers"] = {name: f"{{env:OPEN_DOTS_HEADER_{index}}}" for index, name in enumerate(headers)}
            env.update({f"OPEN_DOTS_HEADER_{index}": value for index, value in enumerate(headers.values())})
        providers = {
            PROVIDER_ID: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Open Dots model provider",
                "options": options,
                "models": {model: {"name": model} for model in model_ids},
            }
        }

    config = {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "share": "disabled",
        "model": f"{provider}/{default_model}",
        # Titles and summaries use the same model, never a surprise second one.
        "small_model": f"{provider}/{default_model}",
        "provider": providers,
        "permission": PERMISSIONS,
    }
    return {"config": config, "env": env}


def model_ref(model: str, app_settings: Dict[str, Any]) -> Dict[str, str]:
    """An Open Dots model ID ("anthropic/claude-sonnet-4.5") as OpenCode names it."""
    base_url = (app_settings.get("model_api_base_url") or settings.MODEL_API_BASE_URL).rstrip("/")
    return {"providerID": provider_id_for(base_url), "modelID": model}


def project_dir_for(bot: Dict[str, Any]) -> Path:
    """The folder a coding assistant works in: its own, or one under PROJECTS_DIR."""
    configured = (bot.get("project_dir") or "").strip()
    path = Path(configured).expanduser() if configured else settings.PROJECTS_DIR / bot["id"]
    path = path.resolve()
    if not configured:
        path.mkdir(parents=True, exist_ok=True)
    return path


def validate_project_dir(value: str) -> str:
    """Accept an existing folder that isn't Open Dots itself or its data."""
    value = (value or "").strip()
    if not value:
        return ""
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Use the full path of a folder, such as ~/Projects/my-app.")
    path = path.resolve()
    if not path.is_dir():
        raise ValueError(f"There is no folder at {path}.")
    if path == Path.home().resolve() or path == Path(path.anchor):
        raise ValueError("Choose a project folder, not your whole home folder or disk.")
    under_projects = settings.PROJECTS_DIR in path.parents
    app_root = Path(__file__).resolve().parents[3]
    for protected in (app_root, settings.DATA_DIR):
        overlaps = path == protected or protected in path.parents or path in protected.parents
        if overlaps and not under_projects:
            raise ValueError("Choose a project folder outside Open Dots and its data.")
    return str(path)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class OpenCodeAgent:
    def __init__(self, storage: StorageService = storage_service, binary: Optional[str] = None,
                 home: Optional[Path] = None):
        self.storage = storage
        self.binary = binary or settings.OPENCODE_BIN
        self.home = home or settings.OPENCODE_DIR
        self.process: Optional[asyncio.subprocess.Process] = None
        self.base_url: Optional[str] = None
        self.password: Optional[str] = None
        self.digest: Optional[str] = None
        self.client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
        self._listeners: Dict[str, Set[asyncio.Queue]] = {}
        self._events_task: Optional[asyncio.Task] = None
        self._connected = asyncio.Event()

    # ----- the process -------------------------------------------------------

    def executable(self) -> Optional[str]:
        if self.binary and Path(self.binary).is_file() and os.access(self.binary, os.X_OK):
            return self.binary
        return shutil.which("opencode")

    def available(self) -> bool:
        return self.executable() is not None

    def _running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def ensure_running(self) -> None:
        """Start OpenCode, or restart it after the model provider changed (when no reply is running)."""
        async with self._lock:
            prepared = build_config(self.storage.get_settings())
            digest = hashlib.sha256(json.dumps(prepared, sort_keys=True).encode()).hexdigest()
            if self._running() and (digest == self.digest or self._listeners):
                return
            await self._stop()
            await self._start(prepared, digest)

    async def _start(self, prepared: Dict[str, Any], digest: str) -> None:
        executable = self.executable()
        if not executable:
            raise CodingAgentError("OpenCode isn't installed. Run scripts/start-mac.sh (or scripts/update.sh) to install it.")
        self.home.mkdir(parents=True, exist_ok=True)
        os.chmod(self.home, 0o700)
        self._kill_stale()
        config_path = self.home / "opencode.json"
        config_path.write_text(json.dumps(prepared["config"], indent=2), encoding="utf-8")
        os.chmod(config_path, 0o600)
        settings.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

        port = _free_port()
        self.password = secrets.token_urlsafe(32)
        env = {
            **os.environ,
            **prepared["env"],
            # OpenCode's own data, separate from any OpenCode the person uses in a terminal.
            "XDG_DATA_HOME": str(self.home / "data"),
            "XDG_CONFIG_HOME": str(self.home / "config"),
            "XDG_CACHE_HOME": str(self.home / "cache"),
            "XDG_STATE_HOME": str(self.home / "state"),
            "OPENCODE_CONFIG": str(config_path),
            "OPENCODE_SERVER_USERNAME": SERVER_USER,
            "OPENCODE_SERVER_PASSWORD": self.password,
        }
        log = open(self.home / "serve.log", "ab")
        try:
            self.process = await asyncio.create_subprocess_exec(
                executable, "serve", "--hostname", "127.0.0.1", "--port", str(port),
                cwd=str(settings.PROJECTS_DIR), env=env,
                stdin=asyncio.subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True,
            )
        finally:
            log.close()
        (self.home / "serve.pid").write_text(str(self.process.pid), encoding="utf-8")
        self.base_url = f"http://127.0.0.1:{port}"
        self.client = httpx.AsyncClient(
            base_url=self.base_url, auth=(SERVER_USER, self.password), timeout=httpx.Timeout(30.0, read=None),
        )
        deadline = asyncio.get_running_loop().time() + settings.OPENCODE_START_TIMEOUT
        while True:
            if not self._running():
                raise CodingAgentError(f"OpenCode stopped while starting; see {self.home / 'serve.log'}.")
            try:
                response = await self.client.get("/global/health", timeout=2.0)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if asyncio.get_running_loop().time() > deadline:
                await self._stop()
                raise CodingAgentError("OpenCode didn't start in time.")
            await asyncio.sleep(0.25)
        self.digest = digest
        self._connected.clear()
        self._events_task = asyncio.create_task(self._follow_events())
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=10)
        except asyncio.TimeoutError:
            logger.warning("OpenCode's event stream didn't connect in time")
        logger.info("OpenCode is running on %s", self.base_url)

    def _kill_stale(self) -> None:
        """A previous Open Dots that didn't exit cleanly may have left its OpenCode running."""
        pid_file = self.home / "serve.pid"
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return
        pid_file.unlink(missing_ok=True)
        try:
            os.kill(pid, 0)
        except OSError:
            return
        try:
            command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True,
                                     text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return
        # The number may belong to another program by now: only stop an OpenCode server.
        if "opencode" not in command or "serve" not in command:
            return
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()

    async def _stop(self) -> None:
        if self._events_task:
            self._events_task.cancel()
            self._events_task = None
        if self.client:
            await self.client.aclose()
            self.client = None
        if self._running():
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except OSError:
                    pass
        self.process = None
        (self.home / "serve.pid").unlink(missing_ok=True)
        self.digest = None

    # ----- events ------------------------------------------------------------

    def listen(self, session_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.setdefault(session_id, set()).add(queue)
        return queue

    def unlisten(self, session_id: str, queue: asyncio.Queue) -> None:
        queues = self._listeners.get(session_id)
        if queues:
            queues.discard(queue)
            if not queues:
                self._listeners.pop(session_id, None)

    def _dispatch(self, event: Dict[str, Any]) -> None:
        properties = event.get("properties") or {}
        session_id = properties.get("sessionID")
        if not session_id and isinstance(properties.get("info"), dict):
            session_id = properties["info"].get("sessionID")
        if not session_id and isinstance(properties.get("part"), dict):
            session_id = properties["part"].get("sessionID")
        for queue in list(self._listeners.get(session_id, ())):
            queue.put_nowait(event)

    def _broadcast(self, event: Dict[str, Any]) -> None:
        for queues in list(self._listeners.values()):
            for queue in list(queues):
                queue.put_nowait(event)

    async def _follow_events(self) -> None:
        while self._running() and self.client:
            try:
                async with self.client.stream("GET", "/global/event") as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            envelope = json.loads(line[5:])
                        except json.JSONDecodeError:
                            continue
                        event = envelope.get("payload") if isinstance(envelope, dict) else None
                        if not isinstance(event, dict):
                            continue
                        if event.get("type") == "server.connected":
                            self._connected.set()
                            continue
                        self._dispatch(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # The stream dropped; replies in progress can't finish.
                logger.warning("OpenCode event stream dropped: %s", exc)
            self._broadcast({"type": "agent.disconnected", "properties": {}})
            await asyncio.sleep(1)

    # ----- requests ----------------------------------------------------------

    async def _request(self, method: str, path: str, directory: str, body: Any = None) -> Any:
        if not self.client:
            raise CodingAgentError("OpenCode isn't running.")
        try:
            response = await self.client.request(method, path, params={"directory": directory}, json=body,
                                                 timeout=30.0)
        except httpx.HTTPError as exc:
            raise CodingAgentError(f"OpenCode didn't answer: {exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise CodingAgentError(f"OpenCode refused {method} {path} ({response.status_code}): {response.text[:300]}")
        if response.status_code == 204 or not response.content:
            return True
        return response.json()

    async def session_exists(self, session_id: str, directory: str) -> bool:
        return bool(await self._request("GET", f"/session/{session_id}", directory))

    async def create_session(self, directory: str, title: str) -> str:
        session = await self._request("POST", "/session", directory, {"title": title or "Open Dots"})
        if not isinstance(session, dict) or not session.get("id"):
            raise CodingAgentError("OpenCode didn't create a session.")
        return session["id"]

    async def prompt(self, session_id: str, directory: str, text: str, image_url: Optional[str],
                     model: Dict[str, str]) -> None:
        parts: List[Dict[str, Any]] = []
        if text:
            parts.append({"type": "text", "text": text})
        if image_url and image_url.startswith("data:"):
            mime = image_url[5:].split(";", 1)[0] or "image/png"
            parts.append({"type": "file", "mime": mime, "url": image_url, "filename": "photo"})
        if not parts:
            parts.append({"type": "text", "text": "(empty message)"})
        await self._request("POST", f"/session/{session_id}/prompt_async", directory, {"parts": parts, "model": model})

    async def abort(self, session_id: str, directory: str) -> None:
        await self._request("POST", f"/session/{session_id}/abort", directory)

    async def reply_permission(self, request_id: str, directory: str, reply: str) -> None:
        await self._request("POST", f"/permission/{request_id}/reply", directory, {"reply": reply})


coding_agent = OpenCodeAgent()
