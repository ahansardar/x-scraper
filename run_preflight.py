from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xingestion.config import load_app_config
from xingestion.logging_config import configure_logging
from xingestion.migrations import MigrationRunner
from xingestion.releases import ReleaseStore, resolve_approved_manifest
from xingestion.preflight import DeploymentPreflight
from xingestion.secrets import resolve_web_session_auth
from xingestion.xprotocol.runtime import load_env_file


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="preflight", console=False)
    base_url = _arg(argv, "--base-url", None)
    strict_warnings = "--strict-warnings" in argv
    release_store = ReleaseStore(config.sqlite_path)
    resolved_release = resolve_approved_manifest(
        release_store=release_store,
        manifest_dir=ROOT / "protocol_releases",
    )
    preflight = DeploymentPreflight(
        config=config,
        migration_runner=MigrationRunner(
            config.sqlite_path,
            ROOT / "src" / "xingestion" / "migrations" / "sql",
        ),
        manifest=resolved_release.manifest,
        auth=resolve_web_session_auth(config),
        base_url=base_url,
    )
    result = preflight.run()
    for check in result.checks:
        print(f"[{check.status}] {check.name}: {check.message}")
    if not result.ok:
        return 1
    if strict_warnings and any(check.status == "WARN" for check in result.checks):
        return 1
    return 0


def _arg(argv, name, default):
    if name not in argv:
        return default
    index = argv.index(name)
    if index + 1 >= len(argv):
        raise ValueError(f"{name} requires a value")
    return argv[index + 1]


if __name__ == "__main__":
    raise SystemExit(main())
