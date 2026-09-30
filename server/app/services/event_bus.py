"""In-process publish/subscribe for live workspace events.

Every open client (the Mac browser, a paired iPhone) holds one subscription
and sees the same stream: new messages, reply deltas, approvals, and
conversation list changes. The server is a single local process, so a set of
bounded queues is enough.
"""

import asyncio
from typing import Any, Dict, Optional, Set


class Subscription:
    def __init__(self, max_queue: int):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue)
        # Set when events were dropped; the client must reload its state.
        self.lost = False

    async def next(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        if self.lost:
            self.lost = False
            while not self.queue.empty():
                self.queue.get_nowait()
            return {"type": "resync"}
        return await asyncio.wait_for(self.queue.get(), timeout)


class EventBus:
    def __init__(self, max_queue: int = 2000):
        self.max_queue = max_queue
        self._subscriptions: Set[Subscription] = set()

    def subscribe(self) -> Subscription:
        subscription = Subscription(self.max_queue)
        self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        self._subscriptions.discard(subscription)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscriptions)

    def publish(self, event: Dict[str, Any]) -> None:
        for subscription in list(self._subscriptions):
            try:
                subscription.queue.put_nowait(event)
            except asyncio.QueueFull:
                subscription.lost = True


event_bus = EventBus()
