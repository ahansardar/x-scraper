from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging

from psycopg.rows import dict_row

from xingestion.tasks.postgres_ledger import PostgresTaskLedger

LOGGER = logging.getLogger("xingestion.dispatch.redis")
LOGGER.addHandler(logging.NullHandler())


@dataclass(frozen=True)
class DispatchResult:
    dispatched: bool
    event_id: str | None = None
    task_id: str | None = None


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
