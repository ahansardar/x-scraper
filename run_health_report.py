from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xingestion.config import load_app_config
from xingestion.health_report import write_health_report
from xingestion.logging_config import configure_logging
from xingestion.migrations import MigrationRunner
from xrev.protocol import ProtocolReleaseManifest
from xrev.runtime import load_env_file, web_session_auth_from_env


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="health-report", console=False)
    result = write_health_report(
        config=config,
        migration_runner=MigrationRunner(
            config.sqlite_path,
            ROOT / "src" / "xingestion" / "migrations" / "sql",
        ),
        manifest=ProtocolReleaseManifest.from_file(
            ROOT / "protocol_releases" / "search_tweets.candidate.json"
        ),
        auth=web_session_auth_from_env(),
        base_url=_arg(argv, "--base-url", None),
        output_path=_arg(argv, "--output", None),
    )
    status = "PASS" if result.ok else "FAIL"
    print(f"[{status}] health report: {result.path}")
    failed = [
        check
        for check in result.report["preflight"]
        if isinstance(check, dict) and check.get("status") == "FAIL"
    ]
    for check in failed:
        print(f"[FAIL] {check['name']}: {check['message']}")
    return 0 if result.ok else 1


def _arg(argv, name, default):
    if name not in argv:
        return default
    index = argv.index(name)
    if index + 1 >= len(argv):
        raise ValueError(f"{name} requires a value")
    return argv[index + 1]


if __name__ == "__main__":
    raise SystemExit(main())
