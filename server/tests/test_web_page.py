"""One address serves the Mac page, the iPhone app and the API."""

import unittest

import httpx

from app.config import settings

try:
    from app.main import app
except ModuleNotFoundError:
    app = None

ADDRESS = "http://studio.local:4747"
IPHONE_SAFARI = "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1"
ANDROID_CHROME = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36"
MAC_SAFARI = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15"
IPAD_SAFARI = MAC_SAFARI  # iPadOS asks for the desktop site by default


@unittest.skipIf(app is None, "FastAPI dependencies are not installed")
class OneAddressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        transport = httpx.ASGITransport(app=app, client=("192.168.0.20", 43123))
        self.client = httpx.AsyncClient(transport=transport, base_url=ADDRESS)

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_a_page_from_this_address_may_use_the_api(self):
        response = await self.client.get("/api/v1/models", headers={"Origin": ADDRESS})
        self.assertEqual(response.status_code, 401)  # trusted, just not signed in

    @unittest.skipIf("http://localhost:3000" in settings.CORS_ORIGINS, "CORS_ORIGINS trusts port 3000 here")
    async def test_another_app_on_this_computer_may_not(self):
        response = await self.client.get("/api/v1/models", headers={"Origin": "http://localhost:3000"})
        self.assertEqual(response.status_code, 403)

    async def test_the_phone_address_opens_the_phone_app(self):
        response = await self.client.get("/m")
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/m/")

    async def test_the_bare_address_is_the_mac_page_on_a_computer(self):
        for agent in (MAC_SAFARI, IPAD_SAFARI):
            response = await self.client.get("/", headers={"User-Agent": agent})
            self.assertFalse(response.is_redirect, agent)
            self.assertEqual(response.headers.get("cache-control"), "no-cache")
            self.assertIn("User-Agent", response.headers.get("vary", ""))

    async def test_the_bare_address_is_the_phone_app_on_a_phone(self):
        for agent in (IPHONE_SAFARI, ANDROID_CHROME):
            response = await self.client.get("/?pair=abcd-efgh", headers={"User-Agent": agent})
            self.assertEqual(response.status_code, 307, agent)
            self.assertEqual(response.headers["location"], "/m/?pair=ABCD-EFGH")
            self.assertIn("User-Agent", response.headers.get("vary", ""))

    async def test_a_missing_script_is_not_cached(self):
        response = await self.client.get("/_next/static/missing.js")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers.get("cache-control"), "no-cache")


if __name__ == "__main__":
    unittest.main()
