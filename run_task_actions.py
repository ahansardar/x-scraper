from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xingestion.config import load_app_config
from xingestion.logging_config import configure_logging
from xingestion.operator_tasks import DEFAULT_ACTION_STATES, list_operator_task_actions
from xingestion.tasks import TaskState
from xingestion.xprotocol.runtime import load_env_file


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    args = _parser().parse_args(argv)
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="task-actions", console=False)
    states = tuple(TaskState(value) for value in args.state)
    actions = list_operator_task_actions(
        config.sqlite_path,
        states=states,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps([action.public_dict() for action in actions], indent=2, sort_keys=True))
        return 0
    if not actions:
        print("No operator task actions found.")
        return 0
    for action in actions:
        print(
            "{state} task={task_id} error={error} severity={severity} "
            "attempts={attempts}/{max_attempts} next={next_attempt} action={operator_action}".format(
                state=action.state,
                task_id=action.task_id,
                error=action.error_class or "",
                severity=action.severity,
                attempts=action.attempt_count,
                max_attempts=action.max_attempts,
                next_attempt=action.next_attempt_at or "",
                operator_action=action.operator_action,
            )
        )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List failed or retryable tasks with recommended operator actions.",
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument(
        "--state",
        action="append",
        choices=[state.value for state in TaskState],
        default=[state.value for state in DEFAULT_ACTION_STATES],
    )
    parser.add_argument("--json", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
