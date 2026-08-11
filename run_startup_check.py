from __future__ import annotations

import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xingestion.config import load_app_config
from xingestion.logging_config import configure_logging
from xingestion.migrations import MigrationRunner
from xingestion.preflight import DeploymentPreflight
from xingestion.xprotocol.protocol import ProtocolReleaseManifest
from xingestion.xprotocol.runtime import load_env_file, web_session_auth_from_env


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    load_env_file(ROOT / ".env")
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="startup-check", console=False)
    manifest = ProtocolReleaseManifest.from_file(
        ROOT / "protocol_releases" / "search_tweets.candidate.json"
    )
    runner = MigrationRunner(config.sqlite_path, ROOT / "src" / "xingestion" / "migrations" / "sql")
    result = DeploymentPreflight(
        config=config,
        migration_runner=runner,
        manifest=manifest,
        auth=web_session_auth_from_env(),
    ).run()
    startup = next(check for check in result.checks if check.name == "startup_directories")
    print(f"[{startup.status}] {startup.name}: {startup.message}")
    return 0 if startup.status != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
