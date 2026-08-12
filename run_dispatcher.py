from pathlib import Path
import logging
import sys
import time

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import redis
from psycopg_pool import ConnectionPool

from xingestion.config import load_app_config
from xingestion.dispatch import RedisOutboxDispatcher
from xingestion.logging_config import configure_logging
from xingestion.tasks import PostgresTaskLedger
from xingestion.xprotocol.runtime import load_env_file

LOGGER = logging.getLogger("xingestion.dispatch")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    config = load_app_config(ROOT, argv)
    logging_settings = configure_logging(config=config, component="dispatcher")

    pool = ConnectionPool(config.postgres_dsn, open=True)
    redis_client = redis.Redis.from_url(config.redis_url, decode_responses=True)
    ledger = PostgresTaskLedger(pool)
    dispatcher = RedisOutboxDispatcher(
        ledger=ledger,
        redis_client=redis_client,
        stream_key=config.redis_stream_key,
    )

    once = "--once" in argv
    sleep_seconds = config.dispatcher_poll_interval_seconds
    print(f"X ingestion dispatcher using Postgres: {config.postgres_dsn}")
    print(f"Redis stream: {config.redis_stream_key} ({config.redis_url})")
    print(f"Log file: {logging_settings.log_file}")
    LOGGER.info(
        "dispatcher starting postgres=%s redis=%s stream=%s once=%s sleep_seconds=%s",
        config.postgres_dsn,
        config.redis_url,
        config.redis_stream_key,
        once,
        sleep_seconds,
    )

    try:
        while True:
            result = dispatcher.dispatch_once()
            if result.dispatched:
                message = f"dispatched event={result.event_id} task={result.task_id}"
                print(message)
                LOGGER.info(message)
            elif once:
                print("no pending outbox events")
                LOGGER.info("no pending outbox events")
                return 0

            if once:
                return 0
            time.sleep(sleep_seconds)
    finally:
        pool.close()


if __name__ == "__main__":
    raise SystemExit(main())
