from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from xingestion.tasks.postgres_ledger import PostgresTaskLedger

LOGGER = logging.getLogger("xingestion.dispatch.redis")
LOGGER.addHandler(logging.NullHandler())

OUTBOX_NOTIFY_CHANNEL = "xingestion_outbox_events"


@dataclass(frozen=True)
class DispatchResult:
    dispatched: bool
    event_id: str | None = None
    task_id: str | None = None


@dataclass(frozen=True)
class OutboxNotification:
    channel: str
    payload: str
    event_id: str | None
    task_id: str | None
    created_at: str | None
    received_at: str
    wake_latency_ms: int | None

    def public_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "payload": self.payload,
            "event_id": self.event_id,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "received_at": self.received_at,
            "wake_latency_ms": self.wake_latency_ms,
        }


class PostgresOutboxNotificationListener:
    """Block on Postgres NOTIFY events emitted after outbox commits."""

    def __init__(self, dsn: str, *, channel: str = OUTBOX_NOTIFY_CHANNEL) -> None:
        self.channel = channel
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(channel)))

    def wait(self, timeout: float | None) -> OutboxNotification | None:
        for notify in self._conn.notifies(timeout=timeout, stop_after=1):
            return self._parse_notify(notify)
        return None

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PostgresOutboxNotificationListener":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _parse_notify(self, notify: psycopg.Notify) -> OutboxNotification:
        payload = notify.payload
        event_id = task_id = created_at = None
        wake_latency_ms = None
        try:
            parsed: dict[str, Any] = json.loads(payload)
            event_id = parsed.get("event_id")
            task_id = parsed.get("task_id")
            created_at = parsed.get("created_at")
            if created_at:
                wake_latency_ms = max(
                    0,
                    int(
                        (
                            datetime.now(UTC) - datetime.fromisoformat(str(created_at))
                        ).total_seconds()
                        * 1000
                    ),
                )
        except Exception:
            pass
        return OutboxNotification(
            channel=notify.channel,
            payload=payload,
            event_id=str(event_id) if event_id is not None else None,
            task_id=str(task_id) if task_id is not None else None,
            created_at=str(created_at) if created_at is not None else None,
            received_at=datetime.now(UTC).isoformat(),
            wake_latency_ms=wake_latency_ms,
        )


class RedisOutboxDispatcher:
    """Publishes committed-but-undelivered outbox events to a Redis stream.

    PostgreSQL remains the durable authority. An unpublished row is only
    marked published after the XADD has succeeded, so a crash between
    claiming the row and marking it published simply results in a
    harmless duplicate XADD on the next poll -- never a lost delivery.
    Redis is treated as reconstructable delivery infrastructure, not the
    source of truth.
    """

    def __init__(
        self,
        *,
        ledger: PostgresTaskLedger,
        redis_client,
        stream_key: str = "xingestion:capability-tasks",
    ) -> None:
        self.ledger = ledger
        self.redis_client = redis_client
        self.stream_key = stream_key

    def dispatch_once(self) -> DispatchResult:
        with self.ledger.pool.connection() as conn:
            conn.row_factory = dict_row
            with conn.transaction():
                row = conn.execute(
                    """
                    SELECT *
                    FROM outbox_events
                    WHERE published_at IS NULL
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                ).fetchone()
                if row is None:
                    return DispatchResult(dispatched=False)

                self.redis_client.xadd(
                    self.stream_key,
                    {
                        "task_id": row["task_id"],
                        "event_id": row["event_id"],
                        "event_type": row["event_type"],
                    },
                )

                conn.execute(
                    """
                    UPDATE outbox_events
                    SET published_at = %s
                    WHERE event_id = %s
                    """,
                    (datetime.now(UTC).isoformat(), row["event_id"]),
                )

        LOGGER.info("dispatched event=%s task=%s", row["event_id"], row["task_id"])
        return DispatchResult(
            dispatched=True, event_id=row["event_id"], task_id=row["task_id"]
        )

    def dispatch_available(self, *, limit: int | None = None) -> int:
        dispatched = 0
        while limit is None or dispatched < limit:
            result = self.dispatch_once()
            if not result.dispatched:
                break
            dispatched += 1
        return dispatched
