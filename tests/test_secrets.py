import json
import os
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xingestion.config import AppConfig
from xingestion.secrets import (
    EnvSecretProvider,
    FileSecretProvider,
    build_secret_provider,
    secret_provider_status,
)


class SecretProviderTests(unittest.TestCase):
    def test_env_provider_resolves_named_env_keys(self):
        old = {key: os.environ.get(key) for key in ("AUTH_A", "CT0_A", "BEARER_A")}
        try:
            os.environ["AUTH_A"] = "auth"
            os.environ["CT0_A"] = "csrf"
            os.environ["BEARER_A"] = "bearer"

            auth = EnvSecretProvider().resolve_web_session_auth(
                "env:AUTH_A,CT0_A,BEARER_A"
            )

            self.assertEqual(auth.auth_token, "auth")
            self.assertEqual(auth.ct0, "csrf")
            self.assertEqual(auth.bearer_token, "bearer")
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_file_provider_resolves_json_secret(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_dir = Path(temp_dir)
            (secret_dir / "session-a.json").write_text(
                json.dumps(
                    {
                        "auth_token": "auth",
                        "ct0": "csrf",
                        "bearer_token": "bearer",
                    }
                ),
                encoding="utf-8",
            )

            auth = FileSecretProvider(secret_dir).resolve_web_session_auth(
                "file:session-a"
            )

            self.assertEqual(auth.missing_fields(), ())

    def test_file_provider_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "simple secret name"):
                FileSecretProvider(Path(temp_dir)).resolve_web_session_auth(
                    "file:..\\secret"
                )

    def test_status_reports_missing_without_secret_values(self):
        status = EnvSecretProvider().status("env:DOES_NOT_EXIST_A,DOES_NOT_EXIST_B,DOES_NOT_EXIST_C")

        payload = status.public_dict()
        raw = json.dumps(payload)
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["reference_scheme"], "env")
        self.assertTrue(payload["reference_configured"])
        self.assertEqual(payload["missing_fields"], ["auth_token", "ct0", "bearer_token"])
        self.assertNotIn("auth=", raw)
        self.assertNotIn("bearer=", raw)

    def test_builds_provider_from_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(Path(temp_dir), secret_provider="file")

            provider = build_secret_provider(config)

            self.assertIsInstance(provider, FileSecretProvider)
            self.assertEqual(
                secret_provider_status(_config(Path(temp_dir))).provider,
                "env",
            )


def _config(root: Path, *, secret_provider: str = "env") -> AppConfig:
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
        default_credential_ref=(
            "file:session-a"
            if secret_provider == "file"
            else "env:X_AUTH_TOKEN,X_CT0,X_BEARER"
        ),
        default_network_context="direct",
        worker_network_context="",
        secret_provider=secret_provider,
        secret_dir=root / "secrets",
        session_registry_path=None,
        require_migrations=True,
        max_active_tasks_per_capability=100,
    )


if __name__ == "__main__":
    unittest.main()
