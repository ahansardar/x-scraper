from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xingestion.supervision import (
    DeploymentSupervisorCheck,
    UrlApiClient,
    WindowsProcessProbe,
)
from xingestion.config import load_app_config
from xingestion.logging_config import configure_logging
from xingestion.xprotocol.runtime import load_env_file


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    args = _parser().parse_args(argv)
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="supervisor-check", console=False)
    checker = DeploymentSupervisorCheck(
        api_client=UrlApiClient(
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
        ),
        root=ROOT,
        process_probe=WindowsProcessProbe(),
        expect_processes=args.expect_processes,
        required_process_fragments=tuple(args.process_fragment),
        max_unpublished_events=args.max_unpublished_events,
        max_outbox_lag_seconds=args.max_outbox_lag_seconds,
        require_external_data_dir=args.require_external_data_dir,
    )
    result = checker.run()
    for check in result.checks:
        print(f"[{check.status}] {check.name}: {check.message}")
    return 0 if result.ok else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a no-Docker supervised xingestion deployment.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--expect-processes",
        action="store_true",
        help="Require visible process command lines for web and worker.",
    )
    parser.add_argument(
        "--process-fragment",
        action="append",
        default=["run_app.py", "run_worker.py"],
        help="Command-line fragment required when --expect-processes is set.",
    )
    parser.add_argument("--max-unpublished-events", type=int, default=100)
    parser.add_argument("--max-outbox-lag-seconds", type=int, default=300)
    parser.add_argument(
        "--require-external-data-dir",
        action="store_true",
        help="Fail if XINGESTION_DATA_DIR resolves inside the repo checkout.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
