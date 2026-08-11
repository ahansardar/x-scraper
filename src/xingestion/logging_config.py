from __future__ import annotations

from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
import logging
import os

from xingestion.config import AppConfig


@dataclass(frozen=True)
class LoggingSettings:
    component: str
    log_dir: Path
    log_file: Path
    level: str
    max_bytes: int
    backup_count: int


def configure_logging(
    *,
    config: AppConfig,
    component: str,
    console: bool = True,
) -> LoggingSettings:
    settings = load_logging_settings(config=config, component=component)
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(_level(settings.level))
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    file_handler = RotatingFileHandler(
        settings.log_file,
        maxBytes=settings.max_bytes,
        backupCount=settings.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    logging.getLogger("xingestion").info(
        "logging configured component=%s file=%s level=%s max_bytes=%s backup_count=%s",
        settings.component,
        settings.log_file,
        settings.level,
        settings.max_bytes,
        settings.backup_count,
    )
    return settings


def load_logging_settings(*, config: AppConfig, component: str) -> LoggingSettings:
    log_dir = _path_from_env("XINGESTION_LOG_DIR", config.data_dir / "logs")
    level = os.getenv("XINGESTION_LOG_LEVEL", "INFO").upper()
    max_bytes = _int_env("XINGESTION_LOG_MAX_BYTES", 5_242_880)
    backup_count = _int_env("XINGESTION_LOG_BACKUP_COUNT", 5)
    safe_component = _safe_component(component)
    return LoggingSettings(
        component=safe_component,
        log_dir=log_dir,
        log_file=log_dir / f"{safe_component}.log",
        level=level,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


def _safe_component(component: str) -> str:
    safe = "".join(
        char
        for char in component.lower().strip()
        if char.isalnum() or char in {"-", "_"}
    )
    if not safe:
        raise ValueError("logging component cannot be empty")
    return safe


def _level(name: str) -> int:
    value = getattr(logging, name, None)
    if not isinstance(value, int):
        raise ValueError(f"Unsupported log level: {name}")
    return value
