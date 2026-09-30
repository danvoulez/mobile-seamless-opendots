"""Which version of Open Dots is running, and getting the next one.

Open Dots is installed as a git checkout. Changes merged to main are tested in
CI and, once everything passes, published to the ``stable`` branch; this
computer follows that branch. Checking fetches it. Installing hands over to
the start script (scripts/start-mac.sh), which stops Open Dots, runs
scripts/update.sh, starts the new version and goes back to the previous one
if it doesn't come up.
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.event_bus import EventBus, event_bus
from app.services.storage_service import StorageService, storage_service
from app.services.turn_service import TurnService, turn_service


logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
MAX_CHANGES = 20
TICK_SECONDS = 10
# After an update fails before it knows which version it was installing (say,
# offline), wait this long before trying again by itself.
RETRY_AFTER_SECONDS = 30 * 60
FIELD = "\x1f"


class GitError(Exception):
    pass


class UpdateUnavailable(Exception):
    pass


def git(root: Path, *args: str, timeout: float = 20) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(str(exc)) from exc


def git_output(root: Path, *args: str, timeout: float = 20) -> str:
    result = git(root, *args, timeout=timeout)
    if result.returncode != 0:
        raise GitError((result.stderr or "").strip() or f"git {args[0]} failed")
    return result.stdout.strip()


def describe(root: Path, ref: str = "HEAD") -> Optional[Dict[str, str]]:
    try:
        commit, date, subject = git_output(root, "log", "-1", f"--format=%H{FIELD}%cI{FIELD}%s", ref).split(FIELD, 2)
    except (GitError, ValueError):
        return None
    return {"commit": commit, "short": commit[:7], "date": date, "subject": subject}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UpdateService:
    def __init__(
        self,
        root: Path = REPO_ROOT,
        data_dir: Path = settings.DATA_DIR,
        bus: EventBus = event_bus,
        turns: TurnService = turn_service,
        storage: StorageService = storage_service,
        channel: str = settings.UPDATE_CHANNEL,
    ):
        self.root = root
        self.status_path = data_dir / "update" / "status.json"
        # The start script looks for this file every couple of seconds.
        self.request_path = data_dir / "update" / "requested"
        self.bus = bus
        self.turns = turns
        self.storage = storage
        self.channel = channel
        # The running code. It changes only by restarting, so read it once.
        self.current = describe(root)
        self.available: Optional[Dict[str, Any]] = None
        self.checked_at: Optional[str] = None
        self.check_error: Optional[str] = None
        self.state = "idle"  # idle | waiting (for a reply to finish) | updating
        self._checking = asyncio.Lock()

    # ----- what clients see ----------------------------------------------------

    @property
    def version(self) -> Optional[str]:
        return self.current["short"] if self.current else None

    @property
    def auto(self) -> bool:
        return self.storage.get_settings().get("auto_update", True) is not False

    def set_auto(self, enabled: bool) -> Dict[str, Any]:
        self.storage.save_settings({"auto_update": bool(enabled)})
        self.publish()
        return self.status()

    @staticmethod
    def supervisor_pid() -> Optional[int]:
        """The start script that runs this server, which performs updates."""
        raw = os.getenv("OPEN_DOTS_SUPERVISOR_PID", "")
        if not raw.isdigit():
            return None
        try:
            os.kill(int(raw), 0)
        except OSError:
            return None
        return int(raw)

    def has_local_changes(self) -> bool:
        try:
            return bool(git_output(self.root, "status", "--porcelain", "--untracked-files=no"))
        except GitError:
            return False

    def unavailable_reason(self) -> Optional[str]:
        if self.current is None:
            return "This copy of Open Dots isn't a git checkout, so it can't update itself."
        if self.supervisor_pid() is None:
            return "Start Open Dots with scripts/start-mac.sh to install updates from here."
        if self.has_local_changes():
            return f"There are local changes in {self.root}. Commit or discard them to get updates."
        return None

    def last_result(self) -> Optional[Dict[str, Any]]:
        """What the last update did, as recorded by scripts/update.sh."""
        try:
            data = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def status(self) -> Dict[str, Any]:
        reason = self.unavailable_reason()
        return {
            "current": self.current,
            "channel": self.channel,
            "available": self.available,
            "state": self.state,
            "auto": self.auto,
            "checked_at": self.checked_at,
            "check_error": self.check_error,
            "can_update": reason is None,
            "reason": reason,
            "last": self.last_result(),
        }

    def publish(self) -> None:
        self.bus.publish({"type": "update.status", "update": self.status()})

    # ----- checking ------------------------------------------------------------

    async def check(self) -> Dict[str, Any]:
        if self.current is None:
            return self.status()
        async with self._checking:
            try:
                self.available = await asyncio.to_thread(self._find_update)
                self.check_error = None
            except GitError as exc:
                logger.warning("Update check failed: %s", exc)
                self.check_error = "Couldn't check for updates. Is this computer online?"
            self.checked_at = _now()
        self.publish()
        return self.status()

    def _find_update(self) -> Optional[Dict[str, Any]]:
        tracking = f"refs/remotes/origin/{self.channel}"
        git_output(self.root, "fetch", "--quiet", "--no-tags", "origin", f"+refs/heads/{self.channel}:{tracking}", timeout=90)
        target = git_output(self.root, "rev-parse", tracking)
        head = self.current["commit"]
        if target == head:
            return None
        # A checkout that already has everything on the channel (say, a
        # developer's own clone that is ahead of it) has nothing to install.
        ancestor = git(self.root, "merge-base", "--is-ancestor", target, head)
        if ancestor.returncode == 0:
            return None
        if ancestor.returncode != 1:
            raise GitError((ancestor.stderr or "").strip() or "git merge-base failed")
        count = int(git_output(self.root, "rev-list", "--count", f"{head}..{target}"))
        log = git_output(self.root, "log", f"--format=%h{FIELD}%s{FIELD}%cI", f"-{MAX_CHANGES}", "--no-merges", f"{head}..{target}")
        changes: List[Dict[str, str]] = []
        for line in log.splitlines():
            parts = line.split(FIELD, 2)
            if len(parts) == 3:
                changes.append({"short": parts[0], "subject": parts[1], "date": parts[2]})
        last = self.last_result() or {}
        return {
            **(describe(self.root, target) or {"commit": target, "short": target[:7]}),
            "count": count,
            "changes": changes,
            # Tried already and it didn't work: wait for a newer version, unless asked.
            "failed_before": last.get("state") in {"rolled-back", "failed"} and last.get("to") == target,
        }

    # ----- installing ----------------------------------------------------------

    async def request(self) -> Dict[str, Any]:
        """Install the available update now, or as soon as replies finish."""
        reason = self.unavailable_reason()
        if reason:
            raise UpdateUnavailable(reason)
        if self.state != "updating":
            if self.turns.active:
                self.state = "waiting"
                self.publish()
            else:
                self._start()
        return self.status()

    def _start(self) -> None:
        pid = self.supervisor_pid()
        if pid is None:
            return
        self.state = "updating"
        self.publish()  # before the restart, so every client can say so
        # Ask twice: a file the start script checks every couple of seconds,
        # which works even where the signal is ignored, and the signal, which
        # wakes it at once.
        self.request_path.parent.mkdir(parents=True, exist_ok=True)
        self.request_path.write_text(_now() + "\n", encoding="utf-8")
        try:
            os.kill(pid, signal.SIGUSR1)
        except OSError:
            pass

    def _auto_blocked(self, target: str) -> bool:
        """Whether a recent failure means automatic updates should hold off."""
        last = self.last_result() or {}
        if last.get("state") not in {"failed", "rolled-back"}:
            return False
        if last.get("to"):
            return last.get("to") == target  # a newer version gets its own try
        try:
            at = datetime.fromisoformat(str(last.get("at")).replace("Z", "+00:00"))
        except ValueError:
            return False
        return (datetime.now(timezone.utc) - at).total_seconds() < RETRY_AFTER_SECONDS

    def _maybe_install(self) -> None:
        if self.state == "updating" or self.turns.active or self.unavailable_reason():
            return
        if self.state == "waiting":
            self._start()  # asked for by hand
        elif self.available and self.auto and not self._auto_blocked(self.available["commit"]):
            self._start()

    async def run(self) -> None:
        """Check every few minutes; install when allowed and nothing is running."""
        loop = asyncio.get_running_loop()
        next_check = loop.time()
        while True:
            try:
                if loop.time() >= next_check:
                    next_check = loop.time() + max(5.0, settings.UPDATE_CHECK_MINUTES * 60)
                    await self.check()
                self._maybe_install()
            except asyncio.CancelledError:
                raise
            except Exception:  # never let the checker take the server down
                logger.exception("Update checker failed")
            await asyncio.sleep(TICK_SECONDS)

    def start(self) -> Optional[asyncio.Task]:
        # Only a server run by the start script checks by itself; tests and
        # hand-started servers can still check on request.
        if self.supervisor_pid() is None or self.current is None or settings.UPDATE_CHECK_MINUTES <= 0:
            return None
        return asyncio.create_task(self.run())


update_service = UpdateService()
