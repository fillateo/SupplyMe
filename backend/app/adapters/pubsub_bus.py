"""Cloud Pub/Sub publisher.

Delivery is a push subscription to `/events/pubsub` on the Cloud Run service —
see terraform/pubsub.tf. The event's dedup `key` travels as a message attribute
so the receiving side can reject a replay before doing any work, and so Pub/Sub's
own `enable_message_ordering` is not load-bearing.
"""

from __future__ import annotations

import asyncio

from google.cloud import pubsub_v1

from ..domain.events import Event


class PubSubBus:
    def __init__(self, project: str, topic: str) -> None:
        self._publisher = pubsub_v1.PublisherClient()
        self._topic_path = self._publisher.topic_path(project, topic)

    async def publish(self, event: Event) -> None:
        payload = event.model_dump_json().encode()
        future = self._publisher.publish(
            self._topic_path,
            payload,
            event_type=event.type.value,
            mission_id=event.mission_id,
            dedup_key=event.key,
        )
        await asyncio.wrap_future(future)
