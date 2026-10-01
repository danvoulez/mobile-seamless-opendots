import unittest
from unittest.mock import patch

import httpx

from app.routers import models as models_router
from app.services.model_catalog import (
    CATALOG_TTL_SECONDS,
    RETRY_AFTER_FAILURE_SECONDS,
    ModelCatalog,
    chat_models_from_listing,
)

GATEWAY_LISTING = {
    "object": "list",
    "data": [
        {"id": "openai/gpt-old", "name": "GPT Old", "owned_by": "openai", "type": "language", "released": 100},
        {"id": "openai/gpt-new", "name": "GPT New", "owned_by": "openai", "type": "language", "released": 200},
        {"id": "bfl/flux", "name": "Flux", "owned_by": "bfl", "type": "image", "released": 300},
        {"id": "zai/glm", "name": "GLM", "owned_by": "zai", "type": "language", "released": 50},
        {"id": "anthropic/claude", "name": "Claude", "owned_by": "anthropic", "type": "language"},
        {"name": "no id"},
    ],
}


class ChatModelsFromListingTests(unittest.TestCase):
    def test_keeps_chat_models_by_provider_newest_first(self):
        models = chat_models_from_listing(GATEWAY_LISTING)
        self.assertEqual(
            [(m.provider, m.id) for m in models],
            [("Anthropic", "anthropic/claude"), ("OpenAI", "openai/gpt-new"), ("OpenAI", "openai/gpt-old"), ("Z.ai", "zai/glm")],
        )

    def test_a_plain_openai_listing_without_types_or_names(self):
        models = chat_models_from_listing({"data": [{"id": "gpt-5", "owned_by": "openai", "created": 1}]})
        self.assertEqual([(m.id, m.name, m.provider) for m in models], [("gpt-5", "gpt-5", "OpenAI")])

    def test_anything_else_is_an_empty_catalog(self):
        self.assertEqual(chat_models_from_listing({"error": "nope"}), [])
        self.assertEqual(chat_models_from_listing(["not", "a", "listing"]), [])


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ModelCatalogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = Clock()
        self.calls = []
        self.fail = False

    async def fetch(self, url, headers):
        self.calls.append((url, headers))
        if self.fail:
            raise httpx.ConnectError("offline")
        return GATEWAY_LISTING

    async def test_fetches_once_with_the_key_then_serves_the_cache(self):
        catalog = ModelCatalog(self.fetch, self.clock)
        first = await catalog.chat_models("https://gateway.example/v1", "key", {"X-Team": "lab"})
        self.clock.now += CATALOG_TTL_SECONDS - 1
        second = await catalog.chat_models("https://gateway.example/v1", "key")
        self.assertEqual(len(first), 4)
        self.assertIs(first, second)
        self.assertEqual(self.calls, [("https://gateway.example/v1/models", {"X-Team": "lab", "Authorization": "Bearer key"})])

    async def test_a_failing_provider_is_left_alone_for_a_while(self):
        catalog = ModelCatalog(self.fetch, self.clock)
        self.fail = True
        self.assertEqual(await catalog.chat_models("https://gateway.example/v1"), [])
        self.fail = False
        self.assertEqual(await catalog.chat_models("https://gateway.example/v1"), [])  # not asked again yet
        self.assertEqual(len(self.calls), 1)
        self.clock.now += RETRY_AFTER_FAILURE_SECONDS
        self.assertEqual(len(await catalog.chat_models("https://gateway.example/v1")), 4)

    async def test_an_expired_list_is_still_used_while_the_provider_fails(self):
        catalog = ModelCatalog(self.fetch, self.clock)
        good = await catalog.chat_models("https://gateway.example/v1")
        self.clock.now += CATALOG_TTL_SECONDS
        self.fail = True
        self.assertIs(await catalog.chat_models("https://gateway.example/v1"), good)
        self.assertEqual(len(self.calls), 2)


class ListModelsRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.catalog = ModelCatalog()
        patcher = patch.object(models_router, "model_catalog", self.catalog)
        patcher.start()
        self.addCleanup(patcher.stop)

    def configure(self, **values):
        patcher = patch.object(models_router.storage_service, "get_settings", return_value=values)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_a_responses_provider_offers_its_live_list(self):
        async def fetch(url, headers):
            return GATEWAY_LISTING

        self.catalog.fetch = fetch
        self.configure(model_api_wire_api="responses", model_api_base_url="https://gateway.example/v1", model_ids=["typed/model"])
        self.assertEqual((await models_router.list_models())[0].id, "anthropic/claude")

    async def test_without_a_live_list_the_typed_ids_are_used(self):
        async def fetch(url, headers):
            raise httpx.HTTPStatusError("404", request=httpx.Request("GET", url), response=httpx.Response(404))

        self.catalog.fetch = fetch
        self.configure(model_api_wire_api="responses", model_api_base_url="https://other.example/v1", model_ids=["typed/model"])
        self.assertEqual([m.id for m in await models_router.list_models()], ["typed/model"])

    async def test_the_prediction_api_is_never_asked_for_a_list(self):
        async def fetch(url, headers):
            raise AssertionError("should not fetch")

        self.catalog.fetch = fetch
        self.configure(model_api_wire_api="prediction", model_api_base_url="https://predict.example", model_ids=[])
        self.assertEqual(await models_router.list_models(), models_router.AVAILABLE_MODELS)


if __name__ == "__main__":
    unittest.main()
