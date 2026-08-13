from __future__ import annotations

from typing import Protocol

import redis


class TaskExistenceCheck(Protocol):
    def get_task(self, task_id: str) -> object | None:
        """Return a task by ID, or None if it does not exist."""


def reconcile_redis_stream_backlog(
    redis_client,
    ledger: TaskExistenceCheck,
    *,
    stream_key: str,
    limit: int = 500,
    dry_run: bool = True,
) -> dict[str, object]:
    """Find (and optionally remove) stream entries whose task no longer exists.

    Enumerates up to `limit` stream entries via XRANGE (oldest first) and
    cross-references each entry's task_id against Postgres, the durable
    authority -- Redis is reconstructable delivery infrastructure, never the
    source of truth. An entry whose task doesn't exist can never be
    successfully processed (a worker would immediately drop it as
    TASK_NOT_FOUND); this can legitimately happen if retention deletes a
    terminal task before a stalled or backlogged consumer group ever
    delivers its still-unread stream entry.

    Deletes orphaned entries via XDEL when dry_run=False. Entries whose task
    still exists are never touched here regardless of age -- that is a
    dispatch-lag/backlog concern (see redis_queue_stats), not an orphan.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")

    raw_entries = redis_client.xrange(stream_key, min="-", max="+", count=limit)
    orphaned: list[dict[str, object]] = []
    for message_id, fields in raw_entries:
        task_id = fields.get("task_id")
        if not task_id:
            continue
        if ledger.get_task(task_id) is None:
            orphaned.append({"message_id": message_id, "task_id": task_id})

    deleted_entries = 0
    if not dry_run and orphaned:
        deleted_entries = int(
            redis_client.xdel(stream_key, *[entry["message_id"] for entry in orphaned])
        )

    return {
        "dry_run": dry_run,
        "stream_key": stream_key,
        "scanned_entries": len(raw_entries),
        "orphaned_count": len(orphaned),
        "orphaned_entries": orphaned,
        "deleted_entries": deleted_entries,
    }


def redis_queue_stats(redis_client, *, stream_key: str, group_name: str) -> dict[str, object]:
    """Return stream length, consumer-group lag, and pending-entry stats.

    ``lag`` is the number of stream entries the group has not yet read
    (Redis-computed, requires Redis >= 7.0; ``None`` on older servers).
    ``pending_count`` is entries read but not yet XACKed -- delivered work
    a worker may have crashed while processing.
    """
    stream_length = int(redis_client.xlen(stream_key))
    try:
        groups = redis_client.xinfo_groups(stream_key)
    except redis.ResponseError:
        # The stream itself doesn't exist yet (e.g. nothing has been
        # dispatched since a fresh deployment/CI run) -- XINFO GROUPS
        # errors on a missing key even though XLEN above happily reports 0
        # for one. No stream means no group either.
        groups = []
    group = next((g for g in groups if g.get("name") == group_name), None)
    if group is None:
        return {
            "stream_key": stream_key,
            "group_name": group_name,
            "group_exists": False,
            "stream_length": stream_length,
            "pending_count": 0,
            "lag": None,
            "oldest_pending_idle_ms": None,
        }

    pending_summary = redis_client.xpending(stream_key, group_name) or {}
    pending_count = int(pending_summary.get("pending") or 0)

    oldest_pending_idle_ms = None
    if pending_count:
        oldest = redis_client.xpending_range(
            stream_key, group_name, min="-", max="+", count=1
        )
        if oldest:
            oldest_pending_idle_ms = int(oldest[0].get("time_since_delivered") or 0)

    lag = group.get("lag")
    return {
        "stream_key": stream_key,
        "group_name": group_name,
        "group_exists": True,
        "stream_length": stream_length,
        "pending_count": pending_count,
        "lag": int(lag) if lag is not None else None,
        "oldest_pending_idle_ms": oldest_pending_idle_ms,
    }
