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
