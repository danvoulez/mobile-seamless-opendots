import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.device_service import device_may_access
from app.services.event_bus import EventBus
from app.services.update_service import UpdateService, UpdateUnavailable


def run_git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


class FakeStorage:
    def __init__(self):
        self.values = {"auto_update": True}

    def get_settings(self):
        return dict(self.values)

    def save_settings(self, data):
        self.values.update(data)


class Repos:
    """An origin, a developer's clone that pushes to it, and an install."""

    def __init__(self, root: Path):
        self.origin = root / "origin.git"
        self.work = root / "work"
        self.install = root / "install"
        run_git(root, "init", "--quiet", "--bare", "-b", "main", str(self.origin))
        run_git(root, "clone", "--quiet", str(self.origin), str(self.work))
        self.commit("First version")
        run_git(self.work, "push", "--quiet", "origin", "HEAD:main", "HEAD:stable")
        run_git(root, "clone", "--quiet", "--branch", "stable", str(self.origin), str(self.install))

    def commit(self, subject: str) -> str:
        (self.work / "notes.txt").write_text(subject + "\n")
        run_git(self.work, "add", "notes.txt")
        run_git(self.work, "commit", "--quiet", "-m", subject)
        return run_git(self.work, "rev-parse", "HEAD")

    def publish(self, *subjects: str) -> str:
        for subject in subjects:
            head = self.commit(subject)
        run_git(self.work, "push", "--quiet", "origin", "HEAD:main", "HEAD:stable")
        return head


class SignalCatcher:
    """A stand-in for the start script: notes the "update now" signal."""

    def __init__(self, directory: Path):
        self.flag = directory / "update-requested"
        self.ready = directory / "catcher-ready"
        code = (
            "import signal, sys, time, pathlib\n"
            "signal.signal(signal.SIGUSR1, lambda *a: pathlib.Path(sys.argv[1]).write_text('yes'))\n"
            "pathlib.Path(sys.argv[2]).write_text('ready')\n"
            "time.sleep(60)\n"
        )
        self.process = subprocess.Popen([sys.executable, "-c", code, str(self.flag), str(self.ready)])
        deadline = time.time() + 10
        while not self.ready.exists() and time.time() < deadline:
            time.sleep(0.05)

    def signalled(self) -> bool:
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.flag.exists():
                return True
            time.sleep(0.05)
        return False

    def stop(self):
        self.process.kill()
        self.process.wait()


class UpdateServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.repos = Repos(self.root)
        self.turns = SimpleNamespace(active={})
        self.storage = FakeStorage()
        self.bus = EventBus()
        self.catcher = None

    def tearDown(self):
        if self.catcher:
            self.catcher.stop()
        self.directory.cleanup()

    def service(self, **overrides) -> UpdateService:
        options = dict(root=self.repos.install, data_dir=self.root / "data", bus=self.bus, turns=self.turns, storage=self.storage)
        options.update(overrides)
        return UpdateService(**options)

    def supervised(self):
        self.catcher = SignalCatcher(self.root)
        return patch.dict(os.environ, {"OPEN_DOTS_SUPERVISOR_PID": str(self.catcher.process.pid)})

    async def test_reports_the_running_version_and_nothing_new(self):
        service = self.service()
        self.assertEqual(service.current["subject"], "First version")
        self.assertEqual(len(service.version), 7)
        status = await service.check()
        self.assertIsNone(status["available"])
        self.assertIsNone(status["check_error"])
        self.assertIsNotNone(status["checked_at"])

    async def test_finds_what_was_published_with_its_changes(self):
        service = self.service()
        head = self.repos.publish("Quieter cards", "Faster steps")
        subscription = self.bus.subscribe()
        available = (await service.check())["available"]
        self.assertEqual(available["commit"], head)
        self.assertEqual(available["count"], 2)
        self.assertEqual([change["subject"] for change in available["changes"]], ["Faster steps", "Quieter cards"])
        self.assertFalse(available["failed_before"])
        event = await subscription.next(timeout=1)
        self.assertEqual(event["type"], "update.status")
        self.assertEqual(event["update"]["available"]["commit"], head)

    async def test_a_checkout_ahead_of_the_channel_has_nothing_to_install(self):
        (self.repos.install / "local.txt").write_text("mine\n")
        run_git(self.repos.install, "add", "local.txt")
        run_git(self.repos.install, "commit", "--quiet", "-m", "Local work")
        self.assertIsNone((await self.service().check())["available"])

    async def test_a_version_that_was_rolled_back_is_not_retried_by_itself(self):
        head = self.repos.publish("Broken change")
        status_file = self.root / "data" / "update" / "status.json"
        status_file.parent.mkdir(parents=True)
        status_file.write_text(json.dumps({"state": "rolled-back", "to": head}))
        with self.supervised():
            service = self.service()
            self.assertTrue((await service.check())["available"]["failed_before"])
            service._maybe_install()
            self.assertEqual(service.state, "idle")
            self.assertFalse(self.catcher.flag.exists())
            # Asking for it explicitly still tries again.
            await service.request()
            self.assertTrue(self.catcher.signalled())

    async def test_a_failure_without_a_version_holds_automatic_updates_for_a_while(self):
        self.repos.publish("New version")
        status_file = self.root / "data" / "update" / "status.json"
        status_file.parent.mkdir(parents=True)
        with self.supervised():
            service = self.service()
            await service.check()
            status_file.write_text(json.dumps({"state": "failed", "to": "", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
            service._maybe_install()
            self.assertEqual(service.state, "idle")
            status_file.write_text(json.dumps({"state": "failed", "to": "", "at": "2020-01-01T00:00:00Z"}))
            service._maybe_install()
            self.assertEqual(service.state, "updating")
            self.assertTrue(self.catcher.signalled())

    async def test_unreachable_origin_is_reported_not_raised(self):
        run_git(self.repos.install, "remote", "set-url", "origin", str(self.root / "missing.git"))
        status = await self.service().check()
        self.assertIsNone(status["available"])
        self.assertIn("Couldn't check", status["check_error"])

    async def test_local_changes_block_updates_before_anything_restarts(self):
        (self.repos.install / "notes.txt").write_text("edited here\n")
        with self.supervised():
            service = self.service()
            self.assertIn("local changes", service.status()["reason"])
            with self.assertRaises(UpdateUnavailable):
                await service.request()
            service.available = {"commit": "x", "failed_before": False}
            service._maybe_install()
            self.assertFalse(self.catcher.flag.exists())

    async def test_installing_needs_the_start_script(self):
        service = self.service()
        with patch.dict(os.environ, {"OPEN_DOTS_SUPERVISOR_PID": ""}):
            self.assertFalse(service.status()["can_update"])
            with self.assertRaises(UpdateUnavailable):
                await service.request()

    async def test_install_asks_the_start_script_and_waits_for_replies(self):
        self.repos.publish("New version")
        with self.supervised():
            service = self.service()
            await service.check()
            self.turns.active = {"thread-1": object()}
            self.assertEqual((await service.request())["state"], "waiting")
            service._maybe_install()
            self.assertFalse(self.catcher.flag.exists())
            self.turns.active = {}
            service._maybe_install()
            self.assertEqual(service.state, "updating")
            self.assertTrue(self.catcher.signalled())
            # Also asked through a file, for where the signal can't get through.
            self.assertTrue((self.root / "data" / "update" / "requested").exists())

    async def test_automatic_updates_follow_the_setting(self):
        self.repos.publish("New version")
        with self.supervised():
            service = self.service()
            service.set_auto(False)
            self.assertFalse(service.status()["auto"])
            await service.check()
            service._maybe_install()
            self.assertEqual(service.state, "idle")
            service.set_auto(True)
            service._maybe_install()
            self.assertEqual(service.state, "updating")
            self.assertTrue(self.catcher.signalled())

    async def test_not_a_git_checkout(self):
        plain = self.root / "plain"
        plain.mkdir()
        service = self.service(root=plain)
        self.assertIsNone(service.current)
        self.assertIn("git checkout", service.status()["reason"])
        self.assertIsNone((await service.check())["available"])

    def test_linked_phones_cannot_update_or_mint_sign_in_links(self):
        for method, path in (("GET", "/api/v1/system/update"), ("POST", "/api/v1/system/update"),
                             ("PUT", "/api/v1/system/update"), ("POST", "/api/v1/auth/signin-links")):
            self.assertFalse(device_may_access(method, path), path)


if __name__ == "__main__":
    unittest.main()
