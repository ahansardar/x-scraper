from __future__ import annotations

import redis


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
