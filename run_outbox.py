from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from psycopg_pool import ConnectionPool

from xingestion.config import load_app_config
from xingestion.logging_config import configure_logging
from xingestion.outbox_operations import list_outbox_queue, process_outbox
from xingestion.tasks import PostgresTaskLedger
from xingestion.workers.worker_app import build_worker
from xingestion.xprotocol.runtime import load_env_file


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    args = _parser().parse_args(argv)
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="outbox", console=False)

    if args.process:
        worker = build_worker(config=config, root=ROOT)
        result = process_outbox(ledger=worker.ledger, worker=worker, limit=args.limit)
        payload = result.public_dict()
    else:
        pool = ConnectionPool(config.postgres_dsn, min_size=1, max_size=1, open=True)
        try:
            payload = list_outbox_queue(PostgresTaskLedger(pool), limit=args.limit)
        finally:
            pool.close()

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    _print_human(payload, processed=args.process)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or process the local transactional outbox.",
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--process", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _print_human(payload: dict[str, object], *, processed: bool) -> None:
    if processed:
        before = payload["before"]
        after = payload["after"]
        print(
            "Processed {processed_events}/{requested_limit} outbox events. "
            "Pending before={before_pending} after={after_pending}.".format(
                processed_events=payload["processed_events"],
                requested_limit=payload["requested_limit"],
                before_pending=before["unpublished_events"],
                after_pending=after["unpublished_events"],
            )
        )
        for result in payload["worker_results"]:
            print(
                "task={task_id} state={state} error={error} message={message}".format(
                    task_id=result["task_id"],
                    state=result["state"] or "",
                    error=result["error_class"] or "",
                    message=result["message"] or "",
                )
            )
        return

    stats = payload["stats"]
    print(
        "Outbox pending={pending} oldest={oldest} lag_seconds={lag}".format(
            pending=stats["unpublished_events"],
            oldest=stats["oldest_unpublished_at"] or "",
            lag=stats["oldest_unpublished_lag_seconds"] or "",
        )
    )
    for event in payload["events"]:
        print(
            "event={event_id} task={task_id} type={event_type} state={task_state} age={age_seconds}".format(
                event_id=event["event_id"],
                task_id=event["task_id"],
                event_type=event["event_type"],
                task_state=event["task_state"],
                age_seconds=event["age_seconds"],
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
