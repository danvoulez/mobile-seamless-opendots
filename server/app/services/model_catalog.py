"""The chat models the configured provider offers, from its own /models list.

Vercel AI Gateway and other OpenAI-compatible services publish one; it is
fetched on demand and kept for an hour. This only lists models: each
assistant names the one it calls (turn_service).
"""

import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import httpx

from app.schemas.contracts import ModelInfo


logger = logging.getLogger(__name__)

CATALOG_TTL_SECONDS = 60 * 60
# The Mac page waits for this list while it opens: when the provider is slow or
# down, give up quickly and don't ask again for a while.
FETCH_TIMEOUT_SECONDS = 5.0
RETRY_AFTER_FAILURE_SECONDS = 5 * 60

# How providers are written where the listing only has an id like "zai".
# Any other id is shown capitalized ("anthropic" → "Anthropic").
PROVIDER_NAMES = {
    "openai": "OpenAI",
    "spacexai": "SpaceX AI",
    "xai": "xAI",
    "zai": "Z.ai",
    "deepseek": "DeepSeek",
    "minimax": "MiniMax",
    "moonshotai": "Moonshot AI",
    "inclusionai": "inclusionAI",
    "nvidia": "NVIDIA",
    "bytedance": "ByteDance",
    "stepfun": "StepFun",
    "thinkingmachines": "Thinking Machines",
    "arcee-ai": "Arcee AI",
    "inference-net": "Inference.net",
    "quiverai": "QuiverAI",
}


def provider_name(owner: str) -> str:
    return PROVIDER_NAMES.get(owner.lower(), owner[:1].upper() + owner[1:]) if owner else "Configured provider"


def chat_models_from_listing(listing: Any) -> List[ModelInfo]:
    """Core: an OpenAI-style {"data": [...]} listing → chat models, newest first per provider."""
    entries = listing.get("data") if isinstance(listing, dict) else None
    if not isinstance(entries, list):
        return []
    found: List[Tuple[str, int, ModelInfo]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        # The Gateway also lists image, video and embedding models; plain
        # OpenAI-style listings have no type, so keep those.
        if entry.get("type") not in (None, "language"):
            continue
        model_id = entry["id"]
        owner = entry.get("owned_by") or (model_id.split("/", 1)[0] if "/" in model_id else "")
        provider = provider_name(str(owner))
        released = entry.get("released") or entry.get("created") or 0
        found.append((
            provider.lower(),
            -int(released) if isinstance(released, (int, float)) else 0,
            ModelInfo(
                id=model_id,
                name=str(entry.get("name") or model_id),
                provider=provider,
                description=str(entry.get("description") or ""),
            ),
        ))
    found.sort(key=lambda item: (item[0], item[1]))
    return [model for _, _, model in found]


Fetcher = Callable[[str, Dict[str, str]], Awaitable[Any]]


async def fetch_listing(url: str, headers: Dict[str, str]) -> Any:
    """Edge: GET the provider's model listing."""
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


class ModelCatalog:
    def __init__(self, fetch: Fetcher = fetch_listing, clock: Callable[[], float] = time.monotonic):
        self.fetch = fetch
        self.clock = clock
        self._cache: Dict[str, Tuple[float, List[ModelInfo]]] = {}  # base URL → (fetched at, models)
        self._failed_at: Dict[str, float] = {}

    async def chat_models(self, base_url: str, api_key: str = "", extra_headers: Optional[Dict[str, str]] = None) -> List[ModelInfo]:
        """The provider's chat models, or [] when it doesn't list them (callers fall back)."""
        now = self.clock()
        cached = self._cache.get(base_url)
        if cached and now - cached[0] < CATALOG_TTL_SECONDS:
            return cached[1]
        # A stale list beats none, and beats asking a failing provider again.
        stale = cached[1] if cached else []
        if now - self._failed_at.get(base_url, -RETRY_AFTER_FAILURE_SECONDS) < RETRY_AFTER_FAILURE_SECONDS:
            return stale
        headers = dict(extra_headers or {})
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            models = chat_models_from_listing(await self.fetch(f"{base_url}/models", headers))
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Couldn't list the provider's models: %s", type(exc).__name__)
            models = []
        if not models:
            self._failed_at[base_url] = now
            return stale
        self._failed_at.pop(base_url, None)
        self._cache[base_url] = (now, models)
        return models


model_catalog = ModelCatalog()
