from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from psycopg_pool import ConnectionPool

from xingestion.config import load_app_config
from xingestion.logging_config import configure_logging
from xingestion.migrations import PostgresMigrationRunner
from xingestion.xprotocol.runtime import load_env_file


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    config = load_app_config(ROOT, argv)
    configure_logging(config=config, component="postgres-migrations", console=False)
    pool = ConnectionPool(config.postgres_dsn, min_size=1, max_size=1, open=True)
    try:
        runner = PostgresMigrationRunner(
            pool,
            ROOT / "src" / "xingestion" / "migrations" / "postgres_sql",
        )
        applied = runner.apply()
    finally:
        pool.close()
    if applied:
        print(f"Applied migrations: {', '.join(applied)}")
    else:
        print("No pending migrations.")
    print(f"Postgres DSN: {config.postgres_dsn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
