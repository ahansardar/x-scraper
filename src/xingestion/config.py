from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    root: Path
    data_dir: Path
    sqlite_path: Path
    raw_evidence_dir: Path
    host: str
    port: int
    retention_days: int
    default_session_id: str
    default_account_label: str
    default_credential_ref: str
    default_network_context: str
    worker_network_context: str
    secret_provider: str
    secret_dir: Path
    session_registry_path: Path | None
    require_migrations: bool
    max_active_tasks_per_capability: int
    postgres_dsn: str
    postgres_pool_min_size: int
    postgres_pool_max_size: int
    redis_url: str
    redis_stream_key: str
    redis_consumer_group: str
    redis_consumer_name: str
    dispatcher_poll_interval_seconds: float
    worker_lease_heartbeat_seconds: int
    redis_claim_min_idle_ms: int


def load_app_config(root: Path, argv: list[str] | None = None) -> AppConfig:
    argv = argv or []
    data_dir = _path_from_env("XINGESTION_DATA_DIR", root / "data")
    host = _value_from_args(argv, "--host") or os.getenv("XINGESTION_HOST", "127.0.0.1")
    port_value = _value_from_args(argv, "--port") or os.getenv("XINGESTION_PORT", "8000")
    port = int(port_value)
    retention_days = int(os.getenv("XINGESTION_RETENTION_DAYS", "30"))
    default_session_id = os.getenv("XINGESTION_SESSION_ID", "local-env-session")
    default_account_label = os.getenv("XINGESTION_ACCOUNT_LABEL", "local-env")
    default_credential_ref = os.getenv(
        "XINGESTION_CREDENTIAL_REF",
        "env:X_AUTH_TOKEN,X_CT0,X_BEARER",
    )
    default_network_context = os.getenv("XINGESTION_NETWORK_CONTEXT", "direct")
    worker_network_context = os.getenv("XINGESTION_WORKER_NETWORK_CONTEXT", "").strip()
    secret_provider = os.getenv("XINGESTION_SECRET_PROVIDER", "env").strip().lower()
    secret_dir = _path_from_env("XINGESTION_SECRET_DIR", data_dir / "secrets")
    session_registry_path = _optional_path_from_env("XINGESTION_SESSION_REGISTRY")
    require_migrations = os.getenv("XINGESTION_REQUIRE_MIGRATIONS", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    max_active_tasks_per_capability = int(
        os.getenv("XINGESTION_MAX_ACTIVE_TASKS_PER_CAPABILITY", "100")
    )
    postgres_dsn = os.getenv(
        "XINGESTION_POSTGRES_DSN",
        "postgresql://xingestion:xingestion@127.0.0.1:55432/xingestion",
    )
    postgres_pool_min_size = int(os.getenv("XINGESTION_POSTGRES_POOL_MIN", "1"))
    postgres_pool_max_size = int(os.getenv("XINGESTION_POSTGRES_POOL_MAX", "10"))
    redis_url = os.getenv("XINGESTION_REDIS_URL", "redis://127.0.0.1:6379/0")
    redis_stream_key = os.getenv("XINGESTION_REDIS_STREAM", "xingestion:capability-tasks")
    redis_consumer_group = os.getenv(
        "XINGESTION_REDIS_CONSUMER_GROUP", "capability-workers"
    )
    redis_consumer_name = os.getenv("XINGESTION_REDIS_CONSUMER_NAME", "").strip()
    dispatcher_poll_interval_seconds = float(
        os.getenv("XINGESTION_DISPATCHER_POLL_SECONDS", "1.0")
    )
    worker_lease_heartbeat_seconds = int(
        os.getenv("XINGESTION_WORKER_LEASE_HEARTBEAT_SECONDS", "100")
    )
    redis_claim_min_idle_ms = int(
        os.getenv("XINGESTION_REDIS_CLAIM_MIN_IDLE_MS", "300000")
    )

    return AppConfig(
        root=root,
        data_dir=data_dir,
        sqlite_path=data_dir / "tasks.sqlite3",
        raw_evidence_dir=data_dir / "raw_evidence",
        host=host,
        port=port,
        retention_days=retention_days,
        default_session_id=default_session_id,
        default_account_label=default_account_label,
        default_credential_ref=default_credential_ref,
        default_network_context=default_network_context,
        worker_network_context=worker_network_context,
        secret_provider=secret_provider,
        secret_dir=secret_dir,
        session_registry_path=session_registry_path,
        require_migrations=require_migrations,
        max_active_tasks_per_capability=max_active_tasks_per_capability,
        postgres_dsn=postgres_dsn,
        postgres_pool_min_size=postgres_pool_min_size,
        postgres_pool_max_size=postgres_pool_max_size,
        redis_url=redis_url,
        redis_stream_key=redis_stream_key,
        redis_consumer_group=redis_consumer_group,
        redis_consumer_name=redis_consumer_name,
        dispatcher_poll_interval_seconds=dispatcher_poll_interval_seconds,
        worker_lease_heartbeat_seconds=worker_lease_heartbeat_seconds,
        redis_claim_min_idle_ms=redis_claim_min_idle_ms,
    )


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else default.resolve()


def _optional_path_from_env(name: str) -> Path | None:
    raw = os.getenv(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else None


def _value_from_args(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    index = argv.index(name)
    if index + 1 >= len(argv):
        raise ValueError(f"{name} requires a value")
    return argv[index + 1]
