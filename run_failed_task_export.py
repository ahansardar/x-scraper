from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xingestion.config import load_app_config
from xingestion.logging_config import configure_logging
from xingestion.support_export import write_failed_task_export
from xrev.protocol import ProtocolReleaseManifest
from xrev.runtime import load_env_file


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    args = _parser().parse_args(argv)
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="failed-task-export", console=False)
    result = write_failed_task_export(
        task_id=args.task_id,
        config=config,
        manifest=ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        ),
        output_path=args.output,
    )
    summary = result.package["support_summary"]
    print(f"[PASS] failed task export: {result.path}")
    print(
        "task={task_id} state={state} error={error_class} severity={severity} action={action}".format(
            task_id=result.package["task_id"],
            state=result.package["state"],
            error_class=summary["error_class"],
            severity=summary["severity"],
            action=summary["operator_action"],
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a safe failed-task support package from local SQLite state.",
    )
    parser.add_argument("task_id")
    parser.add_argument("--output")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
