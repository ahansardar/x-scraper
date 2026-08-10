import os
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xrev.runtime import load_env_file, web_session_auth_from_env


class EnvAuthTests(unittest.TestCase):
    def test_load_env_file_populates_web_session_auth_without_overwrite(self):
        old_values = {
            key: os.environ.get(key)
            for key in ("X_AUTH_TOKEN", "X_CT0", "X_BEARER")
        }
        try:
            for key in old_values:
                os.environ.pop(key, None)

            with tempfile.TemporaryDirectory() as temp_dir:
                env_path = Path(temp_dir) / ".env"
                env_path.write_text(
                    "\n".join(
                        [
                            "X_AUTH_TOKEN=auth",
                            "X_CT0=csrf",
                            "X_BEARER=bearer",
                        ]
                    ),
                    encoding="utf-8",
                )
                load_env_file(env_path)

            auth = web_session_auth_from_env()

            self.assertEqual(auth.auth_token, "auth")
            self.assertEqual(auth.ct0, "csrf")
            self.assertEqual(auth.bearer_token, "bearer")
            self.assertEqual(auth.missing_fields(), ())
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
