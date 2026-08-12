import os
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.config import load_app_config


class ConfigTests(unittest.TestCase):
    def test_defaults_storage_to_repo_data_directory(self):
        config = load_app_config(ROOT, [])

        self.assertEqual(config.data_dir, (ROOT / "data").resolve())
        self.assertEqual(config.sqlite_path, (ROOT / "data" / "tasks.sqlite3").resolve())
        self.assertEqual(config.raw_evidence_dir, (ROOT / "data" / "raw_evidence").resolve())
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 8000)
        self.assertEqual(config.retention_days, 30)
        self.assertEqual(config.default_session_id, "local-env-session")
        self.assertEqual(config.default_credential_ref, "env:X_AUTH_TOKEN,X_CT0,X_BEARER")
        self.assertEqual(config.worker_network_context, "")
        self.assertEqual(config.secret_provider, "env")
        self.assertEqual(config.secret_dir, (ROOT / "data" / "secrets").resolve())
        self.assertIsNone(config.session_registry_path)
        self.assertTrue(config.require_migrations)
        self.assertEqual(config.max_active_tasks_per_capability, 100)

    def test_env_and_args_override_deployment_settings(self):
        old_values = {
            key: os.environ.get(key)
            for key in (
                "XINGESTION_DATA_DIR",
                "XINGESTION_HOST",
                "XINGESTION_PORT",
                "XINGESTION_RETENTION_DAYS",
                "XINGESTION_SESSION_ID",
                "XINGESTION_ACCOUNT_LABEL",
                "XINGESTION_CREDENTIAL_REF",
                "XINGESTION_NETWORK_CONTEXT",
                "XINGESTION_WORKER_NETWORK_CONTEXT",
                "XINGESTION_SECRET_PROVIDER",
                "XINGESTION_SECRET_DIR",
                "XINGESTION_SESSION_REGISTRY",
                "XINGESTION_REQUIRE_MIGRATIONS",
                "XINGESTION_MAX_ACTIVE_TASKS_PER_CAPABILITY",
            )
        }
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.environ["XINGESTION_DATA_DIR"] = temp_dir
                os.environ["XINGESTION_HOST"] = "0.0.0.0"
                os.environ["XINGESTION_PORT"] = "9000"
                os.environ["XINGESTION_RETENTION_DAYS"] = "14"
                os.environ["XINGESTION_SESSION_ID"] = "session-a"
                os.environ["XINGESTION_ACCOUNT_LABEL"] = "account-a"
                os.environ["XINGESTION_CREDENTIAL_REF"] = "secret:x/session-a"
                os.environ["XINGESTION_NETWORK_CONTEXT"] = "direct:iad"
                os.environ["XINGESTION_WORKER_NETWORK_CONTEXT"] = "direct:iad"
                os.environ["XINGESTION_SECRET_PROVIDER"] = "file"
                os.environ["XINGESTION_SECRET_DIR"] = str(Path(temp_dir) / "mounted-secrets")
                os.environ["XINGESTION_SESSION_REGISTRY"] = str(Path(temp_dir) / "sessions.json")
                os.environ["XINGESTION_REQUIRE_MIGRATIONS"] = "false"
                os.environ["XINGESTION_MAX_ACTIVE_TASKS_PER_CAPABILITY"] = "7"

                config = load_app_config(ROOT, ["--port", "9001"])

                self.assertEqual(config.data_dir, Path(temp_dir).resolve())
                self.assertEqual(config.host, "0.0.0.0")
                self.assertEqual(config.port, 9001)
                self.assertEqual(config.retention_days, 14)
                self.assertEqual(config.default_session_id, "session-a")
                self.assertEqual(config.default_account_label, "account-a")
                self.assertEqual(config.default_credential_ref, "secret:x/session-a")
                self.assertEqual(config.default_network_context, "direct:iad")
                self.assertEqual(config.worker_network_context, "direct:iad")
                self.assertEqual(config.secret_provider, "file")
                self.assertEqual(config.secret_dir, (Path(temp_dir) / "mounted-secrets").resolve())
                self.assertEqual(config.session_registry_path, (Path(temp_dir) / "sessions.json").resolve())
                self.assertFalse(config.require_migrations)
                self.assertEqual(config.max_active_tasks_per_capability, 7)
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
