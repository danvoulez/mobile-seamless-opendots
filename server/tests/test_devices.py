import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.main import app
from app.routers import devices as devices_router
from app.routers import threads as threads_router
from app.services import device_service as device_module
from app.services.auth_service import auth_service
from app.services.device_service import DEVICE_COOKIE, DeviceService, PairingError
from app.services.event_bus import EventBus
from app.services.storage_service import StorageService
from app.services.turn_service import TurnService

IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"


class DeviceLinkingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.directory.name))
        self.devices = DeviceService(self.storage.database)
        self.bus = EventBus()
        self.turns = TurnService(storage=self.storage, bus=self.bus)
        self.patches = [
            patch("app.main.device_service", self.devices),
            patch.object(devices_router, "device_service", self.devices),
            patch.object(devices_router, "event_bus", self.bus),
            patch.object(threads_router, "storage_service", self.storage),
            patch.object(threads_router, "turn_service", self.turns),
            patch.object(threads_router, "event_bus", self.bus),
        ]
        for item in self.patches:
            item.start()
        transport = httpx.ASGITransport(app=app, client=("192.168.1.20", 50000))
        self.mac = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1")
        self.phone = httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1", headers={"User-Agent": IPHONE_UA}
        )
        await self.mac.post("/api/v1/auth/login", json={"token": auth_service.token})

    async def asyncTearDown(self):
        await self.mac.aclose()
        await self.phone.aclose()
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    async def link_phone(self):
        pairing = (await self.mac.post("/api/v1/devices/pairing")).json()
        response = await self.phone.post("/api/v1/devices/pair", json={"code": pairing["code"]})
        self.assertEqual(response.status_code, 200, response.text)
        return pairing, response

    async def test_pairing_link_and_qr_come_from_the_computer(self):
        with patch.object(devices_router, "base_urls", return_value=[{"url": "http://studio.local:8000", "kind": "Bonjour name"}]):
            pairing = (await self.mac.post("/api/v1/devices/pairing")).json()
        self.assertRegex(pairing["code"], r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertEqual(pairing["url"], f"http://studio.local:8000/m/?pair={pairing['code']}")
        self.assertEqual(len(pairing["qr"]["rows"]), pairing["qr"]["size"])
        self.assertFalse(pairing["reachable"])  # tests run with the loopback default

    async def test_code_links_phone_once_with_a_durable_httponly_cookie(self):
        pairing, response = await self.link_phone()
        cookie_header = response.headers["set-cookie"]
        self.assertIn(f"{DEVICE_COOKIE}=", cookie_header)
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("Max-Age=34560000", cookie_header)
        self.assertNotIn("token", response.json())
        self.assertEqual(response.json()["device"]["name"], "iPhone")
        self.assertEqual(self.bus.subscriber_count, 0)

        current = (await self.phone.get("/api/v1/devices/current")).json()
        self.assertEqual(current["device"]["name"], "iPhone")
        again = await httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ).post("/api/v1/devices/pair", json={"code": pairing["code"]})
        self.assertEqual(again.status_code, 400)

    async def test_linked_phone_continues_conversations_but_cannot_administer(self):
        await self.link_phone()
        self.assertEqual((await self.phone.get("/api/v1/threads")).status_code, 200)
        self.assertEqual((await self.phone.get("/api/v1/bots")).status_code, 200)
        created = await self.phone.post("/api/v1/threads", json={"bot_id": "bot-open-dots-1"})
        self.assertEqual(created.status_code, 201)
        with patch.object(self.turns, "start") as start:
            start.return_value.snapshot.return_value = {}
            sent = await self.phone.post(f"/api/v1/threads/{created.json()['id']}/messages", json={"text": "Hi"})
        self.assertEqual(sent.status_code, 202)
        self.assertEqual(sent.json()["message"]["origin"], "iPhone")

        for method, path in (
            ("GET", "/api/v1/settings"),
            ("POST", "/api/v1/settings"),
            ("POST", "/api/v1/devices/pairing"),
            ("GET", "/api/v1/devices"),
            ("POST", "/api/v1/bots"),
            ("GET", "/api/v1/audit"),
            ("GET", "/api/v1/computers/bot-open-dots-1"),
            ("GET", "/api/v1/connectors/catalog"),
            ("DELETE", f"/api/v1/threads/{created.json()['id']}"),
            ("GET", "/api/v1/auth/session"),
        ):
            with self.subTest(method=method, path=path):
                response = await self.phone.request(method, path, json={} if method == "POST" else None)
                self.assertIn(response.status_code, {401, 403})

    async def test_unlinking_from_either_side_revokes_the_phone(self):
        await self.link_phone()
        device_id = (await self.mac.get("/api/v1/devices")).json()[0]["id"]
        self.assertEqual((await self.mac.delete(f"/api/v1/devices/{device_id}")).status_code, 200)
        self.assertEqual((await self.phone.get("/api/v1/threads")).status_code, 401)

        await self.link_phone()
        self.assertEqual((await self.phone.delete("/api/v1/devices/current")).status_code, 200)
        self.assertEqual((await self.mac.get("/api/v1/devices")).json(), [])

    async def test_bearer_device_credential_and_origin_check(self):
        pairing = self.devices.create_pairing_code()
        _, token = self.devices.redeem(pairing["code"], IPHONE_UA)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as native:
            ok = await native.get("/api/v1/threads", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(ok.status_code, 200)
            forged = await native.get(
                "/api/v1/threads",
                headers={"Authorization": f"Bearer {token}", "Origin": "http://evil.example"},
            )
            self.assertEqual(forged.status_code, 403)


class PairingCodeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.devices = DeviceService(StorageService(Path(self.directory.name)).database)

    def tearDown(self):
        self.directory.cleanup()

    def test_codes_are_forgiving_to_type(self):
        code = self.devices.create_pairing_code()["code"]
        device, token = self.devices.redeem(f"  {code.replace('-', '').lower()} ")
        self.assertTrue(token.startswith("odd_"))
        self.assertEqual(self.devices.authenticate(token)["id"], device["id"])

    def test_expired_codes_are_rejected(self):
        with patch.object(device_module.settings, "PAIRING_CODE_TTL_SECONDS", -1):
            code = self.devices.create_pairing_code()["code"]
        with self.assertRaises(PairingError):
            self.devices.redeem(code)

    def test_repeated_guesses_void_outstanding_codes(self):
        code = self.devices.create_pairing_code()["code"]
        for _ in range(device_module.MAX_FAILED_ATTEMPTS):
            with self.assertRaises(PairingError):
                self.devices.redeem("AAAA-AAAA")
        with self.assertRaises(PairingError):
            self.devices.redeem(code)

    def test_tokens_are_stored_hashed(self):
        code = self.devices.create_pairing_code()["code"]
        _, token = self.devices.redeem(code)
        raw = Path(self.devices.database.path).read_bytes()
        self.assertNotIn(token.encode(), raw)


class MobileAppServingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_page_carries_pair_code_into_manifest_and_strict_headers(self):
        page = await self.client.get("/m/?pair=abcd-efgh")
        self.assertEqual(page.status_code, 200)
        self.assertIn('href="/m/manifest.webmanifest?pair=ABCD-EFGH"', page.text)
        self.assertIn("script-src 'self'", page.headers["content-security-policy"])
        self.assertEqual(page.headers["cache-control"], "no-cache")

        manifest = (await self.client.get("/m/manifest.webmanifest?pair=ABCD-EFGH")).json()
        self.assertEqual(manifest["start_url"], "/m/?pair=ABCD-EFGH")
        self.assertEqual(manifest["display"], "standalone")

    async def test_untrusted_pair_values_are_dropped(self):
        page = await self.client.get('/m/?pair="><script>alert(1)</script>')
        self.assertIn('href="/m/manifest.webmanifest"', page.text)
        self.assertNotIn("<script>alert", page.text)
        redirect = await self.client.get("/?pair=ABCD-EFGH")
        self.assertEqual(redirect.headers["location"], "/m/?pair=ABCD-EFGH")


if __name__ == "__main__":
    unittest.main()
