"""Azure Service Bus queue — durable jobs consumed by standalone workers."""
from __future__ import annotations

import json
from typing import Callable

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("jobs")


class ServiceBusQueue:
    backend = "azure"

    def __init__(self) -> None:
        self.cfg = settings()
        if not self.cfg.servicebus_connection_string:
            raise RuntimeError(
                "QUEUE_BACKEND=azure but AZURE_SERVICEBUS_CONNECTION_STRING is not set"
            )

    def _client(self):
        from azure.servicebus import ServiceBusClient
        return ServiceBusClient.from_connection_string(
            self.cfg.servicebus_connection_string
        )

    def enqueue(self, job: dict) -> None:
        from azure.servicebus import ServiceBusMessage
        with self._client() as client:
            with client.get_queue_sender(self.cfg.servicebus_queue) as sender:
                sender.send_messages(ServiceBusMessage(json.dumps(job)))
        log.info("service bus: queued %s job for ws=%s", job.get("type"), job.get("ws"))

    def consume(self, handler: Callable[[dict], None]) -> None:
        wait = self.cfg.worker_max_wait_secs
        with self._client() as client:
            with client.get_queue_receiver(self.cfg.servicebus_queue) as receiver:
                while True:
                    batch = receiver.receive_messages(max_message_count=1,
                                                      max_wait_time=wait)
                    for msg in batch:
                        try:
                            job = json.loads(str(msg))
                        except (ValueError, TypeError):
                            log.warning("service bus: bad message — dead-lettering")
                            receiver.dead_letter_message(msg, reason="invalid-json")
                            continue
                        try:
                            handler(job)
                            receiver.complete_message(msg)
                            log.info("service bus: completed %s job ws=%s",
                                     job.get("type"), job.get("ws"))
                        except Exception as exc:
                            log.exception("service bus: job failed — abandoning: %s", exc)
                            receiver.abandon_message(msg)