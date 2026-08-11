from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xingestion.config import load_app_config
from xingestion.logging_config import configure_logging
from xingestion.migrations import MigrationRunner
from xingestion.xprotocol.runtime import load_env_file


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="migrations", console=False)
    runner = MigrationRunner(
        config.sqlite_path,
        ROOT / "src" / "xingestion" / "migrations" / "sql",
    )
    applied = runner.apply()
    if applied:
        print(f"Applied migrations: {', '.join(applied)}")
    else:
        print("No pending migrations.")
    print(f"SQLite database: {config.sqlite_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
