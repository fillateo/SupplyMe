"""Cloud Pub/Sub publisher.

Delivery is a push subscription to `/events/pubsub` on the Cloud Run service —
see terraform/pubsub.tf. Deduplication is the orchestrator's job and it works off
the decoded payload, so nothing here is load-bearing for correctness: the
`dedup_key`, `event_type` and `mission_id` attributes are published so a message
can be identified in the Pub/Sub console or a dead-letter pull without decoding
its body.
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
