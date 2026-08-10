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
        self.assertEqual(config.admin_token, "")
        self.assertTrue(config.require_migrations)

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
                "XINGESTION_ADMIN_TOKEN",
                "XINGESTION_REQUIRE_MIGRATIONS",
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
                os.environ["XINGESTION_ADMIN_TOKEN"] = "admin-secret"
                os.environ["XINGESTION_REQUIRE_MIGRATIONS"] = "false"

                config = load_app_config(ROOT, ["--port", "9001"])

                self.assertEqual(config.data_dir, Path(temp_dir).resolve())
                self.assertEqual(config.host, "0.0.0.0")
                self.assertEqual(config.port, 9001)
                self.assertEqual(config.retention_days, 14)
                self.assertEqual(config.default_session_id, "session-a")
                self.assertEqual(config.default_account_label, "account-a")
                self.assertEqual(config.default_credential_ref, "secret:x/session-a")
                self.assertEqual(config.default_network_context, "direct:iad")
                self.assertEqual(config.admin_token, "admin-secret")
                self.assertFalse(config.require_migrations)
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
