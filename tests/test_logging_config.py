import logging
import os
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.config import AppConfig
from xingestion.logging_config import configure_logging, load_logging_settings


class LoggingConfigTests(unittest.TestCase):
    def test_logging_defaults_to_data_dir_logs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(Path(temp_dir))

            settings = load_logging_settings(config=config, component="worker")

            self.assertEqual(settings.log_dir, config.data_dir / "logs")
            self.assertEqual(settings.log_file, config.data_dir / "logs" / "worker.log")
            self.assertEqual(settings.level, "INFO")

    def test_configure_logging_writes_rotating_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = _config(root)
            log_dir = root / "runtime-logs"
            old = _set_env(
                {
                    "XINGESTION_LOG_DIR": str(log_dir),
                    "XINGESTION_LOG_LEVEL": "DEBUG",
                    "XINGESTION_LOG_MAX_BYTES": "1024",
                    "XINGESTION_LOG_BACKUP_COUNT": "2",
                }
            )
            try:
                settings = configure_logging(
                    config=config,
                    component="Worker Service",
                    console=False,
                )
                logging.getLogger("xingestion.test").debug("debug probe")
                self.assertEqual(settings.component, "workerservice")
                self.assertTrue(settings.log_file.exists())
                self.assertIn("debug probe", settings.log_file.read_text(encoding="utf-8"))
            finally:
                _close_logging_handlers()
                _restore_env(old)


def _set_env(values):
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    return old


def _restore_env(values):
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _close_logging_handlers():
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()


def _config(root: Path) -> AppConfig:
    return AppConfig(
        root=root,
        data_dir=root / "data",
        sqlite_path=root / "data" / "tasks.sqlite3",
        raw_evidence_dir=root / "data" / "raw_evidence",
        host="127.0.0.1",
        port=8000,
        retention_days=30,
        default_session_id="session-1",
        default_account_label="local",
        default_credential_ref="env:X_AUTH_TOKEN,X_CT0,X_BEARER",
        default_network_context="direct",
        admin_token="token",
        require_migrations=True,
        max_active_tasks_per_capability=100,
    )


if __name__ == "__main__":
    unittest.main()
